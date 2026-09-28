"""avis : code court pour le lien de candidature

Le lien de candidature (`/apply/<clé publique>`) fait une quarantaine de
caractères : il ne se recopie pas depuis un avis imprimé ou paru dans la
presse. Chaque avis reçoit un code de huit caractères, servi à `/p/<code>`.

L'ancien lien reste valide : la clé publique n'est ni retirée ni modifiée, et
les avis déjà diffusés continuent de mener au formulaire.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.models.recrutement import nouveau_code_court

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connexion = op.get_bind()
    existantes = {c["name"] for c in inspect(connexion).get_columns("avis")}
    if "code_court" not in existantes:
        op.add_column("avis", sa.Column("code_court", sa.String(16), nullable=True))

    # Un code pour chaque avis existant, publié ou non.
    avis = sa.table("avis", sa.column("id", sa.String), sa.column("code_court", sa.String))
    pris = {
        code
        for (code,) in connexion.execute(sa.select(avis.c.code_court)).all()
        if code
    }
    sans_code = connexion.execute(
        sa.select(avis.c.id).where(avis.c.code_court.is_(None))
    ).all()
    for (identifiant,) in sans_code:
        code = nouveau_code_court()
        while code in pris:
            code = nouveau_code_court()
        pris.add(code)
        connexion.execute(
            avis.update().where(avis.c.id == identifiant).values(code_court=code)
        )

    index = {i["name"] for i in inspect(connexion).get_indexes("avis")}
    if "ix_avis_code_court" not in index:
        op.create_index("ix_avis_code_court", "avis", ["code_court"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_avis_code_court", table_name="avis")
    op.drop_column("avis", "code_court")
