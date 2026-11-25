"""Tools to open, find, change and resolve incidents."""

import base64
import json
from contextlib import closing
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import AcceptedElicitation, CancelledElicitation, Context, Elicit, ElicitationResult, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ClientCapabilities, ElicitationCapability, ToolAnnotations
from pydantic import BaseModel, Field, create_model

from flarepost import storage
from flarepost.domain import Incident, IncidentPage, ResolvedIncident, Severity, Status, UpdatedIncident
from flarepost.errors import incident_not_found
from flarepost.resources.incidents import notify_incident_changed
from flarepost.schemas import Description, IncidentId, ResolutionSummary, Service, Title

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
ELICITATION = ClientCapabilities(elicitation=ElicitationCapability())
NO_ANSWER = (
    "The user was asked directly, in a dialog you do not see, and closed it without "
    "answering. Nothing was changed. Ask them in the conversation before trying again."
)
ESCALATION_NOTE = "Escalation to sev1 confirmed by the user"

# Hints for the host, which may use them to decide when to ask the user. A host must
# not trust them, so the real protection stays in the tools that ask the user themselves.
READS = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ADDS = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
CHANGES = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)


class Resolution(BaseModel):
    """What the user confirms, or corrects, before an incident is resolved."""

    summary: ResolutionSummary


class Escalation(BaseModel):
    """What the user is asked before an incident is escalated to sev1."""

    confirm: bool = Field(description="Escalate to sev1? Use it only for a full outage.")


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


async def ask_to_escalate(
    incident_id: int, ctx: Context, severity: Severity | None = None
) -> Escalation | Elicit[Escalation]:
    """Resolver for update_incident. With MRTR it runs again on the retry, so it only reads."""
    with closing(storage.connect()) as conn:
        current = _check_not_resolved(conn, incident_id)
    if not _is_escalation(current, severity):
        return Escalation(confirm=True)  # not an escalation to sev1, nothing to confirm
    _require_elicitation(ctx, "Escalating to sev1")
    return Elicit(
        f'Escalate incident #{incident_id} "{current.title}" from {current.severity} '
        "to sev1? Sev1 means a full outage.",
        Escalation,
    )


async def update_incident(
    incident_id: IncidentId,
    escalation: Annotated[ElicitationResult[Escalation], Resolve(ask_to_escalate)],
    ctx: Context,
    status: Annotated[
        Status | None,
        Field(description="New status: open, investigating or mitigated. To resolve, use resolve_incident."),
    ] = None,
    severity: Annotated[
        Severity | None,
        Field(description="New severity, if the impact turned out bigger or smaller."),
    ] = None,
) -> UpdatedIncident:
    """Change the status, the severity or both of an incident.

    Every change is added to the incident timeline automatically. Escalating
    to sev1 needs the user's confirmation in a dialog; if they do not give it,
    nothing changes and reason says why. To resolve an incident use
    resolve_incident, which also records what fixed it.
    """
    if status is None and severity is None:
        raise ToolError("Nothing to update. Pass a new status, a new severity or both.")
    if status is Status.RESOLVED:
        raise ToolError(
            "To resolve an incident use resolve_incident, which also records what fixed it."
        )
    with closing(storage.connect()) as conn:
        current = _check_not_resolved(conn, incident_id)
        if not (isinstance(escalation, AcceptedElicitation) and escalation.data.confirm):
            reason = _refusal(
                escalation,
                "The user was asked directly, in a dialog you do not see, and said no to "
                "escalating this incident to sev1. Nothing was changed. Do not call "
                f"update_incident again to escalate it; tell the user it stays at {current.severity}.",
            )
            return UpdatedIncident(incident=current, updated=False, reason=reason)
        note = ESCALATION_NOTE if _is_escalation(current, severity) else None
        updated = storage.update_incident(conn, incident_id, status, severity, note)
    await notify_incident_changed(ctx, incident_id)
    return UpdatedIncident(incident=updated, updated=True)


