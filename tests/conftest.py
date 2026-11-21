"""Shared fixtures: every test gets its own database and an in-memory client."""

import pytest
from mcp import Client

from flarepost.server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAREPOST_DB", str(tmp_path / "flarepost.db"))
    monkeypatch.delenv("FLAREPOST_SLACK_WEBHOOK_URL", raising=False)


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as connected:
        yield connected