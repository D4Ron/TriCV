"""boîte : trace des messages traités, expéditeurs ignorés

Un message importé, ignoré ou laissé faute de pièce est reconnu au relevé
suivant ; un dossier supprimé comme inutile ne revient donc pas. Les
expéditeurs ignorés — une lettre d'information, un rapport automatique — ne
produisent plus de dossier.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    # Idempotente : une base montée par `create_all` a déjà les tables.
    if "message_traite" not in tables:
        op.create_table(
            "message_traite",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("message_id", sa.String(512), nullable=False),
            sa.Column("statut", sa.String(16), nullable=False),
            sa.Column("expediteur", sa.String(320), nullable=False, server_default=""),
            sa.Column("sujet", sa.String(512), nullable=False, server_default=""),
            sa.Column("recu_le", sa.DateTime),
            sa.Column("candidature_id", sa.String(36)),
            sa.Column("motif", sa.String(500)),
            sa.Column("traite_le", sa.DateTime, nullable=False),
            sa.Column("traite_par", sa.String(36)),
        )
        op.create_index("ix_message_traite_message_id", "message_traite", ["message_id"], unique=True)
        op.create_index("ix_message_traite_statut", "message_traite", ["statut"])
        op.create_index("ix_message_traite_expediteur", "message_traite", ["expediteur"])
        op.create_index("ix_message_traite_candidature_id", "message_traite", ["candidature_id"])
    if "expediteur_ignore" not in tables:
        op.create_table(
            "expediteur_ignore",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("motif_adresse", sa.String(320), nullable=False, unique=True),
            sa.Column("raison", sa.String(500)),
            sa.Column("cree_le", sa.DateTime, nullable=False),
            sa.Column("cree_par", sa.String(36)),
        )


def downgrade() -> None:
    op.drop_table("expediteur_ignore")
    op.drop_index("ix_message_traite_candidature_id", table_name="message_traite")
    op.drop_index("ix_message_traite_expediteur", table_name="message_traite")
    op.drop_index("ix_message_traite_statut", table_name="message_traite")
    op.drop_index("ix_message_traite_message_id", table_name="message_traite")
    op.drop_table("message_traite")
