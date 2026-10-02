# Seat Reservation at Scale

High-concurrency ticket booking and seat reservation engine built with Python, FastAPI, and PostgreSQL (`asyncpg`).

## Architecture & Design Principles
- **Async I/O**: FastAPI with native ASGI and `asyncpg` connection pooling for ultra-low latency and zero ORM overhead.
- **Strict Concurrency Control**: Row-level locking (`FOR UPDATE`) with deterministic ordering to prevent deadlocks and overselling.
- **Idempotency (Planned)**: Hash-checked idempotency key tracking ensuring exactly-once reservation semantics.
- **Quota Enforcement (Planned)**: Dedicated quota counters (`active_count`) serialized per user.
- **Zero 5xx Under Load (Planned)**: Strict error handling with 4xx domain declines and retry loops for transient locks.

## Development

### Prerequisites
- Python 3.10+
- PostgreSQL 16+

### Setup
```bash
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### Running Locally
```bash
# Run tests
make test

# Run server
make run
```

### API Endpoints

- `GET /healthz` - Liveness probe
- `GET /readyz` - Readiness probe (database connectivity)
- `POST /auth/token` - Development token issuer (requires `ENV=dev` or `ADMIN_KEY` for admin tokens)
  ```bash
  curl -X POST http://localhost:8080/auth/token?role=admin
  ```
- `POST /shows` - Create show and seats (Admin only)
  ```bash
  curl -X POST http://localhost:8080/shows \
    -H "Authorization: Bearer <TOKEN>" \
    -H "Content-Type: application/json" \
    -d '{"name": "Eras Tour", "price_paise": 500000, "per_user_limit": 4, "seats": ["A1", "A2"]}'
  ```
- `GET /shows/{id}` - Show availability and counts
  ```bash
  curl http://localhost:8080/shows/<SHOW_ID>
  ```
- `PATCH /internal/shows/{id}` - Configure show
- `POST /shows/{id}/reserve` (Planned) - Atomic seat reservation
- `POST /reservations/{id}/cancel` (Planned) - Owner-only cancellation
- `GET /metrics` (Planned) - Prometheus metrics
