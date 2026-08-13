from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import uuid_pk


class CriterionScore(Base):
    __tablename__ = "criterion_score"
    __table_args__ = (
        sa.UniqueConstraint("candidate_id", "criterion_id", name="uq_score_candidate_criterion"),
    )

    id: Mapped[str] = uuid_pk()
    candidate_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidate.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    criterion_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("criterion.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    score: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    justification: Mapped[str | None] = mapped_column(sa.Text)

    candidate: Mapped["Candidate"] = relationship(back_populates="criterion_scores")  # noqa: F821
    criterion: Mapped["Criterion"] = relationship(lazy="selectin")  # noqa: F821
