from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import get_session_or_404
from app.deps import CurrentUser, DbSession
from app.models import (
    AnalysisStatus,
    Candidate,
    CandidateSource,
    Criterion,
    HrStatus,
    Recommendation,
)
from app.schemas.candidate import (
    BulkCandidateUpdate,
    CandidateDetail,
    CandidateListItem,
    CandidateUpdate,
    CriterionScoreOut,
    PaginatedCandidates,
    ReanalyzeRequest,
    RedactionSummary,
    UploadResponse,
    UploadResult,
)
from app.services import analysis, audit, redaction, uploads
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["candidates"])

SortField = Literal["score", "-score", "date", "-date", "name", "-name"]


# --- serialisation ----------------------------------------------------------


def to_list_item(candidate: Candidate) -> CandidateListItem:
    item = CandidateListItem.model_validate(candidate)
    item.effective_score = candidate.effective_score
    item.ai_score = float(candidate.ai_score) if candidate.ai_score is not None else None
    item.manual_score = (
        float(candidate.manual_score) if candidate.manual_score is not None else None
    )
    return item


def to_detail(candidate: Candidate, criteria_by_id: dict[str, Criterion]) -> CandidateDetail:
    detail = CandidateDetail.model_validate(candidate)
    detail.effective_score = candidate.effective_score
    detail.ai_score = float(candidate.ai_score) if candidate.ai_score is not None else None
    detail.manual_score = (
        float(candidate.manual_score) if candidate.manual_score is not None else None
    )
    detail.redaction = RedactionSummary(
        applied=candidate.redaction_applied,
        mode=candidate.analysis_mode or "redacted_text",
        counts=candidate.pii_detected or {},
        total=sum((candidate.pii_detected or {}).values()),
    )

    scores = []
    for score in candidate.criterion_scores:
        criterion = criteria_by_id.get(score.criterion_id)
        scores.append(
            CriterionScoreOut(
                criterion_id=score.criterion_id,
                criterion_name=criterion.name if criterion else "—",
                weight=criterion.weight if criterion else 5,
                is_must_have=criterion.is_must_have if criterion else False,
                score=float(score.score),
                justification=score.justification,
            )
        )
    # Same order as the fiche, so the drawer reads like the criteria editor.
    scores.sort(key=lambda s: criteria_by_id[s.criterion_id].display_order
                if s.criterion_id in criteria_by_id else 999)
    detail.criterion_scores = scores
    return detail


async def get_candidate_or_404(db: AsyncSession, candidate_id: str) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return candidate


# --- HR bulk upload ---------------------------------------------------------


@router.post(
    "/sessions/{session_id}/candidates",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_candidates(
    session_id: str,
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    files: list[UploadFile] = File(..., description="One or more CVs (PDF or .docx)"),
    full_name: str | None = Form(default=None, description="Only meaningful for a single file"),
    email: str | None = Form(default=None),
) -> UploadResponse:
    """Accept CVs HR received elsewhere. Returns immediately; analysis runs behind."""
    session = await get_session_or_404(db, session_id)
    if not session.criteria:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Define the criteria for this session before uploading CVs.",
        )

    results: list[UploadResult] = []
    queued: list[str] = []
    single = len(files) == 1

    for upload in files:
        name = upload.filename or "cv"
        try:
            accepted = await uploads.validate(upload)
        except uploads.RejectedUpload as exc:
            results.append(UploadResult(filename=name, accepted=False, error=str(exc)))
            continue

        duplicates = await uploads.find_duplicates(
            db, session_id, cv_hash=accepted.sha256, email=email if single else None
        )
        storage_path = await uploads.store(accepted)

        candidate = Candidate(
            session_id=session_id,
            source=CandidateSource.HR_UPLOAD,
            full_name=(full_name.strip() if full_name and single else None),
            email=(email.strip().lower() if email and single else None),
            cv_filename=accepted.filename,
            cv_storage_path=storage_path,
            cv_mime_type=accepted.mime_type,
            cv_hash=accepted.sha256,
            analysis_status=AnalysisStatus.PENDING,
        )
        db.add(candidate)
        await db.flush()

        queued.append(candidate.id)
        results.append(
            UploadResult(
                filename=accepted.filename,
                candidate_id=candidate.id,
                accepted=True,
                duplicate_of=duplicates[0].candidate_id if duplicates else None,
            )
        )

    if queued:
        await audit.record(
            db,
            action="candidate.upload",
            entity_type="recruitment_session",
            entity_id=session_id,
            user_id=user.id,
            details={"accepted": len(queued), "rejected": len(results) - len(queued)},
        )
    await db.commit()

    if queued:
        background.add_task(analysis.analyze_many, queued)

    return UploadResponse(
        accepted=len(queued), rejected=len(results) - len(queued), results=results
    )


