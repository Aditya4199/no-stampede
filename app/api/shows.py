import uuid
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.store.db import acquire_conn
from app.exceptions import DomainError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shows")


class ShowResponse(BaseModel):
    id: uuid.UUID
    name: str
    price_paise: int
    per_user_limit: int
    total_seats: int
    available_seats: int


@router.get("/{show_id}", response_model=ShowResponse)
async def get_show(show_id: uuid.UUID):
    async with acquire_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, price_paise, per_user_limit, total_seats
            FROM shows
            WHERE id = $1
            """,
            show_id
        )
        
        if not row:
            raise DomainError("show_not_found", "Show not found", 404)

        available_count = await conn.fetchval(
            """
            SELECT count(*)
            FROM seats
            WHERE show_id = $1 AND status = 'available'
            """,
            show_id
        )

    return ShowResponse(
        id=row["id"],
        name=row["name"],
        price_paise=row["price_paise"],
        per_user_limit=row["per_user_limit"],
        total_seats=row["total_seats"],
        available_seats=available_count
    )
