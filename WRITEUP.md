# No-Stampede — Architecture & Writeup

## The Atomic Decision

When a `POST /shows/{id}/reserve` request arrives, the reservation logic runs in two phases inside a single DB connection.

### Phase 1 — Unlocked pre-check (fast path)

Before acquiring any lock, we read the requested seats with a plain `SELECT`:

```sql
SELECT label, status, hold_expires_at
FROM seats
WHERE show_id = $1 AND label = ANY($2)
```

If any seat is `confirmed`, or is `held` with a non-expired `hold_expires_at`, we immediately return `409 seat_taken` — no lock contention needed. This eliminates the majority of doomed requests in a hot-seat storm before they ever touch a row lock.

### Phase 2 — Locked re-check + write (one transaction)

For requests that pass the pre-check, we open a transaction and re-read the same rows with `SELECT … FOR UPDATE` in **deterministic lexicographic order** to prevent deadlocks:

```sql
SELECT label, status, hold_expires_at, reservation_id, user_id
FROM seats
WHERE show_id = $1 AND label = ANY($2)
ORDER BY label
FOR UPDATE
```

Inside the same transaction we:
1. Re-verify seat availability (the state may have changed since the pre-check).
2. Lock and increment the user's `user_show_quota.active_count`; reject with `409 per_user_limit` if adding the new seats would exceed `per_user_limit`.
3. Insert a row in `reservations`. If `hold_ttl_seconds` is set on the show, the reservation status is `held` and `hold_expires_at = NOW() + hold_ttl_seconds`. Otherwise the reservation is **`confirmed` immediately** — no hold required.
4. Flip each `seats.status` to match, write `seats.reservation_id`.
5. Commit — lock released.

This is race-free: PostgreSQL serialises all concurrent transactions that try to lock the same row. The one that wins commits; every waiter reads the newly committed state and fails gracefully.

### Avoiding Deadlocks (multi-seat requests)

All seat labels are sorted lexicographically before `FOR UPDATE`. Two concurrent transactions requesting `["B1","A1"]` and `["A1","B1"]` both resolve to `["A1","B1"]` and acquire locks in the same order — deadlock is mathematically impossible.

---

## Idempotency

The idempotency hash covers **`show_id` + sorted seat labels**:

```python
req_hash = hashlib.sha256(f"{show_id}-{','.join(sorted_seats)}".encode()).hexdigest()
```

The flow:
1. **Fast-path read** (before the transaction): `SELECT … FROM idempotency_keys WHERE user_id=$1 AND key=$2`. If the row exists and has a stored `response`, return it immediately — no DB write needed.
2. **Inside the transaction**: `INSERT INTO idempotency_keys … ON CONFLICT (user_id, key) DO NOTHING` inside it, where a concurrent duplicate waits on the primary key and then replays the stored response.
   - Same hash → return cached response (exactly-once semantics).  
   - Different hash → `409 idempotency_mismatch`.

---

## Holds & Expiry

`hold_ttl_seconds` is an optional per-show setting (set via `PATCH /shows/{id}`). When non-null, new reservations are `held` rather than immediately `confirmed`, and `hold_expires_at = NOW() + interval`.

Holds model a payment window that is cancelled or expires, and confirmation is out of scope.

A background **Reaper** task polls for expired holds every few seconds:

```sql
UPDATE seats SET status='available', reservation_id=NULL
WHERE status='held' AND hold_expires_at < NOW()
RETURNING reservation_id
```

The Reaper also decrements `user_show_quota.active_count` for the affected user and marks the `reservations` row as `expired`.

**Expired-hold takeover:** When a second user reserves a seat whose hold has just expired (reaper has not yet run), the locked re-check finds `hold_expires_at < NOW()` and treats it as available. The old owner's quota is decremented within the same write transaction, so the released quota is immediately visible to the new reservation.

---

## Load-Shedding (Admission Semaphore)

