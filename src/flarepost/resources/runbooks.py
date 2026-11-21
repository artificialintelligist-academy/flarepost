"""Runbooks as resources: one per service, read from the Markdown files in the package."""

from importlib.resources import files
from importlib.resources.abc import Traversable

from mcp.server import MCPServer

RUNBOOKS = files("flarepost.runbooks")


def runbook_uri(service: str) -> str:
    return f"flarepost://runbooks/{service}"


def runbook_text(service: str) -> str | None:
    """The runbook for a service, or None if the team has not written one."""
    path = RUNBOOKS / f"{service}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def register(mcp: MCPServer) -> None:
    runbooks = sorted(
        (path for path in RUNBOOKS.iterdir() if path.name.endswith(".md")),
        key=lambda path: path.name,
    )
    for path in runbooks:
        service = path.name.removesuffix(".md")
        mcp.resource(
            runbook_uri(service),
            name=f"runbook-{service}",
            title=f"Runbook for {service}",
            description=f"What to check and do when {service} is failing.",
            mime_type="text/markdown",
        )(_reader(path))


def _reader(path: Traversable):
    def read_runbook() -> str:
        return path.read_text(encoding="utf-8")

    return read_runbook