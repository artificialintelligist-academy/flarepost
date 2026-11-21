"""Connect to Flarepost as an MCP client and show what it offers."""

import os
import sys

import anyio
from mcp import Client, StdioServerParameters

# Over stdio the server only inherits a minimal allow-list of variables,
# so anything Flarepost needs has to be passed on explicitly.
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


async def run() -> None:
    async with Client(server_parameters()) as client:
        print(await describe(client))


def main() -> None:
    anyio.run(run)