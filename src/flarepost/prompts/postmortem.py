"""A prompt that turns an incident and its timeline into a blameless postmortem."""

from contextlib import closing
from typing import Annotated

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver import Message, UserMessage
from mcp.types import INVALID_PARAMS, EmbeddedResource, TextResourceContents
from pydantic import Field, TypeAdapter

from flarepost import storage
from flarepost.domain import Incident, TimelineEntry
from flarepost.resources.incidents import incident_uri, timeline_uri
from flarepost.resources.runbooks import runbook_text, runbook_uri

INSTRUCTIONS = """\
Write a blameless postmortem for the incident above, using only the facts in
its timeline. Use these Markdown sections:

1. Summary: two or three sentences.
2. Impact: what was affected and for how long.
3. Timeline: the key moments, with times in UTC.
4. Root cause.
5. What went well.
6. What went wrong.
7. Action items: each with an owner role and a priority.

Do not invent numbers or events that are not in the timeline. If something is
unknown, say so. Focus on systems and processes, never on people."""


def write_postmortem(
    incident_id: Annotated[str, Field(description="Id of the incident, e.g. 8.")],
) -> list[Message]:
    """Draft a blameless postmortem from an incident, its timeline and its runbook."""
    number = int(incident_id) if incident_id.isdigit() else 0
    with closing(storage.connect()) as conn:
        incident = storage.get_incident(conn, number)
        if incident is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Incident #{incident_id} does not exist.")
        timeline = storage.get_timeline(conn, number)

    messages: list[Message] = [
        _embed(incident_uri(number), "application/json", _json(Incident, incident)),
        _embed(timeline_uri(number), "application/json", _json(list[TimelineEntry], timeline)),
    ]
    runbook = runbook_text(incident.service)
    if runbook is not None:
        messages.append(_embed(runbook_uri(incident.service), "text/markdown", runbook))
    messages.append(UserMessage(INSTRUCTIONS))
    return messages


def _embed(uri: str, mime_type: str, text: str) -> UserMessage:
    contents = TextResourceContents(uri=uri, mime_type=mime_type, text=text)
    return UserMessage(EmbeddedResource(type="resource", resource=contents))


def _json(kind, value) -> str:
    return TypeAdapter(kind).dump_json(value, indent=2).decode()


def register(mcp: MCPServer) -> None:
    mcp.prompt(title="Write a postmortem")(write_postmortem)