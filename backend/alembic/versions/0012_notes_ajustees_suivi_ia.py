"""notes ajustées par ligne, mesure des lectures

- `candidature.ajustements_note` : les lignes de note corrigées par les RH. Sur
  la candidature, parce que la notation est refaite à chaque recalcul.
- `ligne_notation.points_calcules` et `ajustement_motif` : ce que le calcul
  aurait donné, et pourquoi quelqu'un l'a changé.
- `travail.secondes`, `jetons`, `fournisseur`, `clos` : ce qu'a coûté chaque
  lecture, d'où se tire le temps restant.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_B = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _ajouter(table: str, colonne: sa.Column) -> None:
    if colonne.name not in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, colonne)


def upgrade() -> None:
    _ajouter("candidature", sa.Column("ajustements_note", JSON_B, nullable=True))
    _ajouter("ligne_notation", sa.Column("points_calcules", sa.Numeric(5, 2), nullable=True))
    _ajouter("ligne_notation", sa.Column("ajustement_motif", sa.Text(), nullable=True))
    _ajouter("travail", sa.Column("secondes", sa.Float(), nullable=True))
    _ajouter("travail", sa.Column("jetons", sa.Integer(), nullable=True))
    _ajouter("travail", sa.Column("fournisseur", sa.String(64), nullable=True))
    _ajouter(
        "travail",
        sa.Column("clos", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("travail", "clos")
    op.drop_column("travail", "fournisseur")
    op.drop_column("travail", "jetons")
    op.drop_column("travail", "secondes")
    op.drop_column("ligne_notation", "ajustement_motif")
    op.drop_column("ligne_notation", "points_calcules")
    op.drop_column("candidature", "ajustements_note")
