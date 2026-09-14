from __future__ import annotations

import base64
import logging

from app.config import settings
from app.llm import http
from app.llm.base import (
    Attachment,
    BaseLLMProvider,
    LLMConfigError,
    LLMError,
    LLMQuotaError,
    modele_configure,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# The Messages API takes PDFs natively as a `document` content block. It has no
# equivalent for .docx, so the full-document path is PDF-only here; anything
# else falls back to the extracted text, which is what redaction produces anyway.
PDF_MIME = "application/pdf"


class AnthropicProvider(BaseLLMProvider):
    """Intended production provider for the full-document path.

    It reads PDFs natively — including scanned ones — and paid keys are not
    subject to the free-tier training concerns that apply to unpaid Gemini keys.
    """

    name = "anthropic"
    supports_documents = True

    def __init__(self) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise LLMConfigError(
                "LLM_PROVIDER=anthropic requires the `anthropic` package."
            ) from exc

        if not settings.anthropic_api_key:
            raise LLMConfigError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set.")

        self.model = modele_configure("anthropic", DEFAULT_MODEL)
        # max_retries=0: backoff is handled by app.llm.http.retry_async so every
        # provider retries on the same schedule.
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=float(settings.llm_timeout_seconds),
            max_retries=0,
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        import anthropic

        if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return exc.status_code >= 500
        return False

    async def complete(
        self,
        system: str,
        user: str,
        attachment: Attachment | None = None,
        *,
        json_mode: bool = True,
    ) -> str:
        # `json_mode` ne change rien ici : la Messages API n'a pas de mode JSON
        # global, le format tient à la consigne. Le paramètre existe pour que
        # tous les fournisseurs présentent la même signature.
        import anthropic

        content: list[dict] = []
        if attachment is not None:
            if attachment.mime_type != PDF_MIME:
                raise LLMConfigError(
                    "The full-document path supports PDF only. Convert the CV to PDF, "
                    "or analyse it with redaction on so the text is sent instead."
                )
            # The document block goes before the text block.
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": PDF_MIME,
                        "data": base64.b64encode(attachment.data).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": user})

        async def _call():
            # No temperature/top_p: current models reject sampling parameters.
            return await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": content}],
            )

        try:
            message = await http.retry_async(
                _call, is_retryable=self._is_retryable, provider=self.name
            )
        except anthropic.AuthenticationError as exc:
            raise LLMConfigError(f"Anthropic rejected the API key: {exc}") from exc
        except anthropic.RateLimitError as exc:
            # Survivre aux quatre tentatives veut dire que la limite n'est pas
            # celle de la minute : c'est l'allocation. Une chaîne de secours
            # doit pouvoir le distinguer d'une panne.
            raise LLMQuotaError(f"Anthropic rate limit persists: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (402, 429):
                raise LLMQuotaError(
                    f"Anthropic returned HTTP {exc.status_code}: {exc.message}"
                ) from exc
            raise LLMError(f"Anthropic returned HTTP {exc.status_code}: {exc.message}") from exc

        # A refusal is a successful HTTP 200 with empty or partial content —
        # check it before reading blocks.
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None)
            raise LLMError(
                "Anthropic's safety classifiers declined to analyse this CV"
                + (f" (category: {category})" if category else "")
                + ". Re-run it with a different provider, or review the CV manually."
            )

        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise LLMError(
                f"Anthropic returned an empty response (stop_reason={message.stop_reason})."
            )
        return text
