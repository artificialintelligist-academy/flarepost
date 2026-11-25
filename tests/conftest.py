"""Shared fixtures: every test gets its own database and an in-memory client."""

import pytest
from mcp import Client
from mcp.types import ElicitResult

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


async def say_yes(context, params):
    """A user who confirms every question, for tests about what happens after they agree."""
    return ElicitResult(action="accept", content={"confirm": True})


@pytest.fixture
async def confirming_client():
    async with Client(mcp, raise_exceptions=True, elicitation_callback=say_yes) as connected:
        yield connected