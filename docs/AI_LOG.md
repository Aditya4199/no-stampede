# AI Development Log

This document records the human-AI collaborative decisions, generated components, and model versions across each phase of development.

---

### Phase 1 — Skeleton
- **Commit**: `chore: bootstrap python service with health endpoint`
- **Model**: Gemini 3.8 Flash (High)
- **Generated**:
  - Python project structure: `app/`, `app/api/`, `app/store/`, `app/auth/`, `app/metrics/`, `tests/`.
  - FastAPI application with lifespan context manager for startup and graceful shutdown (`app/main.py`).
  - Structured JSON logger (`JSONFormatter`) outputting single-line JSON records to stdout.
  - Environment-based configuration loader (`app/config.py`) loading `PORT`, `DATABASE_URL`, `JWT_SECRET`, and `DB_MAX_CONNS` with defaults.
  - Liveness probe handler `GET /healthz` returning `{"status": "ok"}` (`app/api/health.py`).
  - Unit tests for configuration loading and async integration tests for `/healthz` using `httpx.AsyncClient` (`tests/test_config.py`, `tests/test_health.py`).
  - Build and dependency management: `requirements.txt`, `Makefile`, `.gitignore`, `pytest.ini`, `README.md`.
- **Human Decisions / Clarifications**:
  - Aditya requested a stack pivot from Go to Python.
  - Agreed via interactive alignment to:
    1. Reset Git commit history cleanly so Phase 1 starts directly with the Python service.
    2. Use FastAPI + `asyncpg` for maximum async performance with plain SQL and zero ORM overhead.
    3. Adopt `active_count` (or `seat_count`) for the `user_show_quota` table to cleanly account for all active seats (held + confirmed) against `per_user_limit`.

### Phase 2 — Schema Migrations & Application Lifecycle
- Implemented robust migration runner using `pg_advisory_lock`.
- Added application lifecycle hooks for DB pooling and migrations.
- Built `/readyz` endpoint.

### Phase 3 — Internal API - Create Show
- Added `POST /internal/shows` endpoint.
- Implemented bulk insert for seat generation in a single transaction.

### Phase 4 — Internal API - Show Configuration
- Added `POST /internal/shows/{show_id}` endpoint.
- Updated `hold_ttl_seconds` setting for a show.

### Phase 4.1 — Alignment, Security, and Spec Compliance
- **Bugs found during review**:
  - `POST /shows` and `PATCH /internal/shows/{id}` had no authentication. Fixed by adding JWT role checking (requires `role=admin`).
  - DB failures threw unhandled 500s. Fixed by implementing a `DomainError` exception handler and mapping `asyncpg` timeout/connection errors to `503 Service Unavailable` with `Retry-After: 5`.
  - The request shape for `POST /shows` allowed unbounded memory allocation with `total_seats`. Fixed by migrating to taking an explicit `seats[]` array and validating it using pydantic (`max_length=10000`).
  - Tests only used mocks. Re-wrote `test_shows.py` and `test_internal_shows.py` to target the actual Postgres database spun up locally.
  - Test migration didn't verify a successful insert count. Updated to check `count == 1`.
  - `docker-compose.yml` had obsolete `version` tag. Cleaned it up and added `app` build to test from a clean clone.
- **Architectural changes**:
  - Created `/shows/{id}` endpoint combining counts of seats by status along with a JSON-aggregated list of all seats. 
  - Restricted `/auth/token` for generating `role=admin` tokens unless running in `dev` or explicitly authorized via `ADMIN_KEY`.
