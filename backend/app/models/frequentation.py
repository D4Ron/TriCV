"""La fréquentation des pages publiques, comptée par jour.

Ce que le serveur ne voit pas, il ne peut pas le compter : un dossier refusé
par le serveur frontal pour sa taille n'atteint jamais l'application, et une
page de candidature s'affiche sans qu'aucune écriture n'ait lieu. Le
navigateur du visiteur le signale donc, une fois par page et par onglet, et le
serveur incrémente un compteur.

Rien n'identifie personne : ni adresse IP, ni navigateur, ni cookie. Un
compteur par jour, par événement, et par poste quand l'événement en concerne
un. C'est assez pour savoir si les candidats arrivent et s'ils repartent sans
avoir pu déposer ; ce n'est pas assez pour suivre qui que ce soit.

Les candidatures, elles, ne sont pas comptées ici : elles sont en base, avec
leur date et leur source, et le tableau de bord les lit directement.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import uuid_pk

# Les seuls événements admis. Une liste fermée : le point d'entrée est public,
# et un compteur ouvert à n'importe quel libellé se remplirait de n'importe quoi.
EVENEMENTS = frozenset(
    {
        "visite_postes",  # la liste des postes ouverts
        "visite_avis",  # la page de candidature d'un avis
        "visite_aide",  # la page d'aide
        "depot_refuse_taille",  # refusé par le serveur frontal (413)
        "depot_echoue",  # interrompu : réseau, délai, erreur serveur
    }
)


class Frequentation(Base):
    __tablename__ = "frequentation"
    __table_args__ = (
        sa.UniqueConstraint("jour", "evenement", "poste_id", name="uq_frequentation_jour"),
        sa.Index("ix_frequentation_jour", "jour"),
    )

    id: Mapped[str] = uuid_pk()
    jour: Mapped[date] = mapped_column(sa.Date, nullable=False)
    evenement: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    # Chaîne vide plutôt que NULL : une contrainte d'unicité ne considère pas
    # deux NULL comme égaux, et chaque visite de la page d'aide ouvrirait
    # alors sa propre ligne au lieu d'incrémenter la même.
    poste_id: Mapped[str] = mapped_column(sa.String(36), nullable=False, default="")
    compte: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
