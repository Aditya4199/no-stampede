import json
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI

from app.api import health_router, ready_router
from app.config import Config
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
    app.include_router(health_router)
    app.include_router(ready_router)

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
