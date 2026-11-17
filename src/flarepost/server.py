"""Flarepost MCP server."""

from mcp.server import MCPServer

mcp = MCPServer("Flarepost")


@mcp.tool()
def hello(name: str) -> str:
    """Say hello and confirm that Flarepost is running."""
    return f"Hello, {name}! Flarepost is up and running."


def main() -> None:
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()