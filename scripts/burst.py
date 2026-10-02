import argparse
import asyncio
import json
import random
import sys
import time
import uuid
import httpx
from typing import List, Dict

def percentile(data, p):
    if not data: return 0.0
    s_data = sorted(data)
    k = (len(s_data) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s_data) - 1)
    if f == c: return s_data[int(k)]
    return s_data[f] * (c - k) + s_data[c] * (k - f)

class BurstClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
        timeout = httpx.Timeout(10.0)
        self.client = httpx.AsyncClient(base_url=base_url, limits=limits, timeout=timeout)
        self.admin_token = ""
        
    async def get_token(self, user_id: str, role: str = "user") -> str:
        resp = await self.client.post(f"/auth/token?user_id={user_id}&role={role}")
        resp.raise_for_status()
        return resp.json()["token"]

    async def create_show(self, name: str, seats: List[str]) -> str:
        if not self.admin_token:
            self.admin_token = await self.get_token("admin", "admin")
        
        resp = await self.client.post(
            "/shows",
            json={"name": name, "price_paise": 1000, "per_user_limit": 4, "seats": seats},
            headers={"Authorization": f"Bearer {self.admin_token}", "ADMIN_KEY": "dummy"}
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def get_show(self, show_id: str):
        resp = await self.client.get(f"/shows/{show_id}")
        return resp.json()

    async def get_metrics(self):
        resp = await self.client.get("/metrics")
        return resp.text

    async def reserve(self, show_id: str, token: str, seats: List[str], idempotency_key: str = None, extra_json: dict = None):
        headers = {"Authorization": f"Bearer {token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
            
        data = {"seats": seats}
        if extra_json:
            data.update(extra_json)
            
        start = time.perf_counter()
        try:
            resp = await self.client.post(f"/shows/{show_id}/reserve", json=data, headers=headers)
            status = resp.status_code
            body = resp.json()
        except Exception as e:
            status = 503
            body = {"error": {"code": "client_error", "message": str(e)}}
        duration = time.perf_counter() - start
        
        return status, body, duration

    async def cancel(self, reservation_id: str, token: str):
        headers = {"Authorization": f"Bearer {token}"}
        resp = await self.client.post(f"/reservations/{reservation_id}/cancel", headers=headers)
        return resp.status_code, resp.json()
        
    async def close(self):
        await self.client.aclose()


async def run_scenario_hot_seat(client: BurstClient):
    print("--- Scenario 1: Hot-seat storm (500 users -> 1 seat) ---")
    seats = [f"A{i}" for i in range(1, 10)]
    show_id = await client.create_show("Hot Seat Show", seats)
    
    tokens = await asyncio.gather(*[client.get_token(f"user-{i}") for i in range(500)])
    
    tasks = []
    for token in tokens:
        tasks.append(client.reserve(show_id, token, ["A1"], str(uuid.uuid4())))
        
    results = await asyncio.gather(*tasks)
    
    status_counts = {}
    for st, _, _ in results:
        status_counts[st] = status_counts.get(st, 0) + 1
        
    print(f"Status codes: {status_counts}")
    assert status_counts.get(201, 0) == 1, "Exactly 1 request should succeed"
    assert status_counts.get(409, 0) == 499, "Exactly 499 requests should fail with conflict"
    assert sum(status_counts.values()) == 500
    print("[PASS] Hot-seat storm passed")
    return results

async def run_scenario_per_user_limit(client: BurstClient):
    print("--- Scenario 2: Per-user limit (1 user, 10 parallel single-seat requests) ---")
    seats = [f"B{i}" for i in range(1, 20)]
    show_id = await client.create_show("Per User Limit Show", seats)
    token = await client.get_token("greedy-user")
    
    tasks = []
    for i in range(1, 11):
        tasks.append(client.reserve(show_id, token, [f"B{i}"], str(uuid.uuid4())))
        
    results = await asyncio.gather(*tasks)
    status_counts = {}
    for st, _, _ in results:
        status_counts[st] = status_counts.get(st, 0) + 1
        
    print(f"Status codes: {status_counts}")
    assert status_counts.get(201, 0) <= 4, "No more than 4 requests should succeed"
    print("[PASS] Per-user limit passed")
    return results

async def run_scenario_idempotency(client: BurstClient):
    print("--- Scenario 3: Idempotency (50 parallel same key; then same key diff seats) ---")
    seats = [f"C{i}" for i in range(1, 20)]
    show_id = await client.create_show("Idempotency Show", seats)
    token = await client.get_token("idem-user")
    idem_key = str(uuid.uuid4())
    
    # 50 parallel same key
    tasks = [client.reserve(show_id, token, ["C1", "C2"], idem_key) for _ in range(50)]
    results = await asyncio.gather(*tasks)
    
    status_counts = {}
    res_ids = set()
    for st, body, _ in results:
        status_counts[st] = status_counts.get(st, 0) + 1
        if st == 201:
            res_ids.add(body.get("reservation_id"))
            
    print(f"Phase 1 Status codes: {status_counts}")
    assert len(res_ids) == 1, "Should have exactly one reservation ID returned for all 201s"
    
    # same key diff seats
    st, body, _ = await client.reserve(show_id, token, ["C3"], idem_key)
    print(f"Phase 2 Status: {st}")
    assert st == 409, "Should fail with idempotency mismatch"
    print("[PASS] Idempotency passed")

async def run_scenario_spoof(client: BurstClient):
    print("--- Scenario 4: Spoof user_id & cancel other's reservation ---")
    seats = ["D1", "D2"]
    show_id = await client.create_show("Spoof Show", seats)
    
    token_a = await client.get_token("userA")
    token_b = await client.get_token("userB")
    
    st, body, _ = await client.reserve(show_id, token_a, ["D1"], str(uuid.uuid4()), extra_json={"user_id": "userB"})
    assert st == 201
    assert body["user_id"] == "userA", "user_id from body must be ignored"
    
    res_id = body["reservation_id"]
    
    # cancel other's
    st, body = await client.cancel(res_id, token_b)
    assert st == 404, "Canceling other's reservation should return 404"
    print("[PASS] Spoofing passed")

async def run_scenario_stampede(client: BurstClient, args):
    print(f"--- Scenario 5: Stampede (~{args.requests} requests) ---")
    
    num_seats = min(args.requests, 10000)
    seats = [f"S{i}" for i in range(num_seats)]
    show_id = await client.create_show("Stampede Show", seats)
    
    users = [f"user-stampede-{i}" for i in range(args.users)]
    # Create tokens sequentially in batches to avoid overwhelming auth endpoint if poorly configured
    # We are testing the show/reserve endpoint mostly
    print("Generating tokens...")
    tokens = []
    chunk_size = 100
    for i in range(0, len(users), chunk_size):
        chunk = users[i:i+chunk_size]
        toks = await asyncio.gather(*[client.get_token(u) for u in chunk])
        tokens.extend(toks)
        
    print(f"Launching {args.requests} requests with concurrency {args.concurrency}...")
    
    # Prepare requests
    tasks = []
    hot_seats = ["S0", "S1", "S2"]
    
    sem = asyncio.Semaphore(args.concurrency)
    
    async def worker(token, seats_to_reserve, idem_key):
        async with sem:
            return await client.reserve(show_id, token, seats_to_reserve, idem_key)
            
    reqs_to_make = []
    for i in range(args.requests):
        token = random.choice(tokens)
        idem_key = str(uuid.uuid4())
        
        # 10% retries
        if i > 0 and i % 10 == 0:
            token = reqs_to_make[-1][0]
            idem_key = reqs_to_make[-1][2]
            seats_to_reserve = reqs_to_make[-1][1]
        else:
            # mix hot seats and random seats
            if random.random() < 0.2:
                seats_to_reserve = [random.choice(hot_seats)]
            else:
                seats_to_reserve = [f"S{random.randint(3, num_seats-1)}"]
                
        reqs_to_make.append((token, seats_to_reserve, idem_key))
        
    start_time = time.time()
    results = await asyncio.gather(*[worker(*r) for r in reqs_to_make])
    elapsed = time.time() - start_time
    
    print(f"Stampede finished in {elapsed:.2f}s ({(args.requests / elapsed):.2f} req/s)")
    
    # Report
    latencies = []
    status_counts = {}
    reasons = {}
    
    for st, body, dur in results:
        latencies.append(dur)
        status_counts[st] = status_counts.get(st, 0) + 1
        if st >= 400 and "error" in body:
            reason = body["error"].get("code", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
            
    print("\n--- STAMPEDE REPORT ---")
    print(f"Status codes: {status_counts}")
    print(f"Error reasons: {reasons}")
    
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    print(f"Latencies: p50={p50*1000:.1f}ms, p95={p95*1000:.1f}ms, p99={p99*1000:.1f}ms")
    
    assert status_counts.get(500, 0) == 0, "5xx count must be 0"
    assert status_counts.get(502, 0) == 0, "5xx count must be 0"
    assert status_counts.get(503, 0) == 0, "5xx count must be 0"
    
    # Reconciliation
    show = await client.get_show(show_id)
    print("\nShow Reconciliation:")
    print(f"Total: {show['total_seats']}, Available: {show['available']}, Confirmed/Held: {show['confirmed'] + show['held']}")
    assert show['available'] + show['confirmed'] + show['held'] == show['total_seats'], "Invariant violation"
    
    print("\nMetrics (partial):")
    metrics = await client.get_metrics()
    for line in metrics.split('\n'):
        if "reservations_confirmed_total" in line or "reservations_declined_total" in line:
            print(line)
            
    print("[PASS] Stampede passed")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--requests", type=int, default=2000) # reduced default for fast local run, use 20000 for full test
    parser.add_argument("--users", type=int, default=500)
    
    args = parser.parse_args()
    
    client = BurstClient(args.url)
    try:
        await run_scenario_hot_seat(client)
        await run_scenario_per_user_limit(client)
        await run_scenario_idempotency(client)
        await run_scenario_spoof(client)
        await run_scenario_stampede(client, args)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
