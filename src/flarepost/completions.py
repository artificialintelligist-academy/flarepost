"""Argument completion: suggest incident ids while the user types."""

from contextlib import closing

from mcp.server import MCPServer
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from flarepost import storage
from flarepost.resources.incidents import INCIDENT_TEMPLATE, TIMELINE_TEMPLATE

MAX_VALUES = 100  # the spec allows at most 100 suggestions per response
PROMPTS_WITH_INCIDENT_ID = {"write_postmortem"}
TEMPLATES_WITH_INCIDENT_ID = {INCIDENT_TEMPLATE, TIMELINE_TEMPLATE}


async def complete(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    if argument.name != "incident_id" or not _takes_incident_id(ref):
        return None
    prefix = argument.value.strip()
    if prefix and not prefix.isdigit():
        return Completion(values=[])
    with closing(storage.connect()) as conn:
        ids, total = storage.incident_ids_starting_with(conn, prefix, MAX_VALUES)
    return Completion(values=[str(i) for i in ids], total=total, has_more=total > len(ids))


def _takes_incident_id(ref: PromptReference | ResourceTemplateReference) -> bool:
    if isinstance(ref, PromptReference):
        return ref.name in PROMPTS_WITH_INCIDENT_ID
    return ref.uri in TEMPLATES_WITH_INCIDENT_ID


def register(mcp: MCPServer) -> None:
    mcp.completion()(complete)