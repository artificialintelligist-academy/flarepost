"""Resolving needs a summary: from the model, or from the user through MRTR."""

import pytest
from mcp import Client
from mcp.types import ElicitResult

from flarepost.server import mcp

pytestmark = pytest.mark.anyio

CHECKOUT = {"title": "Checkout API returning 500 errors", "service": "checkout-api", "severity": "sev1"}


async def create(client: Client) -> int:
    return (await client.call_tool("create_incident", CHECKOUT)).structured_content["id"]


async def timeline(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["message"] for entry in result.structured_content["result"]]


class User:
    """A scripted person who answers elicitation requests and remembers being asked."""

    def __init__(self, action: str, summary: str = ""):
        self.action = action
        self.summary = summary
        self.asked: list[str] = []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        if self.action == "accept":
            return ElicitResult(action="accept", content={"summary": self.summary})
        return ElicitResult(action=self.action)


async def test_summary_from_the_model_resolves_without_asking(client: Client):
    incident_id = await create(client)

    result = await client.call_tool(
        "resolve_incident", {"incident_id": incident_id, "summary": "Rolled back v2.31.0."}
    )

    assert result.structured_content["incident"]["status"] == "resolved"
    assert result.structured_content["resolution"] == "Rolled back v2.31.0."
    assert (await timeline(client, incident_id))[-1] == "Resolution: Rolled back v2.31.0."


async def test_without_elicitation_the_model_is_asked_for_the_summary(client: Client):
    incident_id = await create(client)

    result = await client.call_tool("resolve_incident", {"incident_id": incident_id})

    assert result.is_error
    assert "call resolve_incident again with summary" in result.content[0].text


async def test_the_user_is_asked_through_mrtr_and_the_model_sees_the_answer():
    user = User("accept", "Rolled back v2.31.0 and the error rate dropped.")
    async with Client(mcp, raise_exceptions=True, elicitation_callback=user) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id})

        assert user.asked == [f"How was incident #{incident_id} fixed? This goes into its timeline and postmortem."]
        assert result.structured_content["incident"]["status"] == "resolved"
        assert result.structured_content["resolution"] == user.summary
        assert (await timeline(client, incident_id))[-1] == f"Resolution: {user.summary}"


async def test_declining_leaves_the_incident_open():
    async with Client(mcp, raise_exceptions=True, elicitation_callback=User("decline")) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id})
        incident = (await client.call_tool("get_incident", {"incident_id": incident_id})).structured_content

    assert result.is_error
    assert "was not resolved" in result.content[0].text
    assert incident["status"] == "open"


async def test_the_user_is_never_asked_about_a_missing_incident():
    user = User("accept", "This answer should never be needed.")
    async with Client(mcp, raise_exceptions=True, elicitation_callback=user) as client:
        result = await client.call_tool("resolve_incident", {"incident_id": 999})

    assert result.is_error
    assert user.asked == []