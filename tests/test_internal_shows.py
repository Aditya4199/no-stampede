import os
import uuid
import pytest
import jwt
from httpx import ASGITransport, AsyncClient

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
    token = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")
    return token

@pytest.fixture(scope="function")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}

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
async def test_create_show(app_instance, headers):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        payload = {
            "name": "Integration Test Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["A1", "A2", "A3", "A4"]
        }
        response = await client.post("/shows", json=payload, headers=headers)
    
    assert response.status_code == 201
    data = response.json()
    assert "id" in data


@pytest.mark.asyncio
async def test_configure_show(app_instance, headers):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        # First create a show to update
        create_payload = {
            "name": "Configure Test Show",
            "price_paise": 500,
            "per_user_limit": 2,
            "seats": ["B1", "B2"]
        }
        create_resp = await client.post("/shows", json=create_payload, headers=headers)
        assert create_resp.status_code == 201
        show_id = create_resp.json()["id"]

        # Now configure it
        configure_payload = {
            "hold_ttl_seconds": 300
        }
        response = await client.patch(f"/shows/{show_id}", json=configure_payload, headers=headers)
    
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
