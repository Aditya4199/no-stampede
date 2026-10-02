import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_readyz_ok(monkeypatch):
    # Mock get_pool to avoid actual db connection during tests
    import contextlib
    @contextlib.asynccontextmanager
    async def mock_acquire():
        class MockConnection:
            async def execute(self, query):
                return "1"
        yield MockConnection()

    import app.api.ready
    monkeypatch.setattr(app.api.ready, "acquire_conn", mock_acquire)

    app_instance = create_app()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "db": "ok"}


@pytest.mark.asyncio
async def test_readyz_503(monkeypatch):
    import contextlib
    @contextlib.asynccontextmanager
    async def mock_acquire():
        class MockConnection:
            async def execute(self, query):
                raise Exception("Database is down")
        yield MockConnection()

    import app.api.ready
    monkeypatch.setattr(app.api.ready, "acquire_conn", mock_acquire)

    app_instance = create_app()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready", "error": "internal error"}
