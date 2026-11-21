"""The tool-calling loop, driven by a scripted fake LLM: no network, no cost."""

from types import SimpleNamespace

import pytest
from mcp import Client

from flarepost.copilot.agent import ask

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


async def test_the_model_calls_a_tool_and_gets_the_result(client: Client):
    await client.call_tool(
        "create_incident",
        {"title": "Checkout API returning 500 errors", "service": "checkout-api", "severity": "sev1"},
    )
    llm = FakeLLM(
        SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_use("call-1", "list_incidents", {"severity": "sev1"})],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[text("There is one sev1: #1.")]),
    )

    answer = await ask(client, llm, "Any sev1 incidents?", log=lambda _: None)

    assert answer == "There is one sev1: #1."
    tool_names = {tool["name"] for tool in llm.requests[0]["tools"]}
    assert "list_incidents" in tool_names
    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["tool_use_id"] == "call-1"
    assert result["is_error"] is False
    assert "Checkout API returning 500 errors" in result["content"]


async def test_tool_errors_go_back_to_the_model(client: Client):
    llm = FakeLLM(
        SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_use("call-1", "get_incident", {"incident_id": 999})],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[text("Incident 999 does not exist.")]),
    )

    await ask(client, llm, "Show me incident 999", log=lambda _: None)

    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert "list_incidents" in result["content"]