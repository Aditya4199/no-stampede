import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    await conn.execute("CREATE TABLE IF NOT EXISTS test_seats (id UUID, status TEXT)")
    await conn.execute("TRUNCATE test_seats")
    
    my_id = uuid.uuid4()
    await conn.execute("INSERT INTO test_seats VALUES ($1, 'available')", my_id)
    await conn.close()
    
    async def worker(worker_id):
        conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
        try:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT status FROM test_seats WHERE id = $1 FOR UPDATE", my_id)
                if row["status"] != "available":
                    raise Exception(f"Taken: {row['status']}")
                
                # Simulate work
                await asyncio.sleep(0.1)
                
                await conn.execute("UPDATE test_seats SET status = 'confirmed' WHERE id = $1", my_id)
                return "SUCCESS"
        except Exception as e:
            return f"FAIL: {e}"
        finally:
            await conn.close()

    tasks = [worker(i) for i in range(10)]
    results = await asyncio.gather(*tasks)
    
    successes = [r for r in results if r == "SUCCESS"]
    print(f"Successes: {len(successes)}")
    for r in results:
        if r != "SUCCESS":
            print(r)

asyncio.run(main())
