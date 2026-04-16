"""Create the TTA database and user on local Postgres."""

import asyncio
import os
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# Read connection info from environment or fall back to Docker defaults
_PG_HOST = os.environ.get("TTA_PG_HOST", "localhost")
_PG_PORT = os.environ.get("TTA_PG_PORT", "5433")
_PG_SUPERUSER = os.environ.get("TTA_PG_SUPERUSER", "postgres")
_PG_SUPERPASS = os.environ.get("TTA_PG_SUPERPASS", "postgres")
_TTA_USER = os.environ.get("TTA_DB_USER", "tta")
_TTA_PASS = os.environ.get("TTA_DB_PASS", "tta")

CONN_URL = (
    f"postgresql+asyncpg://{_PG_SUPERUSER}:{_PG_SUPERPASS}"
    f"@{_PG_HOST}:{_PG_PORT}/postgres"
)


async def main() -> None:
    try:
        engine = create_async_engine(CONN_URL, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        print(f"Connected to {_PG_HOST}:{_PG_PORT}")
    except Exception as exc:
        print(f"ERROR: Could not connect to Postgres: {exc}")
        sys.exit(1)

    async with engine.connect() as conn:
        # Check if user exists
        r = await conn.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :u"),
            {"u": _TTA_USER},
        )
        if r.scalar() is None:
            # DDL doesn't support parameterised passwords; values come from env
            await conn.execute(
                sa.text(f"CREATE USER {_TTA_USER} WITH PASSWORD '{_TTA_PASS}'")
            )
            print(f"Created user '{_TTA_USER}'")
        else:
            print(f"User '{_TTA_USER}' already exists")

        # Check if database exists
        r = await conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :db"),
            {"db": _TTA_USER},
        )
        if r.scalar() is None:
            await conn.execute(
                sa.text(f"CREATE DATABASE {_TTA_USER} OWNER {_TTA_USER}")
            )
            print(f"Created database '{_TTA_USER}'")
        else:
            print(f"Database '{_TTA_USER}' already exists")

        # Grant privileges
        await conn.execute(
            sa.text(f"GRANT ALL PRIVILEGES ON DATABASE {_TTA_USER} TO {_TTA_USER}")
        )
        print(f"Granted privileges to '{_TTA_USER}'")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
