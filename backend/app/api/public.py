from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import client_ip
from app.models import AnalysisStatus, Candidate, CandidateSource, RecruitmentSession, SessionStatus
from app.schemas.candidate import PublicApplyResponse
from app.schemas.session import PublicRoleItem, PublicSessionOut
from app.services import analysis, uploads
from app.services.ratelimit import public_limiter

router = APIRouter(prefix="/public", tags=["public"])

# Candidates never see a score, a rank, or another applicant. Everything in this
# router is deliberately minimal about what it exposes.


async def _session_by_key(db: AsyncSession, public_key: str) -> RecruitmentSession:
    result = await db.execute(
        select(RecruitmentSession).where(RecruitmentSession.public_key == public_key)
    )
    session = result.scalar_one_or_none()
    if session is None or session.status == SessionStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This application link is not valid.")
    return session


def _accepting(session: RecruitmentSession) -> bool:
    return session.accepts_public_applications and session.status == SessionStatus.OPEN


@router.get("/roles", response_model=list[PublicRoleItem])
async def public_roles(db: AsyncSession = Depends(get_db)) -> list[PublicRoleItem]:
    """The careers index: every role currently open to public applications.

    Unauthenticated, so it is scoped tightly — only OPEN sessions that have
    public applications switched on, and only the fields a candidate needs.
    """
    result = await db.execute(
        select(RecruitmentSession)
        .where(
            RecruitmentSession.status == SessionStatus.OPEN,
            RecruitmentSession.accepts_public_applications.is_(True),
        )
        .order_by(RecruitmentSession.created_at.desc())
    )
    return [
        PublicRoleItem(
            public_key=session.public_key,
            title=session.title,
            position=session.position,
            department=session.department,
            description=session.description,
            language=session.language,
            posted_at=session.created_at,
        )
        for session in result.scalars()
    ]


@router.get("/session/{public_key}", response_model=PublicSessionOut)
async def public_session(
    public_key: str, db: AsyncSession = Depends(get_db)
) -> PublicSessionOut:
    """Feeds both the /apply page and the embeddable widget."""
    session = await _session_by_key(db, public_key)
    return PublicSessionOut(
        title=session.title,
        position=session.position,
        description=session.description,
        department=session.department,
        language=session.language,
        accepts_applications=_accepting(session),
    )


@router.post(
    "/apply/{public_key}",
    response_model=PublicApplyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply(
    public_key: str,
    background: BackgroundTasks,
    ip: str = Depends(client_ip),
    db: AsyncSession = Depends(get_db),
    full_name: str = Form(..., min_length=2, max_length=255),
    email: EmailStr = Form(...),
    phone: str | None = Form(default=None, max_length=64),
    cv: UploadFile = File(...),
) -> PublicApplyResponse:
    public_limiter.check(ip)

    session = await _session_by_key(db, public_key)
    if not _accepting(session):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This position is no longer accepting applications.",
        )

    try:
        accepted = await uploads.validate(cv)
    except uploads.RejectedUpload as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    candidate = Candidate(
        session_id=session.id,
        source=CandidateSource.PUBLIC_FORM,
        # These typed values are the most reliable redaction input we get.
        full_name=full_name.strip(),
        email=str(email).lower(),
        phone=phone.strip() if phone else None,
        cv_filename=accepted.filename,
        cv_storage_path=await uploads.store(accepted),
        cv_mime_type=accepted.mime_type,
        cv_hash=accepted.sha256,
        analysis_status=AnalysisStatus.PENDING,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    background.add_task(analysis.analyze_candidate, candidate.id)

    message = (
        "Votre candidature a bien été reçue. Merci !"
        if session.language.value == "fr"
        else "Your application has been received. Thank you!"
    )
    return PublicApplyResponse(message=message, candidate_id=candidate.id)
