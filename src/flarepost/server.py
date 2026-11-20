"""Flarepost MCP server."""

from contextlib import closing
from typing import Annotated

from mcp.server import CacheHint, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, StringConstraints

from flarepost import storage

mcp = MCPServer(
    "Flarepost",
    cache_hints={
        # Our tools are the same for every user and only change when we deploy,
        # so clients may reuse the list for five minutes.
        "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
    },
)

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
IncidentId = Annotated[
    int,
    Field(ge=1, description="Numeric id of the incident, e.g. 3."),
]


@mcp.tool()
def create_incident(
    title: Title,
    service: Service,
    severity: storage.Severity,
    description: Description = "",
) -> storage.Incident:
    """Open a new incident for a service that is failing or degraded.

    Use sev1 for a full outage, sev2 for a major degradation, sev3 for a
    partial or minor problem and sev4 for something to watch.
    """
    with closing(storage.connect()) as conn:
        return storage.create_incident(conn, title, service, severity, description)


@mcp.tool()
def get_incident(incident_id: IncidentId) -> storage.Incident:
    """Get the full details of an existing incident by its id."""
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
    if incident is None:
        raise ToolError(
            f"Incident #{incident_id} does not exist. "
            "Find the right id with list_incidents, or open a new incident with create_incident."
        )
    return incident


@mcp.tool()
def list_incidents(
    status: Annotated[
        storage.Status | None,
        Field(description="Only incidents in this status, e.g. 'open'."),
    ] = None,
    service: Annotated[
        str | None,
        Field(description="Only incidents for this service slug, e.g. 'checkout-api'."),
    ] = None,
    severity: Annotated[
        storage.Severity | None,
        Field(description="Only incidents with this severity, e.g. 'sev1'."),
    ] = None,
) -> list[storage.Incident]:
    """List incidents, newest first.

    All filters are optional and combine with AND. Call it with no filters
    to see everything, or use it to find the id of an incident before
    calling get_incident.
    """
    with closing(storage.connect()) as conn:
        return storage.list_incidents(conn, status, service, severity)


def main() -> None:
    """Start the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()