"""Slack updates the user reviews first: a draft lives behind an explicit, expiring handle."""

from datetime import timedelta

import pytest
from mcp import Client

from flarepost.integrations import slack
from flarepost.tools import notify

pytestmark = pytest.mark.anyio

PAYMENTS = {"title": "Card payments failing", "service": "payments-api", "severity": "sev2"}


@pytest.fixture
def sent(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(slack, "post_message", messages.append)
    return messages


async def create(client: Client) -> int:
    return (await client.call_tool("create_incident", PAYMENTS)).structured_content["id"]


async def draft(client: Client, incident_id: int, message: str = "Investigating card payment errors.") -> str:
    result = await client.call_tool("draft_status_update", {"incident_id": incident_id, "message": message})
    return result.structured_content["draft_id"]


async def timeline(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["message"] for entry in result.structured_content["result"]]


async def test_drafts_get_opaque_ids_that_cannot_be_guessed(client: Client):
    incident_id = await create(client)

    first, second = await draft(client, incident_id), await draft(client, incident_id)

    assert first != second
    assert first.startswith("drf_") and len(first) == len("drf_") + 22


async def test_nothing_is_posted_until_the_draft_is_published(client: Client, sent: list[str]):
    incident_id = await create(client)

    await draft(client, incident_id)

    assert sent == []
    assert await timeline(client, incident_id) == ["Incident opened as sev2"]


async def test_a_draft_is_revised_and_then_published(client: Client, sent: list[str]):
    incident_id = await create(client)
    draft_id = await draft(client, incident_id)

    await client.call_tool(
        "revise_status_update", {"draft_id": draft_id, "message": "Rolled back the payments deploy."}
    )
    result = await client.call_tool("publish_status_update", {"draft_id": draft_id})

    assert not result.is_error
    assert sent[0].endswith("Rolled back the payments deploy.")
    assert (await timeline(client, incident_id))[-1] == "Posted to Slack: Rolled back the payments deploy."


async def test_a_published_draft_cannot_be_published_again(client: Client, sent: list[str]):
    draft_id = await draft(client, await create(client))
    await client.call_tool("publish_status_update", {"draft_id": draft_id})

    result = await client.call_tool("publish_status_update", {"draft_id": draft_id})

    assert result.is_error
    assert "already published or discarded" in result.content[0].text
    assert len(sent) == 1


async def test_a_discarded_draft_is_gone(client: Client, sent: list[str]):
    draft_id = await draft(client, await create(client))
    await client.call_tool("discard_status_update", {"draft_id": draft_id})

    result = await client.call_tool("publish_status_update", {"draft_id": draft_id})

    assert result.is_error
    assert sent == []


async def test_an_expired_draft_says_it_expired(client: Client, monkeypatch):
    monkeypatch.setattr(notify, "DRAFT_TTL", timedelta(seconds=-1))
    draft_id = await draft(client, await create(client))

    result = await client.call_tool("revise_status_update", {"draft_id": draft_id, "message": "Still looking."})

    assert result.is_error
    assert f"Draft {draft_id} expired" in result.content[0].text
    assert "draft_status_update" in result.content[0].text


async def test_a_failed_publish_keeps_the_draft(client: Client):
    draft_id = await draft(client, await create(client))

    failed = await client.call_tool("publish_status_update", {"draft_id": draft_id})
    revised = await client.call_tool("revise_status_update", {"draft_id": draft_id, "message": "Retrying later."})

    assert failed.is_error
    assert "not configured" in failed.content[0].text
    assert not revised.is_error


async def test_drafting_for_a_missing_incident_points_to_list_incidents(client: Client):
    result = await client.call_tool("draft_status_update", {"incident_id": 999, "message": "Hello team."})

    assert result.is_error
    assert "list_incidents" in result.content[0].text