import asyncio
import os
os.environ["MAX_INFLIGHT_RESERVES"] = "2000"
import uuid
from collections import Counter
import pytest
from httpx import ASGITransport, AsyncClient
import jwt

from app.main import create_app
from app.store.db import init_db, close_db, get_pool

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
    
    # Ensure pool is closed before starting
    try:
        await close_db()
    except Exception:
        pass
        
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

        quota_sum = await conn.fetchval("SELECT COALESCE(SUM(active_count), 0) FROM user_show_quota WHERE show_id = $1", uuid.UUID(show_id))
        assert quota_sum == row["held"] + row["confirmed"], \
            f"Quota invariant failed: sum({quota_sum}) != held({row['held']}) + confirmed({row['confirmed']})"

@pytest.mark.asyncio
async def test_reserve_scenario_1_concurrent_distinct_users(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload_1 = {
            "name": "Scenario 1 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["A12"]
        }
        resp = await client.post("/shows", json=show_payload_1, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_1_id = resp.json()["id"]

        async def reserve_s1(user_idx):
            token = create_user_token(app_instance, f"user-s1-{user_idx}")
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_1_id}/reserve",
                json={"seats": ["A12"]},
                headers={
                    "Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4()),
                    "Idempotency-Key": idem_key
                }
            )

        tasks_1 = [reserve_s1(i) for i in range(500)]
        results_1 = await asyncio.gather(*tasks_1)
        
        status_counts_1 = Counter([r.status_code for r in results_1])
        assert status_counts_1[201] == 1
        assert status_counts_1[409] == 499
        for r in results_1:
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "seat_taken"
        assert len(status_counts_1) == 2, f"Unexpected status codes: {status_counts_1}"

        await verify_seats(show_1_id)

@pytest.mark.asyncio
async def test_reserve_scenario_2_per_user_limit(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        seats_2 = [f"A{i}" for i in range(1, 11)]
        show_payload_2 = {
            "name": "Scenario 2 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": seats_2
        }
        resp = await client.post("/shows", json=show_payload_2, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_2_id = resp.json()["id"]

        s2_user_token = create_user_token(app_instance, "user-s2-single")
        
        async def reserve_s2(seat_label):
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_2_id}/reserve",
                json={"seats": [seat_label]},
                headers={
                    "Authorization": f"Bearer {s2_user_token}", "Idempotency-Key": str(uuid.uuid4()),
                    "Idempotency-Key": idem_key
                }
            )

        tasks_2 = [reserve_s2(seat) for seat in seats_2]
        results_2 = await asyncio.gather(*tasks_2)

        status_counts_2 = Counter([r.status_code for r in results_2])
        assert status_counts_2[201] == 4
        assert status_counts_2[409] == 6
        for r in results_2:
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "per_user_limit"

        await verify_seats(show_2_id)

