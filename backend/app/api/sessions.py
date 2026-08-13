from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession
from app.llm.base import LLMError
from app.models import (
    AnalysisStatus,
    Candidate,
    Criterion,
    HrStatus,
    RecruitmentSession,
    SessionStatus,
    new_public_key,
)
from app.models.base import utcnow
from app.schemas.session import (
    CandidateCounts,
    CriterionDraft,
    CriterionOut,
    DuplicateSessionRequest,
    SessionCreate,
    SessionListItem,
    SessionOut,
    SessionUpdate,
    StructureFicheRequest,
    StructureFicheResponse,
)
from app.services import analysis, audit

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Once a candidate has been analysed, the criteria and weights that produced
# every existing score are frozen. Editing them would silently invalidate the
# ranking, so we offer "duplicate session" instead.
LOCKING_STATUSES = (AnalysisStatus.ANALYZED, AnalysisStatus.PROCESSING)


async def _counts(db: AsyncSession, session_id: str) -> CandidateCounts:
    rows = await db.execute(
        select(Candidate.analysis_status, Candidate.hr_status, func.count())
        .where(Candidate.session_id == session_id)
        .group_by(Candidate.analysis_status, Candidate.hr_status)
    )
    counts = CandidateCounts()
    for analysis_status, hr_status, n in rows:
        counts.total += n
        match analysis_status:
            case AnalysisStatus.PENDING:
                counts.pending += n
            case AnalysisStatus.PROCESSING:
                counts.processing += n
            case AnalysisStatus.ANALYZED:
                counts.analyzed += n
            case AnalysisStatus.FAILED:
                counts.failed += n
        if hr_status == HrStatus.SHORTLISTED:
            counts.shortlisted += n
        elif hr_status == HrStatus.REJECTED:
            counts.rejected += n
    return counts


async def criteria_locked(db: AsyncSession, session_id: str) -> bool:
    result = await db.execute(
        select(Candidate.id)
        .where(
            Candidate.session_id == session_id,
            Candidate.analysis_status.in_(LOCKING_STATUSES),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_session_or_404(db: AsyncSession, session_id: str) -> RecruitmentSession:
    session = await db.get(RecruitmentSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recruitment session not found")
    return session


async def _to_out(db: AsyncSession, session: RecruitmentSession) -> SessionOut:
    out = SessionOut.model_validate(session)
    out.counts = await _counts(db, session.id)
    out.criteria_locked = await criteria_locked(db, session.id)
    # Retention only starts counting once the session is closed.
    if session.retention_days and session.closed_at:
        out.retention_deletes_at = session.closed_at + timedelta(days=session.retention_days)
    return out


def _replace_criteria(session: RecruitmentSession, criteria: list) -> None:
    session.criteria.clear()
    for index, spec in enumerate(criteria):
        session.criteria.append(
            Criterion(
                name=spec.name,
                description=spec.description,
                weight=spec.weight,
                is_must_have=spec.is_must_have,
                display_order=spec.display_order or index,
            )
        )


@router.post("/structure-fiche", response_model=StructureFicheResponse)
async def structure_fiche(
    payload: StructureFicheRequest, _: CurrentUser
) -> StructureFicheResponse:
    """Turn a pasted job description into draft criteria. Nothing is persisted —
    HR reviews and edits every draft in the builder before the session opens."""
    try:
        drafts = await analysis.structure_fiche(payload.raw_text, payload.language.value)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if not drafts:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No criteria could be drawn from that text. Try pasting a fuller job description.",
        )
    # The LLM layer has its own CriterionDraft DTO; convert to the API schema.
    return StructureFicheResponse(
        criteria=[CriterionDraft.model_validate(d.model_dump()) for d in drafts]
    )


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate, db: DbSession, user: CurrentUser
) -> SessionOut:
    session = RecruitmentSession(
        title=payload.title,
        position=payload.position,
        description=payload.description,
        department=payload.department,
        language=payload.language,
        status=payload.status,
        score_threshold=payload.score_threshold,
        accepts_public_applications=payload.accepts_public_applications,
        retention_days=payload.retention_days,
        created_by_id=user.id,
        public_key=new_public_key(),
    )
    _replace_criteria(session, payload.criteria)
    db.add(session)
    await db.flush()

    await audit.record(
        db,
        action="session.create",
        entity_type="recruitment_session",
        entity_id=session.id,
        user_id=user.id,
        details={"title": session.title, "criteria": len(session.criteria)},
    )
    await db.commit()
    await db.refresh(session)
    return await _to_out(db, session)


@router.get("", response_model=list[SessionListItem])
async def list_sessions(
    db: DbSession,
    _: CurrentUser,
    session_status: SessionStatus | None = Query(default=None, alias="status"),
    search: str | None = None,
) -> list[SessionListItem]:
    query = select(RecruitmentSession).order_by(RecruitmentSession.created_at.desc())
    if session_status is not None:
        query = query.where(RecruitmentSession.status == session_status)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            RecruitmentSession.title.ilike(pattern)
            | RecruitmentSession.position.ilike(pattern)
        )

    sessions = list((await db.execute(query)).scalars())
    items = []
    for session in sessions:
        item = SessionListItem.model_validate(session)
        item.criteria_count = len(session.criteria)
        item.counts = await _counts(db, session.id)
        items.append(item)
    return items


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, db: DbSession, _: CurrentUser) -> SessionOut:
    return await _to_out(db, await get_session_or_404(db, session_id))


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str, payload: SessionUpdate, db: DbSession, user: CurrentUser
) -> SessionOut:
    session = await get_session_or_404(db, session_id)

    if payload.criteria is not None:
        if await criteria_locked(db, session_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Candidates have already been scored against these criteria. Changing "
                "the weights now would invalidate every existing score — duplicate the "
                "session instead and start a fresh ranking.",
            )
        if not payload.criteria:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A session needs at least one criterion.",
            )
        _replace_criteria(session, payload.criteria)

    changed = payload.model_dump(exclude_unset=True, exclude={"criteria"})
    for field, value in changed.items():
        setattr(session, field, value)

    if session.status == SessionStatus.OPEN and not session.criteria:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A session cannot be opened without at least one criterion.",
        )
    if session.status == SessionStatus.CLOSED and session.closed_at is None:
        session.closed_at = utcnow()

    await audit.record(
        db,
        action="session.update",
        entity_type="recruitment_session",
        entity_id=session.id,
        user_id=user.id,
        details={"fields": sorted(changed), "criteria_replaced": payload.criteria is not None},
    )
    await db.commit()
    await db.refresh(session)
    return await _to_out(db, session)


