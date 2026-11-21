"""Subscribers hear about changes to the incidents they watch, and only those."""

import anyio
import pytest
from mcp import Client
from mcp.client.subscriptions import ResourceUpdated

pytestmark = pytest.mark.anyio

CHECKOUT = {
    "title": "Checkout API returning 500 errors",
    "service": "checkout-api",
    "severity": "sev1",
}


async def create(client: Client) -> int:
    result = await client.call_tool("create_incident", CHECKOUT)
    return result.structured_content["id"]


async def next_event(subscription):
    with anyio.fail_after(2):
        return await anext(aiter(subscription))


async def test_update_notifies_incident_subscribers(client: Client):
    incident_id = await create(client)
    uri = f"flarepost://incidents/{incident_id}"

    async with client.listen(resource_subscriptions=[uri]) as subscription:
        await client.call_tool("update_incident", {"incident_id": incident_id, "status": "investigating"})
        event = await next_event(subscription)

    assert isinstance(event, ResourceUpdated)
    assert event.uri == uri


async def test_note_notifies_timeline_subscribers(client: Client):
    incident_id = await create(client)
    uri = f"flarepost://incidents/{incident_id}/timeline"

    async with client.listen(resource_subscriptions=[uri]) as subscription:
        await client.call_tool("add_note", {"incident_id": incident_id, "message": "Rolled back the deploy."})
        event = await next_event(subscription)

    assert isinstance(event, ResourceUpdated)
    assert event.uri == uri


async def test_subscribers_only_hear_about_what_they_asked_for(client: Client):
    watched = await create(client)
    other = await create(client)
    uri = f"flarepost://incidents/{watched}"

    async with client.listen(resource_subscriptions=[uri]) as subscription:
        await client.call_tool("update_incident", {"incident_id": other, "status": "investigating"})
        await client.call_tool("update_incident", {"incident_id": watched, "status": "investigating"})
        event = await next_event(subscription)

    assert event.uri == uri