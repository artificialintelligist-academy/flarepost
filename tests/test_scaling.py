"""Running several instances: shared requestState keys, and events that travel through Redis."""

from mcp.server.mcpserver import RequestStateSecurity
from mcp.server.subscriptions import ResourceUpdated, ToolsListChanged

from flarepost.events import decode, encode
from flarepost.server import request_state_security, subscription_bus


def test_without_a_key_each_instance_makes_its_own(monkeypatch):
    monkeypatch.delenv("FLAREPOST_REQUEST_STATE_KEY", raising=False)

    assert request_state_security() is None


def test_with_a_key_every_instance_seals_with_it(monkeypatch):
    monkeypatch.setenv("FLAREPOST_REQUEST_STATE_KEY", "a" * 64)

    assert isinstance(request_state_security(), RequestStateSecurity)


def test_a_resource_update_survives_the_trip_through_redis():
    event = ResourceUpdated(uri="flarepost://incidents/2/timeline")

    assert decode(encode(event)) == event


def test_a_list_change_survives_the_trip_through_redis():
    assert decode(encode(ToolsListChanged())) == ToolsListChanged()


def test_without_redis_the_sdk_keeps_events_in_memory(monkeypatch):
    monkeypatch.delenv("FLAREPOST_REDIS_URL", raising=False)

    assert subscription_bus() is None