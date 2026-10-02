# System Design Writeup: Seat Reservation at Scale

## 1. Atomic Decisions: Single Transaction vs. SAGA
For ticket reservation, we need absolute guarantees that a seat is not double-sold. 
We chose a **Single Database Transaction** using PostgreSQL's row-level locking (`SELECT ... FOR UPDATE`) instead of a distributed SAGA pattern.
- **Why?** Relational databases are exceptional at ACID compliance. By locking the specific seat rows in a deterministic order (e.g., sorting alphabetically by seat label), we avoid deadlocks and ensure that concurrent requests attempting to book the same seats will queue up at the database level.
- **SAGA Tradeoffs**: A SAGA pattern (choreography/orchestration between services) introduces eventual consistency, meaning we might oversell and have to issue a refund/compensating transaction later. For this domain, overselling is catastrophic, making strong consistency via a single transaction the right choice.

## 2. Idempotency Implementation
Network failures happen, and clients will retry. If they retry a payment/reservation, we must not charge them twice or book another set of seats.
- We implemented an `idempotency_keys` table.
- Before locking seats, we attempt to `INSERT` the `(user_id, idempotency_key)` pair.
- If it succeeds, this is the first attempt.
- If it fails (`ON CONFLICT`), we retrieve the stored `request_hash` to ensure the user isn't changing the payload on a retry. If it matches, we simply return the previously stored response without hitting the reservation logic again.

## 3. Holds & Expiry Strategy
When a user begins checkout, seats are placed on "hold" for a limited time (e.g., 10 minutes) before they complete payment.
- **Lazy Evaluation**: During any reservation attempt, the system checks `hold_expires_at < now`. If a seat is marked as 'held' but its expiration time has passed, the system treats it as 'available'. This prevents users from being blocked by stale holds.
- **Active Reaper**: Relying solely on lazy evaluation leaves the database cluttered and causes metrics (e.g., available seat counts) to be inaccurate. We implemented a background worker (`reaper.py`) that periodically scans for expired holds and physically updates them back to 'available', ensuring global counts are eventually consistent and accurate.

## 4. Observability and Monitoring
We built a custom Prometheus exporter (`/metrics`).
- **Counters**: We track `reservations_confirmed_total` and `reservations_declined_total` (tagged by `reason` like `seat_taken`, `per_user_limit`).
- This allows us to build Grafana dashboards to monitor if the system is rejecting too many requests (indicating a possible bot attack) or if confirmed reservations suddenly drop (indicating a failure in the checkout flow). 
- **Zero 5xx Guarantee**: By observing metrics and returning 4xx for domain errors (conflicts, limits), we can easily alert on *any* 5xx error, which represents a true system failure.

## 5. CAP Theorem: CP over AP
In the context of the CAP theorem, this system is explicitly designed as a **CP (Consistent and Partition-Tolerant)** system.
- **Consistency**: The highest priority. We must never sell the same seat twice.
- **Partition Tolerance**: We must handle network partitions gracefully.
- **Availability Tradeoff**: If the primary database goes down or a partition separates the app from the DB, the system will refuse to serve reservation requests rather than risking divergent states or overbooking. In this domain, saying "Service Unavailable" is far better than saying "You got the ticket!" and later revoking it.
