"""Flarepost MCP server."""

from contextlib import closing
from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field, StringConstraints

from flarepost import storage

mcp = MCPServer("Flarepost")

Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=120),
    Field(description="Short summary of what is broken, e.g. 'Checkout API returning 500 errors'."),
]
Service = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{1,62}$"),
    Field(description="Affected service as a lowercase slug, e.g. 'checkout-api'."),
]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=2000),
    Field(description="What is happening, the impact and anything already tried."),
]


@mcp.tool()
def create_incident(
    title: Title,
    service: Service,
    severity: storage.Severity,
    description: Description = "",
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