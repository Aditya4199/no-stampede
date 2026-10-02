import asyncio
import asyncpg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool("postgresql://postgres:password@localhost:5432/no_stampede")
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS test_api_tx (id int, count int, PRIMARY KEY (id))")
        await conn.execute("TRUNCATE test_api_tx")
    yield
    await pool.close()

app = FastAPI(lifespan=lifespan)

class DomainError(Exception):
    def __init__(self, code, msg, status):
        self.code = code
        self.msg = msg
        self.status = status

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status, content={"error": exc.code})

@app.post("/test")
async def test_route():
    async with pool.acquire() as conn:
        async with conn.transaction():
            quota = await conn.fetchrow(
                """
                INSERT INTO test_api_tx (id, count) VALUES (1, 1)
                ON CONFLICT (id) DO UPDATE SET count = test_api_tx.count + 1
                RETURNING count
                """
            )
            if quota["count"] > 4:
                raise DomainError("limit", "limit", 409)
    return {"status": "ok"}