# --- ranked list ------------------------------------------------------------


@router.get("/sessions/{session_id}/candidates", response_model=PaginatedCandidates)
async def list_candidates(
    session_id: str,
    db: DbSession,
    _: CurrentUser,
    analysis_status: AnalysisStatus | None = Query(default=None, alias="status"),
    hr_status: HrStatus | None = None,
    recommendation: Recommendation | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    search: str | None = None,
    sort: SortField = "-score",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> PaginatedCandidates:
    """The live ranking. Ranks are computed over the filtered set, in sort order."""
    await get_session_or_404(db, session_id)

    query = select(Candidate).where(Candidate.session_id == session_id)
    if analysis_status is not None:
        query = query.where(Candidate.analysis_status == analysis_status)
    if hr_status is not None:
        query = query.where(Candidate.hr_status == hr_status)
    if recommendation is not None:
        query = query.where(Candidate.ai_recommendation == recommendation)
    if min_score is not None:
        query = query.where(
            func.coalesce(Candidate.manual_score, Candidate.ai_score) >= min_score
        )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Candidate.full_name.ilike(pattern),
                Candidate.email.ilike(pattern),
                Candidate.cv_filename.ilike(pattern),
            )
        )

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()

    # Effective score = manual override when set, else the AI score.
    effective = func.coalesce(Candidate.manual_score, Candidate.ai_score)
    order = {
        "score": effective.asc().nulls_last(),
        "-score": effective.desc().nulls_last(),
        "date": Candidate.submitted_at.asc(),
        "-date": Candidate.submitted_at.desc(),
        "name": Candidate.full_name.asc().nulls_last(),
        "-name": Candidate.full_name.desc().nulls_last(),
    }[sort]

    rows = (
        await db.execute(
            query.order_by(order, Candidate.submitted_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()

    pending = (
        await db.execute(
            select(func.count())
            .select_from(Candidate)
            .where(
                Candidate.session_id == session_id,
                Candidate.analysis_status.in_(
                    (AnalysisStatus.PENDING, AnalysisStatus.PROCESSING)
                ),
            )
        )
    ).scalar_one()

    items = []
    for offset, candidate in enumerate(rows):
        item = to_list_item(candidate)
        item.rank = (page - 1) * page_size + offset + 1
        item.duplicates = await uploads.find_duplicates(
            db,
            session_id,
            cv_hash=candidate.cv_hash,
            email=candidate.email,
            exclude_id=candidate.id,
        )
        items.append(item)

    return PaginatedCandidates(
        items=items, total=total, page=page, page_size=page_size, pending_count=pending
    )


# --- detail and overrides ---------------------------------------------------


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(candidate_id: str, db: DbSession, _: CurrentUser) -> CandidateDetail:
    candidate = await get_candidate_or_404(db, candidate_id)
    criteria = (
        await db.execute(select(Criterion).where(Criterion.session_id == candidate.session_id))
    ).scalars()
    detail = to_detail(candidate, {c.id: c for c in criteria})
    detail.duplicates = await uploads.find_duplicates(
        db,
        candidate.session_id,
        cv_hash=candidate.cv_hash,
        email=candidate.email,
        exclude_id=candidate.id,
    )
    return detail


@router.patch("/candidates/{candidate_id}", response_model=CandidateDetail)
async def update_candidate(
    candidate_id: str, payload: CandidateUpdate, db: DbSession, user: CurrentUser
) -> CandidateDetail:
    """HR's override. Every change here lands in the audit log — the tool ranks,
    a person decides, and the record shows which."""
    candidate = await get_candidate_or_404(db, candidate_id)
    before = {
        "hr_status": candidate.hr_status.value,
        "manual_score": float(candidate.manual_score)
        if candidate.manual_score is not None
        else None,
    }

    if payload.clear_manual_score:
        candidate.manual_score = None
    elif payload.manual_score is not None:
        candidate.manual_score = payload.manual_score
    if payload.hr_status is not None:
        candidate.hr_status = payload.hr_status
    if payload.hr_notes is not None:
        candidate.hr_notes = payload.hr_notes

    after = {
        "hr_status": candidate.hr_status.value,
        "manual_score": float(candidate.manual_score)
        if candidate.manual_score is not None
        else None,
    }
    if before != after or payload.hr_notes is not None:
        await audit.record(
            db,
            action="candidate.override",
            entity_type="candidate",
            entity_id=candidate.id,
            user_id=user.id,
            details={
                "before": before,
                "after": after,
                "ai_score": float(candidate.ai_score) if candidate.ai_score is not None else None,
                "notes_changed": payload.hr_notes is not None,
            },
        )
    await db.commit()
    await db.refresh(candidate)
    return await get_candidate(candidate_id, db, user)


@router.post("/sessions/{session_id}/candidates/bulk", response_model=dict)
async def bulk_update(
    session_id: str, payload: BulkCandidateUpdate, db: DbSession, user: CurrentUser
) -> dict:
    candidates = (
        await db.execute(
            select(Candidate).where(
                Candidate.session_id == session_id,
                Candidate.id.in_(payload.candidate_ids),
            )
        )
    ).scalars()

    updated = 0
    for candidate in candidates:
        candidate.hr_status = payload.hr_status
        updated += 1

    if updated:
        await audit.record(
            db,
            action="candidate.bulk_status",
            entity_type="recruitment_session",
            entity_id=session_id,
            user_id=user.id,
            details={"hr_status": payload.hr_status.value, "count": updated},
        )
    await db.commit()
    return {"updated": updated}


@router.post("/candidates/{candidate_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze(
    candidate_id: str,
    payload: ReanalyzeRequest,
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    """Re-run the analysis. `full_document=true` sends the ORIGINAL, UNREDACTED
    file to the provider — the UI must confirm that explicitly, and it is
    recorded here against the user who asked for it."""
    candidate = await get_candidate_or_404(db, candidate_id)

    candidate.analysis_status = AnalysisStatus.PENDING
    candidate.analysis_error = None

    await audit.record(
        db,
        action="candidate.reanalyze_full_document"
        if payload.full_document
        else "candidate.reanalyze",
        entity_type="candidate",
        entity_id=candidate.id,
        user_id=user.id,
        details={
            "redaction_bypassed": payload.full_document,
            "cv_filename": candidate.cv_filename,
            "session_id": candidate.session_id,
        },
    )
    await db.commit()

    if payload.full_document:
        logger.warning(
            "REDACTION BYPASSED: user %s sent the unredacted CV of candidate %s to the "
            "%s provider",
            user.email, candidate.id, "configured",
        )

    background.add_task(
        analysis.analyze_candidate, candidate.id, force_full_document=payload.full_document
    )
    return {"status": "queued", "candidate_id": candidate.id}


@router.get("/candidates/{candidate_id}/cv")
async def download_cv(candidate_id: str, db: DbSession, _: CurrentUser) -> StreamingResponse:
    candidate = await get_candidate_or_404(db, candidate_id)
    if not candidate.cv_storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No CV file is attached")

    storage = get_storage()
    if not await storage.exists(candidate.cv_storage_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored CV file is missing")

    return StreamingResponse(
        storage.stream(candidate.cv_storage_path),
        media_type=candidate.cv_mime_type or "application/octet-stream",
        headers={
            # inline so the dashboard can preview the PDF in an iframe
            "Content-Disposition": f'inline; filename="{candidate.cv_filename or "cv.pdf"}"'
        },
    )


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(candidate_id: str, db: DbSession, user: CurrentUser) -> Response:
    candidate = await get_candidate_or_404(db, candidate_id)
    storage_path = candidate.cv_storage_path

    await audit.record(
        db,
        action="candidate.delete",
        entity_type="candidate",
        entity_id=candidate.id,
        user_id=user.id,
        details={"session_id": candidate.session_id, "cv_filename": candidate.cv_filename},
    )
    await db.delete(candidate)
    await db.commit()

    if storage_path:
        try:
            await get_storage().delete(storage_path)
        except Exception:
            logger.warning("could not delete stored CV %s", storage_path, exc_info=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidates/{candidate_id}/redaction-preview", response_model=dict)
async def redaction_preview(candidate_id: str, db: DbSession, _: CurrentUser) -> dict:
    """Exactly what was sent to the provider, for the privacy panel and for the
    acceptance check that no name, email, phone or address leaves the system."""
    candidate = await get_candidate_or_404(db, candidate_id)
    counts = candidate.pii_detected or {}
    return {
        "redaction_applied": candidate.redaction_applied,
        "mode": candidate.analysis_mode,
        "counts": counts,
        "summary_en": redaction.describe(counts, "en"),
        "summary_fr": redaction.describe(counts, "fr"),
        "payload_sent": candidate.cv_text_redacted,
        "demographics_visible_to_hr": candidate.demographics,
    }
