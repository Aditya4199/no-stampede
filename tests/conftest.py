import os
import asyncio
import pytest

os.environ.setdefault("ENV", "dev")

@pytest.fixture(scope="function")
def event_loop():
    """Create a fresh event loop for each test function."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
