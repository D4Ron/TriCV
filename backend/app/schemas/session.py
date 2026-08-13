from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import Language, SessionStatus


class CriterionBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    weight: int = Field(default=5, ge=1, le=10)
    is_must_have: bool = False
    display_order: int = 0


class CriterionCreate(CriterionBase):
    pass


class CriterionOut(CriterionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str


class CriterionDraft(BaseModel):
    """Output of `structure_fiche`. Never persisted directly — HR reviews first."""

    name: str
    description: str | None = None
    weight: int = Field(default=5, ge=1, le=10)
    is_must_have: bool = False


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    position: str = Field(min_length=1, max_length=255)
    description: str | None = None
    department: str | None = None
    language: Language = Language.FR
    status: SessionStatus = SessionStatus.DRAFT
    score_threshold: int = Field(default=60, ge=0, le=100)
    accepts_public_applications: bool = True
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    criteria: list[CriterionCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _open_sessions_need_criteria(self) -> "SessionCreate":
        if self.status == SessionStatus.OPEN and not self.criteria:
            raise ValueError("a session cannot be opened without at least one criterion")
        return self


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    position: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    department: str | None = None
    language: Language | None = None
    status: SessionStatus | None = None
    score_threshold: int | None = Field(default=None, ge=0, le=100)
    accepts_public_applications: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    # Omit to leave criteria untouched. Sending a list replaces the whole set,
    # and is rejected once any candidate has been analysed.
    criteria: list[CriterionCreate] | None = None


class CandidateCounts(BaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    analyzed: int = 0
    failed: int = 0
    shortlisted: int = 0
    rejected: int = 0


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    position: str
    description: str | None
    department: str | None
    status: SessionStatus
    language: Language
    score_threshold: int
    public_key: str
    accepts_public_applications: bool
    retention_days: int | None
    created_by_id: str | None
    created_at: datetime
    closed_at: datetime | None
    criteria: list[CriterionOut] = Field(default_factory=list)
    counts: CandidateCounts = Field(default_factory=CandidateCounts)
    criteria_locked: bool = False
    # When the retention sweep will delete this session's candidates. Null when
    # no retention is set or the session is still open. The dashboard warns on
    # it so a deletion is never a surprise.
    retention_deletes_at: datetime | None = None


class SessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    position: str
    department: str | None
    status: SessionStatus
    language: Language
    created_at: datetime
    criteria_count: int = 0
    counts: CandidateCounts = Field(default_factory=CandidateCounts)


class PublicSessionOut(BaseModel):
    """What an unauthenticated applicant (or the widget) is allowed to see."""

    title: str
    position: str
    description: str | None
    department: str | None
    language: Language
    accepts_applications: bool


class PublicRoleItem(BaseModel):
    """One card on the public careers index.

    Deliberately narrow: a candidate must never see criteria, weights, score
    thresholds, or how many other people applied.
    """

    public_key: str
    title: str
    position: str
    department: str | None
    description: str | None
    language: Language
    posted_at: datetime


class StructureFicheRequest(BaseModel):
    raw_text: str = Field(min_length=20)
    language: Language = Language.FR


class StructureFicheResponse(BaseModel):
    criteria: list[CriterionDraft]


class DuplicateSessionRequest(BaseModel):
    title: str | None = None
