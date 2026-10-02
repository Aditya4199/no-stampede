import logging
from typing import Optional
from contextlib import asynccontextmanager
import time

import asyncpg

from app.config import Config

logger = logging.getLogger(__name__)

# Global connection pool
_pool: Optional[asyncpg.Pool] = None
_config: Optional[Config] = None


async def init_db(config: Config) -> None:
    """Initialize the global asyncpg connection pool."""
    global _pool, _config
    if _pool is not None:
        await close_db()

    _config = config
    logger.info("Initializing database connection pool")
    try:
        _pool = await asyncpg.create_pool(
            config.database_url,
            min_size=5,
            max_size=20,
            command_timeout=30.0,
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error("Failed to initialize database connection pool", exc_info=True)
        raise e


async def close_db() -> None:
    """Close the global database connection pool."""
    global _pool, _config
    if _pool is not None:
        logger.info("Closing database connection pool")
        await _pool.close()
        _pool = None
        _config = None
        logger.info("Database connection pool closed")


def get_pool() -> asyncpg.Pool:
    """Get the active connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool


@asynccontextmanager
async def acquire_conn():
    """Acquire a connection from the pool with the configured timeout and measure wait duration."""
    if _pool is None or _config is None:
        raise RuntimeError("Database pool is not initialized")
        
    start_time = time.perf_counter()
    async with _pool.acquire(timeout=_config.db_pool_acquire_timeout) as conn:
        wait_duration = time.perf_counter() - start_time
        from app.metrics.collector import db_pool_wait_duration_seconds
        db_pool_wait_duration_seconds.observe(wait_duration)
        yield conn
