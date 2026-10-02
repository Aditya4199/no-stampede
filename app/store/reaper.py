import asyncio
import logging
from datetime import datetime, timezone
from app.store.db import get_pool

logger = logging.getLogger(__name__)

async def reap_expired_holds():
    while True:
        try:
            pool = get_pool()
            if not pool:
                await asyncio.sleep(5)
                continue
                
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Find reservations with held seats that have expired
                    # We lock the reservation rows FOR UPDATE SKIP LOCKED to avoid blocking
                    now = datetime.now(timezone.utc)
                    expired = await conn.fetch(
                        """
                        WITH expired_seats AS (
                            SELECT show_id, reservation_id, label
                            FROM seats
                            WHERE status = 'held' AND hold_expires_at < $1
                            FOR UPDATE SKIP LOCKED
                        ),
                        agg AS (
                            SELECT show_id, reservation_id, count(*) as expired_count
                            FROM expired_seats
                            GROUP BY show_id, reservation_id
                        )
                        SELECT * FROM agg
                        """,
                        now
                    )
                    
                    if not expired:
                        await asyncio.sleep(5)
                        continue

                    logger.info(f"Reaping {len(expired)} expired reservations")

                    for row in expired:
                        res_id = row["reservation_id"]
                        show_id = row["show_id"]
                        expired_count = row["expired_count"]
                        
                        # 1. Update seats
                        await conn.execute(
                            """
                            UPDATE seats
                            SET status = 'available', user_id = NULL, reservation_id = NULL, hold_expires_at = NULL
                            WHERE reservation_id = $1 AND status = 'held' AND hold_expires_at < $2
                            """,
                            res_id, now
                        )
                        
                        # 2. Update reservation
                        # Find the user_id for quota update
                        res = await conn.fetchrow("SELECT user_id FROM reservations WHERE id = $1", res_id)
                        if res:
                            await conn.execute(
                                """
                                UPDATE reservations
                                SET status = 'expired'
                                WHERE id = $1
                                """,
                                res_id
                            )
                            
                            # 3. Decrement quota
                            await conn.execute(
                                """
                                UPDATE user_show_quota
                                SET active_count = active_count - $1
                                WHERE user_id = $2 AND show_id = $3
                                """,
                                expired_count, res["user_id"], show_id
                            )
                            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in hold reaper: {e}")
            
        await asyncio.sleep(5)

async def start_reaper(app):
    app.state.reaper_task = asyncio.create_task(reap_expired_holds())

async def stop_reaper(app):
    if hasattr(app.state, 'reaper_task'):
        app.state.reaper_task.cancel()
        try:
            await app.state.reaper_task
        except asyncio.CancelledError:
            pass
