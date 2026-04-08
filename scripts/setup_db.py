"""Create the TTA database and user on local Postgres."""

import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

CONN_VARIANTS = [
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
    "postgresql+asyncpg://theinterneti:theinterneti@localhost:5432/postgres",
    "postgresql+asyncpg://theinterneti:@localhost:5432/postgres",
]


async def main() -> None:
    engine = None
    for url in CONN_VARIANTS:
        try:
            e = create_async_engine(url, isolation_level="AUTOCOMMIT")
            async with e.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            engine = e
            print(f"Connected with: {url}")
            break
        except Exception as exc:
            print(f"  SKIP  {url} — {exc}")
            await e.dispose()

    if engine is None:
        print("ERROR: Could not connect to local Postgres.")
        sys.exit(1)

    async with engine.connect() as conn:
        # Check if user exists
        r = await conn.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'tta'"))
        if r.scalar() is None:
            await conn.execute(sa.text("CREATE USER tta WITH PASSWORD 'tta'"))
            print("Created user 'tta'")
        else:
            print("User 'tta' already exists")

        # Check if database exists
        r = await conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = 'tta'")
        )
        if r.scalar() is None:
            await conn.execute(sa.text("CREATE DATABASE tta OWNER tta"))
            print("Created database 'tta'")
        else:
            print("Database 'tta' already exists")

        # Grant privileges
        await conn.execute(sa.text("GRANT ALL PRIVILEGES ON DATABASE tta TO tta"))
        print("Granted privileges on 'tta' to user 'tta'")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
