"""Flarepost MCP server: creates the server and plugs in every tool and resource."""

from mcp.server import CacheHint, MCPServer

from flarepost.resources import runbooks
from flarepost.tools import incidents, notify, timeline

mcp = MCPServer(
    "Flarepost",
    cache_hints={
        # Tools and the list of resources only change when we deploy, and they
        # are the same for every user, so clients may reuse them for five minutes.
        "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
        "resources/list": CacheHint(ttl_ms=300_000, scope="public"),
    },
)

incidents.register(mcp)
timeline.register(mcp)
notify.register(mcp)
runbooks.register(mcp)


def main() -> None:
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()