# Seat Reservation at Scale - Architecture & Writeup

## The Atomic Decision
The atomic decision of whether a user can reserve a set of seats lives strictly within the PostgreSQL database layer using a combination of **row-level locking (`SELECT ... FOR UPDATE`)** and **transactional boundaries**. 

When a `POST /reserve` request arrives, the application starts a database transaction and executes a `SELECT ... FOR UPDATE` on the specific seats requested (ordered alphabetically to prevent deadlocks). This acquires an exclusive row lock on those seats. Inside the same transaction, the state is evaluated:
1. If the seats are already `held` or `confirmed`, a `409 Conflict` is returned.
2. The user's current active reservation count is locked and checked. If adding the new seats exceeds `per_user_limit`, it returns `409 Conflict`.
3. If both conditions pass, the seats are updated to `held` (or `confirmed`) and the transaction commits, releasing the lock. 

This is race-free because PostgreSQL's MVCC ensures that if 500 parallel transactions try to lock the exact same seat row, 1 will acquire the lock and 499 will wait. Once the 1st transaction commits and changes the state to `held`, the remaining 499 transactions wake up sequentially, read the newly committed `held` state, and gracefully abort with a `409 Conflict`.

**Avoiding Deadlocks (Multi-seat requests):** When users request multiple seats (e.g., `["B1", "A1"]`), the application always sorts the requested seat IDs lexicographically before querying `SELECT ... FOR UPDATE`. This guarantees all concurrent transactions attempt to lock rows in the exact same global order, making deadlocks mathematically impossible.

## Idempotency
Idempotency is enforced by a dedicated `idempotency_keys` table. 
1. We store a composite unique key of `(user_id, idempotency_key)`.
2. Before processing a reservation, we attempt an `INSERT` into this table. 
3. If the insert succeeds, it's a new request. If it fails due to a unique constraint violation, it's a retry.
4. For retries, we fetch the previously stored request body and response payload. If the requested seats match the original request exactly, we return the cached response (exactly-once semantics). If the seats differ, we reject it with `409 Conflict` (same-key-different-body handling).

## Holds & Expiry
We implemented a time-boxed hold mechanism. When a user reserves a seat, its status becomes `held` and an `expires_at` timestamp is set (e.g., 10 minutes in the future). 
- A background asynchronous task (the "Reaper") continuously polls the database for expired holds.
- The Reaper executes an atomic `UPDATE seats SET status = 'available', user_id = NULL WHERE status = 'held' AND expires_at < NOW()`.
- Users can also explicitly release their holds via `POST /shows/{id}/reservations/{reservation_id}/cancel`.
This ensures a released seat becomes cleanly re-bookable. A release can never resurrect a seat confirmed to someone else because a confirmed seat permanently loses its `expires_at` timestamp and transitions to the `confirmed` status, making it immune to the Reaper.

## Consistency vs Availability under a Partition
The system strictly favors **Consistency (CP in CAP theorem)**. Because a seat is a unique physical asset that can only be sold once, double-booking is catastrophic. If the application server loses connection to the database (network partition), it fails closed, returning a `503` (or `429 Too Many Requests` during extreme load-shedding) rather than attempting to serve potentially stale or overlapping reservations. The readiness endpoint `/readyz` explicitly performs a live database ping and fails if the DB is unreachable, removing the node from the load balancer.

## Observability
If paged at 2 AM for an incident, the primary signals I would rely on are the exposed Prometheus metrics:
- `reservations_confirmed_total` vs `reservations_declined_total`: A massive spike in declines (specifically `internal_error`) indicates database connectivity or application bugs.
- `http_requests_total{code="5xx"}`: Alerts on any server crashes.
- Database CPU/Memory saturation and Postgres lock queue length: To detect if the database size needs scaling due to a massive stampede (we scaled to 512MB RAM on Fly to handle 2000+ burst connections gracefully).
All API logs are strictly structured in JSON, containing `X-Request-ID` and `duration_ms`, allowing me to trace any slow request or specific user idempotency failure directly through Datadog or ELK.

## AI Usage
AI tools were used extensively as a pair-programming partner to scaffold the boilerplate FastAPI application, generate the `asyncpg` connection pool logic, and write the extensive Python test suite (`scripts/burst.py`). The core architectural decisions—such as the deterministic row-locking strategy, the 429 backoff mechanism, and the idempotency table schema—were architected directly based on the exact problem constraints, with AI executing the implementation details. 

## What I'd do next
1. **Redis Caching for Show State**: Currently, `GET /shows/{id}` hits Postgres. I'd add Redis to cache available seats, invalidating it asynchronously to relieve read-heavy load during a stampede.
2. **Postgres Connection Bouncer**: Introduce `PgBouncer` to manage connection pooling at scale, instead of relying solely on the application's internal `asyncpg` pool limit.
3. **Queueing System**: Introduce a Kafka/RabbitMQ queue for incoming reservations during massive spikes, converting the API from a synchronous lock model to an asynchronous worker model to protect the DB from lock exhaustion entirely.
