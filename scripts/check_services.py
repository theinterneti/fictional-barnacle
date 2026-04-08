"""Quick service connectivity check."""

import asyncio
import sys

import redis.asyncio as aioredis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    errors = []

    # --- Postgres ---
    try:
        engine = create_async_engine("postgresql+asyncpg://tta:tta@localhost:5433/tta")
        async with engine.connect() as conn:
            r = await conn.execute(sa.text("SELECT 1"))
            print(f"  Postgres: OK (SELECT 1 = {r.scalar()})")
            # Check tables
            r2 = await conn.execute(
                sa.text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = [row[0] for row in r2]
            print(f"  Tables:   {', '.join(tables) if tables else '(none)'}")
        await engine.dispose()
    except Exception as e:
        print(f"  Postgres: FAIL — {e}")
        errors.append("postgres")

    # --- Redis ---
    try:
        r = aioredis.Redis.from_url("redis://localhost:6379", decode_responses=True)
        pong = await r.ping()
        print(f"  Redis:    OK (ping = {pong})")
        await r.aclose()
    except Exception as e:
        print(f"  Redis:    FAIL — {e}")
        errors.append("redis")

    if errors:
        print(f"\nFailed: {', '.join(errors)}")
        sys.exit(1)
    else:
        print("\nAll services reachable.")


if __name__ == "__main__":
    asyncio.run(main())
