import logging
import os

import asyncpg

from app.store.db import acquire_conn

logger = logging.getLogger(__name__)


async def run_migrations(migrations_dir: str = "migrations") -> None:
    """Run all unapplied SQL migrations in ascending order."""
    if not os.path.isdir(migrations_dir):
        logger.warning(f"Migrations directory not found: {migrations_dir}")
        return

    files = [f for f in os.listdir(migrations_dir) if f.endswith(".sql")]
    files.sort()

    if not files:
        logger.info("No migration files found.")
        return

    async with acquire_conn() as conn:
        # Advisory lock to prevent concurrent migrations
        # 42 is an arbitrary key for the lock
        logger.info("Acquiring migration advisory lock")
        await conn.execute("SELECT pg_advisory_lock(42)")
        try:
            # Ensure schema_migrations table exists (in case 001 hasn't run)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INT PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )

            for file in files:
                try:
                    version = int(file.split("_")[0])
                except ValueError:
                    logger.warning(f"Skipping migration file with invalid prefix: {file}")
                    continue

                row = await conn.fetchrow(
                    "SELECT version FROM schema_migrations WHERE version = $1", version
                )
                if row is not None:
                    continue  # Already applied

                file_path = os.path.join(migrations_dir, file)
                logger.info(f"Applying migration: {file}")
                with open(file_path, "r", encoding="utf-8") as f:
                    sql = f.read()

                # Run each migration inside a transaction
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)", version
                    )
                logger.info(f"Successfully applied migration: {file}")

        finally:
            logger.info("Releasing migration advisory lock")
            await conn.execute("SELECT pg_advisory_unlock(42)")
