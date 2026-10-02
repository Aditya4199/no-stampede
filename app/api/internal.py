import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_admin_user
from app.exceptions import DomainError
from app.store.db import acquire_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", dependencies=[Depends(get_current_admin_user)])


class ConfigureShowRequest(BaseModel):
    hold_ttl_seconds: int = Field(..., gt=0)


@router.patch("/shows/{show_id}", status_code=200)
async def configure_show(show_id: uuid.UUID, req: ConfigureShowRequest):
    async with acquire_conn() as conn:
        result = await conn.execute(
            """
            UPDATE shows
            SET hold_ttl_seconds = $1
            WHERE id = $2
            """,
            req.hold_ttl_seconds,
            show_id,
        )
        
        if result == "UPDATE 0":
            raise DomainError("show_not_found", "Show not found", 404)

    return {"status": "success"}
