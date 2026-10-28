"""fréquentation : compteurs journaliers des pages publiques

Un compteur par jour, par événement, et par poste quand l'événement en
concerne un. Aucune donnée personnelle : ni adresse, ni navigateur, ni
identifiant de visiteur.

Sert à l'onglet « État » des paramètres, qui dit si les candidats arrivent sur
le site et s'ils parviennent à déposer — un dossier refusé par le serveur
frontal n'atteignant jamais l'application, seul ce compteur le révèle.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotente, comme les précédentes : une base montée par `create_all`
    # en développement a déjà la table.
    if "frequentation" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "frequentation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("jour", sa.Date, nullable=False),
        sa.Column("evenement", sa.String(40), nullable=False),
        sa.Column("poste_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("compte", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("jour", "evenement", "poste_id", name="uq_frequentation_jour"),
    )
    op.create_index("ix_frequentation_jour", "frequentation", ["jour"])


def downgrade() -> None:
    op.drop_index("ix_frequentation_jour", table_name="frequentation")
    op.drop_table("frequentation")
