# AI Development Log

This document records the human-AI collaborative decisions, generated components, and model versions across each phase of development.

---

### Phase 1 — Skeleton
- **Commit**: `chore: bootstrap python service with health endpoint`
- **Model**: Antigravity (Gemini)
- **Collaboration**: 
  - I initialized the Python project structure, FastAPI application, JSON logger, environment-based config, and liveness probe. 
  - Used Antigravity to quickly scaffold boilerplate and reset Git commit history cleanly after pivoting from Go to Python.

### Phase 2 — Schema Migrations & Application Lifecycle
- **Collaboration**:
  - I implemented the robust migration runner using `pg_advisory_lock` and the `/readyz` endpoint.
  - Used Antigravity to review and refactor the application lifecycle hooks for DB pooling to ensure clean startup/shutdown.

### Phase 3 — Internal API - Create Show
- **Collaboration**:
  - I designed the `POST /shows` endpoint and the bulk insert logic for seat generation.
  - Antigravity assisted in optimizing the raw SQL bulk insert syntax for `asyncpg`.

### Phase 4 — Internal API - Show Configuration
- **Collaboration**:
  - I added the `PATCH /shows/{show_id}` endpoint to support the `hold_ttl_seconds` setting.

### Phase 5 — Cancel Reservation
- **Collaboration**:
  - I wrote the core `POST /reservations/{id}/cancel` endpoint logic.
  - Decided to enforce owner-only cancellation returning 404 instead of 403 to prevent existence leaking.
  - Used Antigravity to review the transaction scope and add the deadlock retry loop to mirror the reservation endpoint.

### Phases 6–7 — Holds and the Reaper
- **Collaboration**:
  - I designed the "expired-hold takeover" model so the locking transaction natively overwrites expired holds without waiting for the reaper.
  - I wrote the background task (`reaper.py`) to periodically free expired seats.
  - Antigravity caught a connection leak in my initial reaper implementation where the sleep was inside the transaction block, which I subsequently fixed.

### Phase 8 — Metrics
- **Collaboration**:
  - I added the Prometheus `/metrics` endpoint with reservation counters and latency histograms.
  - Decided to tie metric labels strictly to domain outcomes (`seat_taken`, `per_user_limit`, `idempotency_mismatch`).

### Phase 9 — Burst tool
- **Commit**: `feat: add python burst testing harness and fix requirements`
- **Collaboration**: 
  - I wrote the load-testing harness `scripts/burst.py` wrapping scenarios.
  - Antigravity helped refactor the httpx async gather logic for maximum concurrency and handled Windows Unicode encoding edge cases.

### Phase 10 — Hardening passes
- **Collaboration**:
  - I prioritized CP (Consistency) over AP, enforcing 429 shedding instead of risking DB starvation, and designed the admission semaphore.
  - Antigravity reviewed the locking mechanics, catching a minor quota leak on hold takeover and a 429 relabelling mistake, which I fixed.

### Phase 11 — The Fly deploy
- **Collaboration**:
  - I configured `fly.toml` and the Dockerfile, ensuring memory limits and concurrency settings matched the `DB_MAX_CONNS` assumptions.
