import uuid
import logging
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.store.db import acquire_conn
from app.exceptions import DomainError
from app.auth.jwt import get_current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shows")


class SeatItem(BaseModel):
    label: str
    status: str

class CreateShowRequest(BaseModel):
    name: str = Field(..., min_length=1)
    price_paise: int = Field(..., ge=0)
    per_user_limit: int = Field(4, gt=0)
    hold_ttl_seconds: Optional[int] = Field(None, gt=0)
    seats: List[str] = Field(..., max_length=10000)
    
    @field_validator("seats")
    @classmethod
    def validate_seats(cls, seats: List[str]) -> List[str]:
        if not seats:
            raise ValueError("Seat list cannot be empty")
        seen = set()
        for seat in seats:
            if not seat or len(seat.strip()) == 0:
                raise ValueError("Seat label cannot be empty")
            if len(seat) > 16:
                raise ValueError(f"Seat label '{seat}' is over 16 characters")
            if seat in seen:
                raise ValueError(f"Duplicate seat label '{seat}' found")
            seen.add(seat)
        return seats


class ShowResponse(BaseModel):
    id: uuid.UUID
    name: str
    price_paise: int
    per_user_limit: int
    total_seats: int
    available: int = 0
    held: int = 0
    confirmed: int = 0
    seats: List[SeatItem] = []


@router.post("", response_model=ShowResponse, status_code=201)
async def create_show(req: CreateShowRequest, admin=Depends(get_current_admin_user)):
    show_id = uuid.uuid4()
    total_seats = len(req.seats)
    
    async with acquire_conn() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO shows (id, name, price_paise, per_user_limit, hold_ttl_seconds, total_seats)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                show_id,
                req.name,
                req.price_paise,
                req.per_user_limit,
                req.hold_ttl_seconds,
                total_seats,
            )
            
            seat_records = [(show_id, label, "available") for label in req.seats]
            await conn.copy_records_to_table(
                "seats",
                columns=["show_id", "label", "status"],
                records=seat_records,
            )

    return ShowResponse(
        id=show_id,
        name=req.name,
        price_paise=req.price_paise,
        per_user_limit=req.per_user_limit,
        total_seats=total_seats,
        available=total_seats,
        held=0,
        confirmed=0,
        seats=[SeatItem(label=label, status="available") for label in req.seats]
    )


@router.get("/{show_id}", response_model=ShowResponse)
async def get_show(show_id: uuid.UUID):
    async with acquire_conn() as conn:
        row = await conn.fetchrow(
            """
            WITH seat_counts AS (
                SELECT show_id,
                       count(*) as total,
                       count(*) FILTER (WHERE status = 'available') as available_count,
                       count(*) FILTER (WHERE status = 'held') as held_count,
                       count(*) FILTER (WHERE status = 'confirmed') as confirmed_count,
                       jsonb_agg(jsonb_build_object('label', label, 'status', status) ORDER BY label) as seats_json
                FROM seats
                WHERE show_id = $1
                GROUP BY show_id
            )
            SELECT s.id, s.name, s.price_paise, s.per_user_limit,
                   coalesce(c.total, 0) as total,
                   coalesce(c.available_count, 0) as available,
                   coalesce(c.held_count, 0) as held,
                   coalesce(c.confirmed_count, 0) as confirmed,
                   coalesce(c.seats_json, '[]'::jsonb) as seats
            FROM shows s
            LEFT JOIN seat_counts c ON s.id = c.show_id
            WHERE s.id = $1
            """,
            show_id
        )
        
        if not row:
            raise DomainError("not_found", "Show not found", 404)

    return ShowResponse(
        id=row["id"],
        name=row["name"],
        price_paise=row["price_paise"],
        per_user_limit=row["per_user_limit"],
        total_seats=row["total"],
        available=row["available"],
        held=row["held"],
        confirmed=row["confirmed"],
        seats=[SeatItem(**s) for s in (json.loads(row["seats"]) if isinstance(row["seats"], str) else row["seats"])]
    )


class ConfigureShowRequest(BaseModel):
    hold_ttl_seconds: int = Field(..., gt=0)

@router.patch("/{show_id}", status_code=200)
async def configure_show(show_id: uuid.UUID, req: ConfigureShowRequest, admin=Depends(get_current_admin_user)):
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
            raise DomainError("not_found", "Show not found", 404)

    return {"status": "success"}
