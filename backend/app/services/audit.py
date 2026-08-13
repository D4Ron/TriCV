from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    user_id: str | None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry. The caller owns the commit."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        details=details,
    )
    db.add(entry)
    return entry
