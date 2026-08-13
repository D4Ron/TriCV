from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import uuid_pk


class Criterion(Base):
    __tablename__ = "criterion"
    __table_args__ = (
        sa.CheckConstraint("weight >= 1 AND weight <= 10", name="ck_criterion_weight"),
    )

    id: Mapped[str] = uuid_pk()
    session_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("recruitment_session.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    weight: Mapped[int] = mapped_column(sa.Integer, default=5, nullable=False)
    is_must_have: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    session: Mapped["RecruitmentSession"] = relationship(back_populates="criteria")  # noqa: F821
