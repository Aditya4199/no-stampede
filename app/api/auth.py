import time
import jwt
import hmac
from fastapi import APIRouter, Request, Header
from app.exceptions import DomainError

router = APIRouter(prefix="/auth")

@router.post("/token")
async def issue_token(
    request: Request,
    user_id: str = "test-user",
    role: str = "user",
    admin_key: str | None = Header(default=None, alias="ADMIN_KEY")
):
    """Development token issuer."""
    cfg = request.app.state.config
    
    if role == "admin":
        if cfg.env != "dev":
            if not cfg.admin_key or not admin_key or not hmac.compare_digest(cfg.admin_key, admin_key):
                raise DomainError("forbidden", "Admin privileges cannot be minted in this environment without valid ADMIN_KEY", 403)
            
    payload = {
        "sub": user_id,
        "role": role,
        "exp": int(time.time()) + 3600
    }
    token = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")
    return {"token": token}
