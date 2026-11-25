"""Tools to tell people about an incident."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Annotated

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import AcceptedElicitation, CancelledElicitation, Context, Elicit, ElicitationResult, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from flarepost import storage
from flarepost.domain import Digest, Incident, SlackPost, Status, StatusUpdateDraft
from flarepost.errors import incident_not_found
from flarepost.integrations import slack
from flarepost.resources.incidents import notify_timeline_changed
from flarepost.schemas import DraftId, IncidentId, SlackText
from flarepost.tools.incidents import ADDS, CHANGES, ELICITATION, NO_ANSWER

DRAFT_TTL = timedelta(hours=1)
# Slack accepts about one incoming webhook message per second.
SLACK_INTERVAL_SECONDS = 1.0
# A flag the model could set would not protect anything: a poisoned runbook
# could tell it to set it. Only a dialog the user answers counts.
NO_ELICITATION = (
    "Posting to Slack needs the user's confirmation in a dialog, and this client cannot "
    "show one. Nothing was posted. Give the user the text so they can post it themselves."
)
# Posting adds a message outside Flarepost and cannot be taken back.
POSTS = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
# Publishing also uses up the draft, so it changes Flarepost as well.
PUBLISHES = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)


class Publication(BaseModel):
    """What the user is asked before a message leaves for Slack."""

    confirm: bool = Field(description="Post this message to Slack?")


def ask_before_posting(ctx: Context, incident: Incident, message: str) -> Elicit[Publication]:
    """Show the user the exact text that would be posted, or refuse if they cannot be asked."""
    _require_elicitation(ctx)
    return Elicit(
        f'Post this to Slack about incident #{incident.id} "{incident.title}"?\n\n{message}',
        Publication,
    )


async def ask_to_post(incident_id: int, message: str, ctx: Context) -> Publication | Elicit[Publication]:
    """Resolver for post_to_slack. With MRTR it runs again on the retry, so it only reads."""
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
    if incident is None:
        raise incident_not_found(incident_id)
    return ask_before_posting(ctx, incident, message)


async def post_to_slack(
    incident_id: IncidentId,
    message: SlackText,
    publication: Annotated[ElicitationResult[Publication], Resolve(ask_to_post)],
    ctx: Context,
) -> SlackPost:
    """Post an update about an incident to the team's Slack channel.

    Use it when people need to know: a new sev1 or sev2, an escalation, a
    mitigation or the resolution. The post is also added to the timeline.
    The user always confirms the exact text first; if they do not, nothing is
    posted and reason says why. If the user wants to work on the text first,
    use draft_status_update.
    """
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
        if incident is None:
            raise incident_not_found(incident_id)
        if not _confirmed(publication):
            reason = _refusal(
                publication,
                "The user was asked directly, in a dialog you do not see, and said no to posting "
                "this message. Nothing was posted. Do not post it again; ask the user what to change.",
            )
            return SlackPost(posted=False, reason=reason)
        _post(incident, message)
        entry = storage.add_note(conn, incident_id, f"Posted to Slack: {message}")
    await notify_timeline_changed(ctx, incident_id)
    return SlackPost(posted=True, entry=entry)


async def ask_to_post_digest(ctx: Context) -> Publication | Elicit[Publication]:
    """Resolver for post_incident_digest. With MRTR it runs again on the retry, so it only reads."""
    pending = _pending()
    if not pending:
        return Publication(confirm=True)  # nothing would be posted, nothing to confirm
    _require_elicitation(ctx)
    lines = "\n".join(f"#{incident.id} [{incident.severity}] {incident.title}" for incident in pending)
    return Elicit(
        f"Post the daily digest to Slack? It sends one message for each of these "
        f"{len(pending)} incidents:\n\n{lines}",
        Publication,
    )


async def post_incident_digest(
    publication: Annotated[ElicitationResult[Publication], Resolve(ask_to_post_digest)],
    ctx: Context,
) -> Digest:
    """Post one Slack update for every incident that is not resolved yet, as a daily digest.

    The user confirms the list of incidents first; if they do not, nothing is
    posted and reason says why. It takes about one second per incident,
    because Slack accepts about one message per second, and it reports
    progress after each post. If the call is cancelled, the incidents already
    posted stay posted and recorded in their timelines, and the rest are not
    posted.
    """
    pending = _pending()
    if not _confirmed(publication):
        reason = _refusal(
            publication,
            "The user was asked directly, in a dialog you do not see, and said no to posting the "
            "daily digest. Nothing was posted. Do not post it again unless the user asks for it.",
        )
        return Digest(posted=[], total=len(pending), reason=reason)
    posted: list[int] = []
    for number, incident in enumerate(pending, start=1):
        if number > 1:
            await anyio.sleep(SLACK_INTERVAL_SECONDS)
        message = f"Daily digest: still {incident.status}."
        # Posting and recording run with no await in between, so a
        # cancellation can never leave an incident posted but not recorded.
        with closing(storage.connect()) as conn:
            _post(incident, message)
            storage.add_note(conn, incident.id, f"Posted to Slack: {message}")
        posted.append(incident.id)
        await notify_timeline_changed(ctx, incident.id)
        await ctx.report_progress(number, total=len(pending), message=f"Posted #{incident.id}")
    return Digest(posted=posted, total=len(pending))


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


async def ask_to_publish(draft_id: str, ctx: Context) -> Publication | Elicit[Publication]:
    """Resolver for publish_status_update. With MRTR it runs again on the retry, so it only reads."""
    with closing(storage.connect()) as conn:
        draft = _check_draft(draft_id, storage.get_draft(conn, draft_id))
        incident = storage.get_incident(conn, draft.incident_id)
    return ask_before_posting(ctx, incident, draft.message)


async def publish_status_update(
    draft_id: DraftId,
    publication: Annotated[ElicitationResult[Publication], Resolve(ask_to_publish)],
    ctx: Context,
) -> SlackPost:
    """Post a draft to the team's Slack channel.

    The user confirms the exact text first. If they do, the post is added to
    the timeline and the draft is used up: its draft_id stops working. If they
    do not, nothing is posted, the draft is kept and reason says why.
    """
    with closing(storage.connect()) as conn:
        draft = _live_draft(conn, draft_id)
        if not _confirmed(publication):
            reason = _refusal(
                publication,
                "The user was asked directly, in a dialog you do not see, and said no to posting "
                "this draft. Nothing was posted and the draft is kept. Ask the user what to change.",
            )
            return SlackPost(posted=False, reason=reason)
        _post(storage.get_incident(conn, draft.incident_id), draft.message)
        entry = storage.finish_draft(conn, draft_id, f"Posted to Slack: {draft.message}")
    await notify_timeline_changed(ctx, draft.incident_id)
    return SlackPost(posted=True, entry=entry)


def discard_status_update(draft_id: DraftId) -> StatusUpdateDraft:
    """Throw a draft away without posting it, when the user no longer wants to send it."""
    with closing(storage.connect()) as conn:
        draft = _live_draft(conn, draft_id)
        storage.delete_draft(conn, draft_id)
    return draft


def _require_elicitation(ctx: Context) -> None:
    if not ctx.session.check_client_capability(ELICITATION):
        raise ToolError(NO_ELICITATION)


def _pending() -> list[Incident]:
    """Every incident that is not resolved yet, oldest first: what the digest posts."""
    with closing(storage.connect()) as conn:
        return [i for i in reversed(storage.list_incidents(conn)) if i.status is not Status.RESOLVED]


def _confirmed(answer: ElicitationResult[Publication]) -> bool:
    return isinstance(answer, AcceptedElicitation) and answer.data.confirm


def _refusal(answer: ElicitationResult, declined: str) -> str:
    """Why nothing was posted: the user said no, or closed the question without choosing."""
    return NO_ANSWER if isinstance(answer, CancelledElicitation) else declined


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
    """The draft if it can still be used. An expired one is deleted on the way."""
    draft = storage.get_draft(conn, draft_id)
    if draft is not None and draft.expires_at <= datetime.now(UTC):
        storage.delete_draft(conn, draft_id)
    return _check_draft(draft_id, draft)


def _check_draft(draft_id: str, draft: StatusUpdateDraft | None) -> StatusUpdateDraft:
    """Raise a clear error if the draft is gone or expired. It only reads, so resolvers can use it."""
    if draft is None:
        raise ToolError(
            f"Draft {draft_id} does not exist: it was already published or discarded, or the id "
            "is wrong. Start a new one with draft_status_update."
        )
    if draft.expires_at <= datetime.now(UTC):
        raise ToolError(
            f"Draft {draft_id} expired at {draft.expires_at:%H:%M} UTC, one hour after its last "
            "change. Start a new one with draft_status_update."
        )
    return draft


def register(mcp: MCPServer) -> None:
    mcp.tool(annotations=POSTS)(post_to_slack)
    mcp.tool(annotations=POSTS)(post_incident_digest)
    mcp.tool(annotations=ADDS)(draft_status_update)
    mcp.tool(annotations=CHANGES)(revise_status_update)
    mcp.tool(annotations=PUBLISHES)(publish_status_update)
    mcp.tool(annotations=CHANGES)(discard_status_update)