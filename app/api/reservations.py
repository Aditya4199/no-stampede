import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from app.store.db import acquire_conn
from app.exceptions import DomainError
from app.auth.jwt import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reservations")

class CancelResponse(BaseModel):
    status: str

@router.post("/{reservation_id}/cancel", response_model=CancelResponse)
async def cancel_reservation(reservation_id: uuid.UUID, user=Depends(get_current_user)):
    user_id = user.get("sub")
    if not user_id:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Missing sub in token"}})
        
    async with acquire_conn() as conn:
        async with conn.transaction():
            # Check if reservation exists and belongs to the user
            reservation = await conn.fetchrow(
                "SELECT show_id, status FROM reservations WHERE id = $1 AND user_id = $2 FOR UPDATE",
                reservation_id, user_id
            )
            
            if not reservation:
                # 404 if not owner or not found to avoid leaking existence
                raise DomainError("not_found", "Reservation not found", 404)
                
            if reservation["status"] == "cancelled":
                # Idempotent: cancelling twice -> 200
                return CancelResponse(status="cancelled")
                
            if reservation["status"] == "expired":
                raise DomainError("already_expired", "Reservation already expired", 409)
                
            show_id = reservation["show_id"]
            
            # 1. Free the seats
            # Keyed on reservation_id AND user_id to never free a seat owned by someone else
            freed_seats = await conn.fetch(
                """
                UPDATE seats 
                SET status = 'available', user_id = NULL, reservation_id = NULL, hold_expires_at = NULL
                WHERE reservation_id = $1 AND user_id = $2 AND status IN ('confirmed', 'held')
                RETURNING label
                """,
                reservation_id, user_id
            )
            
            rows_affected = len(freed_seats)
            if rows_affected > 0:
                # 2. Decrement the user quota by rows affected
                await conn.execute(
                    """
                    UPDATE user_show_quota
                    SET active_count = active_count - $1
                    WHERE user_id = $2 AND show_id = $3
                    """,
                    rows_affected, user_id, show_id
                )
                
            # 3. Mark reservation cancelled
            await conn.execute(
                """
                UPDATE reservations
                SET status = 'cancelled'
                WHERE id = $1
                """,
                reservation_id
            )

    return CancelResponse(status="cancelled")
