from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import AnalysisStatus, CandidateSource, HrStatus, Recommendation


class CriterionScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion_id: str
    criterion_name: str = ""
    weight: int = 5
    is_must_have: bool = False
    score: float
    justification: str | None = None


class DuplicateFlag(BaseModel):
    candidate_id: str
    full_name: str | None
    reason: str  # "identical_file" | "same_email"


class RedactionSummary(BaseModel):
    """Powers the "name, email, phone, 2 URLs hidden from AI" indicator."""

    applied: bool = False
    mode: str = "redacted_text"  # redacted_text | full_document
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class CandidateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rank: int | None = None
    full_name: str | None
    email: EmailStr | None = None
    phone: str | None
    source: CandidateSource
    analysis_status: AnalysisStatus
    analysis_error: str | None = None
    ai_score: float | None
    manual_score: float | None
    effective_score: float | None
    ai_recommendation: Recommendation | None
    hr_status: HrStatus
    years_experience: int | None
    missing_must_haves: list[str] | None = None
    redaction_applied: bool = False
    submitted_at: datetime
    analyzed_at: datetime | None
    duplicates: list[DuplicateFlag] = Field(default_factory=list)


class CandidateDetail(CandidateListItem):
    education_level: str | None = None
    extracted_skills: list[str] | None = None
    ai_summary: str | None = None
    ai_strengths: list[str] | None = None
    ai_gaps: list[str] | None = None
    hr_notes: str | None = None
    cv_filename: str | None = None
    cv_mime_type: str | None = None
    demographics: dict | None = None
    # Filled in by the serialiser after model_validate(); the Candidate row has
    # no `redaction` attribute of its own.
    redaction: RedactionSummary = Field(default_factory=RedactionSummary)
    criterion_scores: list[CriterionScoreOut] = Field(default_factory=list)


class CandidateUpdate(BaseModel):
    hr_status: HrStatus | None = None
    hr_notes: str | None = None
    manual_score: float | None = Field(default=None, ge=0, le=100)
    # Explicitly clear an override rather than leaving it at its old value.
    clear_manual_score: bool = False


class BulkCandidateUpdate(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    hr_status: HrStatus


class ReanalyzeRequest(BaseModel):
    # True sends the original, unredacted file to the provider. The UI must
    # confirm this explicitly; the API writes an audit_log entry either way.
    full_document: bool = False


class PaginatedCandidates(BaseModel):
    items: list[CandidateListItem]
    total: int
    page: int
    page_size: int
    pending_count: int = 0


class PublicApplyResponse(BaseModel):
    ok: bool = True
    message: str
    candidate_id: str


class UploadResult(BaseModel):
    filename: str
    candidate_id: str | None = None
    accepted: bool
    error: str | None = None
    duplicate_of: str | None = None


class UploadResponse(BaseModel):
    accepted: int
    rejected: int
    results: list[UploadResult]
