"""pièces reçues par courriel : reclassement d'après leur nom

L'import par courriel rangeait en « CV » tout fichier qu'il ne reconnaissait
pas : passeport, carte d'identité, certificat de travail, certificat de langue.
Constaté en production. Le classement est corrigé dans le code ; cette
migration répare les pièces déjà importées.

Prudente : une pièce n'est touchée que si son type est exactement celui que
l'ancienne règle aurait donné — donc que personne ne l'a corrigé depuis — et
que la nouvelle règle reconnaît, au nom du fichier, un autre type. Le contenu
n'est pas relu ici ; les notes se recalculent depuis le poste (« Recalculer »).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def ancien_type(nom: str) -> str:
    """La règle d'avant, recopiée telle quelle : ce qu'elle a produit."""
    normalise = (nom or "").lower()
    if any(mot in normalise for mot in ("motivation", "lm", "lettre")):
        return "LETTRE_MOTIVATION"
    if any(mot in normalise for mot in ("diplome", "diplôme", "attestation")):
        return "COPIE_DIPLOMES"
    return "CV"


def nouveau_type(nom: str) -> tuple[str | None, str | None]:
    from app.services import lots

    return lots.classer(nom or "")


def upgrade() -> None:
    connexion = op.get_bind()
    tables = inspect(connexion).get_table_names()
    if "piece_candidature" not in tables or "candidature" not in tables:
        return
    lignes = connexion.execute(
        sa.text(
            "SELECT p.id, p.nom_fichier, p.type_piece FROM piece_candidature p "
            "JOIN candidature c ON c.id = p.candidature_id "
            "WHERE c.source = 'EMAIL' AND p.nom_fichier IS NOT NULL"
        )
    ).all()
    for identifiant, nom, actuel in lignes:
        if actuel != ancien_type(nom):
            continue  # corrigé à la main depuis, ou classé autrement : on n'y touche pas
        type_piece, intitule = nouveau_type(nom)
        if type_piece is None or type_piece == actuel:
            continue
        connexion.execute(
            sa.text(
                "UPDATE piece_candidature SET type_piece = :t, intitule_libre = :i WHERE id = :id"
            ),
            {"t": type_piece, "i": intitule, "id": identifiant},
        )


def downgrade() -> None:
    # Le reclassement n'est pas défait : l'ancien était faux.
    pass
