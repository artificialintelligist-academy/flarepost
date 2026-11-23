"""The copilot's report, and how it reaches Flarepost: over stdio or over Streamable HTTP."""

import pytest
from mcp import Client, StdioServerParameters

from flarepost.copilot.app import describe, flarepost_server


async def test_describe_shows_capabilities_and_open_incidents(client: Client):
    await client.call_tool(
        "create_incident",
        {"title": "Checkout API returning 500 errors", "service": "checkout-api", "severity": "sev1"},
    )

    report = await describe(client)

    assert report.startswith("Connected to Flarepost")
    assert "create_incident" in report
    assert "flarepost://runbooks/checkout-api" in report
    assert "write_postmortem" in report
    assert "#1 [sev1] Checkout API returning 500 errors (checkout-api)" in report


def test_without_a_url_the_copilot_starts_flarepost_over_stdio(monkeypatch):
    monkeypatch.delenv("FLAREPOST_URL", raising=False)

    server = flarepost_server()

    assert isinstance(server, StdioServerParameters)
    assert server.args == ["-m", "flarepost"]


def test_with_a_url_the_copilot_uses_the_running_server(monkeypatch):
    monkeypatch.setenv("FLAREPOST_URL", "http://127.0.0.1:8000/mcp")

    assert flarepost_server() == "http://127.0.0.1:8000/mcp"


test_describe_shows_capabilities_and_open_incidents = pytest.mark.anyio(
    test_describe_shows_capabilities_and_open_incidents
)