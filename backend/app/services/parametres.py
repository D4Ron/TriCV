"""Réglages modifiables depuis l'application.

Le fichier `.env` reste la valeur de départ ; ce module ne fait que la
surcharger quand quelqu'un a réglé la valeur dans l'interface. Ce partage est
délibéré : ce qui touche à l'infrastructure — fournisseur de modèle, stockage,
stockage — appartient au déploiement et n'a rien à faire dans un écran ; ce qui
relève de la pratique de recrutement — seuil, expurgation des données
sensibles, inscription libre, boîte de candidatures — change avec l'usage et
doit pouvoir se régler sans redémarrage ni accès au serveur.

La boîte de candidatures fait exception à la règle « les secrets restent au
déploiement » : son mot de passe est réglable ici. Le motif est pratique et
assumé — l'adresse de recrutement change avec les campagnes, et un mot de passe
d'application Gmail se révoque et se recrée. Le secret n'est jamais renvoyé par
l'API ; l'interface sait seulement s'il est renseigné.

Chaque écriture passe au journal d'audit par l'appelant : un seuil par défaut
ou l'expurgation des données démographiques sont des décisions, pas des
préférences. Les valeurs des secrets n'y figurent pas, seulement leur nom.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


class Parametre(Base):
    """Une surcharge du fichier de configuration, réglée depuis l'interface."""

    __tablename__ = "parametre"

    cle: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    valeur: Mapped[str] = mapped_column(sa.String(512), nullable=False)


# Clés reconnues, avec leur valeur par défaut lue dans .env.
SEUIL_DEFAUT = "seuil_preselection_defaut"
REDACTION_DEMOGRAPHIQUE = "redact_demographics"
INSCRIPTION_LIBRE = "allow_self_registration"

# Boîte de candidatures. Elle se règle depuis l'interface parce que l'adresse
# de recrutement change avec les campagnes et les mots de passe d'application
# se renouvellent : demander un accès au serveur à chaque fois condamnerait la
# fonction à ne jamais être utilisée.
COURRIEL_ACTIF = "courriel_actif"
IMAP_HOTE = "imap_host"
IMAP_PORT = "imap_port"
IMAP_UTILISATEUR = "imap_user"
IMAP_MOT_DE_PASSE = "imap_password"
IMAP_DOSSIER = "imap_folder"

# Ce que l'API ne renvoie jamais en clair.
SECRETS = frozenset({IMAP_MOT_DE_PASSE})


@dataclass(slots=True)
class Reglages:
    seuil_preselection_defaut: float
    redact_demographics: bool
    allow_self_registration: bool
    courriel_actif: bool
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str

    @property
    def courriel_utilisable(self) -> bool:
        """Relevable : activé, et avec de quoi ouvrir une session."""
        return bool(
            self.courriel_actif and self.imap_host and self.imap_user and self.imap_password
        )


def _defauts() -> Reglages:
    return Reglages(
        seuil_preselection_defaut=20.0,
        redact_demographics=settings.redact_demographics,
        allow_self_registration=settings.allow_self_registration,
        # Le .env sert d'amorçage : une installation peut arriver préconfigurée,
        # et l'interface prend ensuite le relais.
        courriel_actif=bool(settings.imap_host and settings.imap_user),
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
        imap_user=settings.imap_user,
        imap_password=settings.imap_password,
        imap_folder=settings.imap_folder or "INBOX",
    )


def _en_bool(valeur: str) -> bool:
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "on"}


async def lire(db: AsyncSession) -> Reglages:
    """Les réglages effectifs : .env, surchargé par ce qui a été réglé."""
    reglages = _defauts()
    lignes = await db.execute(select(Parametre.cle, Parametre.valeur))
    for cle, valeur in lignes:
        try:
            if cle == SEUIL_DEFAUT:
                reglages.seuil_preselection_defaut = float(valeur)
            elif cle == REDACTION_DEMOGRAPHIQUE:
                reglages.redact_demographics = _en_bool(valeur)
            elif cle == INSCRIPTION_LIBRE:
                reglages.allow_self_registration = _en_bool(valeur)
            elif cle == COURRIEL_ACTIF:
                reglages.courriel_actif = _en_bool(valeur)
            elif cle == IMAP_HOTE:
                reglages.imap_host = valeur.strip()
            elif cle == IMAP_PORT:
                reglages.imap_port = int(valeur)
            elif cle == IMAP_UTILISATEUR:
                reglages.imap_user = valeur.strip()
            elif cle == IMAP_MOT_DE_PASSE:
                # Gmail affiche le mot de passe d'application par groupes de
                # quatre ; recopié tel quel, il est refusé. On retire donc les
                # espaces plutôt que de laisser les RH deviner.
                reglages.imap_password = valeur.replace(" ", "")
            elif cle == IMAP_DOSSIER:
                reglages.imap_folder = valeur.strip() or "INBOX"
        except (TypeError, ValueError):
            # Une valeur illisible en base ne doit pas empêcher l'application
            # de démarrer : on retombe sur le défaut du fichier.
            continue
    return reglages


async def ecrire(db: AsyncSession, modifications: dict[str, object]) -> list[str]:
    """Enregistre les surcharges. Renvoie les clés effectivement changées.

    Un secret vide vaut « inchangé », pas « effacé » : le formulaire ne peut pas
    réafficher le mot de passe, donc l'enregistrer sans y toucher ne doit pas
    déconnecter la boîte. Pour vraiment le retirer, on vide l'utilisateur ou on
    décoche l'activation.
    """
    changees: list[str] = []
    for cle, valeur in modifications.items():
        if valeur is None:
            continue
        if cle in SECRETS and not str(valeur).strip():
            continue
        texte = str(valeur).lower() if isinstance(valeur, bool) else str(valeur)
        existant = await db.get(Parametre, cle)
        if existant is None:
            db.add(Parametre(cle=cle, valeur=texte))
        elif existant.valeur == texte:
            continue
        else:
            existant.valeur = texte
        changees.append(cle)
    await db.flush()
    return changees
