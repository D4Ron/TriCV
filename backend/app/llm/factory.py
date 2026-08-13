from __future__ import annotations

import logging

from app.config import settings
from app.llm.base import LLMConfigError, LLMProvider

logger = logging.getLogger(__name__)

_instance: LLMProvider | None = None
_instance_key: str | None = None


def build_provider(name: str | None = None) -> LLMProvider:
    """The only place that knows which provider classes exist.

    Switching `LLM_PROVIDER` requires no change anywhere outside `app/llm/`.
    """
    name = (name or settings.llm_provider).lower()

    if name == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider()
    if name == "anthropic":
        from app.llm.anthropic import AnthropicProvider

        return AnthropicProvider()
    if name == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider()

    raise LLMConfigError(
        f"Unknown LLM_PROVIDER {name!r}. Supported values: gemini, anthropic, ollama."
    )


def get_provider() -> LLMProvider:
    """Cached per provider+model so a config change in tests takes effect."""
    global _instance, _instance_key

    key = f"{settings.llm_provider}:{settings.llm_model}"
    if _instance is None or _instance_key != key:
        _instance = build_provider()
        _instance_key = key
        logger.info(
            "LLM provider ready: %s (model=%s)",
            settings.llm_provider,
            settings.llm_model or "provider default",
        )
    return _instance


def reset_provider() -> None:
    global _instance, _instance_key
    _instance = None
    _instance_key = None
