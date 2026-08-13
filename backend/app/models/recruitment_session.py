from __future__ import annotations

import secrets
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk
from app.models.enums import Language, SessionStatus


def new_public_key() -> str:
    """32 URL-safe characters. Used by the widget and the public apply page."""
    return secrets.token_urlsafe(24)[:32]


class RecruitmentSession(Base, TimestampMixin):
    __tablename__ = "recruitment_session"

    id: Mapped[str] = uuid_pk()
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    department: Mapped[str | None] = mapped_column(sa.String(255))
    status: Mapped[SessionStatus] = mapped_column(
        sa.Enum(SessionStatus, name="session_status"),
        default=SessionStatus.DRAFT,
        nullable=False,
    )
    language: Mapped[Language] = mapped_column(
        sa.Enum(Language, name="session_language"), default=Language.FR, nullable=False
    )
    score_threshold: Mapped[int] = mapped_column(sa.Integer, default=60, nullable=False)
    public_key: Mapped[str] = mapped_column(
        sa.String(32), unique=True, index=True, default=new_public_key, nullable=False
    )
    accepts_public_applications: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, nullable=False
    )
    retention_days: Mapped[int | None] = mapped_column(sa.Integer)

    created_by_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime)

    criteria: Mapped[list["Criterion"]] = relationship(  # noqa: F821
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Criterion.display_order",
        lazy="selectin",
    )
    candidates: Mapped[list["Candidate"]] = relationship(  # noqa: F821
        back_populates="session", cascade="all, delete-orphan", lazy="noload"
    )
    created_by: Mapped["User | None"] = relationship(lazy="selectin")  # noqa: F821
