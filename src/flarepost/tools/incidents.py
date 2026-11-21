"""Tools to open, find and change incidents."""

import base64
import json
from contextlib import closing
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from flarepost import storage
from flarepost.domain import Incident, IncidentPage, Severity, Status
from flarepost.errors import incident_not_found
from flarepost.resources.incidents import notify_incident_changed
from flarepost.schemas import Description, IncidentId, Service, Title

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


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
    limit: Annotated[
        int,
        Field(ge=1, le=MAX_PAGE_SIZE, description="How many incidents to return in this page."),
    ] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[
        str | None,
        Field(description="The next_cursor from a previous call, to get the following page."),
    ] = None,
) -> IncidentPage:
    """List incidents, newest first, one page at a time.

    All filters are optional and combine with AND. If next_cursor is not
    null there are more incidents: call again with the same filters and
    that cursor. Use it to find the id of an incident before calling
    get_incident.
    """
    before_id = _decode_cursor(cursor) if cursor is not None else None
    with closing(storage.connect()) as conn:
        found = storage.list_incidents(conn, status, service, severity, before_id, limit + 1)
    page = found[:limit]
    has_more = len(found) > limit
    return IncidentPage(
        incidents=page,
        next_cursor=_encode_cursor(page[-1].id) if has_more else None,
    )


async def update_incident(
    incident_id: IncidentId,
    ctx: Context,
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
        updated = storage.update_incident(conn, incident_id, status, severity)
    await notify_incident_changed(ctx, incident_id)
    return updated


def _encode_cursor(before_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"before": before_id}).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        before_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))["before"]
        if not isinstance(before_id, int) or before_id < 1:
            raise ValueError
        return before_id
    except (ValueError, KeyError, TypeError):
        raise ToolError(
            "That cursor is not valid. Call list_incidents without a cursor to start "
            "again from the newest incidents."
        ) from None


def register(mcp: MCPServer) -> None:
    for tool in (create_incident, get_incident, list_incidents, update_incident):
        mcp.tool()(tool)