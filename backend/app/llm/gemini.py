from __future__ import annotations

import base64

from app.config import settings
from app.llm import http
from app.llm.base import Attachment, BaseLLMProvider, LLMConfigError, LLMError

DEFAULT_MODEL = "gemini-2.0-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS = 8192


class GeminiProvider(BaseLLMProvider):
    """Default provider. Free tier available without a credit card.

    Note the free tier may use submitted content to improve models — see the
    README. Production deployments should use a paid key or the local Ollama
    provider.
    """

    name = "gemini"
    supports_documents = True

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise LLMConfigError("LLM_PROVIDER=gemini requires GEMINI_API_KEY to be set.")
        self.api_key = settings.gemini_api_key
        self.model = settings.llm_model or DEFAULT_MODEL

    async def complete(
        self, system: str, user: str, attachment: Attachment | None = None
    ) -> str:
        parts: list[dict] = [{"text": user}]
        if attachment is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": attachment.mime_type,
                        "data": base64.b64encode(attachment.data).decode(),
                    }
                }
            )

        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                # Thinking models (2.5 and later) spend part of this budget on
                # reasoning before they emit a token of JSON — measured at
                # 1300-2000 tokens on a real fiche. At 4096 the JSON is
                # truncated mid-object and arrives as unparseable text.
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
            },
        }

        data = await http.post_json(
            f"{API_ROOT}/models/{self.model}:generateContent",
            json=body,
            headers={"x-goog-api-key": self.api_key, "content-type": "application/json"},
            provider=self.name,
        )

        candidates = data.get("candidates") or []
        if not candidates:
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            raise LLMError(
                f"Gemini returned no candidates"
                + (f" (blocked: {blocked})" if blocked else f": {str(data)[:300]}")
            )

        finish = candidates[0].get("finishReason", "unknown")
        segments = [
            part["text"]
            for part in (candidates[0].get("content") or {}).get("parts", [])
            if "text" in part
        ]

        # Truncation produces half a JSON object, which would otherwise surface
        # as a baffling parse error. Name the real cause instead.
        if finish == "MAX_TOKENS":
            usage = data.get("usageMetadata", {})
            raise LLMError(
                f"Gemini hit its {MAX_OUTPUT_TOKENS}-token output limit and the response was "
                f"cut short (thinking used {usage.get('thoughtsTokenCount', '?')} tokens). "
                f"Use a smaller model, or fewer criteria on this session."
            )
        if not segments:
            raise LLMError(f"Gemini returned an empty response (finishReason={finish}).")
        return "".join(segments)
