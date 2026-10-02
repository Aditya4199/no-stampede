import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_create_show(monkeypatch):
    class MockConnection:
        async def execute(self, *args, **kwargs):
            pass
            
        async def copy_records_to_table(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self
            
        async def __aexit__(self, exc_type, exc, tb):
            pass
            
        def transaction(self):
            return self

    import contextlib
    @contextlib.asynccontextmanager
    async def mock_acquire():
        yield MockConnection()

    import app.api.internal
    monkeypatch.setattr(app.api.internal, "acquire_conn", mock_acquire)
    
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        payload = {
            "name": "Test Show",
            "price_paise": 1000,
            "per_user_limit": 4,
            "total_seats": 50
        }
        response = await client.post("/internal/shows", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert "show_id" in data


@pytest.mark.asyncio
async def test_configure_show(monkeypatch):
    class MockConnection:
        async def execute(self, *args, **kwargs):
            # return "UPDATE 1" so it simulates a found show
            return "UPDATE 1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    import contextlib
    @contextlib.asynccontextmanager
    async def mock_acquire():
        yield MockConnection()

    import app.api.internal
    monkeypatch.setattr(app.api.internal, "acquire_conn", mock_acquire)
    
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        payload = {
            "hold_ttl_seconds": 300
        }
        # Using a valid UUID
        response = await client.post("/internal/shows/12345678-1234-5678-1234-567812345678", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
