"""indices, lexique des postes, origine du type des pièces, file de travaux

- `elimination.indice` : ce qui, dans le dossier, pourrait contredire le motif.
- `poste.lexique` : les mots propres au poste, validés par les RH.
- `piece_candidature.type_source` : qui a rangé la pièce. Une correction humaine
  ne doit jamais être défaite par une relecture.
- `travail` : la file des lectures, qui survit à un redémarrage et attend le
  retour du quota au lieu d'échouer.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_B = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _colonnes(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "indice" not in _colonnes("elimination"):
        op.add_column("elimination", sa.Column("indice", sa.Text(), nullable=True))
    if "lexique" not in _colonnes("poste"):
        op.add_column("poste", sa.Column("lexique", JSON_B, nullable=True))
    if "type_source" not in _colonnes("piece_candidature"):
        op.add_column("piece_candidature", sa.Column("type_source", sa.String(16), nullable=True))
    if "travail" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "travail",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("nature", sa.String(32), nullable=False),
            sa.Column(
                "candidature_id",
                sa.String(36),
                sa.ForeignKey("candidature.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("poste_id", sa.String(36), nullable=True),
            sa.Column("etat", sa.String(16), nullable=False),
            sa.Column("essais", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pas_avant", sa.DateTime(), nullable=True),
            sa.Column("erreur", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_travail_etat", "travail", ["etat"])
        op.create_index("ix_travail_candidature", "travail", ["candidature_id"])
        op.create_index("ix_travail_poste", "travail", ["poste_id"])


def downgrade() -> None:
    op.drop_table("travail")
    op.drop_column("piece_candidature", "type_source")
    op.drop_column("poste", "lexique")
    op.drop_column("elimination", "indice")
