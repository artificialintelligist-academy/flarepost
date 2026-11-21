"""Errors shared by several tools."""

from mcp.server.mcpserver.exceptions import ToolError


def incident_not_found(incident_id: int) -> ToolError:
    return ToolError(
        f"Incident #{incident_id} does not exist. "
        "Find the right id with list_incidents, or open a new incident with create_incident."
    )