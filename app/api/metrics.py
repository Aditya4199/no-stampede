from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.store.db import get_pool
from app.metrics.collector import seats_available, seats_held, seats_confirmed, db_pool_acquired_conns, db_pool_idle_conns

router = APIRouter()

@router.get("/metrics")
async def metrics():
    pool = get_pool()
    if pool:
        # Update pool metrics
        db_pool_acquired_conns.set(pool.get_size() - pool.get_idle_size())
        db_pool_idle_conns.set(pool.get_idle_size())

        # Update seat gauges from DB
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT show_id,
                       count(*) FILTER (WHERE status = 'available') as available,
                       count(*) FILTER (WHERE status = 'held') as held,
                       count(*) FILTER (WHERE status = 'confirmed') as confirmed
                FROM seats
                GROUP BY show_id
                """
            )
            for row in rows:
                show_id_str = str(row["show_id"])
                seats_available.labels(show_id=show_id_str).set(row["available"] or 0)
                seats_held.labels(show_id=show_id_str).set(row["held"] or 0)
                seats_confirmed.labels(show_id=show_id_str).set(row["confirmed"] or 0)

    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
