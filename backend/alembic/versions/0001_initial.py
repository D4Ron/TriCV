"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "RECRUITER", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "recruitment_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("position", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("department", sa.String(255)),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "OPEN", "CLOSED", "ARCHIVED", name="session_status"),
            nullable=False,
        ),
        sa.Column("language", sa.Enum("FR", "EN", name="session_language"), nullable=False),
        sa.Column("score_threshold", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.String(32), nullable=False),
        sa.Column("accepts_public_applications", sa.Boolean(), nullable=False),
        sa.Column("retention_days", sa.Integer()),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_recruitment_session_public_key", "recruitment_session", ["public_key"], unique=True
    )

    op.create_table(
        "criterion",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("recruitment_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("is_must_have", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("weight >= 1 AND weight <= 10", name="ck_criterion_weight"),
    )
    op.create_index("ix_criterion_session_id", "criterion", ["session_id"])

    op.create_table(
        "candidate",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("recruitment_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(255)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(64)),
        sa.Column(
            "source",
            sa.Enum("PUBLIC_FORM", "HR_UPLOAD", name="candidate_source"),
            nullable=False,
        ),
        sa.Column("cv_text_redacted", sa.Text()),
        sa.Column("pii_detected", JSONB),
        sa.Column("redaction_applied", sa.Boolean(), nullable=False),
        sa.Column("demographics", JSONB),
        sa.Column("cv_filename", sa.String(512)),
        sa.Column("cv_storage_path", sa.String(512)),
        sa.Column("cv_mime_type", sa.String(128)),
        sa.Column("cv_hash", sa.String(64)),
        sa.Column("years_experience", sa.Integer()),
        sa.Column("education_level", sa.String(255)),
        sa.Column("extracted_skills", JSONB),
        sa.Column(
            "analysis_status",
            sa.Enum("PENDING", "PROCESSING", "ANALYZED", "FAILED", name="analysis_status"),
            nullable=False,
        ),
        sa.Column("analysis_error", sa.Text()),
        sa.Column("analysis_mode", sa.String(32)),
        sa.Column("ai_score", sa.Numeric(5, 2)),
        sa.Column(
            "ai_recommendation",
            sa.Enum("STRONG_FIT", "FIT", "MAYBE", "NOT_FIT", name="recommendation"),
        ),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("ai_strengths", JSONB),
        sa.Column("ai_gaps", JSONB),
        sa.Column("missing_must_haves", JSONB),
        sa.Column("manual_score", sa.Numeric(5, 2)),
        sa.Column(
            "hr_status",
            sa.Enum("NEW", "SHORTLISTED", "MAYBE", "REJECTED", name="hr_status"),
            nullable=False,
        ),
        sa.Column("hr_notes", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime()),
    )
    op.create_index("ix_candidate_session_id", "candidate", ["session_id"])
    op.create_index("ix_candidate_email", "candidate", ["email"])
    op.create_index("ix_candidate_cv_hash", "candidate", ["cv_hash"])
    op.create_index("ix_candidate_session_hash", "candidate", ["session_id", "cv_hash"])
    op.create_index("ix_candidate_session_status", "candidate", ["session_id", "analysis_status"])

    op.create_table(
        "criterion_score",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criterion_id",
            sa.String(36),
            sa.ForeignKey("criterion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("justification", sa.Text()),
        sa.UniqueConstraint("candidate_id", "criterion_id", name="uq_score_candidate_criterion"),
    )
    op.create_index("ix_criterion_score_candidate_id", "criterion_score", ["candidate_id"])
    op.create_index("ix_criterion_score_criterion_id", "criterion_score", ["criterion_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36)),
        sa.Column("details", JSONB),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("criterion_score")
    op.drop_table("candidate")
    op.drop_table("criterion")
    op.drop_table("recruitment_session")
    op.drop_table("user")
    for enum_name in (
        "hr_status",
        "recommendation",
        "analysis_status",
        "candidate_source",
        "session_status",
        "session_language",
        "user_role",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
