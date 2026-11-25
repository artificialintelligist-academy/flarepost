"""Every tool tells the host how it behaves, so the host can decide when to ask the user."""

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio


async def hints(client: Client) -> dict:
    return {tool.name: tool.annotations for tool in (await client.list_tools()).tools}


async def test_every_tool_declares_its_hints(client: Client):
    assert all(annotations is not None for annotations in (await hints(client)).values())


async def test_only_the_reading_tools_are_read_only(client: Client):
    read_only = {name for name, annotations in (await hints(client)).items() if annotations.read_only_hint}
    assert read_only == {"get_incident", "list_incidents", "get_timeline"}


async def test_only_the_slack_tools_reach_the_outside_world(client: Client):
    outside = {name for name, annotations in (await hints(client)).items() if annotations.open_world_hint}
    assert outside == {"post_to_slack", "post_incident_digest", "publish_status_update"}


async def test_the_tools_that_change_or_remove_something_are_destructive(client: Client):
    destructive = {
        name
        for name, annotations in (await hints(client)).items()
        if not annotations.read_only_hint and annotations.destructive_hint
    }
    assert destructive == {
        "update_incident",
        "resolve_incident",
        "revise_status_update",
        "publish_status_update",
        "discard_status_update",
    }