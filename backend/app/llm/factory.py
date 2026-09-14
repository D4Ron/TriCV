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
    if name == "openai":
        from app.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider()

    raise LLMConfigError(
        f"Unknown LLM_PROVIDER {name!r}. Supported values: gemini, anthropic, "
        f"ollama, openai."
    )


def _noms_de_la_chaine() -> list[str]:
    """Le principal, puis les secours déclarés, sans doublon et dans l'ordre."""
    noms = [settings.llm_provider]
    for nom in settings.llm_fallback.split(","):
        nom = nom.strip().lower()
        if nom and nom not in noms:
            noms.append(nom)
    return noms


def build_chain() -> LLMProvider:
    """Le fournisseur effectif : un seul, ou une chaîne de secours.

    Un fournisseur qu'on ne peut pas construire — clé absente, adresse vide —
    est **écarté**, pas fatal. C'est ce qui permet de préparer la bascule vers
    un nouveau fournisseur avant d'avoir sa clé : la configuration est en place,
    la chaîne retombe sur celui qui marche, et coller la clé suffit à le
    promouvoir. Sans cela, préparer la configuration reviendrait à casser
    l'installation jusqu'à ce que quelqu'un trouve le temps de créer un compte.
    """
    from app.llm.chaine import ChaineFournisseurs

    construits: dict[str, LLMProvider] = {}
    refus: list[str] = []

    for nom in _noms_de_la_chaine():
        try:
            construits[nom] = build_provider(nom)
        except LLMConfigError as exc:
            refus.append(f"{nom} ({exc})")
            logger.info("Fournisseur %s écarté de la chaîne : %s", nom, exc)

    # Le rédacteur, s'il est déclaré et s'il n'est pas déjà de la chaîne.
    redacteur = settings.llm_prose_provider.strip().lower()
    if redacteur and redacteur not in construits:
        try:
            construits[redacteur] = build_provider(redacteur)
        except LLMConfigError as exc:
            refus.append(f"{redacteur} ({exc})")
            logger.info("Rédacteur %s écarté : %s", redacteur, exc)

    if not construits:
        raise LLMConfigError(
            "Aucun fournisseur utilisable. " + " ; ".join(refus)
            if refus
            else "Aucun fournisseur configuré."
        )

    depouilleurs = [construits[n] for n in _noms_de_la_chaine() if n in construits]
    if not depouilleurs:
        # Seul le rédacteur a pu être bâti : il fait tout, faute de mieux.
        depouilleurs = list(construits.values())

    # L'ordre de la prose : le rédacteur d'abord, puis les autres en secours.
    # Un rédacteur muet ou épuisé ne doit pas faire perdre le rapport ; il doit
    # seulement passer en premier.
    prose = None
    if redacteur in construits:
        prose = [construits[redacteur]] + [
            f for f in depouilleurs if f is not construits[redacteur]
        ]

    if len(construits) == 1 and prose is None:
        return depouilleurs[0]
    return ChaineFournisseurs(depouilleurs, prose=prose)


def get_provider() -> LLMProvider:
    """Cached per provider+model so a config change in tests takes effect."""
    global _instance, _instance_key

    key = (
        f"{settings.llm_provider}:{settings.llm_model}:{settings.llm_fallback}"
        f":{settings.llm_prose_provider}"
    )
    if _instance is None or _instance_key != key:
        _instance = build_chain()
        _instance_key = key
        logger.info(
            "LLM provider ready: %s (model=%s)",
            _instance.name,
            settings.llm_model or "provider default",
        )
    return _instance


def reset_provider() -> None:
    global _instance, _instance_key
    _instance = None
    _instance_key = None
