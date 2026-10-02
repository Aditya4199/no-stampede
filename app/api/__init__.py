"""API routers package."""
from app.api.health import router as health_router
from app.api.ready import router as ready_router

__all__ = ["health_router", "ready_router"]
