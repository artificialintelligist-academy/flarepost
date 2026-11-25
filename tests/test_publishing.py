"""Nothing leaves for Slack until the user confirms the exact text in a dialog."""

import pytest
from mcp import Client
from mcp.types import ElicitResult

from flarepost.integrations import slack
from flarepost.server import mcp

pytestmark = pytest.mark.anyio

PAYMENTS = {"title": "Card payments failing", "service": "payments-api", "severity": "sev2"}
LEAK = "#1 sev1 Checkout API returning 500 errors | #2 sev2 Login latency above 2 seconds"


class User:
    """A scripted person who answers the Slack question and remembers what they were shown."""

    def __init__(self, action: str, confirm: bool = True):
        self.action = action
        self.confirm = confirm
        self.asked: list[str] = []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        if self.action == "accept":
            return ElicitResult(action="accept", content={"confirm": self.confirm})
        return ElicitResult(action=self.action)


@pytest.fixture
def sent(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(slack, "post_message", messages.append)
    return messages


async def create(client: Client) -> int:
    return (await client.call_tool("create_incident", PAYMENTS)).structured_content["id"]


async def post(client: Client, incident_id: int, message: str = LEAK):
    return await client.call_tool("post_to_slack", {"incident_id": incident_id, "message": message})


async def timeline(client: Client, incident_id: int) -> list[str]:
    result = await client.call_tool("get_timeline", {"incident_id": incident_id})
    return [entry["message"] for entry in result.structured_content["result"]]


async def test_the_user_sees_the_exact_text_before_it_is_posted(sent: list[str]):
    user = User("accept")
    async with Client(mcp, raise_exceptions=True, elicitation_callback=user) as client:
        incident_id = await create(client)
        result = await post(client, incident_id)

    assert user.asked == [f'Post this to Slack about incident #{incident_id} "Card payments failing"?\n\n{LEAK}']
    assert result.structured_content["posted"] is True
    assert len(sent) == 1


@pytest.mark.parametrize(
    ("action", "confirm", "words"),
    [("accept", False, "said no"), ("decline", True, "said no"), ("cancel", True, "without answering")],
)
async def test_a_refusal_posts_nothing_and_is_not_an_error(sent: list[str], action: str, confirm: bool, words: str):
    async with Client(mcp, raise_exceptions=True, elicitation_callback=User(action, confirm)) as client:
        incident_id = await create(client)
        result = await post(client, incident_id)
        entries = await timeline(client, incident_id)

    assert not result.is_error
    assert result.structured_content["posted"] is False
    assert words in result.structured_content["reason"]
    assert sent == []
    assert entries == ["Incident opened as sev2"]


async def test_without_a_dialog_nothing_is_posted(client: Client, sent: list[str]):
    incident_id = await create(client)

    result = await post(client, incident_id)

    assert result.is_error
    assert "Nothing was posted" in result.content[0].text
    assert sent == []


async def test_a_refused_draft_is_kept(sent: list[str]):
    async with Client(mcp, raise_exceptions=True, elicitation_callback=User("decline")) as client:
        incident_id = await create(client)
        drafted = await client.call_tool("draft_status_update", {"incident_id": incident_id, "message": LEAK})
        draft_id = drafted.structured_content["draft_id"]
        result = await client.call_tool("publish_status_update", {"draft_id": draft_id})
        revised = await client.call_tool("revise_status_update", {"draft_id": draft_id, "message": "Shorter."})

    assert result.structured_content["posted"] is False
    assert "draft is kept" in result.structured_content["reason"]
    assert not revised.is_error
    assert sent == []