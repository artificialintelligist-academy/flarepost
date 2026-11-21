"""The postmortem prompt brings the incident, its timeline and its runbook together."""

import pytest
from mcp import Client, MCPError

pytestmark = pytest.mark.anyio


async def create(client: Client, service: str) -> str:
    result = await client.call_tool(
        "create_incident",
        {"title": "Checkout API returning 500 errors", "service": service, "severity": "sev1"},
    )
    return str(result.structured_content["id"])


async def test_lists_the_postmortem_prompt(client: Client):
    result = await client.list_prompts()
    assert [prompt.name for prompt in result.prompts] == ["write_postmortem"]


async def test_postmortem_embeds_incident_timeline_and_runbook(client: Client):
    incident_id = await create(client, "checkout-api")

    result = await client.get_prompt("write_postmortem", {"incident_id": incident_id})
    uris = [str(m.content.resource.uri) for m in result.messages if m.content.type == "resource"]
    assert uris == [
        f"flarepost://incidents/{incident_id}",
        f"flarepost://incidents/{incident_id}/timeline",
        "flarepost://runbooks/checkout-api",
    ]
    assert "blameless postmortem" in result.messages[-1].content.text


async def test_postmortem_skips_a_missing_runbook(client: Client):
    incident_id = await create(client, "media-api")

    result = await client.get_prompt("write_postmortem", {"incident_id": incident_id})
    kinds = [message.content.type for message in result.messages]
    assert kinds == ["resource", "resource", "text"]


async def test_postmortem_for_a_missing_incident_is_a_protocol_error(client: Client):
    with pytest.raises(MCPError, match="does not exist"):
        await client.get_prompt("write_postmortem", {"incident_id": "999"})