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
