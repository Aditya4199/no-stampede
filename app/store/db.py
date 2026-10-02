import logging
from typing import Optional

import asyncpg

from app.config import Config

logger = logging.getLogger(__name__)

# Global connection pool
_pool: Optional[asyncpg.Pool] = None


async def init_db(config: Config) -> None:
    """Initialize the global asyncpg connection pool."""
    global _pool
    if _pool is not None:
        return

    logger.info("Initializing database connection pool")
    try:
        _pool = await asyncpg.create_pool(
            dsn=config.database_url,
            min_size=4,
            max_size=config.db_max_conns,
            server_settings={
                "statement_timeout": "5000",
                "lock_timeout": "3000",
                "timezone": "UTC",
            },
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error("Failed to initialize database connection pool", exc_info=True)
        raise e


async def close_db() -> None:
    """Close the global database connection pool."""
    global _pool
    if _pool is not None:
        logger.info("Closing database connection pool")
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


def get_pool() -> asyncpg.Pool:
    """Get the active connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool
