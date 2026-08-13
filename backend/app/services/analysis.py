"""Analysis orchestration: extract -> redact -> score -> persist.

Runs in a FastAPI BackgroundTask. Uploads return 202 immediately and the
dashboard polls; nothing here ever blocks a request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.llm.base import (
    AnalysisResult,
    CriterionSpec,
    CvPayload,
    FichePayload,
    LLMError,
)
from app.llm.factory import get_provider
from app.models import (
    AnalysisStatus,
    Candidate,
    CandidateSource,
    Criterion,
    CriterionScore,
    RecruitmentSession,
)
from app.models.base import utcnow
from app.services import extraction, redaction, scoring
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

MODE_REDACTED = "redacted_text"
MODE_DOCUMENT = "full_document"


@dataclass(slots=True)
class AnalysisRequest:
    candidate_id: str
    force_full_document: bool = False


async def analyze_candidate(candidate_id: str, *, force_full_document: bool = False) -> None:
    """Entry point for BackgroundTasks. Owns its own DB session and never raises."""
    try:
        async with SessionLocal() as db:
            await _run(db, candidate_id, force_full_document)
    except Exception as exc:  # a background task that raises would vanish silently
        logger.exception("analysis crashed for candidate %s", candidate_id)
        try:
            async with SessionLocal() as db:
                # Name the failure. A bare "unexpected error" sends whoever is
                # debugging to the server logs for something the UI could say.
                await _mark_failed(
                    db,
                    candidate_id,
                    f"The analysis failed unexpectedly: {type(exc).__name__}: {exc}"[:500],
                )
        except Exception:
            logger.exception("could not record the failure for candidate %s", candidate_id)


async def analyze_many(candidate_ids: list[str]) -> None:
    """Sequential by design — the provider semaphore is the real concurrency gate."""
    for candidate_id in candidate_ids:
        await analyze_candidate(candidate_id)


async def _mark_failed(db: AsyncSession, candidate_id: str, message: str) -> None:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return
    candidate.analysis_status = AnalysisStatus.FAILED
    candidate.analysis_error = message
    candidate.analyzed_at = utcnow()
    await db.commit()


async def _run(db: AsyncSession, candidate_id: str, force_full_document: bool) -> None:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        logger.warning("candidate %s disappeared before analysis", candidate_id)
        return

    session = await db.get(RecruitmentSession, candidate.session_id)
    if session is None:
        await _mark_failed(db, candidate_id, "The recruitment session no longer exists.")
        return

    criteria = list(
        (await db.execute(
            select(Criterion)
            .where(Criterion.session_id == session.id)
            .order_by(Criterion.display_order)
        )).scalars()
    )
    if not criteria:
        await _mark_failed(
            db, candidate_id, "This session has no criteria, so nothing can be scored."
        )
        return

    candidate.analysis_status = AnalysisStatus.PROCESSING
    candidate.analysis_error = None
    await db.commit()

    # --- read the file -----------------------------------------------------
    if not candidate.cv_storage_path:
        await _mark_failed(db, candidate_id, "No CV file is attached to this candidate.")
        return

    try:
        file_bytes = await get_storage().read(candidate.cv_storage_path)
    except FileNotFoundError:
        await _mark_failed(db, candidate_id, "The stored CV file is missing.")
        return

    use_document_path = force_full_document or not settings.pii_redaction

    # --- extraction + redaction -------------------------------------------
    cv_payload: CvPayload
    if use_document_path:
        # The unredacted file is about to leave the system. The caller has
        # already written the audit entry naming the user who chose this.
        cv_payload = CvPayload(
            file_bytes=file_bytes,
            mime_type=candidate.cv_mime_type,
            filename=candidate.cv_filename or "cv.pdf",
            redacted=False,
        )
        candidate.redaction_applied = False
        candidate.analysis_mode = MODE_DOCUMENT
        # Extract anyway when we can: HR still gets the profile panel and the
        # audit trail of what PII the document contained.
        try:
            document = await extraction.extract(
                file_bytes, candidate.cv_mime_type or "", candidate.cv_filename or ""
            )
        except extraction.UnreadableDocument:
            document = None
        if document is not None:
            result = await redaction.redact(
                document.text, _known_values(candidate), enabled=False
            )
            _apply_redaction_metadata(candidate, result, store_text=False)
    else:
        try:
            document = await extraction.extract(
                file_bytes, candidate.cv_mime_type or "", candidate.cv_filename or ""
            )
        except extraction.UnreadableDocument as exc:
            await _mark_failed(db, candidate_id, str(exc))
            return

        result = await redaction.redact(document.text, _known_values(candidate))
        _apply_redaction_metadata(candidate, result, store_text=True)
        candidate.analysis_mode = MODE_REDACTED
        cv_payload = CvPayload(text=result.text, redacted=True)

    await db.commit()

    # --- the provider call -------------------------------------------------
    fiche = FichePayload(
        position=session.position,
        description=session.description,
        language=session.language.value,
        criteria=[
            CriterionSpec(
                id=c.id,
                name=c.name,
                description=c.description,
                weight=c.weight,
                is_must_have=c.is_must_have,
            )
            for c in criteria
        ],
    )

    try:
        analysis = await get_provider().analyze_cv(cv_payload, fiche)
    except LLMError as exc:
        await _mark_failed(db, candidate_id, str(exc))
        return

    await _persist(db, candidate, criteria, analysis, redacted=not use_document_path)


def _known_values(candidate: Candidate) -> redaction.KnownValues:
    """The application form is the most reliable source of identity we have."""
    return redaction.KnownValues(
        full_name=candidate.full_name, email=candidate.email, phone=candidate.phone
    )


def _apply_redaction_metadata(
    candidate: Candidate, result: redaction.RedactionResult, *, store_text: bool
) -> None:
    candidate.redaction_applied = result.applied
    candidate.pii_detected = dict(result.counts)  # types and counts only, never values
    candidate.demographics = dict(result.demographics) or None
    if store_text:
        candidate.cv_text_redacted = result.text

    # Only fill in contact details we did not already have; the form wins.
    contacts = result.contacts
    if not candidate.full_name and contacts.get("full_name"):
        candidate.full_name = contacts["full_name"][:255]
    if not candidate.email and contacts.get("email"):
        candidate.email = contacts["email"][:255]
    if not candidate.phone and contacts.get("phone"):
        candidate.phone = contacts["phone"][:64]


async def _persist(
    db: AsyncSession,
    candidate: Candidate,
    criteria: list[Criterion],
    analysis: AnalysisResult,
    *,
    redacted: bool,
) -> None:
    valid_ids = {c.id for c in criteria}
    scores_by_criterion: dict[str, float] = {}

    # Replace rather than append, so a re-analysis does not leave stale rows.
    # The flush is load-bearing: SQLAlchemy emits INSERTs before DELETEs within
    # one flush, so without it the new scores collide with the old ones on
    # uq_score_candidate_criterion and every re-analysis fails.
    for existing in list(candidate.criterion_scores):
        await db.delete(existing)
    candidate.criterion_scores = []
    await db.flush()

    for item in analysis.criterion_scores:
        if item.criterion_id not in valid_ids:
            logger.warning(
                "provider returned an unknown criterion_id %r for candidate %s",
                item.criterion_id, candidate.id,
            )
            continue
        if item.criterion_id in scores_by_criterion:
            continue  # a duplicate id: keep the first
        scores_by_criterion[item.criterion_id] = float(item.score)
        db.add(
            CriterionScore(
                candidate_id=candidate.id,
                criterion_id=item.criterion_id,
                score=float(item.score),
                justification=item.justification.strip() or None,
            )
        )

    missing_ids = valid_ids - set(scores_by_criterion)
    if missing_ids:
        logger.warning(
            "provider skipped %d/%d criteria for candidate %s",
            len(missing_ids), len(valid_ids), candidate.id,
        )

    outcome = scoring.compute(
        [
            scoring.CriterionInput(c.id, c.name, c.weight, c.is_must_have)
            for c in criteria
        ],
        scores_by_criterion,
    )

    candidate.ai_score = outcome.ai_score
    candidate.ai_recommendation = outcome.recommendation
    candidate.missing_must_haves = outcome.missing_must_haves
    candidate.ai_summary = analysis.summary.strip() or None
    candidate.ai_strengths = [s for s in analysis.strengths if s.strip()]
    candidate.ai_gaps = [g for g in analysis.gaps if g.strip()]

    extracted = analysis.candidate
    if extracted.years_experience is not None:
        candidate.years_experience = extracted.years_experience
    if extracted.education_level:
        candidate.education_level = extracted.education_level[:255]
    if extracted.skills:
        candidate.extracted_skills = extracted.skills

    # On the redacted path the model only ever saw placeholders, so anything it
    # "found" for name/email/phone is a hallucination — ignore it. On the full
    # document path it genuinely read them, so fill gaps only.
    if not redacted:
        if not candidate.full_name and extracted.full_name:
            candidate.full_name = extracted.full_name[:255]
        if not candidate.email and extracted.email:
            candidate.email = extracted.email[:255]
        if not candidate.phone and extracted.phone:
            candidate.phone = extracted.phone[:64]

    candidate.analysis_status = AnalysisStatus.ANALYZED
    candidate.analysis_error = None
    candidate.analyzed_at = utcnow()

    await db.commit()
    logger.info(
        "analysed candidate %s: score=%.1f recommendation=%s%s",
        candidate.id,
        outcome.ai_score,
        outcome.recommendation.value,
        f" missing={outcome.missing_must_haves}" if outcome.missing_must_haves else "",
    )


async def structure_fiche(raw_text: str, language: str = "fr"):
    """Input helper for the session builder — HR reviews every draft criterion."""
    return await get_provider().structure_fiche(raw_text, language)


__all__ = [
    "AnalysisRequest",
    "CandidateSource",
    "analyze_candidate",
    "analyze_many",
    "structure_fiche",
]
