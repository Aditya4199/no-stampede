from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
async def healthz():
    """Liveness probe - returns 200 without checking external dependencies."""
    return JSONResponse(status_code=200, content={"status": "ok"})
