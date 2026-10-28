"""courriel : Microsoft 365 seul, les réglages IMAP et SMTP retirés

Le cabinet relève et envoie par Microsoft Graph ; les voies IMAP et SMTP ont
été retirées du code. Quatre réglages restent utiles sous un nouveau nom —
l'adresse de la boîte, son dossier, l'activation de l'envoi et l'adresse
d'expédition — et sont renommés. Le reste est supprimé, mots de passe compris :
un secret qu'aucun code ne lit n'a plus rien à faire en base.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENOMMES = {
    "imap_user": "adresse_boite",
    "imap_folder": "dossier_boite",
    "smtp_actif": "envoi_actif",
    "smtp_expediteur": "adresse_expediteur",
}

SUPPRIMES = (
    "imap_host",
    "imap_port",
    "imap_password",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_tls",
    "oauth_refresh_token",
    "fournisseur_courriel",
)


def upgrade() -> None:
    connexion = op.get_bind()
    if "parametre" not in inspect(connexion).get_table_names():
        return
    for ancienne, nouvelle in RENOMMES.items():
        # Le nouveau nom l'emporte s'il existe déjà : c'est le plus récent.
        deja = connexion.execute(
            sa.text("SELECT 1 FROM parametre WHERE cle = :cle"), {"cle": nouvelle}
        ).first()
        if deja is None:
            connexion.execute(
                sa.text("UPDATE parametre SET cle = :nouvelle WHERE cle = :ancienne"),
                {"nouvelle": nouvelle, "ancienne": ancienne},
            )
        else:
            connexion.execute(
                sa.text("DELETE FROM parametre WHERE cle = :cle"), {"cle": ancienne}
            )
    for cle in SUPPRIMES:
        connexion.execute(sa.text("DELETE FROM parametre WHERE cle = :cle"), {"cle": cle})


def downgrade() -> None:
    # Les secrets supprimés ne se recréent pas ; les renommés reprennent leur nom.
    connexion = op.get_bind()
    if "parametre" not in inspect(connexion).get_table_names():
        return
    for ancienne, nouvelle in RENOMMES.items():
        connexion.execute(
            sa.text("UPDATE parametre SET cle = :ancienne WHERE cle = :nouvelle"),
            {"nouvelle": nouvelle, "ancienne": ancienne},
        )
