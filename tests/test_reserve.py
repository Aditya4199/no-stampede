import asyncio
import os
import uuid
from collections import Counter
import pytest
from httpx import ASGITransport, AsyncClient
import jwt

from app.main import create_app
from app.store.db import init_db, close_db, get_pool

@pytest.fixture(scope="module")
def app_instance():
    return create_app()

@pytest.fixture(scope="module")
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
    from app.store.migrations import run_migrations
    await run_migrations()
    yield
    await close_db()

def create_user_token(app_instance, user_id):
    cfg = app_instance.state.config
    payload = {"role": "user", "sub": user_id}
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")

async def verify_seats(show_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'available') as available,
                COUNT(*) FILTER (WHERE status = 'held') as held,
                COUNT(*) FILTER (WHERE status = 'confirmed') as confirmed
            FROM seats
            WHERE show_id = $1
        """, uuid.UUID(show_id))
        
        # Verify the invariant
        assert row["available"] + row["held"] + row["confirmed"] == row["total"], \
            f"Invariant failed: available({row['available']}) + held({row['held']}) + confirmed({row['confirmed']}) != total({row['total']})"

@pytest.mark.asyncio
async def test_reserve_scenarios(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        
        # --- Scenario 1: 500 concurrent POST /shows/{id}/reserve requests with 500 distinct users all targeting "A12" ---
        show_payload_1 = {
            "name": "Scenario 1 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["A12"]
        }
        resp = await client.post("/shows", json=show_payload_1, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        show_1_id = resp.json()["id"]

        async def reserve_s1(user_idx):
            token = create_user_token(app_instance, f"user-s1-{user_idx}")
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_1_id}/reserve",
                json={"seats": ["A12"]},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": idem_key
                }
            )

        tasks_1 = [reserve_s1(i) for i in range(500)]
        results_1 = await asyncio.gather(*tasks_1)
        
        status_counts_1 = Counter([r.status_code for r in results_1])
        assert status_counts_1[201] == 1
        assert status_counts_1[409] == 499
        # Check that they are 409 seat_taken
        for r in results_1:
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "seat_taken"
        assert len(status_counts_1) == 2, f"Unexpected status codes: {status_counts_1}"

        await verify_seats(show_1_id)

        # --- Scenario 2: 1 user, 10 parallel single-seat requests on distinct seats (A1-A10), per_user_limit=4 ---
        seats_2 = [f"A{i}" for i in range(1, 11)]
        show_payload_2 = {
            "name": "Scenario 2 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": seats_2
        }
        resp = await client.post("/shows", json=show_payload_2, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        show_2_id = resp.json()["id"]

        s2_user_token = create_user_token(app_instance, "user-s2-single")
        
        async def reserve_s2(seat_label):
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_2_id}/reserve",
                json={"seats": [seat_label]},
                headers={
                    "Authorization": f"Bearer {s2_user_token}",
                    "Idempotency-Key": idem_key
                }
            )

        tasks_2 = [reserve_s2(seat) for seat in seats_2]
        results_2 = await asyncio.gather(*tasks_2)

        status_counts_2 = Counter([r.status_code for r in results_2])
        assert status_counts_2[201] == 4
        # The other 6 should be 409 per_user_limit
        assert status_counts_2[409] == 6
        for r in results_2:
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "per_user_limit"

        await verify_seats(show_2_id)

        # --- Scenario 3: 50 parallel requests with the same idempotency key and same seat ---
        show_payload_3 = {
            "name": "Scenario 3 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["B1"]
        }
        resp = await client.post("/shows", json=show_payload_3, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        show_3_id = resp.json()["id"]

        s3_user_token = create_user_token(app_instance, "user-s3-single")
        s3_idem_key = str(uuid.uuid4())

        async def reserve_s3():
            return await client.post(
                f"/shows/{show_3_id}/reserve",
                json={"seats": ["B1"]},
                headers={
                    "Authorization": f"Bearer {s3_user_token}",
                    "Idempotency-Key": s3_idem_key
                }
            )

        tasks_3 = [reserve_s3() for _ in range(50)]
        results_3 = await asyncio.gather(*tasks_3)

        status_counts_3 = Counter([r.status_code for r in results_3])
        # Depending on how idempotency works with concurrency, one might be 201 and others 409 conflict
        # But wait, the instruction says "assert all 50 return the identical reservation_id"
        # Let's see if the code handles it returning 201 for all (or 409 for some, wait, the instruction says "assert all 50 return the identical reservation_id").
        # If it returns the same id, it means status is 201.
        # But wait, looking at `shows.py`: 
        # ON CONFLICT (user_id, key) DO NOTHING.
        # If not inserted, fetch existing. 
        # If response is None, return 409 "Concurrent request processing for same idempotency key".
        # So only the first will get 201, others might get 409 until the first finishes.
        # Ah, the instructions say: "50 parallel requests with the same idempotency key and same seat - assert all 50 return the identical reservation_id."
        # The prompt might assume that we implement retries on 409 for idempotency conflict, or maybe the code already handles it?
        # Let me check `shows.py` again.
        
        # If they get 409 conflict, they don't have reservation_id. 
        # But the prompt says "assert all 50 return the identical reservation_id."
        # This implies we might need to modify `shows.py` or just see if the tests pass. 
        # Wait, if they are parallel, some will get 409 if the response isn't ready. 
        # Let's just write the assert to see.
        
        # Actually, let's collect successful JSONs.
        reservation_ids = []
        for r in results_3:
            if r.status_code == 201:
                reservation_ids.append(r.json()["reservation_id"])
            else:
                # If they fail with 409, the test will fail on the assert below, which we will fix next.
                reservation_ids.append(f"failed-{r.status_code}")
                
        assert len(set(reservation_ids)) == 1, f"Expected 1 unique reservation ID, got {set(reservation_ids)}. Results: {[r.json() if r.status_code != 409 else r.json() for r in results_3]}"

        await verify_seats(show_3_id)

        # Check that exactly 1 row in reservations exists for this show
        pool = get_pool()
        async with pool.acquire() as conn:
            res_count = await conn.fetchval("SELECT COUNT(*) FROM reservations WHERE show_id = $1", show_3_id)
            assert res_count == 1, f"Expected exactly 1 reservation, got {res_count}"

        # --- Scenario 3a: same idempotency key with a different seat returns 409 idempotency_mismatch ---
        resp_mismatch = await client.post(
            f"/shows/{show_3_id}/reserve",
            json={"seats": ["B2"]},  # Different seat
            headers={
                "Authorization": f"Bearer {s3_user_token}",
                "Idempotency-Key": s3_idem_key
            }
        )
        assert resp_mismatch.status_code == 409
        assert resp_mismatch.json()["error"]["code"] == "idempotency_mismatch"

        # --- Scenario 4: 200 concurrent requests, half ["C1", "C2"] and half ["C2", "C1"] ---
        # Tests sorted lock order to prevent deadlocks
        show_payload_4 = {
            "name": "Scenario 4 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["C1", "C2"]
        }
        resp = await client.post("/shows", json=show_payload_4, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201
        show_4_id = resp.json()["id"]

        async def reserve_s4(user_idx, seats):
            token = create_user_token(app_instance, f"user-s4-{user_idx}")
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_4_id}/reserve",
                json={"seats": seats},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": idem_key
                }
            )

        tasks_4 = []
        for i in range(200):
            seats = ["C1", "C2"] if i % 2 == 0 else ["C2", "C1"]
            tasks_4.append(reserve_s4(i, seats))

        results_4 = await asyncio.gather(*tasks_4)
        
        status_counts_4 = Counter([r.status_code for r in results_4])
        # Assert no 5xx
        for code in status_counts_4:
            assert code < 500, f"Unexpected 5xx status code: {code}"
            
        # Assert each seat confirmed at most once -> This implies exactly 1 successful reservation of the 2 seats
        assert status_counts_4[201] == 1
        
        await verify_seats(show_4_id)
