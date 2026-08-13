from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScoreBucket(BaseModel):
    label: str  # "0-19", "20-39", ...
    count: int


class SessionStats(BaseModel):
    total_candidates: int = 0
    by_recommendation: dict[str, int] = Field(default_factory=dict)
    by_hr_status: dict[str, int] = Field(default_factory=dict)
    by_analysis_status: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    average_score: float | None = None
    median_score: float | None = None
    above_threshold: int = 0
    score_threshold: int = 60
    distribution: list[ScoreBucket] = Field(default_factory=list)


class AuditLogOut(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None
    user_id: str | None
    user_name: str | None = None
    details: dict | None = None
    created_at: datetime


class SettingsOut(BaseModel):
    """Surfaced in the dashboard so the deployment's privacy posture is visible."""

    llm_provider: str
    llm_model: str
    pii_redaction: bool
    redact_demographics: bool
    max_upload_mb: int
    storage_backend: str
    spacy_models_loaded: list[str] = Field(default_factory=list)
