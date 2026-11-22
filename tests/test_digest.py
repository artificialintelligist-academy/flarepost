"""The daily digest is a long call: it reports progress and stops cleanly when cancelled."""

import anyio
import pytest
from mcp import Client

from flarepost.integrations import slack
from flarepost.tools import notify

pytestmark = pytest.mark.anyio


@pytest.fixture
def sent(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(slack, "post_message", messages.append)
    return messages


async def create(client: Client, title: str) -> int:
    incident = {"title": title, "service": "payments-api", "severity": "sev2"}
    return (await client.call_tool("create_incident", incident)).structured_content["id"]


async def last_note(client: Client, incident_id: int) -> str:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return result.structured_content["result"][-1]["message"]


async def test_posts_every_open_incident_and_reports_progress(client: Client, sent: list[str], monkeypatch):
    monkeypatch.setattr(notify, "SLACK_INTERVAL_SECONDS", 0)
    first = await create(client, "Card payments failing")
    resolved = await create(client, "Refunds delayed by an hour")
    second = await create(client, "Payment receipts not sent")
    await client.call_tool("resolve_incident", {"incident_id": resolved, "summary": "Restarted the refunds worker."})
    progress: list[tuple[float, float | None]] = []

    async def record(done, total, message):
        progress.append((done, total))

    result = await client.call_tool("post_incident_digest", {}, progress_callback=record)

    assert result.structured_content == {"posted": [first, second], "total": 2}
    assert progress == [(1, 2), (2, 2)]
    assert len(sent) == 2
    assert await last_note(client, first) == "Posted to Slack: Daily digest: still open."


async def test_a_cancelled_digest_keeps_what_it_posted_and_nothing_else(client: Client, sent: list[str], monkeypatch):
    monkeypatch.setattr(notify, "SLACK_INTERVAL_SECONDS", 0.5)
    first = await create(client, "Card payments failing")
    second = await create(client, "Payment receipts not sent")

    with anyio.move_on_after(0.25):
        await client.call_tool("post_incident_digest", {})
    await anyio.sleep(0.5)

    assert len(sent) == 1
    assert await last_note(client, first) == "Posted to Slack: Daily digest: still open."
    assert await last_note(client, second) == "Incident opened as sev2"


async def test_with_nothing_open_the_digest_posts_nothing(client: Client, sent: list[str]):
    result = await client.call_tool("post_incident_digest", {})

    assert result.structured_content == {"posted": [], "total": 0}
    assert sent == []