"""Flarepost MCP server: creates the server and plugs in every tool, resource and prompt."""

import argparse

import uvicorn
from mcp.server import CacheHint, MCPServer

from flarepost import completions
from flarepost.prompts import postmortem
from flarepost.resources import incidents as incident_resources
from flarepost.resources import runbooks
from flarepost.tools import incidents as incident_tools
from flarepost.tools import notify, timeline

mcp = MCPServer(
    "Flarepost",
    cache_hints={
        # These lists only change when we deploy and are the same for every
        # user, so clients may reuse them for five minutes. resources/read is
        # left uncached on purpose: incidents change all the time.
        "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
        "resources/list": CacheHint(ttl_ms=300_000, scope="public"),
        "resources/templates/list": CacheHint(ttl_ms=300_000, scope="public"),
        "prompts/list": CacheHint(ttl_ms=300_000, scope="public"),
    },
)

incident_tools.register(mcp)
timeline.register(mcp)
notify.register(mcp)
runbooks.register(mcp)
incident_resources.register(mcp)
postmortem.register(mcp)
completions.register(mcp)


def main() -> None:
    """Start the server over stdio, or over Streamable HTTP with --http."""
    parser = argparse.ArgumentParser(description="The Flarepost MCP server.")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8000, help="port for --http (default: 8000)")
    args = parser.parse_args()
    if args.http:
        # Only on this machine for now. The app accepts only localhost Host and
        # Origin headers by default, which protects it from DNS rebinding.
        uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()