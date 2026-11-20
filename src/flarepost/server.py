"""Flarepost MCP server."""

from contextlib import closing

from mcp.server import MCPServer

from flarepost import storage

mcp = MCPServer("Flarepost")


@mcp.tool()
def create_incident(
    title: str,
    service: str,
    severity: storage.Severity,
    description: str = "",
) -> str:
    """Open a new incident for a service that is failing or degraded.

    Use sev1 for a full outage, sev2 for a major degradation, sev3 for a
    partial or minor problem and sev4 for something to watch.
    """
    with closing(storage.connect()) as conn:
        incident = storage.create_incident(conn, title, service, severity, description)
    return (
        f"Opened incident #{incident.id} ({incident.severity}) "
        f"for {incident.service}: {incident.title}"
    )


def main() -> None:
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()