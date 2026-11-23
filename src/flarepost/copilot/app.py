"""Connect to Flarepost as an MCP client: show what it offers, or answer a question with an LLM."""

import argparse
import logging
import os
import sys
from contextlib import AsyncExitStack

import anyio
from anthropic import AsyncAnthropic
from mcp import Client, StdioServerParameters

from flarepost.copilot.agent import GITHUB_NOTE, SYSTEM, ask, toolbox
from flarepost.copilot.elicitation import ask_in_terminal

# Over stdio the server only inherits a minimal allow-list of variables,
# so anything Flarepost needs has to be passed on explicitly. The Anthropic
# key is not on the list: only the copilot talks to the LLM.
PASSTHROUGH_ENV = ("FLAREPOST_DB", "FLAREPOST_SLACK_WEBHOOK_URL")
# Set it to a running server's endpoint, e.g. http://127.0.0.1:8000/mcp.
FLAREPOST_URL_ENV = "FLAREPOST_URL"

GITHUB_TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"
GITHUB_OWNER = os.environ.get("FLAREPOST_GITHUB_OWNER", "artificialintelligist-academy")
# A fixed version, so a new release cannot rename the tools the course relies on.
GITHUB_IMAGE = "ghcr.io/github/github-mcp-server:v2.2.0"


def server_parameters() -> StdioServerParameters:
    """Launch Flarepost with the same Python, passing on the variables it needs."""
    env = {name: os.environ[name] for name in PASSTHROUGH_ENV if name in os.environ}
    return StdioServerParameters(command=sys.executable, args=["-m", "flarepost"], env=env)


def flarepost_server() -> str | StdioServerParameters:
    """Use a running Flarepost over Streamable HTTP if FLAREPOST_URL is set, else start one over stdio."""
    return os.environ.get(FLAREPOST_URL_ENV) or server_parameters()


def github_parameters() -> StdioServerParameters | None:
    """Run GitHub's official MCP server in Docker, read-only and limited to repos and pull requests."""
    token = os.environ.get(GITHUB_TOKEN_ENV)
    if not token:
        return None
    return StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", GITHUB_TOKEN_ENV,
            "-e", "GITHUB_READ_ONLY=1",
            "-e", "GITHUB_TOOLSETS=repos,pull_requests",
            GITHUB_IMAGE,
            # Its logs go to a file inside the container, which --rm throws away.
            "stdio", "--log-file=/tmp/github-mcp-server.log",
        ],
        env={GITHUB_TOKEN_ENV: token},
    )


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
    async with AsyncExitStack() as stack:
        flarepost = await stack.enter_async_context(
            Client(flarepost_server(), elicitation_callback=ask_in_terminal)
        )
        if question is None:
            print(await describe(flarepost))
            return

        clients = {"flarepost": flarepost}
        system = SYSTEM
        github = github_parameters()
        if github is None:
            print(f"(GitHub is not connected: set {GITHUB_TOKEN_ENV} in .env to use it.)")
        else:
            clients["github"] = await stack.enter_async_context(Client(github))
            system += "\n\n" + GITHUB_NOTE.format(owner=GITHUB_OWNER)
        print(await ask(await toolbox(clients), AsyncAnthropic(), question, system=system))


def main() -> None:
    # Importing Flarepost sets up the SDK's logging at INFO, and the Anthropic SDK
    # logs every HTTP request through the httpx2 logger. Keep only warnings.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="The Flarepost on-call copilot.")
    parser.add_argument("question", nargs="?", help="a question for the copilot; omit it for a report")
    args = parser.parse_args()
    anyio.run(run, args.question)