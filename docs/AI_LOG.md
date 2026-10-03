# AI Development Log

This document records the human-AI collaborative decisions, generated components, and model versions across each phase of development.

---

### Phase 1 — Skeleton
- **Commit**: `chore: bootstrap python service with health endpoint`
- **Model**: Antigravity (Gemini)
- **Collaboration**: 
  - I defined the requirements for a Python FastAPI service with an environment-based config and liveness probe. 
  - Antigravity scaffolded the boilerplate project structure, JSON logger, and test suite, allowing us to start with a clean commit history after pivoting from Go.

### Phase 2 — Schema Migrations & Application Lifecycle
- **Collaboration**:
  - I directed the implementation of a robust migration runner using `pg_advisory_lock` to prevent race conditions during deployment.
  - Antigravity wrote the application lifecycle hooks for DB pooling to ensure clean startup/shutdown and built the `/readyz` endpoint.

### Phase 3 — Internal API - Create Show
- **Collaboration**:
  - I designed the `POST /shows` endpoint contract.
  - Antigravity implemented the raw SQL bulk insert syntax for seat generation optimized for `asyncpg`.

### Phase 4 — Internal API - Show Configuration
- **Collaboration**:
  - Antigravity generated the `PATCH /shows/{show_id}` endpoint to support the `hold_ttl_seconds` setting based on my specifications.

### Phase 5 — Cancel Reservation
- **Collaboration**:
  - Antigravity wrote the initial `POST /reservations/{id}/cancel` endpoint logic.
  - I decided to enforce owner-only cancellation returning 404 instead of 403 to prevent existence leaking.
  - Antigravity reviewed the transaction scope and added the deadlock retry loop to mirror the reservation endpoint.

### Phases 6–7 — Holds and the Reaper
- **Collaboration**:
  - I designed the "expired-hold takeover" model so the locking transaction natively overwrites expired holds without waiting for a background job.
  - Antigravity wrote the background task (`reaper.py`) to periodically free expired seats.
  - Antigravity later caught a connection leak in the initial reaper implementation where the sleep was inside the transaction block, which it subsequently fixed.

### Phase 8 — Metrics
- **Collaboration**:
  - Antigravity added the Prometheus `/metrics` endpoint with reservation counters and latency histograms.
  - I decided to tie metric labels strictly to domain outcomes (`seat_taken`, `per_user_limit`, `idempotency_mismatch`).

### Phase 9 — Burst tool
- **Commit**: `feat: add python burst testing harness and fix requirements`
- **Collaboration**: 
  - I defined the scenarios (hot-seat storm, stampede, spoofing) required for the load-testing harness.
  - Antigravity wrote `scripts/burst.py`, refactoring the `httpx` async gather logic for maximum concurrency and handling Windows Unicode encoding edge cases.

### Phase 10 — Hardening passes
- **Collaboration**:
  - I prioritized CP (Consistency) over AP, enforcing 429 shedding instead of risking DB starvation, and designed the admission semaphore.
  - Antigravity reviewed the locking mechanics, catching a minor quota leak on hold takeover and a 429 relabelling mistake, which it fixed.

### Phase 11 — The Fly deploy
- **Collaboration**:
  - Antigravity configured `fly.toml` and the Dockerfile.
  - I ensured memory limits and concurrency settings matched the `DB_MAX_CONNS` assumptions for production deployment.
