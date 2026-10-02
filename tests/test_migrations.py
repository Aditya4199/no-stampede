import os
import pytest

from app.config import Config
from app.store.db import init_db, close_db, get_pool
from app.store.migrations import run_migrations

@pytest.mark.asyncio
async def test_migrations_are_idempotent():
    # Only run this test if a real database is available
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set, skipping real db migration test")

    cfg = Config.load()
    
    # Initialize connection
    await init_db(cfg)
    
    try:
        # Run migrations first time
        await run_migrations()
        
        # Run migrations second time
        await run_migrations()
        
        # Verify schema_migrations table exists and has 1 entry
        pool = get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT count(*) FROM schema_migrations")
            import glob
            files = glob.glob("migrations/*.sql")
            assert count == len(files)
    finally:
        await close_db()
