"""Ce que l'application a fait de chaque message de la boîte de recrutement.

La boîte est partagée : elle reçoit des candidatures, mais aussi des lettres
d'information, des rapports de quarantaine, des réponses à des collègues. Le
relevé en tire des dossiers, et il vaut mieux qu'il en tire un de trop que d'en
manquer un — un dossier inutile se supprime, une candidature perdue ne se
rattrape pas.

Encore faut-il qu'un dossier supprimé ne revienne pas au relevé suivant. D'où
cette trace : un message importé, ignoré ou laissé faute de pièce lisible est
reconnu à son identifiant Internet, et l'écran de la boîte dit ce qu'il en a
été fait. S'y ajoutent les expéditeurs qu'on a décidé d'ignorer : une lettre
d'information supprimée vingt fois ne doit pas revenir une vingt-et-unième.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow, uuid_pk

# Ce qui est arrivé à un message.
IMPORTE = "IMPORTE"  # devenu une candidature (ou versé à un dossier)
IGNORE = "IGNORE"  # écarté à la main, ou par un expéditeur ignoré
SANS_PIECE = "SANS_PIECE"  # aucune pièce lisible : laissé non lu pour une personne
SUPPRIME = "SUPPRIME"  # importé, puis le dossier a été supprimé comme inutile
STATUTS = frozenset({IMPORTE, IGNORE, SANS_PIECE, SUPPRIME})


class MessageTraite(Base):
    __tablename__ = "message_traite"

    id: Mapped[str] = uuid_pk()
    # L'identifiant Internet (« <…@…> ») : stable d'une boîte à l'autre, et
    # c'est lui que porte déjà `Candidature.message_id`.
    message_id: Mapped[str] = mapped_column(sa.String(512), unique=True, index=True, nullable=False)
    statut: Mapped[str] = mapped_column(sa.String(16), nullable=False, index=True)
    expediteur: Mapped[str] = mapped_column(sa.String(320), default="", nullable=False, index=True)
    sujet: Mapped[str] = mapped_column(sa.String(512), default="", nullable=False)
    recu_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    candidature_id: Mapped[str | None] = mapped_column(sa.String(36), index=True)
    motif: Mapped[str | None] = mapped_column(sa.String(500))
    traite_le: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, nullable=False)
    traite_par: Mapped[str | None] = mapped_column(sa.String(36))


class ExpediteurIgnore(Base):
    """Une adresse, ou tout un domaine (« @lettre.example »), dont le relevé ne
    tire plus de dossier : ses messages sont marqués ignorés, pas supprimés."""

    __tablename__ = "expediteur_ignore"

    id: Mapped[str] = uuid_pk()
    # Une adresse complète, ou un domaine précédé de « @ ». En minuscules.
    motif_adresse: Mapped[str] = mapped_column(sa.String(320), unique=True, nullable=False)
    raison: Mapped[str | None] = mapped_column(sa.String(500))
    cree_le: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, nullable=False)
    cree_par: Mapped[str | None] = mapped_column(sa.String(36))


# Les messageries publiques : la plupart des candidats y ont leur adresse. En
# ignorer le domaine entier ferait disparaître toutes leurs candidatures — on
# n'ignore qu'une adresse à la fois chez elles. Constaté en production : 31 des
# 32 dossiers sans poste venaient de @gmail.com ou @yahoo.com.
DOMAINES_PUBLICS = frozenset(
    {
        "@gmail.com", "@googlemail.com", "@yahoo.com", "@yahoo.fr", "@ymail.com",
        "@outlook.com", "@outlook.fr", "@hotmail.com", "@hotmail.fr", "@live.com",
        "@live.fr", "@msn.com", "@icloud.com", "@me.com", "@aol.com", "@gmx.com",
        "@gmx.fr", "@proton.me", "@protonmail.com", "@orange.fr", "@free.fr",
        "@laposte.net", "@yandex.com", "@mail.com", "@zoho.com",
    }
)


def domaine_public(motif: str) -> bool:
    """Un motif « @domaine » qui désigne une messagerie publique."""
    return normaliser_adresse(motif) in DOMAINES_PUBLICS


def normaliser_adresse(adresse: str) -> str:
    return (adresse or "").strip().lower()


def est_ignore(adresse: str, regles: set[str]) -> bool:
    """L'adresse, ou son domaine, figure-t-elle parmi les expéditeurs ignorés ?"""
    adresse = normaliser_adresse(adresse)
    if not adresse:
        return False
    domaine = "@" + adresse.rpartition("@")[2]
    return adresse in regles or domaine in regles
