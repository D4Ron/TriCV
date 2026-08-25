"""Crée le schéma directement depuis les modèles, pour le SQLite de dev.

Docker exécute `alembic upgrade head` sur PostgreSQL ; ceci est le raccourci
sans migration du script de développement local.

`create_all` ne crée que les tables *absentes* : il ne touche jamais à une
table existante. Ajouter une colonne à un modèle laissait donc la base locale
en arrière, et la première écriture partait en erreur 500 sans rien expliquer.
D'où la synchronisation additive ci-dessous : elle ajoute les colonnes
manquantes, et seulement celles-là. Aucune suppression, aucune modification de
type — une base de développement doit suivre le code, pas être reconstruite à
chaque champ ajouté.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

import app.models  # noqa: F401  (effet de bord : enregistre toutes les tables)
from app.db import Base, engine


def _colonnes_manquantes(connection) -> list[tuple[str, object]]:
    inspecteur = inspect(connection)
    tables_existantes = set(inspecteur.get_table_names())
    manquantes: list[tuple[str, object]] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in tables_existantes:
            continue  # create_all s'en occupe
        connues = {c["name"] for c in inspecteur.get_columns(table.name)}
        for colonne in table.columns:
            if colonne.name not in connues:
                manquantes.append((table.name, colonne))
    return manquantes


def _synchroniser(connection) -> list[str]:
    ajoutees: list[str] = []
    for nom_table, colonne in _colonnes_manquantes(connection):
        if not colonne.nullable and colonne.server_default is None and colonne.default is None:
            # Une colonne NOT NULL sans défaut ne peut pas être ajoutée à une
            # table qui contient déjà des lignes : cela réclame une vraie
            # migration, pas un raccourci.
            print(f"  ! {nom_table}.{colonne.name} : NOT NULL sans défaut, migration requise")
            continue
        definition = CreateColumn(colonne).compile(connection.engine).string
        connection.execute(text(f'ALTER TABLE "{nom_table}" ADD COLUMN {definition}'))
        ajoutees.append(f"{nom_table}.{colonne.name}")
    return ajoutees


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        ajoutees = await connection.run_sync(_synchroniser)

    if ajoutees:
        print(f"schema ready (+{len(ajoutees)} colonne(s) : {', '.join(ajoutees)})")
    else:
        print("schema ready")


if __name__ == "__main__":
    asyncio.run(main())