async def ask_for_resolution(
    incident_id: int, summary: str | None, ctx: Context
) -> Elicit[Resolution]:
    """Resolver for resolve_incident. With MRTR it runs again on the retry, so it only reads."""
    with closing(storage.connect()) as conn:
        current = _check_not_resolved(conn, incident_id)
    _require_elicitation(ctx, "Resolving an incident")
    return Elicit(
        f'Resolve incident #{incident_id} "{current.title}"? Check what fixed it: it goes into '
        "the timeline and the postmortem, and a resolved incident can no longer change.",
        _resolution_form(summary),
    )


async def resolve_incident(
    incident_id: IncidentId,
    resolution: Annotated[ElicitationResult[Resolution], Resolve(ask_for_resolution)],
    ctx: Context,
    summary: Annotated[
        ResolutionSummary | None,
        Field(description="What fixed it, if the conversation says. The user sees it and can correct it."),
    ] = None,
) -> ResolvedIncident:
    """Resolve an incident once the service is healthy again, recording what fixed it.

    The user always confirms in a dialog. Pass summary if the conversation
    already says what fixed it: the user sees it written in and can correct
    it. The result includes the resolution that was recorded, because an
    answer given to the server is not shown to you. If resolved is false,
    nothing changed and reason says why.
    """
    if not isinstance(resolution, AcceptedElicitation):
        with closing(storage.connect()) as conn:
            current = _check_not_resolved(conn, incident_id)
        reason = _refusal(
            resolution,
            "The user was asked directly, in a dialog you do not see, and said no to "
            "resolving this incident now. Nothing was changed. Do not call resolve_incident "
            "again for it; tell the user it stays open.",
        )
        return ResolvedIncident(incident=current, resolved=False, reason=reason)
    text = resolution.data.summary
    with closing(storage.connect()) as conn:
        resolved = storage.resolve_incident(conn, incident_id, text)
    await notify_incident_changed(ctx, incident_id)
    return ResolvedIncident(incident=resolved, resolved=True, resolution=text)


def _require_elicitation(ctx: Context, action: str) -> None:
    """Refuse when the user cannot be asked.

    A flag the model could set would not protect anything: a poisoned runbook
    could tell it to set it. Only a dialog the user answers counts.
    """
    if not ctx.session.check_client_capability(ELICITATION):
        raise ToolError(
            f"{action} needs the user's confirmation in a dialog, and this client cannot show one. "
            "Nothing was changed. Tell the user to do it from a client that can ask them."
        )


def _resolution_form(proposal: str | None) -> type[Resolution]:
    """The question to ask, with the model's summary already written in if it gave one."""
    if not proposal:
        return Resolution
    return create_model("Resolution", __base__=Resolution, summary=(ResolutionSummary, proposal))


def _is_escalation(current: Incident, severity: Severity | None) -> bool:
    return severity == Severity.SEV1 and current.severity != Severity.SEV1


def _refusal(answer: ElicitationResult, declined: str) -> str:
    """Why nothing changed: the user said no, or closed the question without choosing."""
    return NO_ANSWER if isinstance(answer, CancelledElicitation) else declined


def _check_not_resolved(conn, incident_id: int) -> Incident:
    incident = storage.get_incident(conn, incident_id)
    if incident is None:
        raise incident_not_found(incident_id)
    if incident.status is Status.RESOLVED:
        raise ToolError(
            f"Incident #{incident_id} is already resolved and can no longer change. "
            "If the problem is back, open a new incident with create_incident."
        )
    return incident


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
    mcp.tool(annotations=ADDS)(create_incident)
    mcp.tool(annotations=READS)(get_incident)
    mcp.tool(annotations=READS)(list_incidents)
    mcp.tool(annotations=CHANGES)(update_incident)
    mcp.tool(annotations=CHANGES)(resolve_incident)