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
    LLMIndisponible,
    LLMQuotaError,
    modele_configure,
)

logger = logging.getLogger(__name__)

# Google retire ses modèles vite, et sature les plus récents. Constaté en
# production : gemini-2.0-flash puis 2.5-flash refusés aux nouveaux comptes
# (HTTP 404) ; gemini-3.8-flash, celui que Google désigne à leur place, en
# « forte demande » (HTTP 503) ou répondant en 70 à 130 s. Mesuré le
# 02/11/2026 avec un simple « OK » : 3.6-flash en 2 à 3 s, 3.5-flash en 3 à 7 s,
# 3.5-flash-lite en 1 s.
DEFAULT_MODEL = "gemini-3.6-flash"

# Les modèles essayés, dans l'ordre, après celui qui est réglé, quand il est
# saturé, retiré ou muet. Un seul essai chacun : insister quatre fois sur un
# modèle saturé faisait attendre deux minutes un écran qui avait un autre
# modèle sous la main. Celui qui répond devient le modèle du fournisseur
# jusqu'au prochain changement de réglage.
MODELES_DE_REPLI = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
)
# Assez pour dépouiller un CV en PDF ; trop peu pour attendre un modèle
# saturé qui finira peut-être par répondre.
DELAI_PAR_MODELE = 90

# Le dernier modèle qui a répondu, pour que l'essai de l'onglet « État » le
# dise : derrière un repli, ce n'est plus forcément celui qui est réglé.
dernier_modele_servi: str | None = None
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
        self.model = modele_configure("gemini", DEFAULT_MODEL)

    async def complete(
        self,
        system: str,
        user: str,
        attachment: Attachment | None = None,
        *,
        json_mode: bool = True,
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

        generation: dict = {
            "temperature": 0.2,
            # Thinking models (2.5 and later) spend part of this budget on
            # reasoning before they emit a token of JSON — measured at
            # 1300-2000 tokens on a real fiche. At 4096 the JSON is
            # truncated mid-object and arrives as unparseable text.
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        }
        # Le mode JSON était armé sur *tous* les appels. Sur une demande de
        # prose — une section de rapport — il contraint le modèle à rendre du
        # JSON sans lui donner de schéma : il répond `{}`, ou emballe la phrase
        # dans un objet, et c'est cela qui s'imprimait dans le rapport remis au
        # client. Il ne s'arme plus que là où l'on attend vraiment du JSON.
        if json_mode:
            generation["responseMimeType"] = "application/json"

        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation,
        }

        data = await self._appeler(body)

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

    async def _appeler(self, body: dict) -> dict:
        """L'appel, sur le modèle réglé puis sur les suivants s'il ne répond pas.

        Une clé refusée ou une requête mal formée échoue pareil sur tous les
        modèles : elle remonte aussitôt. Seuls passent au suivant un modèle
        absent (404), saturé ou muet, et une allocation épuisée — les quotas
        gratuits de Google se comptent par modèle.
        """
        global dernier_modele_servi
        derniere: LLMError | None = None
        quota_partout = True
        for modele in dict.fromkeys((self.model, *MODELES_DE_REPLI)):
            try:
                data = await http.post_json(
                    f"{API_ROOT}/models/{modele}:generateContent",
                    json=body,
                    headers={"x-goog-api-key": self.api_key, "content-type": "application/json"},
                    provider=f"{self.name}/{modele}",
                    max_attempts=1,
                    timeout=DELAI_PAR_MODELE,
                )
            except LLMIndisponible as exc:
                derniere = exc
                quota_partout = quota_partout and isinstance(exc, LLMQuotaError)
                logger.warning("[gemini] %s indisponible, modèle suivant : %s", modele, exc)
                continue
            except LLMError as exc:
                if not _modele_absent(exc):
                    raise
                derniere = exc
                quota_partout = False
                logger.warning("[gemini] %s absent, modèle suivant : %s", modele, exc)
                continue
            if modele != self.model:
                logger.warning("[gemini] %s ne répondait pas ; %s prend le relais", self.model, modele)
                self.model = modele
            dernier_modele_servi = modele
            return data

        message = f"Aucun modèle Gemini n'a répondu. Dernière erreur : {derniere}"
        # La chaîne de fournisseurs passe au suivant sur l'une comme sur l'autre ;
        # le quota se distingue pour que le message dise la vraie cause.
        if quota_partout:
            raise LLMQuotaError(message)
        raise LLMIndisponible(message)


def _modele_absent(exc: LLMError) -> bool:
    """Un 404 de modèle : retiré, inconnu, ou fermé aux nouveaux comptes."""
    texte = str(exc)
    return "HTTP 404" in texte or "no longer available" in texte or "not found" in texte.lower()
