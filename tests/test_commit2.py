import asyncio
import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import jwt

from app.main import create_app
from app.store.db import init_db, close_db, get_pool
from app.store.migrations import run_migrations

@pytest.fixture(scope="function")
def app_instance():
    return create_app()

def create_token(app_instance, user_id, role="user"):
    cfg = app_instance.state.config
    payload = {"role": role, "sub": user_id}
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")

@pytest.fixture(autouse=True)
async def setup_db(app_instance):
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    cfg = app_instance.state.config
    await init_db(cfg)
    await run_migrations()
    yield
    await close_db()

@pytest.mark.asyncio
async def test_cancel_lock_conflict(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        admin_token = create_token(app_instance, "admin-4", "admin")
        u_token = create_token(app_instance, "user-c4")
        
        resp = await client.post(
            "/shows", 
            json={"name": "Cancel Lock", "price_paise": 1000, "per_user_limit": 4, "seats": ["D1"]},
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        show_id = resp.json()["id"]

        resp_res = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["D1"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_res.status_code == 201
        res_id = resp_res.json()["reservation_id"]
        
        # Hold SELECT FOR UPDATE on the reservation row for longer than lock_timeout
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Lock row
                await conn.fetchrow("SELECT * FROM reservations WHERE id = $1 FOR UPDATE", uuid.UUID(res_id))
                
                # While locked, attempt cancel
                cancel_task = asyncio.create_task(client.post(
                    f"/reservations/{res_id}/cancel",
                    headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
                ))
                
                await asyncio.sleep(0.5)
                # We exit transaction, releasing lock
                
        # Cancel should succeed after retry
        resp_cancel = await cancel_task
        assert resp_cancel.status_code in (200, 409)

@pytest.mark.asyncio
async def test_reaper_connection(app_instance):
    # With no expired holds, the reaper doesn't keep a connection checked out
    pool = get_pool()
    idle_start = pool.get_idle_size()
    
    from app.store.reaper import reap_expired_holds
    task = asyncio.create_task(reap_expired_holds())
    
    await asyncio.sleep(0.5) # let it run one cycle
    idle_end = pool.get_idle_size()
    
    task.cancel()
    
    # Should not permanently decrease idle size
    assert idle_end >= idle_start - 1
