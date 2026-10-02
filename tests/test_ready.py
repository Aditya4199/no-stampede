import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_readyz_ok(monkeypatch):
    # Mock get_pool to avoid actual db connection during tests
    class MockConnection:
        async def execute(self, query):
            return "1"
        
        async def __aenter__(self):
            return self
            
        async def __aexit__(self, exc_type, exc, tb):
            pass

    class MockPool:
        def acquire(self):
            return MockConnection()

    import app.api.ready
    monkeypatch.setattr(app.api.ready, "get_pool", lambda: MockPool())

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "db": "ok"}
