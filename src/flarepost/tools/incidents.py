"""Tools to open, find, change and resolve incidents."""

import base64
import json
from contextlib import closing
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import AcceptedElicitation, Context, Elicit, ElicitationResult, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, Field

from flarepost import storage
from flarepost.domain import Incident, IncidentPage, ResolvedIncident, Severity, Status
from flarepost.errors import incident_not_found
from flarepost.resources.incidents import notify_incident_changed
from flarepost.schemas import Description, IncidentId, ResolutionSummary, Service, Title

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
ELICITATION = ClientCapabilities(elicitation=ElicitationCapability())


class Resolution(BaseModel):
    """What the user is asked for when the model resolves without a summary."""

    summary: ResolutionSummary


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
        Field(description="New status: open, investigating or mitigated. To resolve, use resolve_incident."),
    ] = None,
    severity: Annotated[
        Severity | None,
        Field(description="New severity, if the impact turned out bigger or smaller."),
    ] = None,
) -> Incident:
    """Change the status, the severity or both of an incident.

    Every change is added to the incident timeline automatically. To resolve
    an incident use resolve_incident, which also records what fixed it.
    """
    if status is None and severity is None:
        raise ToolError("Nothing to update. Pass a new status, a new severity or both.")
    if status is Status.RESOLVED:
        raise ToolError(
            "To resolve an incident use resolve_incident, which also records what fixed it."
        )
    with closing(storage.connect()) as conn:
        _check_not_resolved(conn, incident_id)
        updated = storage.update_incident(conn, incident_id, status, severity)
    await notify_incident_changed(ctx, incident_id)
    return updated


async def ask_for_resolution(
    incident_id: int, summary: str | None, ctx: Context
) -> Resolution | Elicit[Resolution]:
    """Resolver for resolve_incident. With MRTR it runs again on the retry, so it only reads."""
    with closing(storage.connect()) as conn:
        _check_not_resolved(conn, incident_id)
    if summary:
        return Resolution(summary=summary)
    if not ctx.session.check_client_capability(ELICITATION):
        raise ToolError(
            "Resolving needs a summary of what fixed the incident. Ask the user, then call "
            "resolve_incident again with summary."
        )
    return Elicit(
        f"How was incident #{incident_id} fixed? This goes into its timeline and postmortem.",
        Resolution,
    )


async def resolve_incident(
    incident_id: IncidentId,
    resolution: Annotated[ElicitationResult[Resolution], Resolve(ask_for_resolution)],
    ctx: Context,
    summary: Annotated[
        ResolutionSummary | None,
        Field(description="What fixed it, if you know. If omitted, the user is asked."),
    ] = None,
) -> ResolvedIncident:
    """Resolve an incident once the service is healthy again, recording what fixed it.

    Pass summary if the conversation already says what fixed it; otherwise
    the user is asked for it. The result includes the resolution that was
    recorded, because an answer given to the server is not shown to you.
    """
    if not isinstance(resolution, AcceptedElicitation):
        raise ToolError(
            f"Incident #{incident_id} was not resolved: the user did not give a summary."
        )
    text = resolution.data.summary
    with closing(storage.connect()) as conn:
        resolved = storage.resolve_incident(conn, incident_id, text)
    await notify_incident_changed(ctx, incident_id)
    return ResolvedIncident(incident=resolved, resolution=text)


def _check_not_resolved(conn, incident_id: int) -> None:
    incident = storage.get_incident(conn, incident_id)
    if incident is None:
        raise incident_not_found(incident_id)
    if incident.status is Status.RESOLVED:
        raise ToolError(
            f"Incident #{incident_id} is already resolved and can no longer change. "
            "If the problem is back, open a new incident with create_incident."
        )


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
    for tool in (create_incident, get_incident, list_incidents, update_incident, resolve_incident):
        mcp.tool()(tool)