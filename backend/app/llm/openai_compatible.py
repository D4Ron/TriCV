"""Un fournisseur pour tout ce qui parle le dialecte d'OpenAI.

Groq, Cerebras, Mistral, OpenRouter, Together, et n'importe quel serveur vLLM
posé sur une machine du cabinet exposent tous le même point d'entrée
`/chat/completions`, avec le même corps de requête. Écrire un fournisseur par
marque reviendrait à recopier quatre fois le même fichier ; ici l'adresse est
une variable de configuration, et changer de fournisseur ne demande pas de
changer de code.

Ce que cela règle concrètement : l'offre gratuite de Gemini plafonne à
250 requêtes par jour sur `gemini-2.5-flash`, pour *toute* l'installation. Un
dépouillement de dossier en coûte une, une section de rapport aussi. Une
matinée de travail à trois personnes y passe. Les offres gratuites de Groq et
de Cerebras sont d'un autre ordre de grandeur, et ne demandent pas de carte
bancaire.

Aucun de ces fournisseurs ne lit un PDF : le texte leur part en clair, expurgé
comme partout ailleurs. C'est déjà le chemin normal quand `PII_REDACTION` est
actif — c'est-à-dire toujours, en production.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.llm import http
from app.llm.base import (
    Attachment,
    BaseLLMProvider,
    LLMConfigError,
    LLMError,
    modele_configure,
)

logger = logging.getLogger(__name__)

# Quelques adresses connues, pour que le message d'erreur puisse en citer une.
# Ce ne sont pas des valeurs par défaut : l'adresse se pose dans `.env`.
ADRESSES_CONNUES = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

MAX_TOKENS = 8192


class OpenAICompatibleProvider(BaseLLMProvider):
    """Tout fournisseur exposant `/chat/completions` à la façon d'OpenAI."""

    name = "openai"
    # Le format `document` d'Anthropic et l'`inline_data` de Gemini n'ont pas
    # d'équivalent ici. Le CV part en texte expurgé, ce qui est de toute façon
    # le chemin recommandé.
    supports_documents = False

    def __init__(self) -> None:
        base = (settings.llm_base_url or "").strip().rstrip("/")
        if not base:
            connues = ", ".join(f"{nom} → {url}" for nom, url in ADRESSES_CONNUES.items())
            raise LLMConfigError(
                "LLM_PROVIDER=openai requires LLM_BASE_URL to be set to the "
                f"provider's OpenAI-compatible endpoint. Known ones: {connues}."
            )
        if not settings.llm_api_key:
            raise LLMConfigError("LLM_PROVIDER=openai requires LLM_API_KEY to be set.")

        modele = modele_configure("openai")
        if not modele:
            raise LLMConfigError(
                "LLM_PROVIDER=openai requires LLM_MODEL (or OPENAI_MODEL) to be set — "
                "these providers have no default model."
            )

        self.base_url = base
        self.api_key = settings.llm_api_key
        self.model = modele

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
                f"The {self.name} provider ({self.base_url}) cannot read documents. "
                "Keep PII_REDACTION=true so the CV is extracted and sent as text."
            )

        corps: dict = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            corps["response_format"] = {"type": "json_object"}

        try:
            data = await self._appeler(corps)
        except LLMError as exc:
            # Tous les modèles n'acceptent pas `response_format`, et ceux qui le
            # refusent répondent 400 — que `post_json` ne retente pas, à raison.
            # Le refus est net et nommé : on réessaie une fois sans, plutôt que
            # de laisser l'utilisateur découvrir qu'un modèle sur trois de son
            # fournisseur ne marche pas. La consigne demande déjà du JSON.
            if not json_mode or "response_format" not in str(exc):
                raise
            logger.warning(
                "[%s] %s n'accepte pas response_format ; nouvel essai sans.",
                self.name,
                self.model,
            )
            corps.pop("response_format")
            data = await self._appeler(corps)

        choix = data.get("choices") or []
        if not choix:
            raise LLMError(f"{self.base_url} returned no choices: {str(data)[:300]}")

        premier = choix[0]
        texte = ((premier.get("message") or {}).get("content") or "").strip()

        if premier.get("finish_reason") == "length":
            raise LLMError(
                f"{self.model} hit its {MAX_TOKENS}-token output limit and the response "
                "was cut short. Use a model with a larger output budget."
            )
        if not texte:
            raise LLMError(
                f"{self.model} returned an empty response "
                f"(finish_reason={premier.get('finish_reason', 'unknown')})."
            )
        return texte

    async def _appeler(self, corps: dict) -> dict:
        return await http.post_json(
            f"{self.base_url}/chat/completions",
            json=corps,
            headers={
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            provider=self.name,
        )
