import time
import jwt
from typing import Dict, Any

from fastapi import Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import Config
from app.exceptions import DomainError

security = HTTPBearer()

def decode_token(token: str, secret: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise DomainError("unauthorized", "Token expired", 401)
    except jwt.InvalidTokenError:
        raise DomainError("unauthorized", "Invalid token", 401)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict[str, Any]:
    cfg: Config = request.app.state.config
    payload = decode_token(credentials.credentials, cfg.jwt_secret)
    request.state.user_id = payload.get("sub")
    return payload

async def get_current_admin_user(
    payload: Dict[str, Any] = Security(get_current_user)
) -> Dict[str, Any]:
    if payload.get("role") != "admin":
        raise DomainError("forbidden", "Admin privileges required", 403)
    return payload
