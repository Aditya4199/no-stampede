import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    
    await conn.execute("CREATE TABLE IF NOT EXISTS test_uuid (id UUID)")
    await conn.execute("TRUNCATE test_uuid")
    
    my_id = str(uuid.uuid4())
    
    try:
        await conn.execute("INSERT INTO test_uuid VALUES ($1)", my_id)
        print("Insert str succeeded")
    except Exception as e:
        print(f"Insert str failed: {e}")
        
    await conn.close()

asyncio.run(main())
