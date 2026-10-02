import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    
    await conn.execute("CREATE TABLE IF NOT EXISTS test_tx3 (user_id text, show_id text, active_count int, PRIMARY KEY (user_id, show_id))")
    await conn.execute("TRUNCATE test_tx3")
    
    class DomainError(Exception):
        pass

    async def worker(i):
        try:
            async with conn.transaction():
                quota = await conn.fetchrow(
                    """
                    INSERT INTO test_tx3 (user_id, show_id, active_count)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, show_id) DO UPDATE SET active_count = test_tx3.active_count + $3
                    RETURNING active_count
                    """,
                    "user1", "show1", 1
                )
                if quota["active_count"] > 4:
                    raise DomainError("limit")
        except DomainError:
            return "409"
        return "201"

    # We must use separate connections for concurrent workers
    async def run_with_pool(i, pool):
        async with pool.acquire() as c:
            try:
                async with c.transaction():
                    quota = await c.fetchrow(
                        """
                        INSERT INTO test_tx3 (user_id, show_id, active_count)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, show_id) DO UPDATE SET active_count = test_tx3.active_count + $3
                        RETURNING active_count
                        """,
                        "user1", "show1", 1
                    )
                    if quota["active_count"] > 4:
                        raise DomainError("limit")
            except DomainError:
                return "409"
            return "201"

    pool = await asyncpg.create_pool("postgresql://postgres:password@localhost:5432/no_stampede", min_size=10, max_size=10)
    tasks = [run_with_pool(i, pool) for i in range(10)]
    results = await asyncio.gather(*tasks)
    
    val = await conn.fetchval("SELECT active_count FROM test_tx3 WHERE user_id = 'user1'")
    print(f"Results: {results}")
    print(f"Count after all: {val}")
    
    await pool.close()
    await conn.close()

asyncio.run(main())
