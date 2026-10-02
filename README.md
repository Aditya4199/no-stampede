# Seat Reservation at Scale

High-concurrency ticket booking and seat reservation engine built with Python, FastAPI, and PostgreSQL (`asyncpg`).

## Architecture & Design Principles
- **Async I/O**: FastAPI with native ASGI and `asyncpg` connection pooling for ultra-low latency and zero ORM overhead.
- **Strict Concurrency Control**: Row-level locking (`FOR UPDATE`) with deterministic ordering to prevent deadlocks and overselling.
- **Idempotency**: Hash-checked idempotency key tracking ensuring exactly-once reservation semantics.
- **Quota Enforcement**: Dedicated quota counters (`active_count`) serialized per user.
- **Zero 5xx Under Load**: Strict error handling with 4xx domain declines and retry loops for transient locks.

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
pytest -v

# Run server
python -m app.main
```

### API Endpoints
- `GET /healthz` - Liveness probe
- `GET /readyz` - Readiness probe (database connectivity)
- `POST /auth/token` - Development token issuer
- `POST /shows` - Create show and seats (Admin)
- `GET /shows/{id}` - Show availability and counts
- `POST /shows/{id}/reserve` - Atomic seat reservation
- `POST /reservations/{id}/cancel` - Owner-only cancellation
- `GET /metrics` - Prometheus metrics
