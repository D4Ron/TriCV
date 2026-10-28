"""Jetons d'accès Microsoft pour Microsoft Graph.

La boîte de recrutement est une boîte Microsoft 365, lue et utilisée pour
l'envoi par Graph. L'application s'authentifie seule — flux « client
credentials » : un identifiant d'application et son secret, déclarés dans
Entra ID, sans qu'aucun humain n'ait à se connecter. C'est ce qu'il faut pour
un serveur qui relève une boîte sans surveillance, et cela ne cesse jamais de
fonctionner tant que le secret est valide.

Le module ne fait qu'obtenir un jeton et le garder en mémoire jusqu'à son
expiration. Il n'écrit rien et ne connaît pas Graph.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

AUTORITE = "https://login.microsoftonline.com"

# Tout ce que le principal de service a reçu sur Graph.
PORTEE_GRAPH = "https://graph.microsoft.com/.default"

# On renouvelle un peu avant l'échéance : un jeton qui expire au milieu d'un
# relevé produit un refus incompréhensible.
MARGE_SECONDES = 120


class ErreurOAuth(RuntimeError):
    """Microsoft a refusé de délivrer un jeton. Le message est montré aux RH."""


@dataclass(slots=True)
class ConfigOAuth:
    """Ce qu'il faut pour demander un jeton. Rien de plus."""

    # L'identifiant du tenant, ou son domaine (kapiconsult.onmicrosoft.com).
    tenant: str = ""
    client_id: str = ""
    client_secret: str = ""

    @property
    def utilisable(self) -> bool:
        return bool(self.tenant.strip() and self.client_id.strip() and self.client_secret.strip())


@dataclass(slots=True)
class _JetonEnCache:
    valeur: str = ""
    expire_a: float = 0.0

    def valide(self) -> bool:
        return bool(self.valeur) and time.time() < self.expire_a - MARGE_SECONDES


# Un cache par (tenant, client_id, compte, portée) : deux réglages différents ne
# doivent pas se prêter un jeton.
_cache: dict[tuple[str, str, str, str], _JetonEnCache] = {}


def _demander(config: ConfigOAuth, portee: str) -> tuple[str, int]:
    """Échange les identifiants contre un jeton d'accès. Rend (jeton, durée)."""
    corps = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "grant_type": "client_credentials",
        "scope": portee,
    }
    url = f"{AUTORITE}/{config.tenant}/oauth2/v2.0/token"
    try:
        reponse = httpx.post(url, data=corps, timeout=30)
    except httpx.HTTPError as exc:
        raise ErreurOAuth(
            f"Impossible de joindre Microsoft pour obtenir un jeton ({exc})."
        ) from exc

    if reponse.status_code >= 400:
        raise ErreurOAuth(_expliquer(reponse.status_code, reponse.text))

    charge = reponse.json()
    jeton = charge.get("access_token") or ""
    if not jeton:
        raise ErreurOAuth("Microsoft n'a pas renvoyé de jeton d'accès.")
    return jeton, int(charge.get("expires_in") or 3600)


# Les refus qu'on rencontre réellement, et ce qu'il faut faire. « AADSTS70011 »
# ne dit rien à personne ; la cause, si.
_REFUS = {
    "AADSTS7000215": (
        "Le secret de l'application est refusé. Vérifiez « Secret client » dans "
        "les paramètres, et qu'il s'agit bien de la *valeur* du secret et non de "
        "son identifiant — Entra affiche les deux côte à côte, et la valeur ne "
        "se réaffiche jamais après sa création."
    ),
    "AADSTS7000222": (
        "Le secret de l'application a expiré. Créez-en un nouveau dans Entra › "
        "Inscriptions d'applications › Certificats et secrets, et collez sa "
        "valeur dans Paramètres › Courriel."
    ),
    "AADSTS700016": (
        "L'identifiant d'application est inconnu de ce tenant. Vérifiez "
        "« ID de l'application » et « ID du locataire »."
    ),
    "AADSTS900023": (
        "Le tenant indiqué n'existe pas. C'est l'« ID de l'annuaire (locataire) » "
        "de la page Vue d'ensemble de l'application dans Entra."
    ),
    "AADSTS90002": (
        "Le tenant indiqué n'existe pas. C'est l'« ID de l'annuaire (locataire) » "
        "de la page Vue d'ensemble de l'application dans Entra."
    ),
    "AADSTS70011": (
        "La portée demandée est refusée. Les permissions d'application "
        "« Mail.ReadWrite » et « Mail.Send » doivent être accordées par un "
        "administrateur."
    ),
}


def _expliquer(code: int, corps: str) -> str:
    for marqueur, explication in _REFUS.items():
        if marqueur in corps:
            return explication
    return f"Microsoft a refusé la demande de jeton (HTTP {code}) : {corps[:300]}"


def jeton(config: ConfigOAuth, compte: str, portee: str = PORTEE_GRAPH) -> str:
    """Un jeton d'accès valide, mis en cache jusqu'à échéance."""
    if not config.utilisable:
        raise ErreurOAuth(
            "L'accès Microsoft 365 est incomplet : il faut l'identifiant du "
            "tenant, celui de l'application et son secret."
        )

    cle = (config.tenant, config.client_id, compte, portee)
    en_cache = _cache.get(cle)
    if en_cache is not None and en_cache.valide():
        return en_cache.valeur

    valeur, duree = _demander(config, portee)
    _cache[cle] = _JetonEnCache(valeur=valeur, expire_a=time.time() + duree)
    logger.info("jeton Microsoft obtenu pour %s, valable %d s", compte, duree)
    return valeur


def oublier_cache() -> None:
    """Vide le cache. Sert aux tests et à un changement de réglage."""
    _cache.clear()
