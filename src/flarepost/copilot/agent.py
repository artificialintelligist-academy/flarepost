"""The tool-calling loop: the LLM decides, the MCP client executes."""

import os
from collections.abc import Callable

from mcp import Client, MCPError
from mcp.types import TextContent

MODEL = os.environ.get("FLAREPOST_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 4096
MAX_TURNS = 10

SYSTEM = """\
You are the Flarepost on-call copilot. Use the Flarepost tools to look up and
manage incidents. Never guess facts that a tool can give you. Answer briefly."""


def to_anthropic_tool(tool) -> dict:
    """Translate an MCP tool into the Anthropic API format: same JSON Schema, new field names."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema,
    }


async def ask(
    client: Client,
    llm,
    question: str,
    log: Callable[[str], None] = print,
) -> str:
    """Answer a question, letting the model call Flarepost tools until it is done."""
    tools = [to_anthropic_tool(tool) for tool in (await client.list_tools()).tools]
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(MAX_TURNS):
        response = await llm.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        # Keep the assistant turn exactly as it came, thinking blocks included.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                log(f"→ {block.name} {block.input}")
                results.append(await _run_tool(client, block))
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"No answer after {MAX_TURNS} turns.")


async def _run_tool(client: Client, block) -> dict:
    try:
        result = await client.call_tool(block.name, block.input)
    except MCPError as error:
        return {"type": "tool_result", "tool_use_id": block.id, "content": str(error), "is_error": True}
    text = "\n".join(part.text for part in result.content if isinstance(part, TextContent))
    return {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": result.is_error}