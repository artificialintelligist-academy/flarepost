"""Tools to read and add to an incident timeline."""

from contextlib import closing

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from flarepost import storage
from flarepost.domain import TimelineEntry
from flarepost.errors import incident_not_found
from flarepost.resources.incidents import notify_timeline_changed
from flarepost.schemas import IncidentId, NoteText
from flarepost.tools.incidents import ADDS, READS


async def add_note(incident_id: IncidentId, message: NoteText, ctx: Context) -> TimelineEntry:
    """Add a note to the incident timeline: findings, actions taken or decisions."""
    with closing(storage.connect()) as conn:
        if storage.get_incident(conn, incident_id) is None:
            raise incident_not_found(incident_id)
        entry = storage.add_note(conn, incident_id, message)
    await notify_timeline_changed(ctx, incident_id)
    return entry


def get_timeline(incident_id: IncidentId) -> list[TimelineEntry]:
    """Get everything that happened in an incident, oldest first."""
    with closing(storage.connect()) as conn:
        if storage.get_incident(conn, incident_id) is None:
            raise incident_not_found(incident_id)
        return storage.get_timeline(conn, incident_id)


def register(mcp: MCPServer) -> None:
    mcp.tool(annotations=ADDS)(add_note)
    mcp.tool(annotations=READS)(get_timeline)