"""Tools to tell people about an incident."""

from contextlib import closing
from datetime import UTC, datetime, timedelta

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from flarepost import storage
from flarepost.domain import Incident, StatusUpdateDraft, TimelineEntry
from flarepost.errors import incident_not_found
from flarepost.integrations import slack
from flarepost.resources.incidents import notify_timeline_changed
from flarepost.schemas import DraftId, IncidentId, SlackText

DRAFT_TTL = timedelta(hours=1)


async def post_to_slack(incident_id: IncidentId, message: SlackText, ctx: Context) -> TimelineEntry:
    """Post an update about an incident to the team's Slack channel.

    Use it when people need to know: a new sev1 or sev2, an escalation, a
    mitigation or the resolution. The post is also added to the timeline.
    If the user wants to review the text first, use draft_status_update.
    """
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
        if incident is None:
            raise incident_not_found(incident_id)
        _post(incident, message)
        entry = storage.add_note(conn, incident_id, f"Posted to Slack: {message}")
    await notify_timeline_changed(ctx, incident_id)
    return entry


def draft_status_update(incident_id: IncidentId, message: SlackText) -> StatusUpdateDraft:
    """Start a Slack update about an incident for the user to review before it is sent.

    Nothing is posted yet. Show the user the draft and pass its draft_id to
    revise_status_update, publish_status_update or discard_status_update.
    A draft expires one hour after its last change.
    """
    with closing(storage.connect()) as conn:
        if storage.get_incident(conn, incident_id) is None:
            raise incident_not_found(incident_id)
        return storage.create_draft(conn, incident_id, message, _expiry())


def revise_status_update(draft_id: DraftId, message: SlackText) -> StatusUpdateDraft:
    """Replace the text of a draft. Each change gives it another hour before it expires."""
    with closing(storage.connect()) as conn:
        _live_draft(conn, draft_id)
        return storage.revise_draft(conn, draft_id, message, _expiry())


async def publish_status_update(draft_id: DraftId, ctx: Context) -> TimelineEntry:
    """Post a draft to the team's Slack channel once the user has approved its text.

    The post is also added to the timeline, and the draft is used up: its
    draft_id stops working.
    """
    with closing(storage.connect()) as conn:
        draft = _live_draft(conn, draft_id)
        _post(storage.get_incident(conn, draft.incident_id), draft.message)
        entry = storage.finish_draft(conn, draft_id, f"Posted to Slack: {draft.message}")
    await notify_timeline_changed(ctx, draft.incident_id)
    return entry


def discard_status_update(draft_id: DraftId) -> StatusUpdateDraft:
    """Throw a draft away without posting it, when the user no longer wants to send it."""
    with closing(storage.connect()) as conn:
        draft = _live_draft(conn, draft_id)
        storage.delete_draft(conn, draft_id)
    return draft


def _post(incident: Incident, message: str) -> None:
    text = (
        f"*[{incident.severity.upper()}] #{incident.id} {incident.title}*\n"
        f"`{incident.service}` · {incident.status}\n"
        f"{message}"
    )
    try:
        slack.post_message(text)
    except slack.SlackError as error:
        raise ToolError(
            f"{error} The update was not posted. Tell the user so they can share it another way."
        ) from None


def _expiry() -> datetime:
    return datetime.now(UTC) + DRAFT_TTL


def _live_draft(conn, draft_id: str) -> StatusUpdateDraft:
    draft = storage.get_draft(conn, draft_id)
    if draft is None:
        raise ToolError(
            f"Draft {draft_id} does not exist: it was already published or discarded, or the id "
            "is wrong. Start a new one with draft_status_update."
        )
    if draft.expires_at <= datetime.now(UTC):
        storage.delete_draft(conn, draft_id)
        raise ToolError(
            f"Draft {draft_id} expired at {draft.expires_at:%H:%M} UTC, one hour after its last "
            "change. Start a new one with draft_status_update."
        )
    return draft


def register(mcp: MCPServer) -> None:
    for tool in (
        post_to_slack,
        draft_status_update,
        revise_status_update,
        publish_status_update,
        discard_status_update,
    ):
        mcp.tool()(tool)