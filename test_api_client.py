import asyncio
import httpx
import asyncpg

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        tasks = [client.post("/test") for _ in range(10)]
        results = await asyncio.gather(*tasks)
        print([r.status_code for r in results])
        
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    count = await conn.fetchval("SELECT count FROM test_api_tx WHERE id = 1")
    print(f"Count: {count}")
    await conn.close()

asyncio.run(main())
