import time
import jwt
from typing import Dict, Any

from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import Config

security = HTTPBearer()

def decode_token(token: str, secret: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict[str, Any]:
    cfg: Config = request.app.state.config
    payload = decode_token(credentials.credentials, cfg.jwt_secret)
    
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    return payload
