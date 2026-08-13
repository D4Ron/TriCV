"""Session-level retention.

Runs once at startup. A session with `retention_days` set has its candidate
files and rows deleted once that many days have passed since it closed. Open
sessions are never swept — retention only starts counting at closure.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, Candidate, RecruitmentSession, SessionStatus
from app.models.base import utcnow
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

SWEEPABLE = (SessionStatus.CLOSED, SessionStatus.ARCHIVED)


async def expired_sessions() -> list[tuple[str, str, int]]:
    """(session_id, title, candidate_count) for everything past retention.

    The dashboard calls this to warn HR *before* a deletion ever runs.
    """
    now = utcnow()
    pending: list[tuple[str, str, int]] = []

    async with SessionLocal() as db:
        sessions = (
            await db.execute(
                select(RecruitmentSession).where(
                    RecruitmentSession.retention_days.is_not(None),
                    RecruitmentSession.status.in_(SWEEPABLE),
                    RecruitmentSession.closed_at.is_not(None),
                )
            )
        ).scalars()

        for session in sessions:
            if session.closed_at + timedelta(days=session.retention_days) > now:
                continue
            candidates = (
                await db.execute(
                    select(Candidate.id).where(Candidate.session_id == session.id)
                )
            ).scalars()
            count = len(list(candidates))
            if count:
                pending.append((session.id, session.title, count))

    return pending


async def run_retention_sweep() -> int:
    now = utcnow()
    deleted = 0

    async with SessionLocal() as db:
        sessions = list(
            (
                await db.execute(
                    select(RecruitmentSession).where(
                        RecruitmentSession.retention_days.is_not(None),
                        RecruitmentSession.status.in_(SWEEPABLE),
                        RecruitmentSession.closed_at.is_not(None),
                    )
                )
            ).scalars()
        )

        for session in sessions:
            if session.closed_at + timedelta(days=session.retention_days) > now:
                continue

            candidates = list(
                (
                    await db.execute(
                        select(Candidate).where(Candidate.session_id == session.id)
                    )
                ).scalars()
            )
            if not candidates:
                continue

            for candidate in candidates:
                if candidate.cv_storage_path:
                    try:
                        await get_storage().delete(candidate.cv_storage_path)
                    except Exception:
                        logger.warning(
                            "retention: could not delete file %s",
                            candidate.cv_storage_path,
                            exc_info=True,
                        )
                await db.delete(candidate)
                deleted += 1

            db.add(
                AuditLog(
                    action="retention.purge",
                    entity_type="recruitment_session",
                    entity_id=session.id,
                    user_id=None,
                    details={
                        "candidates_deleted": len(candidates),
                        "retention_days": session.retention_days,
                        "closed_at": session.closed_at.isoformat(),
                    },
                )
            )
            logger.info(
                "retention: purged %d candidate(s) from session %r (%d-day retention)",
                len(candidates), session.title, session.retention_days,
            )

        await db.commit()

    return deleted
