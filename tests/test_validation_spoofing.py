import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import jwt

from app.main import create_app
from app.store.db import init_db, close_db
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
async def test_spoof_and_validation(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        admin_token = create_token(app_instance, "admin-1", "admin")
        u_token = create_token(app_instance, "real-user")
        
        # Create show
        resp = await client.post(
            "/shows", 
            json={"name": "Spoof Test", "price_paise": 1000, "per_user_limit": 4, "seats": ["A1", "A2"]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 201
        show_id = resp.json()["id"]

        # 1. Spoof user_id in body - it should be ignored by the API (we don't even have user_id in ReserveRequest)
        # But we pass it to ensure the Pydantic model doesn't blow up or we ensure it's not mapped.
        # Actually Pydantic throws 400 for extra fields unless configured. FastAPI will ignore or reject it.
        # Let's see how our API handles it.
        resp_spoof = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["A1"], "user_id": "fake-user"},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        # Assuming Pydantic ignores extra, it should be 201
        assert resp_spoof.status_code == 201
        assert resp_spoof.json()["user_id"] == "real-user" # The real token sub, not the fake one
        
        # 2. Bad JSON
        resp_bad = await client.post(
            f"/shows/{show_id}/reserve",
            content="invalid json",
            headers={"Authorization": f"Bearer {u_token}", "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_bad.status_code == 400

        # 3. Unknown show
        resp_unknown_show = await client.post(
            f"/shows/{uuid.uuid4()}/reserve",
            json={"seats": ["A2"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_unknown_show.status_code == 404

        # 4. Unknown seat
        resp_unknown_seat = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["Z99"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_unknown_seat.status_code == 400

        # 5. Oversized body
        huge_payload = {"seats": ["A2"], "padding": "x" * 70000} # > 64KB
        resp_oversized = await client.post(
            f"/shows/{show_id}/reserve",
            json=huge_payload,
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_oversized.status_code == 400
        assert resp_oversized.json()["error"]["message"] == "Request body too large"
