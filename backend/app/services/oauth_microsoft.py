"""Jetons d'accès Microsoft pour IMAP et SMTP.

**Pourquoi ce module existe.** Microsoft a supprimé l'authentification par mot
de passe sur IMAP, POP et SMTP. Sa documentation ne laisse aucune marge :
« Basic authentication is now disabled in all tenants », et « no one (you or
Microsoft support) can re-enable Basic authentication in your tenant ». Les
« mots de passe d'application » reposaient dessus et ne fonctionnent plus non
plus. Côté comptes personnels — outlook.com, hotmail.com, live.com — la même
bascule a eu lieu le 16 septembre 2024.

Une boîte Outlook ne se relève donc pas avec un mot de passe, quel qu'il soit.
Changer d'adresse de serveur ne produirait qu'un refus plus clair. Il faut un
jeton OAuth 2.0, présenté à IMAP par le mécanisme `XOAUTH2`.

**Deux chemins, selon le compte.** Ils n'ont pas les mêmes conséquences
d'exploitation, et c'est la seule chose à trancher avant de configurer :

- **Compte professionnel** (Microsoft 365, un domaine à soi, un administrateur).
  Flux « client credentials » : l'application s'authentifie seule, avec un
  secret, sans qu'aucun humain n'ait à se connecter. C'est ce qu'il faut pour un
  serveur qui relève une boîte toutes les dix minutes, et cela ne cesse jamais
  de fonctionner tant que le secret est valide. L'administrateur doit accorder
  la permission `IMAP.AccessAsApp` et autoriser le principal de service sur la
  boîte visée.

- **Compte personnel** (outlook.com). Microsoft n'y autorise pas le flux
  application. Il faut un consentement humain, une fois, qui produit un *jeton
  de rafraîchissement* que l'application conserve et échange contre des jetons
  d'accès. Cela marche, mais le jeton de rafraîchissement peut être révoqué —
  changement de mot de passe, expiration — et il faut alors refaire le
  consentement. Une boîte de recrutement qui doit tourner sans surveillance
  gagne à être une boîte professionnelle.

Le module ne fait qu'obtenir un jeton et le garder en mémoire jusqu'à son
expiration. Il n'écrit rien et ne connaît ni IMAP ni SMTP.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# L'autorité Microsoft. « consumers » vise les comptes personnels, « organizations »
# n'importe quel tenant, un GUID un tenant précis.
AUTORITE = "https://login.microsoftonline.com"

# La portée du flux application : tout ce que le principal de service a reçu.
PORTEE_APPLICATION = "https://outlook.office365.com/.default"
# Celle du flux délégué : lire la boîte au nom de la personne qui a consenti.
PORTEE_DELEGUEE = (
    "https://outlook.office.com/IMAP.AccessAsUser.All "
    "https://outlook.office.com/SMTP.Send offline_access"
)

# On renouvelle un peu avant l'échéance : un jeton qui expire pendant la
# poignée de main IMAP produit un refus incompréhensible.
MARGE_SECONDES = 120


class ErreurOAuth(RuntimeError):
    """Microsoft a refusé de délivrer un jeton. Le message est montré aux RH."""


@dataclass(slots=True)
class ConfigOAuth:
    """Ce qu'il faut pour demander un jeton. Rien de plus."""

    # « common », « consumers », ou l'identifiant du tenant.
    tenant: str = "consumers"
    client_id: str = ""
    client_secret: str = ""
    # Flux délégué seulement : le jeton obtenu au consentement initial.
    refresh_token: str = ""

    @property
    def delegue(self) -> bool:
        """Un jeton de rafraîchissement présent désigne le flux délégué."""
        return bool(self.refresh_token.strip())

    @property
    def utilisable(self) -> bool:
        return bool(self.client_id.strip() and (self.client_secret.strip() or self.refresh_token.strip()))


@dataclass(slots=True)
class _JetonEnCache:
    valeur: str = ""
    expire_a: float = 0.0

    def valide(self) -> bool:
        return bool(self.valeur) and time.time() < self.expire_a - MARGE_SECONDES


# Un cache par (tenant, client_id, compte) : deux boîtes réglées différemment ne
# doivent pas se prêter un jeton.
_cache: dict[tuple[str, str, str, str], _JetonEnCache] = {}


