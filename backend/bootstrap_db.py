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

Une exception, ajoutée après coup : quand le modèle **relâche** une contrainte
NOT NULL, la table est reconstruite. SQLite ne sait pas modifier une contrainte
en place, et le cas s'est présenté pour de bon — `candidature.poste_id` a dû
s'ouvrir pour les candidatures spontanées, laissant la base de développement
refuser tout dépôt hors avis. Le relâchement est le seul changement de
contrainte traité ici, parce qu'il est le seul qui ne puisse invalider aucune
ligne existante.
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


def _litteral_defaut(colonne) -> str | None:
    """La valeur de départ d'une colonne NOT NULL, rendue en SQL.

    SQLAlchemy applique `default=` côté Python, à l'insertion : il n'apparaît
    donc pas dans le DDL, et `ALTER TABLE ... ADD COLUMN x NOT NULL` échoue sur
    une table déjà peuplée. On rend le défaut explicite ici — ce qui n'est
    possible que pour les valeurs simples, les seules qui aient un sens comme
    valeur de remplissage.
    """
    defaut = colonne.default
    if defaut is None or not getattr(defaut, "is_scalar", False):
        return None
    valeur = defaut.arg
    if isinstance(valeur, bool):
        return "1" if valeur else "0"
    if isinstance(valeur, (int, float)):
        return str(valeur)
    if isinstance(valeur, str):
        echappee = valeur.replace("'", "''")
        return f"'{echappee}'"
    return None


def _synchroniser(connection) -> list[str]:
    ajoutees: list[str] = []
    for nom_table, colonne in _colonnes_manquantes(connection):
        definition = CreateColumn(colonne).compile(connection.engine).string
        if not colonne.nullable and colonne.server_default is None:
            litteral = _litteral_defaut(colonne)
            if litteral is None:
                # Une colonne NOT NULL sans défaut exprimable ne peut pas être
                # ajoutée à une table qui contient déjà des lignes : cela
                # réclame une vraie migration, pas un raccourci.
                print(f"  ! {nom_table}.{colonne.name} : NOT NULL sans défaut, migration requise")
                continue
            definition = f"{definition} DEFAULT {litteral}"
        connection.execute(text(f'ALTER TABLE "{nom_table}" ADD COLUMN {definition}'))
        ajoutees.append(f"{nom_table}.{colonne.name}")
    return ajoutees


def _contraintes_relachees(connection) -> dict[str, list[str]]:
    """Les colonnes que le modèle a rendues nullables, mais NOT NULL en base.

    Le cas s'est présenté avec `candidature.poste_id` : une candidature
    spontanée ne vise aucun poste, donc la colonne a dû s'ouvrir. SQLite ne sait
    pas modifier une contrainte en place, et la synchronisation additive ne
    touche qu'aux colonnes absentes — la base restait donc en arrière et le
    premier dépôt spontané échouait.

    Seul le relâchement est traité, jamais le durcissement : passer de NULL
    autorisé à NULL interdit peut invalider des lignes existantes et demande une
    décision. L'inverse ne peut rien casser, puisqu'aucune ligne ne viole une
    contrainte plus faible.
    """
    inspecteur = inspect(connection)
    existantes = set(inspecteur.get_table_names())
    relachees: dict[str, list[str]] = {}

    for table in Base.metadata.sorted_tables:
        if table.name not in existantes:
            continue
        en_base = {c["name"]: c for c in inspecteur.get_columns(table.name)}
        for colonne in table.columns:
            ligne = en_base.get(colonne.name)
            if ligne is None:
                continue
            # `nullable` vaut False côté base quand la colonne est NOT NULL.
            if colonne.nullable and not ligne["nullable"] and not colonne.primary_key:
                relachees.setdefault(table.name, []).append(colonne.name)
    return relachees


def _reconstruire(connection, table) -> None:
    """Reconstruit une table SQLite à partir du modèle, données comprises.

    La procédure recommandée par SQLite : on met la table de côté, on recrée la
    bonne, on recopie, on jette l'ancienne. Les clés étrangères sont désactivées
    le temps de l'opération, et `legacy_alter_table` empêche SQLite de réécrire
    les références des *autres* tables vers le nom temporaire.

    Les index sont supprimés avant le renommage : leurs noms sont globaux dans
    SQLite, et ceux de la nouvelle table entreraient sinon en collision.
    """
    inspecteur = inspect(connection)
    colonnes_communes = [
        c.name
        for c in table.columns
        if c.name in {x["name"] for x in inspecteur.get_columns(table.name)}
    ]
    liste = ", ".join(f'"{c}"' for c in colonnes_communes)
    provisoire = f"{table.name}__ancien"

    for index in inspecteur.get_indexes(table.name):
        if index.get("name"):
            connection.execute(text(f'DROP INDEX IF EXISTS "{index["name"]}"'))

    connection.execute(text(f'ALTER TABLE "{table.name}" RENAME TO "{provisoire}"'))
    table.create(connection)
    connection.execute(
        text(f'INSERT INTO "{table.name}" ({liste}) SELECT {liste} FROM "{provisoire}"')
    )
    connection.execute(text(f'DROP TABLE "{provisoire}"'))


def _relacher(connection) -> list[str]:
    """Reconstruit les tables dont une contrainte s'est ouverte.

    Attend une connexion en autocommit : les pragmas `foreign_keys` et
    `legacy_alter_table` sont ignorés à l'intérieur d'une transaction, et
    l'opération n'aurait alors pas l'effet voulu.
    """
    relachees = _contraintes_relachees(connection)
    if not relachees:
        return []

    par_nom = {t.name: t for t in Base.metadata.sorted_tables}
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    try:
        for nom_table in relachees:
            _reconstruire(connection, par_nom[nom_table])
    finally:
        connection.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    return [f"{t}.{c}" for t, colonnes in relachees.items() for c in colonnes]


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        ajoutees = await connection.run_sync(_synchroniser)

    # La reconstruction se fait hors transaction : voir `_relacher`.
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        ouvertes = await autocommit.run_sync(_relacher)

    if ajoutees:
        print(f"schema ready (+{len(ajoutees)} colonne(s) : {', '.join(ajoutees)})")
    elif not ouvertes:
        print("schema ready")
    if ouvertes:
        print(f"  contrainte NOT NULL levée sur : {', '.join(ouvertes)}")


if __name__ == "__main__":
    asyncio.run(main())
