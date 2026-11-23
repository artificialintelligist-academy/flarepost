"""Share subscription events between Flarepost instances through Redis pub/sub."""

import dataclasses
import json
from collections.abc import Callable

from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)
from redis.asyncio import Redis

CHANNEL = "flarepost:events"
EVENT_TYPES = {
    cls.__name__: cls
    for cls in (ResourceUpdated, ResourcesListChanged, ToolsListChanged, PromptsListChanged)
}


def encode(event: ServerEvent) -> str:
    """Turn an event into JSON so it can travel through Redis."""
    return json.dumps({"type": type(event).__name__, **dataclasses.asdict(event)})


def decode(message: str) -> ServerEvent:
    """Turn JSON from Redis back into the event the SDK expects."""
    data = json.loads(message)
    return EVENT_TYPES[data.pop("type")](**data)


class RedisSubscriptionBus:
    """A SubscriptionBus for several instances: every event goes through Redis to all of them.

    Each instance relays what arrives from Redis to its own in-memory bus,
    which delivers it to the listen streams open in that process.
    """

    def __init__(self, url: str):
        self._redis = Redis.from_url(url, decode_responses=True)
        self._local = InMemorySubscriptionBus()

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish(CHANNEL, encode(event))

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        return self._local.subscribe(listener)

    async def relay(self) -> None:
        """Run while the instance lives, passing every event from Redis to local listeners."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self._local.publish(decode(message["data"]))
        finally:
            await pubsub.aclose()