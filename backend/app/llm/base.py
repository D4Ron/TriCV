from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings
from app.llm import prompts

logger = logging.getLogger(__name__)

# Shared across every provider instance: free tiers rate-limit per key, not per
# object, so the cap has to be global to the process.
_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)


class LLMError(Exception):
    """Anything that stopped us getting a usable answer from the provider."""


class LLMConfigError(LLMError):
    """Missing key, unknown provider, unsupported payload — not worth retrying."""


# --- payloads ---------------------------------------------------------------


@dataclass(slots=True)
class CriterionSpec:
    id: str
    name: str
    description: str | None
    weight: int
    is_must_have: bool


@dataclass(slots=True)
class FichePayload:
    position: str
    description: str | None
    criteria: list[CriterionSpec]
    language: str = "fr"


@dataclass(slots=True)
class CvPayload:
    """Either redacted text (the default) or the original file bytes.

    Exactly one of `text` / `file_bytes` is set. Providers must handle both;
    `ollama` rejects the file form.
    """

    text: str | None = None
    file_bytes: bytes | None = None
    mime_type: str | None = None
    filename: str | None = None
    redacted: bool = True

    @property
    def is_document(self) -> bool:
        return self.file_bytes is not None


# --- validated provider output ---------------------------------------------


class ExtractedCandidate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    years_experience: int | None = Field(default=None, ge=0, le=70)
    education_level: str | None = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("years_experience", mode="before")
    @classmethod
    def _coerce_years(cls, v: object) -> object:
        if isinstance(v, str):
            digits = re.findall(r"\d+", v)
            return int(digits[0]) if digits else None
        if isinstance(v, float):
            return round(v)
        return v


class CriterionScoreResult(BaseModel):
    criterion_id: str
    score: float = Field(ge=0, le=100)
    justification: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v: object) -> object:
        try:
            return max(0.0, min(100.0, float(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("score must be a number between 0 and 100") from None


class AnalysisResult(BaseModel):
    candidate: ExtractedCandidate = Field(default_factory=ExtractedCandidate)
    criterion_scores: list[CriterionScoreResult] = Field(default_factory=list)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class CriterionDraft(BaseModel):
    name: str
    description: str | None = None
    weight: int = Field(default=5, ge=1, le=10)
    is_must_have: bool = False

    @field_validator("weight", mode="before")
    @classmethod
    def _clamp_weight(cls, v: object) -> object:
        try:
            return max(1, min(10, int(float(v))))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 5


class _CriterionDraftList(BaseModel):
    criteria: list[CriterionDraft] = Field(default_factory=list)


# --- JSON recovery ----------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(raw: str) -> dict:
    """Models add fences and preambles despite being told not to. Recover anyway."""
    text = _FENCE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"Provider did not return valid JSON. First 300 chars: {raw[:300]!r}")


# --- the interface ----------------------------------------------------------


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult: ...

    @abstractmethod
    async def structure_fiche(self, raw_text: str, language: str = "fr") -> list[CriterionDraft]: ...


@dataclass(slots=True)
class Attachment:
    data: bytes
    mime_type: str
    filename: str = "cv.pdf"


class BaseLLMProvider(LLMProvider):
    """Prompting, validation and the one-shot repair retry, shared by all providers.

    Concrete providers implement `complete()` and nothing else, which is what
    keeps provider-specific code confined to this package.
    """

    supports_documents: bool = True

    @abstractmethod
    async def complete(
        self, system: str, user: str, attachment: Attachment | None = None
    ) -> str: ...

    async def _guarded(self, system: str, user: str, attachment: Attachment | None) -> str:
        async with _semaphore:
            if settings.llm_log_payload:
                logger.info(
                    "[%s] payload -> provider (%s):\n%s",
                    self.name,
                    "document attached" if attachment else "text only",
                    user,
                )
            return await self.complete(system, user, attachment)

    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult:
        if cv.is_document and not self.supports_documents:
            raise LLMConfigError(
                f"The {self.name} provider cannot accept documents. Enable PII_REDACTION "
                f"so the CV is sent as text, or switch LLM_PROVIDER."
            )

        system = prompts.analysis_system_prompt(fiche.language)
        user = prompts.analysis_user_prompt(fiche, cv_text=cv.text)
        attachment = (
            Attachment(cv.file_bytes, cv.mime_type or "application/pdf", cv.filename or "cv.pdf")
            if cv.is_document and cv.file_bytes
            else None
        )

        raw = await self._guarded(system, user, attachment)
        try:
            return AnalysisResult.model_validate(parse_json_object(raw))
        except (ValidationError, LLMError) as exc:
            # Python unbinds the `as` name when the except block ends, so keep
            # the message before leaving it.
            first_error = str(exc)
            logger.warning("[%s] invalid analysis response, repairing: %s", self.name, first_error)

        repair = prompts.repair_prompt(user, raw, first_error)
        raw_retry = await self._guarded(system, repair, attachment)
        try:
            return AnalysisResult.model_validate(parse_json_object(raw_retry))
        except (ValidationError, LLMError) as second_error:
            raise LLMError(
                f"The model's response did not match the expected schema after a retry: "
                f"{second_error}"
            ) from second_error

    async def structure_fiche(self, raw_text: str, language: str = "fr") -> list[CriterionDraft]:
        system = prompts.fiche_system_prompt(language)
        user = prompts.fiche_user_prompt(raw_text, language)
        raw = await self._guarded(system, user, None)

        data = parse_json_object(raw)
        try:
            return _CriterionDraftList.model_validate(data).criteria
        except ValidationError as exc:
            raise LLMError(f"Could not read draft criteria from the model: {exc}") from exc


# Re-exported so callers never import a concrete provider module.
__all__ = [
    "AnalysisResult",
    "Attachment",
    "BaseLLMProvider",
    "CriterionDraft",
    "CriterionSpec",
    "CvPayload",
    "FichePayload",
    "LLMConfigError",
    "LLMError",
    "LLMProvider",
    "parse_json_object",
]
