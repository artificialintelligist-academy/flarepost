"""The copilot's report shows the server, its capabilities and the open incidents."""

import pytest
from mcp import Client

from flarepost.copilot.app import describe

pytestmark = pytest.mark.anyio


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