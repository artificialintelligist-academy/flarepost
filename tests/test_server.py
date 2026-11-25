"""Talk to Flarepost through MCP, the same way a host does."""

import json

import pytest
from mcp import Client, MCPError

from flarepost.integrations import slack

pytestmark = pytest.mark.anyio

CHECKOUT = {
    "title": "Checkout API returning 500 errors",
    "service": "checkout-api",
    "severity": "sev1",
}


def text_of(result) -> str:
    return result.content[0].text


async def create(client: Client, **overrides) -> dict:
    result = await client.call_tool("create_incident", {**CHECKOUT, **overrides})
    assert not result.is_error
    return result.structured_content


async def timeline_kinds(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["kind"] for entry in result.structured_content["result"]]


async def test_exposes_all_tools(client: Client):
    result = await client.list_tools()
    assert {tool.name for tool in result.tools} == {
        "create_incident",
        "get_incident",
        "list_incidents",
        "update_incident",
        "resolve_incident",
        "add_note",
        "get_timeline",
        "post_to_slack",
        "post_incident_digest",
        "draft_status_update",
        "revise_status_update",
        "publish_status_update",
        "discard_status_update",
    }


async def test_create_and_get_incident(client: Client):
    created = await create(client)
    assert created["status"] == "open"

    result = await client.call_tool("get_incident", {"incident_id": created["id"]})
    assert result.structured_content == created


async def test_create_rejects_a_bad_service(client: Client):
    result = await client.call_tool("create_incident", {**CHECKOUT, "service": "Checkout API"})
    assert result.is_error
    assert "service" in text_of(result)


async def test_missing_incident_points_to_list_incidents(client: Client):
    result = await client.call_tool("get_incident", {"incident_id": 999})
    assert result.is_error
    assert "list_incidents" in text_of(result)


async def test_list_incidents_filters_by_service(client: Client):
    await create(client)
    await create(client, title="Login latency above 2 seconds", service="auth-service", severity="sev2")

    result = await client.call_tool("list_incidents", {"service": "auth-service"})
    services = [incident["service"] for incident in result.structured_content["incidents"]]
    assert services == ["auth-service"]


async def test_changes_and_notes_go_to_the_timeline(client: Client):
    incident = await create(client, severity="sev3")
    await client.call_tool(
        "update_incident",
        {"incident_id": incident["id"], "status": "investigating", "severity": "sev2"},
    )
    await client.call_tool(
        "add_note", {"incident_id": incident["id"], "message": "Rolled back the last deploy."}
    )

    assert await timeline_kinds(client, incident["id"]) == ["created", "status", "severity", "note"]


async def test_resolved_incident_cannot_change(client: Client):
    incident = await create(client)
    await client.call_tool(
        "resolve_incident",
        {"incident_id": incident["id"], "summary": "Rolled back the last deploy."},
    )

    result = await client.call_tool("update_incident", {"incident_id": incident["id"], "severity": "sev3"})
    assert result.is_error
    assert "already resolved" in text_of(result)


async def test_post_to_slack_sends_and_records_a_note(confirming_client: Client, monkeypatch):
    client = confirming_client
    sent: list[str] = []
    monkeypatch.setattr(slack, "post_message", sent.append)
    incident = await create(client)

    result = await client.call_tool(
        "post_to_slack", {"incident_id": incident["id"], "message": "Rolling back the deploy."}
    )
    assert result.structured_content["posted"] is True
    assert sent[0].startswith("*[SEV1]")
    assert result.structured_content["entry"]["message"] == "Posted to Slack: Rolling back the deploy."


async def test_post_to_slack_without_config_records_nothing(confirming_client: Client):
    client = confirming_client
    incident = await create(client)

    result = await client.call_tool(
        "post_to_slack", {"incident_id": incident["id"], "message": "Rolling back the deploy."}
    )
    assert result.is_error
    assert "not configured" in text_of(result)
    assert await timeline_kinds(client, incident["id"]) == ["created"]


async def test_lists_a_runbook_per_service(client: Client):
    result = await client.list_resources()
    uris = {str(resource.uri) for resource in result.resources}
    assert {
        "flarepost://runbooks/auth-service",
        "flarepost://runbooks/checkout-api",
        "flarepost://runbooks/payments-api",
    } <= uris


async def test_reads_the_checkout_runbook(client: Client):
    result = await client.read_resource("flarepost://runbooks/checkout-api")
    assert result.contents[0].text.startswith("# Runbook: checkout-api")


async def test_lists_the_incident_templates(client: Client):
    result = await client.list_resource_templates()
    templates = {template.uri_template for template in result.resource_templates}
    assert templates == {
        "flarepost://incidents/{incident_id}",
        "flarepost://incidents/{incident_id}/timeline",
    }


async def test_reads_an_incident_as_a_resource(client: Client):
    created = await create(client)

    result = await client.read_resource(f"flarepost://incidents/{created['id']}")
    assert json.loads(result.contents[0].text)["title"] == CHECKOUT["title"]


async def test_reads_a_timeline_as_a_resource(client: Client):
    created = await create(client)

    result = await client.read_resource(f"flarepost://incidents/{created['id']}/timeline")
    entries = json.loads(result.contents[0].text)
    assert [entry["kind"] for entry in entries] == ["created"]


async def test_missing_incident_resource_is_a_protocol_error(client: Client):
    with pytest.raises(MCPError, match="does not exist"):
        await client.read_resource("flarepost://incidents/999")


async def test_list_incidents_walks_every_page_once(client: Client):
    created = [await create(client, title=f"Checkout incident number {n}") for n in range(5)]

    seen: list[int] = []
    cursor = None
    while True:
        arguments = {"limit": 2} if cursor is None else {"limit": 2, "cursor": cursor}
        page = (await client.call_tool("list_incidents", arguments)).structured_content
        assert len(page["incidents"]) <= 2
        seen += [incident["id"] for incident in page["incidents"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == sorted((incident["id"] for incident in created), reverse=True)


async def test_list_incidents_rejects_a_made_up_cursor(client: Client):
    result = await client.call_tool("list_incidents", {"cursor": "page-2"})
    assert result.is_error
    assert "without a cursor" in text_of(result)


async def test_list_incidents_caps_the_page_size(client: Client):
    result = await client.call_tool("list_incidents", {"limit": 500})
    assert result.is_error


async def test_update_incident_sends_resolving_to_resolve_incident(client: Client):
    incident = await create(client)

    result = await client.call_tool("update_incident", {"incident_id": incident["id"], "status": "resolved"})
    assert result.is_error
    assert "resolve_incident" in text_of(result)