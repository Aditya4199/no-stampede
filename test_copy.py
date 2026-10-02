import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    
    await conn.execute("CREATE TABLE IF NOT EXISTS test_seats (show_id UUID, label TEXT, status TEXT)")
    await conn.execute("TRUNCATE test_seats")
    
    show_id = uuid.uuid4()
    seat_records = [(show_id, "F1", "available")]
    
    try:
        await conn.copy_records_to_table(
            "test_seats",
            columns=["show_id", "label", "status"],
            records=seat_records,
        )
        print("Copy succeeded")
    except Exception as e:
        print(f"Copy failed: {e}")
        
    count = await conn.fetchval("SELECT count(*) FROM test_seats")
    print(f"Count: {count}")
    
    await conn.close()

asyncio.run(main())
