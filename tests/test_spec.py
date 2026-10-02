import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.store.db import init_db, close_db

@pytest.fixture(scope="module")
def app_instance():
    return create_app()

@pytest.fixture(autouse=True)
async def setup_db(app_instance):
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    cfg = app_instance.state.config
    await init_db(cfg)
    yield
    await close_db()


@pytest.mark.asyncio
async def test_auth_errors(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        # Missing token
        r1 = await client.post("/shows", json={"name": "x", "price_paise": 1, "seats": ["A1"]})
        assert r1.status_code == 401
        assert r1.json()["error"]["code"] == "unauthorized"

        # Mint non-admin token
        r2 = await client.post("/auth/token", json={})
        token = r2.json()["token"]

        # Use non-admin token
        r3 = await client.post("/shows", json={"name": "x", "price_paise": 1, "seats": ["A1"]}, headers={"Authorization": f"Bearer {token}"})
        assert r3.status_code == 403
        assert r3.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_mint_admin_token_without_key_in_prod(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    # Need to also set a JWT secret so load() doesn't fail early
    monkeypatch.setenv("JWT_SECRET", "super-secret-production-key-that-is-long")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        r = await client.post("/auth/token?role=admin")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_validation_errors(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        # Mint admin token
        r = await client.post("/auth/token?role=admin")
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Empty seats list
        r1 = await client.post("/shows", json={"name": "x", "price_paise": 1, "seats": []}, headers=headers)
        assert r1.status_code == 400
        assert r1.json()["error"]["code"] == "invalid_request"

        # Empty seat label
        r2 = await client.post("/shows", json={"name": "x", "price_paise": 1, "seats": [""]}, headers=headers)
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "invalid_request"

        # Duplicate seat label
        r3 = await client.post("/shows", json={"name": "x", "price_paise": 1, "seats": ["A1", "A1"]}, headers=headers)
        assert r3.status_code == 400
        assert r3.json()["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_unknown_show(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        fake_id = str(uuid.uuid4())
        r = await client.get(f"/shows/{fake_id}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "show_not_found"


@pytest.mark.asyncio
async def test_show_counts(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        r = await client.post("/auth/token?role=admin")
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_r = await client.post("/shows", json={"name": "counts show", "price_paise": 1, "seats": ["A1", "A2", "A3"]}, headers=headers)
        show_id = create_r.json()["id"]

        get_r = await client.get(f"/shows/{show_id}")
        assert get_r.status_code == 200
        data = get_r.json()
        assert data["total_seats"] == 3
        assert data["available"] + data["held"] + data["confirmed"] == data["total_seats"]
