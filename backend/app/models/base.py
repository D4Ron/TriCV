from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

# JSONB on PostgreSQL, plain JSON elsewhere (the test suite runs on SQLite).
JsonB = JSON().with_variant(JSONB(), "postgresql")


def uuid_pk() -> Mapped[str]:
    return mapped_column(
        sa.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=utcnow, nullable=False
    )