An `asyncio.Semaphore(config.max_inflight_reserves)` gates the reserve endpoint. Any request that cannot acquire the semaphore within `config.admission_wait_ms` milliseconds receives:

```json
{"error": {"code": "too_many_requests", "message": "The service is currently overloaded. Please try again later."}}
```

with `HTTP 429` and `Retry-After: 1`. The semaphore is **per process** — in a multi-machine deployment each replica sheds independently.

The admission cap defaults to `DB_MAX_CONNS - 5` because each reserve uses exactly one connection, so admitted requests never wait on the pool.

---

## Error Code Reference

| HTTP | Code | Meaning |
|------|------|---------|
| 400 | `invalid_request` | Bad payload, missing required field |
| 400 | `invalid_seats` | Seat label not in this show |
| 401 | `unauthorized` | Missing or invalid JWT |
| 403 | `forbidden` | Insufficient role |
| 404 | `not_found` | Show or reservation not found |
| 409 | `seat_taken` | Seat confirmed or actively held |
| 409 | `per_user_limit` | User quota exceeded |
| 409 | `idempotency_mismatch` | Same key, different request body |
| 409 | `already_expired` | Reservation already expired |
| 409 | `conflict` | The reservation is currently busy |
| 429 | `too_many_requests` | Admission semaphore timed out |
| 503 | `service_unavailable` | DB pool unavailable — fail closed |
| 500 | `internal_error` | Unexpected bug; never from domain logic |

If all 3 lock retries time out, reserve returns 409 seat_taken.

---

## Observability & Recommended Alerts

Prometheus metrics are exposed at `GET /metrics`.

| Alert | Query | Threshold |
|-------|-------|-----------|
| Any 5xx | `rate(http_requests_total{code=~"5.."}[1m]) > 0` | Immediate |
| High 429 rate | `rate(reservations_declined_total{reason="too_many_requests"}[1m]) > 10` | Warning |
| DB pool wait p99 | `histogram_quantile(0.99, rate(db_pool_wait_duration_seconds_bucket[5m])) > 2` | Warning |

Key metrics:
- `reservations_confirmed_total{show_id}` — bookings per show.
- `reservations_declined_total{reason}` — categorised rejections.
- `http_request_duration_seconds` — per-route latency histogram.

All HTTP logs are structured JSON with `X-Request-ID` and `duration_ms` for tracing in Datadog/ELK.

---

## Consistency vs Availability

The system is **CP** (CAP). A seat is a unique physical asset; double-booking is catastrophic. If the DB is unreachable the app returns `503`, never a stale or speculative answer. `/readyz` performs a live DB ping and removes the node from the load balancer on failure.

---

## Known Limitations

1. **Semaphore is per-process.** A 2-replica deployment has `2 × max_inflight_reserves` total concurrency. Use `MAX_INFLIGHT_RESERVES` per replica to tune.
2. **Single primary DB.** All writes serialise through one Postgres instance. Horizontal write-scaling would require sharding by `show_id` or a queue layer (Kafka).
3. **Reaper is in-process.** If the API process dies with open holds, they expire naturally at `hold_expires_at` but are not reaped until the next process starts.

---

## What I'd Do Next

1. **Redis read-through cache** for `GET /shows/{id}` to relieve Postgres during read-heavy stampedes.
2. **PgBouncer** in transaction-pooling mode to multiply the effective connection count.
3. **Async reservation queue** (Kafka/SQS) for extreme spikes, converting the synchronous lock model to a worker fan-out.

---

## AI Usage

I wrote the initial codebase and designed the core architecture, including the deterministic row-locking, the two-phase pre-check pattern, the idempotency hash scheme, and the 429 admission semaphore based on the problem constraints. I used Antigravity (Gemini) as a pair-programming partner to review iterations, assist with refactoring the `asyncpg` connection pooling logic, and catch edge-case bugs under load (such as a transaction-scope regression, a quota leak on hold takeover, a reaper connection hold, and missing cancel retries).
