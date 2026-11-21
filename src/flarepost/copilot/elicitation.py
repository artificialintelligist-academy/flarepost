"""Answer the server's elicitation requests by asking the person at the terminal."""

import anyio
from mcp.client import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult


async def ask_in_terminal(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    """Ask each field of the requested form; an empty answer declines."""
    schema = getattr(params, "requested_schema", None)
    if not schema:
        return ElicitResult(action="decline")

    print(f"\n? {params.message}")
    content = {}
    for name, field in schema.get("properties", {}).items():
        label = field.get("description", name)
        answer = (await anyio.to_thread.run_sync(input, f"  {label}\n  > ")).strip()
        if not answer:
            return ElicitResult(action="decline")
        content[name] = answer
    return ElicitResult(action="accept", content=content)