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
async def test_cancel_owner_only(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        admin_token = create_token(app_instance, "admin-1", "admin")
        u1_token = create_token(app_instance, "user-c1")
        u2_token = create_token(app_instance, "user-c2")
        
        # 1. Create show
        resp = await client.post(
            "/shows", 
            json={"name": "Cancel Test 1", "price_paise": 1000, "per_user_limit": 4, "seats": ["A1", "A2"]},
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        show_id = resp.json()["id"]

        # 2. Reserve
        idem_key = str(uuid.uuid4())
        resp_res = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["A1"]},
            headers={"Authorization": f"Bearer {u1_token}", "Idempotency-Key": idem_key}
        )
        assert resp_res.status_code == 201
        res_id = resp_res.json()["reservation_id"]

        # 3. Cancel with wrong user (should be 404 to not leak existence)
        resp_cancel_bad = await client.post(
            f"/reservations/{res_id}/cancel",
            headers={"Authorization": f"Bearer {u2_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_cancel_bad.status_code == 404

        # 4. Cancel with owner (should be 200)
        resp_cancel_ok = await client.post(
            f"/reservations/{res_id}/cancel",
            headers={"Authorization": f"Bearer {u1_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_cancel_ok.status_code == 200
        assert resp_cancel_ok.json()["status"] == "cancelled"

        # 5. Idempotent cancel
        resp_cancel_idem = await client.post(
            f"/reservations/{res_id}/cancel",
            headers={"Authorization": f"Bearer {u1_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_cancel_idem.status_code == 200

@pytest.mark.asyncio
async def test_cancel_rebook(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        admin_token = create_token(app_instance, "admin-2", "admin")
        u_token = create_token(app_instance, "user-rebook")
        
        resp = await client.post(
            "/shows", 
            json={"name": "Cancel Rebook", "price_paise": 1000, "per_user_limit": 4, "seats": ["B1"]},
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        show_id = resp.json()["id"]

        # Reserve
        resp_res1 = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["B1"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_res1.status_code == 201
        res1_id = resp_res1.json()["reservation_id"]

        # Cancel
        resp_cancel = await client.post(
            f"/reservations/{res1_id}/cancel",
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_cancel.status_code == 200

        # Re-book
        resp_res2 = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["B1"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_res2.status_code == 201
