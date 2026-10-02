import logging
import uuid
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.store.db import acquire_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal")


class CreateShowRequest(BaseModel):
    name: str = Field(..., min_length=1)
    price_paise: int = Field(..., ge=0)
    per_user_limit: int = Field(4, gt=0)
    total_seats: int = Field(..., ge=0)


class CreateShowResponse(BaseModel):
    show_id: uuid.UUID


class ConfigureShowRequest(BaseModel):
    hold_ttl_seconds: int = Field(..., gt=0)


def generate_seat_labels(total_seats: int) -> List[str]:
    """
    Generate seat labels like A1..A10, B1..B10 up to total_seats.
    Uses rows A-Z (and AA-ZZ if needed) with 10 columns per row.
    """
    labels = []
    cols_per_row = 10
    
    def get_row_chars(row_idx: int) -> str:
        chars = ""
        while True:
            chars = chr(65 + (row_idx % 26)) + chars
            row_idx = (row_idx // 26) - 1
            if row_idx < 0:
                break
        return chars

    for i in range(total_seats):
        row_idx = i // cols_per_row
        col_idx = (i % cols_per_row) + 1
        row_chars = get_row_chars(row_idx)
        labels.append(f"{row_chars}{col_idx}")

    return labels


@router.post("/shows", response_model=CreateShowResponse, status_code=201)
async def create_show(req: CreateShowRequest):
    show_id = uuid.uuid4()
    labels = generate_seat_labels(req.total_seats)
    
    try:
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
                    req.total_seats,
                )
                
                # Batch insert seats
                if labels:
                    seat_records = [
                        (show_id, label, "available") for label in labels
                    ]
                    await conn.copy_records_to_table(
                        "seats",
                        columns=["show_id", "label", "status"],
                        records=seat_records,
                    )
                    
    except Exception as e:
        logger.error(f"Failed to create show: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create show")

    return CreateShowResponse(show_id=show_id)


@router.post("/shows/{show_id}", status_code=200)
async def configure_show(show_id: uuid.UUID, req: ConfigureShowRequest):
    try:
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
                raise HTTPException(status_code=404, detail="Show not found")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure show: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to configure show")

    return {"status": "success"}
