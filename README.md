# No-Stampede — Seat Reservation at Scale

High-concurrency ticket-booking engine built with FastAPI + asyncpg + PostgreSQL.
Handles hot-seat storms, per-user quota, idempotency, and load-shedding with zero overselling.

**Live demo:** https://no-stampede.fly.dev

---

## Quickstart (local, Docker)

```bash
git clone https://github.com/Aditya4199/no-stampede.git
cd no-stampede
docker compose up          # starts postgres + api on :8080
```

Run tests (requires `DATABASE_URL` pointed at a running Postgres):

```bash
pip install -r requirements.txt -r requirements-dev.txt
DATABASE_URL=postgresql://postgres:password@localhost:5432/no_stampede pytest
```

---

## API Reference

### Auth — get a JWT

```bash
# User token (dev only)
curl -s -X POST "http://localhost:8080/auth/token?user_id=alice&role=user" \
     -H "ADMIN_KEY: admin" | jq .token

# Admin token
curl -s -X POST "http://localhost:8080/auth/token?user_id=admin&role=admin" \
     -H "ADMIN_KEY: admin" | jq .token
```

### Create a show (admin)

```bash
TOKEN=$(curl -s -X POST "http://localhost:8080/auth/token?user_id=admin&role=admin" \
        -H "ADMIN_KEY: admin" | jq -r .token)

curl -s -X POST http://localhost:8080/shows \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -H "Idempotency-Key: $(uuidgen)" \
     -d '{"name":"Eras Tour","price_paise":500000,"per_user_limit":4,"seats":["A1","A2","A3","B1"]}' \
  | jq .
```

### Reserve seats (user)

```bash
USER_TOKEN=$(curl -s -X POST "http://localhost:8080/auth/token?user_id=alice&role=user" \
             -H "ADMIN_KEY: admin" | jq -r .token)

# Via header (preferred)
curl -s -X POST "http://localhost:8080/shows/<SHOW_ID>/reserve" \
     -H "Authorization: Bearer $USER_TOKEN" \
     -H "Content-Type: application/json" \
     -H "Idempotency-Key: $(uuidgen)" \
     -d '{"seats":["A1","A2"]}' | jq .

# Via body key (also accepted)
curl -s -X POST "http://localhost:8080/shows/<SHOW_ID>/reserve" \
     -H "Authorization: Bearer $USER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"seats":["A1","A2"],"idempotency_key":"my-unique-key-123"}' | jq .
```

### Get show availability

```bash
curl -s http://localhost:8080/shows/<SHOW_ID> | jq '{available,held,confirmed}'
```

### Configure hold TTL (admin — PATCH /shows/{id})

```bash
curl -s -X PATCH "http://localhost:8080/shows/<SHOW_ID>" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"hold_ttl_seconds":600}' | jq .
```

### Cancel a reservation

```bash
curl -s -X POST "http://localhost:8080/reservations/<RESERVATION_ID>/cancel" \
     -H "Authorization: Bearer $USER_TOKEN" | jq .
```

### Prometheus metrics

```bash
curl -s http://localhost:8080/metrics
```

---

## Burst / Load Test

### Against local server

```bash
# Start server
DATABASE_URL=postgresql://postgres:password@localhost:5432/no_stampede \
ENV=dev ADMIN_KEY=admin uvicorn app.main:app --port 8080

# In another terminal
./burst.sh http://localhost:8080
# or directly:
python scripts/burst.py --url http://localhost:8080 --admin-key admin
```

### Against live deployment

```bash
./burst.sh https://no-stampede.fly.dev
```

### Real burst summary (local, 2026-10-03)

```
--- Scenario 1: Hot-seat storm (500 users -> 1 seat) ---
Status codes: {201: 1, 409: 499}
[PASS] Hot-seat storm passed

--- Scenario 2: Per-user limit (1 user, 10 parallel single-seat requests) ---
Status codes: {201: 4, 409: 6}
[PASS] Per-user limit passed

--- Scenario 3: Idempotency (50 parallel same key; then same key diff seats) ---
Phase 1 Status codes: {201: 50}
Phase 2 Status: 409
[PASS] Idempotency passed

--- Scenario 4: Spoof user_id & cancel other's reservation ---
[PASS] Spoofing passed

--- Scenario 5: Stampede (~20000 requests) ---
Stampede finished in 251.53s (79.51 req/s)
Status codes: {201: 2231, 409: 17769}
Latencies: p50=744.2ms  p95=4176.7ms  p99=5799.3ms
Show Reconciliation: Total=10000 Available=8000 Confirmed/Held=2000
[PASS] Stampede passed
```

---

## Routes summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/token` | ADMIN_KEY | Issue JWT (dev/admin) |
| `POST` | `/shows` | admin JWT | Create show + seats |
| `GET` | `/shows/{id}` | — | Show availability |
| `PATCH` | `/shows/{id}` | admin JWT | Set hold TTL |
| `POST` | `/shows/{id}/reserve` | user JWT | Reserve seats |
| `POST` | `/reservations/{id}/cancel` | user JWT | Cancel reservation |
| `GET` | `/healthz` | — | Liveness |
| `GET` | `/readyz` | — | Readiness (DB ping) |
| `GET` | `/metrics` | — | Prometheus |
