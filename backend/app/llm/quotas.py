"""Ce que les fournisseurs disent de leur quota, relevé au passage.

Aucune offre gratuite ne publie un solde : Mistral annonce sa limite **par
minute** à chaque réponse, Groq ses limites par minute et par jour, Gemini rien.
Seule la consommation se lit partout. Ce module garde le dernier relevé, sans
rien inventer : ce qui n'est pas dit reste vide, et l'écran le dit.

En mémoire seulement : le serveur tourne en un seul processus, et un relevé qui
date d'avant un redémarrage ne vaut plus rien.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True)
class Releve:
    requetes_limite: int | None = None
    requetes_restantes: int | None = None
    jetons_limite: int | None = None
    jetons_restants: int | None = None
    # « minute », ou « jour » chez qui compte ses requêtes à la journée.
    periode_requetes: str = "minute"
    periode_jetons: str = "minute"
    jetons_consommes: int = 0
    appels: int = 0
    instant: float = 0.0


_releves: dict[str, Releve] = {}


def _entier(entetes: Mapping[str, str], cle: str) -> int | None:
    try:
        return int(float(entetes[cle]))
    except (KeyError, TypeError, ValueError):
        return None


def noter_entetes(fournisseur: str, entetes: Mapping[str, str]) -> None:
    releve = _releves.setdefault(fournisseur, Releve())
    # Mistral : tout est par minute, et le dit dans le nom de l'en-tête.
    limite = _entier(entetes, "x-ratelimit-limit-req-minute")
    if limite is not None:
        releve.requetes_limite = limite
        releve.requetes_restantes = _entier(entetes, "x-ratelimit-remaining-req-minute")
        releve.jetons_limite = _entier(entetes, "x-ratelimit-limit-tokens-minute")
        releve.jetons_restants = _entier(entetes, "x-ratelimit-remaining-tokens-minute")
        releve.instant = time.monotonic()
        return
    # Groq : les requêtes au jour, les jetons à la minute.
    limite = _entier(entetes, "x-ratelimit-limit-requests")
    if limite is not None:
        releve.requetes_limite = limite
        releve.requetes_restantes = _entier(entetes, "x-ratelimit-remaining-requests")
        releve.periode_requetes = "jour"
        releve.jetons_limite = _entier(entetes, "x-ratelimit-limit-tokens")
        releve.jetons_restants = _entier(entetes, "x-ratelimit-remaining-tokens")
        releve.instant = time.monotonic()


def noter_usage(fournisseur: str, corps: Any) -> None:
    """Les jetons qu'a coûtés une réponse : le seul chiffre que tous donnent."""
    if not isinstance(corps, dict):
        return
    usage = corps.get("usage") or {}
    gemini = corps.get("usageMetadata") or {}
    jetons = usage.get("total_tokens") or gemini.get("totalTokenCount") or 0
    releve = _releves.setdefault(fournisseur, Releve())
    releve.appels += 1
    releve.jetons_consommes += int(jetons)


def releve(fournisseur: str) -> Releve | None:
    return _releves.get(fournisseur)


def consommation() -> dict[str, int]:
    return {nom: r.jetons_consommes for nom, r in _releves.items()}


def oublier() -> None:
    _releves.clear()
