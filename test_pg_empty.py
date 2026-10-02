import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    await conn.execute("CREATE TABLE IF NOT EXISTS test_seats2 (id UUID, label TEXT, status TEXT)")
    await conn.execute("TRUNCATE test_seats2")
    
    my_id = uuid.uuid4()
    await conn.execute("INSERT INTO test_seats2 VALUES ($1, 'A1', 'available')", my_id)
    await conn.close()
    
    async def worker(worker_id):
        conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
        try:
            async with conn.transaction():
                seats_db = await conn.fetch("SELECT status FROM test_seats2 WHERE id = $1 AND label = ANY($2) FOR UPDATE", my_id, ['A1'])
                
                if len(seats_db) == 0:
                    return "FAIL: EMPTY"
                
                row = seats_db[0]
                if row["status"] != "available":
                    return f"TAKEN: {row['status']}"
                
                await asyncio.sleep(0.1)
                
                await conn.execute("UPDATE test_seats2 SET status = 'confirmed' WHERE id = $1 AND label = ANY($2)", my_id, ['A1'])
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
