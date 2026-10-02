import json
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncpg
import asyncio

from app.api import auth_router, health_router, internal_router, ready_router, shows_router
from app.config import Config
from app.exceptions import DomainError
from app.store.db import close_db, init_db
from app.store.migrations import run_migrations

class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [handler]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger = logging.getLogger("app")
    logger.info("Application starting up")
    cfg = app.state.config
    await init_db(cfg)
    await run_migrations()
    yield
    # Shutdown
    logger.info("Application shutting down")
    await close_db()

def create_app() -> FastAPI:
    setup_logging()
    cfg = Config.load()

    app = FastAPI(
        title="Seat Reservation at Scale",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.config = cfg

    # Routers
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(ready_router)
    app.include_router(internal_router)
    app.include_router(shows_router)
    
    # Exception handlers
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_error_handler(request: Request, exc: asyncio.TimeoutError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "service_unavailable", "message": "The service is currently overloaded"}},
            headers={"Retry-After": "5"}
        )

    @app.exception_handler(asyncpg.exceptions.QueryCanceledError)
    async def query_canceled_handler(request: Request, exc: asyncpg.exceptions.QueryCanceledError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "service_unavailable", "message": "Database query timed out"}},
            headers={"Retry-After": "5"}
        )

    return app


app = create_app()

if __name__ == "__main__":
    cfg = Config.load()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=cfg.port,
        log_config=None,  # Use custom JSON logging
    )