def _demander(config: ConfigOAuth, portee: str | None = None) -> tuple[str, int]:
    """Échange les identifiants contre un jeton d'accès. Rend (jeton, durée).

    `portee` remplace la portée du flux application : IMAP/SMTP visent
    `outlook.office365.com`, Microsoft Graph `graph.microsoft.com`. Un jeton
    ne vaut que pour la ressource qu'il nomme.
    """
    corps: dict[str, str] = {"client_id": config.client_id}
    if config.delegue:
        corps.update(
            {
                "grant_type": "refresh_token",
                "refresh_token": config.refresh_token,
                "scope": PORTEE_DELEGUEE,
            }
        )
        # Une application « publique » n'a pas de secret ; une « confidentielle »
        # en a un et doit le présenter. On envoie celui qu'on a.
        if config.client_secret.strip():
            corps["client_secret"] = config.client_secret
    else:
        corps.update(
            {
                "grant_type": "client_credentials",
                "client_secret": config.client_secret,
                "scope": portee or PORTEE_APPLICATION,
            }
        )

    url = f"{AUTORITE}/{config.tenant or 'consumers'}/oauth2/v2.0/token"
    try:
        reponse = httpx.post(url, data=corps, timeout=30)
    except httpx.HTTPError as exc:
        raise ErreurOAuth(
            f"Impossible de joindre Microsoft pour obtenir un jeton ({exc})."
        ) from exc

    if reponse.status_code >= 400:
        raise ErreurOAuth(_expliquer(reponse.status_code, reponse.text, config))

    charge = reponse.json()
    jeton = charge.get("access_token") or ""
    if not jeton:
        raise ErreurOAuth("Microsoft n'a pas renvoyé de jeton d'accès.")
    return jeton, int(charge.get("expires_in") or 3600)


# Les refus qu'on rencontre réellement, et ce qu'il faut faire. « AADSTS70011 »
# ne dit rien à personne ; la cause, si.
_REFUS = {
    "AADSTS7000215": (
        "Le secret de l'application est refusé. Vérifiez « Client secret » dans "
        "les paramètres, et qu'il s'agit bien de la *valeur* du secret et non de "
        "son identifiant — Entra affiche les deux côte à côte, et la valeur ne "
        "se réaffiche jamais après sa création."
    ),
    "AADSTS700016": (
        "L'identifiant d'application est inconnu de ce tenant. Vérifiez "
        "« Client ID » et « Tenant »."
    ),
    "AADSTS900023": (
        "Le tenant indiqué n'existe pas. Pour une boîte professionnelle, c'est "
        "l'identifiant du tenant ; pour une adresse outlook.com, c'est "
        "« consumers »."
    ),
    "AADSTS70011": (
        "La portée demandée est refusée. Pour une boîte professionnelle, "
        "l'administrateur doit accorder la permission « IMAP.AccessAsApp » à "
        "l'application et autoriser son principal de service sur la boîte."
    ),
    "AADSTS50126": "Identifiants refusés par Microsoft.",
    "invalid_grant": (
        "Le consentement a expiré ou a été révoqué. Refaites le consentement "
        "pour obtenir un nouveau jeton de rafraîchissement."
    ),
}


def _expliquer(code: int, corps: str, config: ConfigOAuth) -> str:
    for marqueur, explication in _REFUS.items():
        if marqueur in corps:
            return explication
    if not config.delegue and config.tenant in ("consumers", "common", ""):
        # L'erreur la plus fréquente sur une boîte personnelle : Microsoft
        # n'autorise pas le flux application pour ces comptes.
        return (
            "Microsoft a refusé (HTTP "
            f"{code}). Une adresse outlook.com personnelle n'accepte pas le flux "
            "« application » : il lui faut un consentement humain une fois, qui "
            "produit un jeton de rafraîchissement. Voir le guide de "
            "configuration de la boîte de candidatures."
        )
    return f"Microsoft a refusé la demande de jeton (HTTP {code}) : {corps[:300]}"


def jeton(config: ConfigOAuth, compte: str, portee: str | None = None) -> str:
    """Un jeton d'accès valide pour ce compte, mis en cache jusqu'à échéance."""
    if not config.utilisable:
        raise ErreurOAuth(
            "L'accès Microsoft est incomplet : il faut au moins un identifiant "
            "d'application et, selon le cas, un secret ou un jeton de "
            "rafraîchissement."
        )

    cle = (config.tenant, config.client_id, compte, portee or "")
    en_cache = _cache.get(cle)
    if en_cache is not None and en_cache.valide():
        return en_cache.valeur

    valeur, duree = _demander(config, portee)
    _cache[cle] = _JetonEnCache(valeur=valeur, expire_a=time.time() + duree)
    logger.info(
        "jeton Microsoft obtenu pour %s (%s), valable %d s",
        compte,
        "délégué" if config.delegue else "application",
        duree,
    )
    return valeur


def chaine_xoauth2(compte: str, jeton_acces: str) -> str:
    """La chaîne que IMAP et SMTP attendent pour `AUTH XOAUTH2`.

    Format imposé par Microsoft et Google : `user=…^Aauth=Bearer …^A^A`, où
    `^A` est l'octet 0x01.
    """
    return f"user={compte}\x01auth=Bearer {jeton_acces}\x01\x01"


def oublier_cache() -> None:
    """Vide le cache. Sert aux tests et à un changement de réglage."""
    _cache.clear()
