"""Answer the server's elicitation requests by asking the person at the terminal."""

import anyio
from mcp.client import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult


async def ask_in_terminal(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    """Ask each field of the requested form; an empty answer cancels and a no to a yes/no question declines."""
    schema = getattr(params, "requested_schema", None)
    if not schema:
        return ElicitResult(action="decline")

    print(f"\n? {params.message}")
    content = {}
    for name, field in schema.get("properties", {}).items():
        label = field.get("description", name)
        is_bool = field.get("type") == "boolean"
        prompt = f"  {label} [y/n, Enter to skip]\n  > " if is_bool else f"  {label}\n  > "
        answer = (await anyio.to_thread.run_sync(input, prompt)).strip()
        if not answer:
            return ElicitResult(action="cancel")
        if is_bool:
            if answer.lower() not in ("y", "yes"):
                return ElicitResult(action="decline")
            content[name] = True
        else:
            content[name] = answer
    return ElicitResult(action="accept", content=content)