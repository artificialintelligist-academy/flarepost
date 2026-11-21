"""Hosts can suggest incident ids while the user fills in a prompt or a template."""

import pytest
from mcp import Client
from mcp.types import PromptReference, ResourceTemplateReference

pytestmark = pytest.mark.anyio

POSTMORTEM = PromptReference(type="ref/prompt", name="write_postmortem")
INCIDENT = ResourceTemplateReference(type="ref/resource", uri="flarepost://incidents/{incident_id}")


async def create_many(client: Client, count: int) -> None:
    for n in range(count):
        await client.call_tool(
            "create_incident",
            {"title": f"Checkout incident number {n}", "service": "checkout-api", "severity": "sev3"},
        )


async def suggest(client: Client, ref, value: str, name: str = "incident_id"):
    result = await client.complete(ref=ref, argument={"name": name, "value": value})
    return result.completion


async def test_suggests_matching_ids_newest_first(client: Client):
    await create_many(client, 12)

    completion = await suggest(client, POSTMORTEM, "1")
    assert completion.values == ["12", "11", "10", "1"]
    assert completion.total == 4
    assert completion.has_more is False


async def test_completes_incident_templates_too(client: Client):
    await create_many(client, 3)

    completion = await suggest(client, INCIDENT, "")
    assert completion.values == ["3", "2", "1"]


async def test_ignores_values_that_are_not_ids(client: Client):
    await create_many(client, 3)

    completion = await suggest(client, POSTMORTEM, "abc")
    assert completion.values == []


async def test_ignores_arguments_it_does_not_know(client: Client):
    await create_many(client, 3)

    completion = await suggest(client, POSTMORTEM, "1", name="service")
    assert completion.values == []