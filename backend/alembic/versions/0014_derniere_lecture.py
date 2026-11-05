"""qui a lu le dossier en dernier

`candidature.derniere_lecture` : le lecteur, la date et ses remarques. Plusieurs
lecteurs peuvent maintenant se partager un mandat, et un candidat qui conteste a
le droit de savoir lequel a lu son dossier.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_B = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    colonnes = {c["name"] for c in inspect(op.get_bind()).get_columns("candidature")}
    if "derniere_lecture" not in colonnes:
        op.add_column("candidature", sa.Column("derniere_lecture", JSON_B, nullable=True))


def downgrade() -> None:
    op.drop_column("candidature", "derniere_lecture")
