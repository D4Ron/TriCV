from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JsonB, uuid_pk, utcnow
from app.models.enums import AnalysisStatus, CandidateSource, HrStatus, Recommendation


class Candidate(Base):
    __tablename__ = "candidate"
    # No unique constraint on (session_id, cv_hash): duplicates are surfaced in
    # the UI so HR decides, rather than rejected at the door.
    __table_args__ = (
        sa.Index("ix_candidate_session_hash", "session_id", "cv_hash"),
        sa.Index("ix_candidate_session_status", "session_id", "analysis_status"),
    )

    id: Mapped[str] = uuid_pk()
    session_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("recruitment_session.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Identity. Populated from the application form, the HR uploader, or
    # redaction's own detection — never from anything the provider returned
    # while redaction is on, since the provider never saw it.
    full_name: Mapped[str | None] = mapped_column(sa.String(255))
    email: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    phone: Mapped[str | None] = mapped_column(sa.String(64))
    source: Mapped[CandidateSource] = mapped_column(
        sa.Enum(CandidateSource, name="candidate_source"), nullable=False
    )

    # Privacy trail.
    cv_text_redacted: Mapped[str | None] = mapped_column(sa.Text)
    pii_detected: Mapped[dict | None] = mapped_column(JsonB)
    redaction_applied: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    # Demographic attributes are stored and shown to HR but kept out of the
    # scoring payload when REDACT_DEMOGRAPHICS is on.
    demographics: Mapped[dict | None] = mapped_column(JsonB)

    # File.
    cv_filename: Mapped[str | None] = mapped_column(sa.String(512))
    cv_storage_path: Mapped[str | None] = mapped_column(sa.String(512))
    cv_mime_type: Mapped[str | None] = mapped_column(sa.String(128))
    cv_hash: Mapped[str | None] = mapped_column(sa.String(64), index=True)

    # Extracted profile.
    years_experience: Mapped[int | None] = mapped_column(sa.Integer)
    education_level: Mapped[str | None] = mapped_column(sa.String(255))
    extracted_skills: Mapped[list | None] = mapped_column(JsonB)

    # Analysis.
    analysis_status: Mapped[AnalysisStatus] = mapped_column(
        sa.Enum(AnalysisStatus, name="analysis_status"),
        default=AnalysisStatus.PENDING,
        nullable=False,
    )
    analysis_error: Mapped[str | None] = mapped_column(sa.Text)
    analysis_mode: Mapped[str | None] = mapped_column(sa.String(32))  # redacted_text | full_document
    ai_score: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    ai_recommendation: Mapped[Recommendation | None] = mapped_column(
        sa.Enum(Recommendation, name="recommendation")
    )
    ai_summary: Mapped[str | None] = mapped_column(sa.Text)
    ai_strengths: Mapped[list | None] = mapped_column(JsonB)
    ai_gaps: Mapped[list | None] = mapped_column(JsonB)
    missing_must_haves: Mapped[list | None] = mapped_column(JsonB)

    # HR's decision. The product ranks; a human decides.
    manual_score: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    hr_status: Mapped[HrStatus] = mapped_column(
        sa.Enum(HrStatus, name="hr_status"), default=HrStatus.NEW, nullable=False
    )
    hr_notes: Mapped[str | None] = mapped_column(sa.Text)

    submitted_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, nullable=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(sa.DateTime)

    session: Mapped["RecruitmentSession"] = relationship(back_populates="candidates")  # noqa: F821
    criterion_scores: Mapped[list["CriterionScore"]] = relationship(  # noqa: F821
        back_populates="candidate", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def effective_score(self) -> float | None:
        score = self.manual_score if self.manual_score is not None else self.ai_score
        return float(score) if score is not None else None