@pytest.mark.asyncio
async def test_reserve_scenario_3_idempotency(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload_3 = {
            "name": "Scenario 3 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["B1"]
        }
        resp = await client.post("/shows", json=show_payload_3, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_3_id = resp.json()["id"]

        s3_user_token = create_user_token(app_instance, "user-s3-single")
        s3_idem_key = str(uuid.uuid4())

        async def reserve_s3():
            return await client.post(
                f"/shows/{show_3_id}/reserve",
                json={"seats": ["B1"]},
                headers={
                    "Authorization": f"Bearer {s3_user_token}", "Idempotency-Key": str(uuid.uuid4()),
                    "Idempotency-Key": s3_idem_key
                }
            )

        tasks_3 = [reserve_s3() for _ in range(50)]
        results_3 = await asyncio.gather(*tasks_3)

        status_counts_3 = Counter([r.status_code for r in results_3])
        for r in results_3:
            if r.status_code == 400:
                print(f"\\nSCENARIO 3 GOT 400: {r.json()}")
                
        assert status_counts_3[400] == 0, "Got unexpected 400 Bad Request"
        
        for r in results_3:
            if r.status_code == 409:
                print(f"\\nSCENARIO 3 GOT 409: {r.json()}")
                
        assert status_counts_3[201] == 50
        reservation_ids = [r.json()["reservation_id"] for r in results_3 if r.status_code == 201]
        assert len(set(reservation_ids)) == 1, f"Expected 1 unique reservation ID, got {set(reservation_ids)}."

        await verify_seats(show_3_id)

        pool = get_pool()
        async with pool.acquire() as conn:
            res_count = await conn.fetchval("SELECT COUNT(*) FROM reservations WHERE show_id = $1", show_3_id)
            assert res_count == 1, f"Expected exactly 1 reservation, got {res_count}"

@pytest.mark.asyncio
async def test_reserve_scenario_3a_idempotency_mismatch(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload_3a = {
            "name": "Scenario 3a Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["B1", "B2"]
        }
        resp = await client.post("/shows", json=show_payload_3a, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_3a_id = resp.json()["id"]

        s3a_user_token = create_user_token(app_instance, "user-s3a-single")
        s3a_idem_key = str(uuid.uuid4())

        resp1 = await client.post(
            f"/shows/{show_3a_id}/reserve",
            json={"seats": ["B1"]},
            headers={
                "Authorization": f"Bearer {s3a_user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": s3a_idem_key
            }
        )
        assert resp1.status_code == 201
        
        resp_mismatch = await client.post(
            f"/shows/{show_3a_id}/reserve",
            json={"seats": ["B2"]},  # Different seat
            headers={
                "Authorization": f"Bearer {s3a_user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": s3a_idem_key
            }
        )
        assert resp_mismatch.status_code == 409
        assert resp_mismatch.json()["error"]["code"] == "idempotency_mismatch"
        
        await verify_seats(show_3a_id)

@pytest.mark.asyncio
async def test_reserve_scenario_4_deadlock_lock_ordering(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload_4 = {
            "name": "Scenario 4 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["C1", "C2"]
        }
        resp = await client.post("/shows", json=show_payload_4, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_4_id = resp.json()["id"]

        async def reserve_s4(user_idx, seats):
            token = create_user_token(app_instance, f"user-s4-{user_idx}")
            idem_key = str(uuid.uuid4())
            return await client.post(
                f"/shows/{show_4_id}/reserve",
                json={"seats": seats},
                headers={
                    "Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4()),
                    "Idempotency-Key": idem_key
                }
            )

        tasks_4 = []
        for i in range(200):
            seats = ["C1", "C2"] if i % 2 == 0 else ["C2", "C1"]
            tasks_4.append(reserve_s4(i, seats))

        results_4 = await asyncio.gather(*tasks_4)
        
        status_counts_4 = Counter([r.status_code for r in results_4])
        for code in status_counts_4:
            assert code < 500, f"Unexpected 5xx status code: {code}"
            
        assert status_counts_4[201] == 1
        assert status_counts_4[409] == 199
        
        for r in results_4:
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "seat_taken"
        
        await verify_seats(show_4_id)

@pytest.mark.asyncio
async def test_reserve_scenario_5_concurrent_cancels(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload = {
            "name": "Scenario 5 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["D1"]
        }
        resp = await client.post("/shows", json=show_payload, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        assert resp.status_code == 201
        show_id = resp.json()["id"]

        user_token = create_user_token(app_instance, "user-s5")
        
        # Reserve seat
        resp = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["D1"]},
            headers={
                "Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": str(uuid.uuid4())
            }
        )
        assert resp.status_code == 201
        reservation_id = resp.json()["reservation_id"]
        
        # 20 parallel cancels
        async def cancel_res():
            return await client.post(
                f"/reservations/{reservation_id}/cancel",
                headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": str(uuid.uuid4())}
            )
            
        tasks = [cancel_res() for _ in range(20)]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            assert r.status_code == 200
            
        await verify_seats(show_id)

@pytest.mark.asyncio
async def test_reserve_scenario_6_cancel_vs_reserve_race(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload = {
            "name": "Scenario 6 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["E1"]
        }
        resp = await client.post("/shows", json=show_payload, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        show_id = resp.json()["id"]

        user_a_token = create_user_token(app_instance, "user-s6-A")
        
        # User A reserves
        resp = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["E1"]},
            headers={
                "Authorization": f"Bearer {user_a_token}", "Idempotency-Key": str(uuid.uuid4()),
                "Idempotency-Key": str(uuid.uuid4())
            }
        )
        assert resp.status_code == 201
        reservation_id = resp.json()["reservation_id"]
        
        async def cancel_res():
            return await client.post(
                f"/reservations/{reservation_id}/cancel",
                headers={"Authorization": f"Bearer {user_a_token}", "Idempotency-Key": str(uuid.uuid4())}
            )

        async def reserve_s6(idx):
            token = create_user_token(app_instance, f"user-s6-{idx}")
            return await client.post(
                f"/shows/{show_id}/reserve",
                json={"seats": ["E1"]},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
            )

        tasks = [cancel_res()] + [reserve_s6(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            assert r.status_code < 500, f"Unexpected 5xx: {r.status_code}"
            
        # Exactly 1 new owner or no owner (if reserve didn't get it after cancel)
        # Actually exactly 1 new owner since we have 50 trying
        status_counts = Counter([r.status_code for r in results[1:]])
        assert status_counts[201] == 1
        assert status_counts[409] == 49
        
        await verify_seats(show_id)

@pytest.mark.asyncio
async def test_reserve_scenario_7_expired_hold_takeover(app_instance, admin_token):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        show_payload = {
            "name": "Scenario 7 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "hold_ttl_seconds": 1,
            "seats": ["F1"]
        }
        resp = await client.post("/shows", json=show_payload, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        show_id = resp.json()["id"]

        user_a_token = create_user_token(app_instance, "user-s7-A")
        user_b_token = create_user_token(app_instance, "user-s7-B")
        
        resp_a = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["F1"]},
            headers={"Authorization": f"Bearer {user_a_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_a.status_code == 201
        res_a_id = resp_a.json()["reservation_id"]
        
        await asyncio.sleep(1.5)
        
        resp_b = await client.post(
            f"/shows/{show_id}/reserve",
            json={"seats": ["F1"]},
            headers={"Authorization": f"Bearer {user_b_token}", "Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp_b.status_code == 201
        
        await verify_seats(show_id)
        
        pool = get_pool()
        async with pool.acquire() as conn:
            status_a = await conn.fetchval("SELECT status FROM reservations WHERE id = $1", uuid.UUID(res_a_id))
            assert status_a == "expired"
            
            quota_a = await conn.fetchval("SELECT active_count FROM user_show_quota WHERE user_id = 'user-s7-A' AND show_id = $1", uuid.UUID(show_id))
            assert quota_a == 0

@pytest.mark.asyncio
async def test_reserve_scenario_8_load_shedding(app_instance, admin_token):
    from app.main import create_app
    from dataclasses import replace
    
    test_app = create_app()
    # Use replace to create a new config with modified max_inflight_reserves
    new_config = replace(test_app.state.config, max_inflight_reserves=1)
    test_app.state.config = new_config

    import os
    os.environ["ADMISSION_WAIT_MS"] = "50"
    
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver") as client:
        show_payload = {
            "name": "Scenario 8 Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "seats": ["G1", "G2"]
        }
        resp = await client.post("/shows", json=show_payload, headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": str(uuid.uuid4())})
        show_id = resp.json()["id"]

        async def reserve_s8(idx):
            token = create_user_token(app_instance, f"user-s8-{idx}")
            return await client.post(
                f"/shows/{show_id}/reserve",
                json={"seats": ["G1"]},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
            )

        tasks = [reserve_s8(i) for i in range(100)]
        results = await asyncio.gather(*tasks)
        
        status_counts = Counter([r.status_code for r in results])
        for code in status_counts:
            assert code < 500, f"Unexpected 5xx: {code}"
            
        assert status_counts[429] > 0, "Expected some 429 Too Many Requests"
        
        await verify_seats(show_id)
