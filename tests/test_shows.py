import uuid
import os
import pytest
from httpx import ASGITransport, AsyncClient
import jwt

from app.main import create_app
from app.config import Config
from app.store.db import init_db, close_db

from app.store.migrations import run_migrations

@pytest.fixture(scope="function")
def app_instance():
    return create_app()

@pytest.fixture(scope="function")
def admin_token(app_instance):
    cfg = app_instance.state.config
    payload = {"role": "admin", "user_id": "test-admin"}
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
async def test_get_show(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        # Create a show as admin first
        create_payload = {
            "name": "Public Show Test",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["A1", "A2", "A3"]
        }
        create_resp = await client.post(
            "/shows",
            json=create_payload,
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert create_resp.status_code == 201
        show_id = create_resp.json()["id"]

        # Now fetch it via public endpoint
        resp = await client.get(f"/shows/{show_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Public Show Test"
        assert data["price_paise"] == 1000
        assert data["total_seats"] == 3
        assert data["available"] == 3
