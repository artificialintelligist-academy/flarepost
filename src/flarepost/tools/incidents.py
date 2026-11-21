"""Tools to open, find and change incidents."""

from contextlib import closing
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from flarepost import storage
from flarepost.domain import Incident, Severity, Status
from flarepost.errors import incident_not_found
from flarepost.schemas import Description, IncidentId, Service, Title


def create_incident(
    title: Title,
    service: Service,
    severity: Severity,
    description: Description = "",
) -> Incident:
    """Open a new incident for a service that is failing or degraded.

    Use sev1 for a full outage, sev2 for a major degradation, sev3 for a
    partial or minor problem and sev4 for something to watch.
    """
    with closing(storage.connect()) as conn:
        return storage.create_incident(conn, title, service, severity, description)


def get_incident(incident_id: IncidentId) -> Incident:
    """Get the full details of an existing incident by its id."""
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
    if incident is None:
        raise incident_not_found(incident_id)
    return incident


def list_incidents(
    status: Annotated[
        Status | None,
        Field(description="Only incidents in this status, e.g. 'open'."),
    ] = None,
    service: Annotated[
        str | None,
        Field(description="Only incidents for this service slug, e.g. 'checkout-api'."),
    ] = None,
    severity: Annotated[
        Severity | None,
        Field(description="Only incidents with this severity, e.g. 'sev1'."),
    ] = None,
) -> list[Incident]:
    """List incidents, newest first.

    All filters are optional and combine with AND. Call it with no filters
    to see everything, or use it to find the id of an incident before
    calling get_incident.
    """
    with closing(storage.connect()) as conn:
        return storage.list_incidents(conn, status, service, severity)


def update_incident(
    incident_id: IncidentId,
    status: Annotated[
        Status | None,
        Field(description="New status. Incidents usually move open, investigating, mitigated, resolved."),
    ] = None,
    severity: Annotated[
        Severity | None,
        Field(description="New severity, if the impact turned out bigger or smaller."),
    ] = None,
) -> Incident:
    """Change the status, the severity or both of an incident.

    Set status to 'resolved' only once the service is healthy again.
    Every change is added to the incident timeline automatically.
    """
    if status is None and severity is None:
        raise ToolError("Nothing to update. Pass a new status, a new severity or both.")
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
        if incident is None:
            raise incident_not_found(incident_id)
        if incident.status is Status.RESOLVED:
            raise ToolError(
                f"Incident #{incident_id} is already resolved and can no longer change. "
                "If the problem is back, open a new incident with create_incident."
            )
        return storage.update_incident(conn, incident_id, status, severity)


def register(mcp: MCPServer) -> None:
    for tool in (create_incident, get_incident, list_incidents, update_incident):
        mcp.tool()(tool)