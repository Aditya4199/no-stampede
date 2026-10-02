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

@pytest.fixture(scope="function")
def admin_token(app_instance):
    cfg = app_instance.state.config
    payload = {"role": "admin", "user_id": "test-admin"}
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")

@pytest.fixture(scope="function")
def user_token(app_instance):
    cfg = app_instance.state.config
    payload = {"role": "user", "sub": "test-user-123"}
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
async def test_reserve_seats(app_instance, admin_token, user_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        # 1. Create a show
        create_payload = {
            "name": "Reservation Test Show",
            "price_paise": 1000,
            "per_user_limit": 3,
            "seats": ["A1", "A2", "A3", "A4"]
        }
        create_resp = await client.post(
            "/shows",
            json=create_payload,
            headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert create_resp.status_code == 201
        show_id = create_resp.json()["id"]

        # 2. Reserve seats
        reserve_payload = {"seats": ["A1", "A2"]}
        idem_key = str(uuid.uuid4())
        resp = await client.post(
            f"/shows/{show_id}/reserve",
            json=reserve_payload,
            headers={
                "Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": idem_key
            }
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["amount_paise"] == 2000
        assert data["seats"] == ["A1", "A2"]

        # 3. Test idempotency
        resp2 = await client.post(
            f"/shows/{show_id}/reserve",
            json=reserve_payload,
            headers={
                "Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": idem_key
            }
        )
        assert resp2.status_code == 201
        assert resp2.json()["reservation_id"] == data["reservation_id"]

        # 4. Test idempotency mismatch
        resp3 = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["A3"]},
            headers={
                "Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": idem_key
            }
        )
        assert resp3.status_code == 409
        assert resp3.json()["error"]["code"] == "idempotency_mismatch"

        # 5. Test quota limit (limit is 3, we try to book 2 more -> total 4 -> fail)
        idem_key_2 = str(uuid.uuid4())
        resp4 = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["A3", "A4"]},
            headers={
                "Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": idem_key_2
            }
        )
        assert resp4.status_code == 409
        assert resp4.json()["error"]["code"] == "per_user_limit"

        # 6. Test invalid seats (already booked)
        user_token_2 = jwt.encode({"role": "user", "sub": "other-user"}, app_instance.state.config.jwt_secret, algorithm="HS256")
        idem_key_3 = str(uuid.uuid4())
        resp5 = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["A1"]},
            headers={
                "Authorization": f"Bearer {user_token_2}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": idem_key_3
            }
        )
        assert resp5.status_code == 409
        assert resp5.json()["error"]["code"] == "seat_taken"

        # 7. Check show availability status
        show_resp = await client.get(f"/shows/{show_id}")
        assert show_resp.status_code == 200
        show_data = show_resp.json()
        assert show_data["available"] == 2
        assert show_data["held"] == 0
        assert show_data["confirmed"] == 2
