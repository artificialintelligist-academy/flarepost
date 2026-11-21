"""Flarepost MCP server: creates the server and plugs in every tool, resource and prompt."""

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
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()