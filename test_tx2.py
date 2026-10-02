import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    await conn.execute("CREATE TABLE IF NOT EXISTS test_tx2 (id int, active_count int, PRIMARY KEY (id))")
    await conn.execute("TRUNCATE test_tx2")
    
    class DomainError(Exception):
        pass

    try:
        async with conn.transaction():
            await conn.execute("INSERT INTO test_tx2 VALUES (1, 1) ON CONFLICT (id) DO UPDATE SET active_count = test_tx2.active_count + 1")
            raise DomainError("abort")
    except DomainError:
        pass
        
    val = await conn.fetchval("SELECT active_count FROM test_tx2 WHERE id = 1")
    print(f"Count after rollback: {val}")
    await conn.close()

asyncio.run(main())
