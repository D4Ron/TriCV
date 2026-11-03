"""candidats reçus par courriel : nom et prénom remis dans le bon ordre

L'import par courriel prenait le premier mot du libellé de l'expéditeur pour
le nom ; or une messagerie affiche « Prénom Nom ». Presque tous les dossiers
arrivés par courriel ont donc nom et prénom inversés, et quelques-uns portent
un libellé qui n'est pas une personne (« Yahoo! »). Constaté en production.

Ce qui est stocké, nom puis prénom, reproduit le libellé d'origine dans son
ordre ; on le relit avec la règle corrigée (`identite.depuis_entete`). Seuls
les dossiers que personne n'a confirmés (provenance EXTRAIT_IA) sont touchés.
Une migration ne passe qu'une fois : l'inversion ne peut pas être refaite sur
un dossier déjà corrigé.

Le CV, lui, n'est pas relu ici : « Relire les noms » dans l'application s'en
charge, et sait trancher l'ordre quand le CV écrit le NOM en capitales.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def nom_corrige(nom: str, prenom: str, email: str) -> tuple[str, str]:
    from app.services import identite

    libelle = f"{nom or ''} {prenom or ''}".strip()
    if libelle.lower() in ("inconnu", ""):
        libelle = ""
    nouveau_nom, nouveau_prenom = identite.depuis_entete(libelle, email or "")
    return (nouveau_nom or nom or "Inconnu")[:255], (nouveau_prenom if nouveau_nom else prenom or "")[:255]


def upgrade() -> None:
    connexion = op.get_bind()
    tables = inspect(connexion).get_table_names()
    if "candidat" not in tables or "candidature" not in tables:
        return
    lignes = connexion.execute(
        sa.text(
            "SELECT DISTINCT ca.id, ca.nom, ca.prenom, ca.email FROM candidat ca "
            "JOIN candidature c ON c.candidat_id = ca.id "
            "WHERE c.source = 'EMAIL' AND ca.provenance = 'EXTRAIT_IA'"
        )
    ).all()
    for identifiant, nom, prenom, email in lignes:
        nouveau = nom_corrige(nom, prenom, email)
        if nouveau == (nom, prenom or ""):
            continue
        connexion.execute(
            sa.text("UPDATE candidat SET nom = :n, prenom = :p WHERE id = :id"),
            {"n": nouveau[0], "p": nouveau[1], "id": identifiant},
        )


def downgrade() -> None:
    # L'ordre d'avant était faux : il n'est pas rétabli.
    pass
