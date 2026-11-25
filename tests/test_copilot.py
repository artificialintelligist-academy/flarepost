"""The copilot's report, how it reaches Flarepost, and the runbooks it attaches."""

import pytest
from mcp import Client, StdioServerParameters

from flarepost.copilot.app import describe, flarepost_server, runbook_attacher


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

    server = flarepost_server()

    assert not isinstance(server, StdioServerParameters)
    assert hasattr(server, "__aenter__")


async def test_the_copilot_attaches_a_runbook_once(client: Client):
    attach = runbook_attacher(client)
    incident = {"service": "payments-api"}

    [runbook] = await attach("flarepost_get_incident", incident)

    assert "flarepost://runbooks/payments-api" in runbook
    assert "Check the card provider's status page" in runbook
    assert await attach("flarepost_get_incident", incident) == []


async def test_a_service_without_a_runbook_gets_nothing(client: Client):
    attach = runbook_attacher(client)

    assert await attach("flarepost_get_incident", {"service": "reporting"}) == []


async def test_other_tools_attach_nothing(client: Client):
    attach = runbook_attacher(client)

    assert await attach("flarepost_list_incidents", {"service": "payments-api"}) == []


test_describe_shows_capabilities_and_open_incidents = pytest.mark.anyio(
    test_describe_shows_capabilities_and_open_incidents
)
test_the_copilot_attaches_a_runbook_once = pytest.mark.anyio(test_the_copilot_attaches_a_runbook_once)
test_a_service_without_a_runbook_gets_nothing = pytest.mark.anyio(
    test_a_service_without_a_runbook_gets_nothing
)
test_other_tools_attach_nothing = pytest.mark.anyio(test_other_tools_attach_nothing)