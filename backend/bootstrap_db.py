"""Create the schema directly from the models, for local SQLite development.

Docker runs `alembic upgrade head` against PostgreSQL instead — this is the
no-migration shortcut for the local dev script, where the database is a
throwaway file.
"""

from __future__ import annotations

import asyncio

from app.db import Base, engine
import app.models  # noqa: F401  (import side effect: registers every table)


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    print("schema ready")


if __name__ == "__main__":
    asyncio.run(main())
