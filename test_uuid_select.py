import asyncio
import asyncpg
import uuid

async def main():
    conn = await asyncpg.connect("postgresql://postgres:password@localhost:5432/no_stampede")
    
    my_id = str(uuid.uuid4())
    await conn.execute("INSERT INTO test_uuid VALUES ($1)", my_id)
    
    try:
        row = await conn.fetchrow("SELECT * FROM test_uuid WHERE id = $1", my_id)
        print("Select str succeeded:", row)
    except Exception as e:
        print(f"Select str failed: {e}")
        
    await conn.close()

asyncio.run(main())
