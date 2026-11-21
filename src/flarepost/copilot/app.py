"""Connect to Flarepost as an MCP client: show what it offers, or answer a question with an LLM."""

import argparse
import logging
import os
import sys

import anyio
from anthropic import AsyncAnthropic
from mcp import Client, StdioServerParameters

from flarepost.copilot.agent import ask
from flarepost.copilot.elicitation import ask_in_terminal

# Over stdio the server only inherits a minimal allow-list of variables,
# so anything Flarepost needs has to be passed on explicitly. The Anthropic
# key is not on the list: only the copilot talks to the LLM.
PASSTHROUGH_ENV = ("FLAREPOST_DB", "FLAREPOST_SLACK_WEBHOOK_URL")


def server_parameters() -> StdioServerParameters:
    """Launch Flarepost with the same Python, passing on the variables it needs."""
    env = {name: os.environ[name] for name in PASSTHROUGH_ENV if name in os.environ}
    return StdioServerParameters(command=sys.executable, args=["-m", "flarepost"], env=env)


async def describe(client: Client) -> str:
    """A short report of the server, what it offers and its open incidents."""
    tools = await client.list_tools()
    resources = await client.list_resources()
    templates = await client.list_resource_templates()
    prompts = await client.list_prompts()
    page = (await client.call_tool("list_incidents", {"status": "open"})).structured_content

    lines = [
        f"Connected to {client.server_info.name} using protocol {client.protocol_version}",
        "",
        "Tools:      " + ", ".join(tool.name for tool in tools.tools),
        "Resources:  " + ", ".join(str(resource.uri) for resource in resources.resources),
        "Templates:  " + ", ".join(t.uri_template for t in templates.resource_templates),
        "Prompts:    " + ", ".join(prompt.name for prompt in prompts.prompts),
        "",
        "Open incidents:",
    ]
    for incident in page["incidents"]:
        lines.append(
            f"  #{incident['id']} [{incident['severity']}] {incident['title']} ({incident['service']})"
        )
    if not page["incidents"]:
        lines.append("  none")
    return "\n".join(lines)


async def run(question: str | None) -> None:
    async with Client(server_parameters(), elicitation_callback=ask_in_terminal) as client:
        if question is None:
            print(await describe(client))
        else:
            print(await ask(client, AsyncAnthropic(), question))


def main() -> None:
    # Importing Flarepost sets up the SDK's logging at INFO, and the Anthropic SDK
    # logs every HTTP request through the httpx2 logger. Keep only warnings.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="The Flarepost on-call copilot.")
    parser.add_argument("question", nargs="?", help="a question for the copilot; omit it for a report")
    args = parser.parse_args()
    anyio.run(run, args.question)