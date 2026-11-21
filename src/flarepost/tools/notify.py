"""Tools to tell people about an incident."""

from contextlib import closing

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from flarepost import storage
from flarepost.domain import TimelineEntry
from flarepost.errors import incident_not_found
from flarepost.integrations import slack
from flarepost.resources.incidents import notify_timeline_changed
from flarepost.schemas import IncidentId, SlackText


async def post_to_slack(incident_id: IncidentId, message: SlackText, ctx: Context) -> TimelineEntry:
    """Post an update about an incident to the team's Slack channel.

    Use it when people need to know: a new sev1 or sev2, an escalation, a
    mitigation or the resolution. The post is also added to the timeline.
    """
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, incident_id)
        if incident is None:
            raise incident_not_found(incident_id)
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
        entry = storage.add_note(conn, incident_id, f"Posted to Slack: {message}")
    await notify_timeline_changed(ctx, incident_id)
    return entry


def register(mcp: MCPServer) -> None:
    mcp.tool()(post_to_slack)