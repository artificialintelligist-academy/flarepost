"""Incidents as resources: one URI per incident and one per timeline."""

from contextlib import closing

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from flarepost import storage
from flarepost.domain import Incident, TimelineEntry


def incident(incident_id: str) -> Incident:
    """One incident with its current status and severity."""
    number = _parse_id(incident_id)
    with closing(storage.connect()) as conn:
        found = storage.get_incident(conn, number)
    if found is None:
        raise _not_found(incident_id)
    return found


def timeline(incident_id: str) -> list[TimelineEntry]:
    """Everything that happened in one incident, oldest first."""
    number = _parse_id(incident_id)
    with closing(storage.connect()) as conn:
        if storage.get_incident(conn, number) is None:
            raise _not_found(incident_id)
        return storage.get_timeline(conn, number)


def _parse_id(raw: str) -> int:
    if not raw.isdigit() or int(raw) < 1:
        raise _not_found(raw)
    return int(raw)


def _not_found(raw: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"Incident #{raw} does not exist.")


def register(mcp: MCPServer) -> None:
    mcp.resource(
        "flarepost://incidents/{incident_id}",
        name="incident",
        title="Incident",
        mime_type="application/json",
    )(incident)
    mcp.resource(
        "flarepost://incidents/{incident_id}/timeline",
        name="incident-timeline",
        title="Incident timeline",
        mime_type="application/json",
    )(timeline)