# AI Development Log

This document records the human-AI collaborative decisions, generated components, and model versions across each phase of development.

---

### Phase 1 — Skeleton
- **Commit**: `chore: bootstrap python service with health endpoint`
- **Model**: Gemini 3.8 Flash (High)
- **Generated**:
  - Python project structure, FastAPI application, JSON logger, environment-based config, liveness probe.
- **Human Decisions / Clarifications**:
  - Aditya requested a stack pivot from Go to Python. Reset Git commit history cleanly. Used FastAPI + `asyncpg`.

### Phase 2 — Schema Migrations & Application Lifecycle
- Implemented robust migration runner using `pg_advisory_lock`.
- Added application lifecycle hooks for DB pooling and migrations. Built `/readyz` endpoint.

### Phase 3 — Internal API - Create Show
- Added `POST /shows` endpoint. Implemented bulk insert for seat generation.

### Phase 4 — Internal API - Show Configuration
- Added `PATCH /shows/{show_id}` endpoint. Updated `hold_ttl_seconds` setting for a show.

### Phase 5 — Cancel Reservation
- **Generated**: `POST /reservations/{id}/cancel` endpoint logic.
- **Human Decisions**: Enforced owner-only cancellation (404 instead of 403 to prevent existence leaking).

### Phases 6–7 — Holds and the Reaper
- **Generated**: `hold_ttl_seconds` expiration logic in reservations, and a background task (`reaper.py`) to periodically free expired seats.
- **Human Decisions**: Designed the "expired-hold takeover" model so the locking transaction natively overwrites expired holds without waiting for the reaper.

### Phase 8 — Metrics
- **Generated**: Prometheus `/metrics` endpoint with reservation counters and latency histograms.
- **Human Decisions**: Tied metric labels strictly to domain outcomes (`seat_taken`, `per_user_limit`, `idempotency_mismatch`).

### Phase 9 — Burst tool
- **Commit**: `feat: add python burst testing harness and fix requirements`
- **Model**: Gemini 3.1 Pro (High)
- **Generated**: Load-testing harness `scripts/burst.py` wrapping scenarios.
- **Human Decisions / Clarifications**: Python was chosen over Go for the test client.

### Phase 10 — Hardening passes
- **Generated**: Updates to CI versions, code cleanups, load-shedding semaphores.
- **Human Decisions**: Directed the AI to prioritize CP (Consistency) over AP, enforcing 429 shedding instead of risking DB starvation.

### Phase 11 — The Fly deploy
- **Generated**: `fly.toml` and Dockerfile configurations.
- **Human Decisions**: Ensured memory limits and concurrency settings in Fly matched the `DB_MAX_CONNS` assumptions.

### External Claude review loop
- **Generated**: Feedback identifying edge cases in the architecture.
- **Human Decisions**: Directed the AI to apply fixes for a transaction-scope regression, a 429 relabelling mistake, a quota leak on hold takeover, a reaper connection hold, and missing cancel retries.
