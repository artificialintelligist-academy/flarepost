"""Resolving always needs the user: they confirm the model's summary, correct it or write it."""

import pytest
from mcp import Client
from mcp.types import ElicitResult

from flarepost.server import mcp

pytestmark = pytest.mark.anyio

CHECKOUT = {"title": "Checkout API returning 500 errors", "service": "checkout-api", "severity": "sev1"}
PROPOSAL = "Rolled back v2.31.0."


async def create(client: Client) -> int:
    return (await client.call_tool("create_incident", CHECKOUT)).structured_content["id"]


async def timeline(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["message"] for entry in result.structured_content["result"]]


def question(incident_id: int) -> str:
    title = CHECKOUT["title"]
    return (
        f'Resolve incident #{incident_id} "{title}"? Check what fixed it: it goes into '
        "the timeline and the postmortem, and a resolved incident can no longer change."
    )


class User:
    """A scripted person who answers elicitation requests and remembers what they were shown."""

    def __init__(self, action: str, summary: str | None = None):
        self.action = action
        self.summary = summary
        self.asked: list[str] = []
        self.offered: list[str | None] = []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        offered = params.requested_schema["properties"]["summary"].get("default")
        self.offered.append(offered)
        if self.action == "accept":
            return ElicitResult(action="accept", content={"summary": self.summary or offered})
        return ElicitResult(action=self.action)


def with_user(user: User) -> Client:
    return Client(mcp, raise_exceptions=True, elicitation_callback=user)


async def test_the_model_summary_is_offered_and_the_user_confirms_it():
    user = User("accept")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id, "summary": PROPOSAL})
        entries = await timeline(client, incident_id)

    assert user.asked == [question(incident_id)]
    assert user.offered == [PROPOSAL]
    assert result.structured_content["resolved"] is True
    assert result.structured_content["incident"]["status"] == "resolved"
    assert result.structured_content["resolution"] == PROPOSAL
    assert entries[-1] == f"Resolution: {PROPOSAL}"


async def test_the_user_can_correct_the_summary():
    user = User("accept", "Rolled back v2.31.0 and drained the stuck payment queue.")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id, "summary": PROPOSAL})
        entries = await timeline(client, incident_id)

    assert user.offered == [PROPOSAL]
    assert result.structured_content["resolution"] == user.summary
    assert entries[-1] == f"Resolution: {user.summary}"


async def test_without_a_summary_the_user_writes_it():
    user = User("accept", "Rolled back v2.31.0 and the error rate dropped.")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id})

    assert user.offered == [None]
    assert result.structured_content["resolved"] is True
    assert result.structured_content["resolution"] == user.summary


@pytest.mark.parametrize(("action", "words"), [("decline", "said no"), ("cancel", "without answering")])
async def test_a_refusal_leaves_the_incident_open_and_is_not_an_error(action: str, words: str):
    async with with_user(User(action)) as client:
        incident_id = await create(client)
        result = await client.call_tool("resolve_incident", {"incident_id": incident_id, "summary": PROPOSAL})
        incident = (await client.call_tool("get_incident", {"incident_id": incident_id})).structured_content

    assert not result.is_error
    assert result.structured_content["resolved"] is False
    assert words in result.structured_content["reason"]
    assert incident["status"] == "open"


async def test_without_elicitation_nothing_is_resolved(client: Client):
    incident_id = await create(client)

    result = await client.call_tool("resolve_incident", {"incident_id": incident_id, "summary": PROPOSAL})
    incident = (await client.call_tool("get_incident", {"incident_id": incident_id})).structured_content

    assert result.is_error
    assert "cannot show one" in result.content[0].text
    assert incident["status"] == "open"


async def test_the_user_is_never_asked_about_a_missing_incident():
    user = User("accept", "This answer should never be needed.")
    async with with_user(user) as client:
        result = await client.call_tool("resolve_incident", {"incident_id": 999})

    assert result.is_error
    assert user.asked == []