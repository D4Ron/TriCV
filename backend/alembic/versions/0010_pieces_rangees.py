"""pièces des postes : chacune une fois, à une seule place

Rien n'empêchait d'exiger la carte d'identité seule *et* dans « carte
d'identité ou passeport » : l'avis la demandait deux fois et le formulaire
offrait deux champs, avec deux règles contradictoires. La règle de rangement
(`app.domain.pieces.normaliser`) s'applique désormais à chaque enregistrement ;
cette migration l'applique une fois aux postes déjà en base.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _liste(valeur):
    if isinstance(valeur, str):
        try:
            valeur = json.loads(valeur)
        except ValueError:
            return []
    return list(valeur or [])


def upgrade() -> None:
    from app.domain import pieces

    connexion = op.get_bind()
    if "poste" not in inspect(connexion).get_table_names():
        return
    lignes = connexion.execute(
        sa.text(
            "SELECT id, pieces_requises, pieces_facultatives, groupes_pieces, "
            "pieces_libres_autorisees FROM poste"
        )
    ).all()
    for identifiant, requises, facultatives, groupes, libres in lignes:
        rangees = pieces.normaliser(_liste(requises), _liste(facultatives), _liste(groupes), bool(libres))
        if not rangees.remarques:
            continue
        connexion.execute(
            sa.text(
                "UPDATE poste SET pieces_requises = :r, pieces_facultatives = :f, "
                "groupes_pieces = :g, pieces_libres_autorisees = :l WHERE id = :id"
            ).bindparams(
                sa.bindparam("r", type_=sa.JSON()),
                sa.bindparam("f", type_=sa.JSON()),
                sa.bindparam("g", type_=sa.JSON()),
            ),
            {
                "r": rangees.requises,
                "f": rangees.facultatives,
                "g": rangees.groupes,
                "l": rangees.libres_autorisees,
                "id": identifiant,
            },
        )


def downgrade() -> None:
    # Le rangement n'est pas défait : l'état d'avant se contredisait.
    pass
