"""Escalating to sev1 needs the user's confirmation: through MRTR, or in the conversation."""

import pytest
from mcp import Client
from mcp.types import ElicitResult

from flarepost.server import mcp

pytestmark = pytest.mark.anyio

AUTH = {"title": "Login slow for some users", "service": "auth-service", "severity": "sev3"}
CONFIRMED_BY_USER = "Escalation to sev1 confirmed by the user"
CONFIRMED_IN_CONVERSATION = "Escalation to sev1 confirmed in conversation"


async def create(client: Client) -> int:
    return (await client.call_tool("create_incident", AUTH)).structured_content["id"]


async def timeline(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["message"] for entry in result.structured_content["result"]]


async def escalate(client: Client, incident_id: int, **extra):
    return await client.call_tool("update_incident", {"incident_id": incident_id, "severity": "sev1", **extra})


class User:
    """A scripted person who answers the escalation question and remembers being asked."""

    def __init__(self, action: str, confirm: bool = True):
        self.action = action
        self.confirm = confirm
        self.asked: list[str] = []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        if self.action == "accept":
            return ElicitResult(action="accept", content={"confirm": self.confirm})
        return ElicitResult(action=self.action)


def with_user(user: User) -> Client:
    return Client(mcp, raise_exceptions=True, elicitation_callback=user)


async def test_changes_below_sev1_never_ask():
    user = User("accept")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await client.call_tool("update_incident", {"incident_id": incident_id, "severity": "sev2"})

    assert user.asked == []
    assert result.structured_content["updated"] is True
    assert result.structured_content["incident"]["severity"] == "sev2"


async def test_the_user_confirms_through_mrtr_and_it_is_audited():
    user = User("accept")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await escalate(client, incident_id)
        entries = await timeline(client, incident_id)

    assert user.asked == [
        f'Escalate incident #{incident_id} "Login slow for some users" from sev3 to sev1? '
        "Sev1 means a full outage."
    ]
    assert result.structured_content["incident"]["severity"] == "sev1"
    assert entries[-2:] == ["Severity changed from sev3 to sev1", CONFIRMED_BY_USER]


@pytest.mark.parametrize(
    ("action", "confirm", "words"),
    [("accept", False, "said no"), ("decline", True, "said no"), ("cancel", True, "without answering")],
)
async def test_a_refusal_changes_nothing_and_is_not_an_error(action: str, confirm: bool, words: str):
    async with with_user(User(action, confirm)) as client:
        incident_id = await create(client)
        result = await escalate(client, incident_id, status="investigating")
        incident = (await client.call_tool("get_incident", {"incident_id": incident_id})).structured_content

    assert not result.is_error
    assert result.structured_content["updated"] is False
    assert words in result.structured_content["reason"]
    assert (incident["severity"], incident["status"]) == ("sev3", "open")


async def test_the_flag_does_not_skip_the_question():
    user = User("decline")
    async with with_user(user) as client:
        incident_id = await create(client)
        result = await escalate(client, incident_id, confirm_sev1=True)

    assert len(user.asked) == 1
    assert result.structured_content["updated"] is False


async def test_without_elicitation_the_model_must_ask_first(client: Client):
    incident_id = await create(client)

    result = await escalate(client, incident_id)

    assert result.is_error
    assert "confirm_sev1 set to true" in result.content[0].text


async def test_without_elicitation_the_flag_escalates_and_is_audited(client: Client):
    incident_id = await create(client)

    result = await escalate(client, incident_id, confirm_sev1=True)

    assert result.structured_content["incident"]["severity"] == "sev1"
    assert (await timeline(client, incident_id))[-1] == CONFIRMED_IN_CONVERSATION