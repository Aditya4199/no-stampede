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
async def test_metrics_endpoint(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        admin_token = create_token(app_instance, "admin-1", "admin")
        u_token = create_token(app_instance, "real-user")
        
        # Create show
        resp = await client.post(
            "/shows", 
            json={"name": "Metrics Test", "price_paise": 1000, "per_user_limit": 4, "seats": ["M1", "M2"]},
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp.status_code == 201
        show_id = resp.json()["id"]

        # Reserve a seat successfully
        resp_res = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["M1"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_res.status_code == 201
        
        # Reserve a taken seat to generate decline
        resp_bad = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["M1"]},
            headers={"Authorization": f"Bearer {u_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_bad.status_code == 409

        # Fetch metrics
        resp_metrics = await client.get("/metrics")
        assert resp_metrics.status_code == 200
        text = resp_metrics.text
        
        assert "http_requests_total" in text
        assert "http_request_duration_seconds" in text
        assert "reservations_confirmed_total" in text
        assert "reservations_declined_total" in text
        assert "db_pool_acquired_conns" in text
        assert "seats_available" in text
        
        # Specific counters should have incremented
        assert f'reservations_confirmed_total{{show_id="{show_id}"}}' in text
        assert f'reservations_declined_total{{reason="seat_taken"}}' in text
        
        # Check gauge values (M1 confirmed, M2 available)
        assert f'seats_available{{show_id="{show_id}"}} 1.0' in text
        assert f'seats_confirmed{{show_id="{show_id}"}} 1.0' in text
