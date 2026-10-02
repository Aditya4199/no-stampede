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

from app.api import auth_router, health_router, ready_router, shows_router, reservations_router, metrics_router
from app.config import Config
from app.exceptions import DomainError
from app.store.db import close_db, init_db
from app.store.migrations import run_migrations
from app.store.reaper import start_reaper, stop_reaper

logger = logging.getLogger(__name__)

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
    await start_reaper(app)
    yield
    # Shutdown
    logger.info("Application shutting down")
    await stop_reaper(app)
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
    app.include_router(shows_router)
    app.include_router(reservations_router)
    app.include_router(metrics_router)
    
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    import uuid
    import traceback

    import time
    from app.metrics.collector import http_requests_total, http_request_duration_seconds, reservations_declined_total

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        start_time = time.perf_counter()
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        # Collect metrics
        duration = time.perf_counter() - start_time
        route_obj = request.scope.get("route")
        route = route_obj.path if route_obj else "unmatched"
        code = response.status_code
        http_requests_total.labels(route=route, code=code).inc()
        http_request_duration_seconds.labels(route=route).observe(duration)
        
        # Log request
        user_id = getattr(request.state, "user_id", "unknown")
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": route,
                "status": code,
                "duration_ms": round(duration * 1000, 2),
                "user_id": user_id
            }
        )
        return response

    @app.middleware("http")
    async def limit_upload_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                cl = int(content_length)
                if cl > 65536:  # 64KB
                    return JSONResponse(
                        status_code=400,
                        content={"error": {"code": "invalid_request", "message": "Request body too large"}},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_request", "message": "Invalid Content-Length"}},
                )
        # Also protect against chunked requests that exceed limit
        # This is a basic implementation; for full streaming protection we would need custom route class
        return await call_next(request)

    # Exception handlers
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        if exc.code in ("seat_taken", "per_user_limit", "idempotency_mismatch", "invalid_seats", "too_many_requests"):
            reservations_declined_total.labels(reason=exc.code).inc()
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_request", "message": str(exc)}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code_map = {401: "unauthorized", 403: "forbidden", 404: "not_found"}
        code = code_map.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": exc.detail}},
        )

    @app.exception_handler(asyncio.TimeoutError)
    @app.exception_handler(asyncpg.exceptions.QueryCanceledError)
    @app.exception_handler(asyncpg.exceptions.PostgresConnectionError)
    @app.exception_handler(OSError)
    async def database_timeout_error_handler(request: Request, exc: Exception):
        logger.error(f"Database error on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "too_many_requests", "message": "The service is currently overloaded. Please try again later."}},
            headers={"Retry-After": "5"}
        )
        
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(f"Unhandled exception [req_id={request_id}]: {exc}", exc_info=True)
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "too_many_requests", "message": "The service is currently overloaded. Please try again later."}},
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
