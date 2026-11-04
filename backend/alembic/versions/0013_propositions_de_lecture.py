"""propositions de relecture

`candidat.propositions_lecture` : ce qu'une relecture voit autrement que les
données posées par un humain. Rien n'y change la note avant d'être accepté.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_B = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    colonnes = {c["name"] for c in inspect(op.get_bind()).get_columns("candidat")}
    if "propositions_lecture" not in colonnes:
        op.add_column("candidat", sa.Column("propositions_lecture", JSON_B, nullable=True))


def downgrade() -> None:
    op.drop_column("candidat", "propositions_lecture")
