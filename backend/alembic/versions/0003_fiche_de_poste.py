"""fiche de poste : rubriques de présentation, document fourni, fiche à compléter

Ajoute au poste ce que les fiches de poste des clients portent et que l'avis
devait reprendre à la main — localisation, rattachement, responsabilités,
compétences — ainsi que le document de la fiche lui-même et son texte, qui
sert désormais de source à la rédaction de l'avis.

`a_completer` marque un poste créé avec son seul intitulé. Il part à `false`
pour les postes existants : ils ont été saisis en entier, et les signaler
« à compléter » après coup serait faux.

Colonnes écrites une à une plutôt que par la synchronisation générique de
0002 : elles sont connues, et une migration qui dit ce qu'elle fait se relit.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.models.base import JsonB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLONNES = [
    sa.Column("localisation", sa.String(255), nullable=True),
    sa.Column("rattachement", sa.String(255), nullable=True),
    sa.Column("responsabilites", JsonB, nullable=True),
    sa.Column("competences_techniques", JsonB, nullable=True),
    sa.Column("competences_comportementales", JsonB, nullable=True),
    sa.Column(
        "a_completer", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
    sa.Column("fiche_nom_fichier", sa.String(512), nullable=True),
    sa.Column("fiche_chemin", sa.String(512), nullable=True),
    sa.Column("fiche_type_mime", sa.String(128), nullable=True),
    sa.Column("fiche_texte", sa.Text(), nullable=True),
    sa.Column("fiche_deposee_le", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    # 0002 crée les tables à partir des modèles : une base passée directement
    # de 0001 à la tête a donc déjà ces colonnes. On n'ajoute que ce qui manque.
    existantes = {c["name"] for c in inspect(op.get_bind()).get_columns("poste")}
    for colonne in _COLONNES:
        if colonne.name not in existantes:
            op.add_column("poste", colonne)


def downgrade() -> None:
    existantes = {c["name"] for c in inspect(op.get_bind()).get_columns("poste")}
    for colonne in reversed(_COLONNES):
        if colonne.name in existantes:
            op.drop_column("poste", colonne.name)
