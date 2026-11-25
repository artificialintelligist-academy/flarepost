"""The Game Day scoreboard measures the team from the incident timeline."""

import pytest
from mcp import Client

from flarepost.gameday import SERVICE, TITLE, scoreboard

pytestmark = pytest.mark.anyio


async def test_the_scoreboard_marks_what_was_done_and_what_was_missed(confirming_client: Client):
    client = confirming_client
    incident = (
        await client.call_tool("create_incident", {"title": TITLE, "service": SERVICE, "severity": "sev3"})
    ).structured_content
    incident_id = incident["id"]
    await client.call_tool("update_incident", {"incident_id": incident_id, "status": "investigating"})
    await client.call_tool("update_incident", {"incident_id": incident_id, "severity": "sev1"})
    await client.call_tool("update_incident", {"incident_id": incident_id, "status": "mitigated"})

    rows = await scoreboard(client, incident_id)

    assert rows == {
        "Started investigating": "00:00",
        "Escalated to sev1": "00:00",
        "Told the team on Slack": "missed",
        "Mitigated": "00:00",
    }