from __future__ import annotations

from app.config import settings
from app.llm import http
from app.llm.base import (
    Attachment,
    BaseLLMProvider,
    LLMConfigError,
    LLMError,
    modele_configure,
)

DEFAULT_MODEL = "llama3.1"


class OllamaProvider(BaseLLMProvider):
    """Fully local provider — no CV data leaves the deployment.

    This is the answer to the free-tier training concern in the README: with
    `LLM_PROVIDER=ollama` nothing is sent to a third party at all.
    """

    name = "ollama"
    supports_documents = False  # text only, by design

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        if not self.base_url:
            raise LLMConfigError("LLM_PROVIDER=ollama requires OLLAMA_BASE_URL to be set.")
        self.model = modele_configure("ollama", DEFAULT_MODEL)

    async def complete(
        self,
        system: str,
        user: str,
        attachment: Attachment | None = None,
        *,
        json_mode: bool = True,
    ) -> str:
        if attachment is not None:
            raise LLMConfigError(
                "The Ollama provider cannot read documents. Keep PII_REDACTION=true so "
                "the CV is extracted and sent as text."
            )

        corps: dict = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Voir la note du fournisseur Gemini : `format: json` sur une demande de
        # prose faisait rendre au modèle un objet vide plutôt qu'un paragraphe.
        if json_mode:
            corps["format"] = "json"

        data = await http.post_json(
            f"{self.base_url}/api/chat", json=corps, provider=self.name
        )

        content = (data.get("message") or {}).get("content", "")
        if not content.strip():
            raise LLMError(
                f"Ollama returned an empty response. Is the model '{self.model}' pulled? "
                f"Run: ollama pull {self.model}"
            )
        return content
