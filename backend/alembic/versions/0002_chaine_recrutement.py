"""chaîne de recrutement, collaboration et rapports

La migration initiale ne couvre que l'ancien modèle (session / candidat). Toute
la chaîne — client, mandat, poste, avis, candidature, notation, entretien — puis
les ajouts de collaboration — accès client, échanges, chronogramme, courriels
envoyés, gabarits imposés, rapports — n'avaient jamais été migrés : le
développement local passait par `bootstrap_db.py`, et le déploiement PostgreSQL
serait donc parti avec un schéma incomplet.

Cette révision crée ce qui manque **à partir des modèles**, et non d'une
transcription à la main. Le motif est simple : recopier vingt-et-une tables
dans un fichier de migration introduit des écarts silencieux entre ce que le
code attend et ce que la base contient, et c'est précisément ce genre d'écart
qui ne se découvre qu'en production. `create_all` ne touche jamais une table
existante ; la synchronisation additive qui suit n'ajoute que des colonnes
absentes et nullables.

Ce qu'elle ne fait pas, volontairement : supprimer, renommer, ni changer un
type. Ces opérations-là demandent une décision et une reprise de données ; les
faire passer pour un rattrapage automatique serait dangereux.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect
from sqlalchemy.schema import CreateColumn

import app.models  # noqa: F401  (effet de bord : enregistre toutes les tables)
from app.db import Base

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _colonnes_manquantes(connexion) -> list[tuple[str, object]]:
    inspecteur = inspect(connexion)
    existantes = set(inspecteur.get_table_names())
    manquantes: list[tuple[str, object]] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existantes:
            continue
        connues = {c["name"] for c in inspecteur.get_columns(table.name)}
        for colonne in table.columns:
            if colonne.name not in connues:
                manquantes.append((table.name, colonne))
    return manquantes


def _litteral_defaut(colonne) -> str | None:
    """La valeur de départ d'une colonne NOT NULL, rendue en SQL.

    SQLAlchemy applique `default=` côté Python, à l'insertion : il n'apparaît
    pas dans le DDL, et `ADD COLUMN x NOT NULL` échoue sur une table peuplée.
    """
    defaut = colonne.default
    if defaut is None or not getattr(defaut, "is_scalar", False):
        return None
    valeur = defaut.arg
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, (int, float)):
        return str(valeur)
    if isinstance(valeur, str):
        echappee = valeur.replace("'", "''")
        return f"'{echappee}'"
    return None


def upgrade() -> None:
    connexion = op.get_bind()

    # N'ajoute que les tables absentes. Celles de 0001 ne sont pas touchées.
    Base.metadata.create_all(bind=connexion, checkfirst=True)

    for nom_table, colonne in _colonnes_manquantes(connexion):
        definition = CreateColumn(colonne).compile(connexion.engine).string
        if not colonne.nullable and colonne.server_default is None:
            litteral = _litteral_defaut(colonne)
            if litteral is None:
                # Le cas ne se présente pas aujourd'hui, mais échouer
                # bruyamment vaut mieux que d'inventer une valeur de
                # remplissage pour des dossiers réels.
                raise RuntimeError(
                    f"{nom_table}.{colonne.name} est NOT NULL sans défaut "
                    "exprimable : cette colonne demande une vraie migration."
                )
            definition = f"{definition} DEFAULT {litteral}"
        op.execute(f'ALTER TABLE "{nom_table}" ADD COLUMN {definition}')


def downgrade() -> None:
    # Rien : cette révision ne fait qu'ajouter, et retirer les tables de la
    # chaîne de recrutement effacerait tous les dossiers. Une base à
    # reconstruire se recrée depuis zéro.
    pass