@router.post("/{session_id}/duplicate", response_model=SessionOut, status_code=201)
async def duplicate_session(
    session_id: str, payload: DuplicateSessionRequest, db: DbSession, user: CurrentUser
) -> SessionOut:
    """Copy the fiche and its criteria into a fresh DRAFT session — no candidates.

    This is the offered alternative when criteria are locked.
    """
    original = await get_session_or_404(db, session_id)

    copy = RecruitmentSession(
        title=payload.title or f"{original.title} (copie)",
        position=original.position,
        description=original.description,
        department=original.department,
        language=original.language,
        status=SessionStatus.DRAFT,
        score_threshold=original.score_threshold,
        accepts_public_applications=original.accepts_public_applications,
        retention_days=original.retention_days,
        created_by_id=user.id,
        public_key=new_public_key(),
    )
    for criterion in original.criteria:
        copy.criteria.append(
            Criterion(
                name=criterion.name,
                description=criterion.description,
                weight=criterion.weight,
                is_must_have=criterion.is_must_have,
                display_order=criterion.display_order,
            )
        )

    db.add(copy)
    await db.flush()
    await audit.record(
        db,
        action="session.duplicate",
        entity_type="recruitment_session",
        entity_id=copy.id,
        user_id=user.id,
        details={"source_session_id": original.id},
    )
    await db.commit()
    await db.refresh(copy)
    return await _to_out(db, copy)


async def _transition(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    new_status: SessionStatus,
    action: str,
) -> SessionOut:
    session = await get_session_or_404(db, session_id)
    session.status = new_status
    if new_status == SessionStatus.CLOSED:
        session.closed_at = utcnow()
        session.accepts_public_applications = False
    await audit.record(
        db,
        action=action,
        entity_type="recruitment_session",
        entity_id=session.id,
        user_id=user_id,
    )
    await db.commit()
    await db.refresh(session)
    return await _to_out(db, session)


@router.post("/{session_id}/open", response_model=SessionOut)
async def open_session(session_id: str, db: DbSession, user: CurrentUser) -> SessionOut:
    session = await get_session_or_404(db, session_id)
    if not session.criteria:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Add at least one criterion before opening this session.",
        )
    return await _transition(db, session_id, user.id, SessionStatus.OPEN, "session.open")


@router.post("/{session_id}/close", response_model=SessionOut)
async def close_session(session_id: str, db: DbSession, user: CurrentUser) -> SessionOut:
    return await _transition(db, session_id, user.id, SessionStatus.CLOSED, "session.close")


@router.post("/{session_id}/archive", response_model=SessionOut)
async def archive_session(session_id: str, db: DbSession, user: CurrentUser) -> SessionOut:
    return await _transition(db, session_id, user.id, SessionStatus.ARCHIVED, "session.archive")


@router.get("/{session_id}/criteria", response_model=list[CriterionOut])
async def list_criteria(session_id: str, db: DbSession, _: CurrentUser) -> list[Criterion]:
    session = await get_session_or_404(db, session_id)
    return list(session.criteria)
