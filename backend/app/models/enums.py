from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    RECRUITER = "RECRUITER"


class SessionStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class CandidateSource(StrEnum):
    PUBLIC_FORM = "PUBLIC_FORM"
    HR_UPLOAD = "HR_UPLOAD"


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class Recommendation(StrEnum):
    STRONG_FIT = "STRONG_FIT"
    FIT = "FIT"
    MAYBE = "MAYBE"
    NOT_FIT = "NOT_FIT"


class HrStatus(StrEnum):
    NEW = "NEW"
    SHORTLISTED = "SHORTLISTED"
    MAYBE = "MAYBE"
    REJECTED = "REJECTED"


class Language(StrEnum):
    FR = "fr"
    EN = "en"
