"""Flarepost MCP server: creates the server and plugs in every group of tools."""

from mcp.server import CacheHint, MCPServer

from flarepost.tools import incidents, notify, timeline

mcp = MCPServer(
    "Flarepost",
    cache_hints={
        # Our tools are the same for every user and only change when we deploy,
        # so clients may reuse the list for five minutes.
        "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
    },
)

incidents.register(mcp)
timeline.register(mcp)
notify.register(mcp)


def main() -> None:
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()