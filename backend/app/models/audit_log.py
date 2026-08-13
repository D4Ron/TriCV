from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JsonB, TimestampMixin, uuid_pk


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(sa.String(36), index=True)
    details: Mapped[dict | None] = mapped_column(JsonB)

    user: Mapped["User | None"] = relationship(lazy="selectin")  # noqa: F821
