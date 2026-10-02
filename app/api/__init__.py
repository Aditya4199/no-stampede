from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.ready import router as ready_router
from app.api.shows import router as shows_router

__all__ = ["auth_router", "health_router", "ready_router", "internal_router", "shows_router"]
