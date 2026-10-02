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


class CreateShowRequest(BaseModel):
    name: str = Field(..., min_length=1)
    price_paise: int = Field(..., ge=0)
    per_user_limit: int = Field(4, gt=0)
    seats: List[str] = Field(..., max_length=10000)


class CreateShowResponse(BaseModel):
    show_id: uuid.UUID


class ConfigureShowRequest(BaseModel):
    hold_ttl_seconds: int = Field(..., gt=0)


@router.post("/shows", response_model=CreateShowResponse, status_code=201)
async def create_show(req: CreateShowRequest):
    show_id = uuid.uuid4()
    total_seats = len(req.seats)
    
    async with acquire_conn() as conn:
        async with conn.transaction():
            # Insert show
            await conn.execute(
                """
                INSERT INTO shows (id, name, price_paise, per_user_limit, total_seats)
                VALUES ($1, $2, $3, $4, $5)
                """,
                show_id,
                req.name,
                req.price_paise,
                req.per_user_limit,
                total_seats,
            )
            
            # Batch insert seats
            if req.seats:
                seat_records = [
                    (show_id, label, "available") for label in req.seats
                ]
                await conn.copy_records_to_table(
                    "seats",
                    columns=["show_id", "label", "status"],
                    records=seat_records,
                )

    return CreateShowResponse(show_id=show_id)


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
