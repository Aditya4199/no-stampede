import uuid
import logging
import json
import hashlib
import asyncio
import random
import asyncpg
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.store.db import acquire_conn
from app.exceptions import DomainError
from app.auth.jwt import get_current_admin_user, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shows")

_reserve_semaphore: Optional[asyncio.Semaphore] = None

def get_reserve_semaphore(request: Request) -> asyncio.Semaphore:
    global _reserve_semaphore
    if _reserve_semaphore is None:
        _reserve_semaphore = asyncio.Semaphore(request.app.state.config.max_inflight_reserves)
    return _reserve_semaphore

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

class ReserveRequest(BaseModel):
    seats: List[str] = Field(..., min_length=1, max_length=10)
    idempotency_key: Optional[str] = None

    @field_validator("seats")
    @classmethod
    def validate_seats(cls, seats: List[str]) -> List[str]:
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

class ReserveResponse(BaseModel):
    reservation_id: uuid.UUID
    show_id: uuid.UUID
    user_id: str
    status: str
    amount_paise: int
    seats: List[str]

@router.post("/{show_id}/reserve", response_model=ReserveResponse, status_code=201)
async def reserve_seats(
    request: Request,
    show_id: uuid.UUID,
    req: ReserveRequest,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    user=Depends(get_current_user)
):
    user_id = user.get("sub")
    if not user_id:
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Missing sub in token"}})
        
    idempotency_key = idempotency_key_header or req.idempotency_key
    if not idempotency_key:
        return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": "Idempotency key is required"}})

    sorted_seats = sorted(req.seats)
    req_hash = hashlib.sha256(f"{show_id}-{','.join(sorted_seats)}".encode()).hexdigest()
    num_seats = len(sorted_seats)

    sem = get_reserve_semaphore(request)
    try:
        async with asyncio.timeout(0.05):
            await sem.acquire()
    except TimeoutError:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "too_many_requests", "message": "The service is currently overloaded. Please try again later."}},
            headers={"Retry-After": "1"}
        )

    try:
        # 1. Fast pre-check on short-lived connection
        async with acquire_conn() as conn:
            now_row = await conn.fetchrow("SELECT NOW()")
            now = now_row["now"]
            pre_check = await conn.fetch(
                "SELECT label, status, hold_expires_at FROM seats WHERE show_id = $1 AND label = ANY($2)",
                show_id, sorted_seats
            )
            if len(pre_check) != num_seats:
                raise DomainError("invalid_seats", "One or more seats are invalid", 400)
                
            for seat in pre_check:
                if seat["status"] == "available":
                    continue
                if seat["status"] == "held" and seat["hold_expires_at"] and seat["hold_expires_at"] < now:
                    continue
                raise DomainError("seat_taken", f"Seat {seat['label']} is not available", 409)

        for attempt in range(1, 4):
            try:
                async with acquire_conn() as conn:
                    async with conn.transaction():
                        try:
                            row = await conn.fetchrow(
                                """
                                INSERT INTO idempotency_keys (user_id, key, show_id, request_hash)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, key) DO NOTHING
                                RETURNING 1
                                """,
                                user_id, idempotency_key, show_id, req_hash
                            )
                        except asyncpg.exceptions.ForeignKeyViolationError:
                            raise DomainError("not_found", "Show not found", 404)
                        if not row:
                            idem = await conn.fetchrow(
                                "SELECT request_hash, response, status_code FROM idempotency_keys WHERE user_id=$1 AND key=$2",
                                user_id, idempotency_key
                            )
                            if idem["request_hash"] != req_hash:
                                raise DomainError("idempotency_mismatch", "Idempotency key already used for a different request", 409)
                            if idem["response"] is not None:
                                return JSONResponse(status_code=idem["status_code"], content=json.loads(idem["response"]))
                            else:
                                raise DomainError("conflict", "Concurrent request processing for same idempotency key", 409)

                    # 3. Fetch show config
                    show = await conn.fetchrow("SELECT price_paise, per_user_limit, hold_ttl_seconds FROM shows WHERE id=$1", show_id)
                    if not show:
                        raise DomainError("not_found", "Show not found", 404)
                    amount_paise = show["price_paise"] * num_seats

                    # 4. Lock seats FOR UPDATE in deterministic order
                    seats_db = await conn.fetch(
                        """
                        SELECT label, status, hold_expires_at, reservation_id, user_id FROM seats 
                        WHERE show_id = $1 AND label = ANY($2)
                        ORDER BY label
                        FOR UPDATE
                        """,
                        show_id, sorted_seats
                    )
                    
                    now_row = await conn.fetchrow("SELECT NOW()")
                    now = now_row["now"]
                    
                    old_owners = {}
                    for seat in seats_db:
                        if seat["status"] == "available":
                            continue
                        if seat["status"] == "held" and seat["hold_expires_at"] and seat["hold_expires_at"] < now:
                            old_res_id = seat["reservation_id"]
                            if old_res_id:
                                if old_res_id not in old_owners:
                                    old_owners[old_res_id] = {"user_id": seat["user_id"], "count": 0}
                                old_owners[old_res_id]["count"] += 1
                            continue
                        raise DomainError("seat_taken", f"Seat {seat['label']} is not available", 409)

                    # 5. User quota check
                    quota = await conn.fetchrow(
                        """
                        INSERT INTO user_show_quota (user_id, show_id, active_count)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, show_id) DO UPDATE SET active_count = user_show_quota.active_count + $3
                        RETURNING active_count
                        """,
                        user_id, show_id, num_seats
                    )
                    if quota["active_count"] > show["per_user_limit"]:
                        raise DomainError("per_user_limit", f"Cannot reserve more than {show['per_user_limit']} seats", 409)

                    # 6. Reserve seats
                    reservation_id = uuid.uuid4()
                    if show["hold_ttl_seconds"]:
                        status = "held"
                        ttl = show["hold_ttl_seconds"]
                        expires_at = now + timedelta(seconds=ttl)
                    else:
                        status = "confirmed"
                        expires_at = None

                    await conn.execute(
                        """
                        UPDATE seats
                        SET status = $1, user_id = $2, reservation_id = $3, hold_expires_at = $4
                        WHERE show_id = $5 AND label = ANY($6)
                        """,
                        status, user_id, reservation_id, expires_at, show_id, sorted_seats
                    )
                    
                    if old_owners:
                        for old_res_id, info in old_owners.items():
                            await conn.execute(
                                """
                                UPDATE user_show_quota 
                                SET active_count = active_count - $1
                                WHERE user_id = $2 AND show_id = $3
                                """,
                                info["count"], info["user_id"], show_id
                            )
                            
                            remaining = await conn.fetchval(
                                "SELECT count(*) FROM seats WHERE reservation_id = $1",
                                old_res_id
                            )
                            if remaining == 0:
                                await conn.execute(
                                    "UPDATE reservations SET status = 'expired' WHERE id = $1 AND status != 'cancelled'",
                                    old_res_id
                                )

                    await conn.execute(
                        """
                        INSERT INTO reservations (id, show_id, user_id, seats, amount_paise, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        reservation_id, show_id, user_id, sorted_seats, amount_paise, status
                    )

                    resp_dict = {
                        "reservation_id": str(reservation_id),
                        "show_id": str(show_id),
                        "user_id": user_id,
                        "status": status,
                        "amount_paise": amount_paise,
                        "seats": sorted_seats
                    }
                    
                    # Metrics
                    from app.metrics.collector import reservations_confirmed_total
                    reservations_confirmed_total.labels(show_id=str(show_id)).inc()
                    
                    await conn.execute(
                        """
                        UPDATE idempotency_keys
                        SET response = $1, status_code = 201
                        WHERE user_id = $2 AND key = $3
                        """,
                        json.dumps(resp_dict), user_id, idempotency_key
                    )

                    return ReserveResponse(**resp_dict)
            except (asyncpg.exceptions.DeadlockDetectedError, asyncpg.exceptions.LockNotAvailableError):
                if attempt == 3:
                    raise DomainError("seat_taken", "Seat lock timeout", 409)
                await asyncio.sleep(random.uniform(0.1, 0.5))
    finally:
        sem.release()
