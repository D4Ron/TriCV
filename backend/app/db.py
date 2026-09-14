from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _activer_les_cles_etrangeres(connexion, _record) -> None:
        """SQLite ignore les clés étrangères tant qu'on ne le lui demande pas.

        Le défaut est OFF, et par connexion. Sans ce réglage, les `ondelete=
        "CASCADE"` déclarés sur les modèles ne s'appliquent qu'en PostgreSQL :
        en développement, supprimer un poste laissait ses candidatures en
        place, invisibles mais bien présentes — les pièces, notations et motifs
        s'accumulaient à chaque rechargement de la démo. L'installation locale
        se comportait donc autrement que celle qui compte.
        """
        curseur = connexion.cursor()
        curseur.execute("PRAGMA foreign_keys=ON")
        curseur.close()

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
