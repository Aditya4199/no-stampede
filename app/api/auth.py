import time
import jwt
from fastapi import APIRouter, Request

router = APIRouter(prefix="/auth")

@router.post("/token")
async def issue_token(request: Request, user_id: str = "test-user", role: str = "user"):
    """Development token issuer."""
    cfg = request.app.state.config
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": int(time.time()) + 3600
    }
    token = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")
    return {"token": token}
