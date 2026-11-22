"""The tool-calling loop, driven by a scripted fake LLM: no network, no cost."""

from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server import MCPServer

from flarepost.copilot.agent import ask, toolbox

pytestmark = pytest.mark.anyio


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def tool_use(id: str, name: str, input: dict):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class FakeLLM:
    """Replays a script of responses and records every request it receives."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    async def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


def calls(*blocks):
    return SimpleNamespace(stop_reason="tool_use", content=list(blocks))


def answer(value: str):
    return SimpleNamespace(stop_reason="end_turn", content=[text(value)])


async def test_the_model_calls_a_tool_and_gets_the_result(client: Client):
    await client.call_tool(
        "create_incident",
        {"title": "Checkout API returning 500 errors", "service": "checkout-api", "severity": "sev1"},
    )
    llm = FakeLLM(
        calls(tool_use("call-1", "flarepost_list_incidents", {"severity": "sev1"})),
        answer("There is one sev1: #1."),
    )

    reply = await ask(await toolbox({"flarepost": client}), llm, "Any sev1 incidents?", log=lambda _: None)

    assert reply == "There is one sev1: #1."
    tool_names = {tool["name"] for tool in llm.requests[0]["tools"]}
    assert "flarepost_list_incidents" in tool_names
    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["tool_use_id"] == "call-1"
    assert result["is_error"] is False
    assert "Checkout API returning 500 errors" in result["content"]


async def test_tool_errors_go_back_to_the_model(client: Client):
    llm = FakeLLM(
        calls(tool_use("call-1", "flarepost_get_incident", {"incident_id": 999})),
        answer("Incident 999 does not exist."),
    )

    await ask(await toolbox({"flarepost": client}), llm, "Show me incident 999", log=lambda _: None)

    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert "list_incidents" in result["content"]


async def test_each_call_goes_to_the_server_that_owns_the_tool(client: Client):
    github = MCPServer("FakeGitHub")

    @github.tool()
    def list_commits(owner: str, repo: str) -> str:
        return f"{owner}/{repo}: Lower the card gateway timeout to 2 seconds"

    llm = FakeLLM(
        calls(
            tool_use(
                "call-1",
                "github_list_commits",
                {"owner": "artificialintelligist-academy", "repo": "payments-api"},
            )
        ),
        answer("The gateway timeout was lowered to 2 seconds."),
    )
    async with Client(github, raise_exceptions=True) as github_client:
        box = await toolbox({"flarepost": client, "github": github_client})
        await ask(box, llm, "What changed in payments-api?", log=lambda _: None)

    tool_names = {tool["name"] for tool in llm.requests[0]["tools"]}
    assert {"flarepost_list_incidents", "github_list_commits"} <= tool_names
    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is False
    assert "artificialintelligist-academy/payments-api" in result["content"]


async def test_an_unknown_tool_goes_back_to_the_model_as_an_error(client: Client):
    llm = FakeLLM(
        calls(tool_use("call-1", "jira_list_issues", {})),
        answer("I cannot reach Jira."),
    )

    await ask(await toolbox({"flarepost": client}), llm, "Any Jira issues?", log=lambda _: None)

    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert "no tool named jira_list_issues" in result["content"]