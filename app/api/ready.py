import asyncio
import logging

import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.store.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/readyz")
async def readyz():
    """
    Readiness probe - checks database connectivity.
    Executes SELECT 1 with a strict 1-second timeout.
    Returns 503 if the database is down or overloaded.
    """
    try:
        pool = get_pool()
        # Acquire a connection and execute SELECT 1 with a strict timeout
        async def _check():
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
        await asyncio.wait_for(_check(), timeout=1.0)
        return JSONResponse(status_code=200, content={"status": "ready", "db": "ok"})
    except asyncio.TimeoutError:
        logger.error("Readiness check timed out waiting for database")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": "db timeout"},
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Readiness check database error: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(e)},
        )
    except Exception as e:
        logger.error(f"Readiness check unexpected error: {e}", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": "internal error"},
        )
