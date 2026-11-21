"""Runbooks as resources: one per service, read from the Markdown files in the package."""

from importlib.resources import files
from importlib.resources.abc import Traversable

from mcp.server import MCPServer

RUNBOOKS = files("flarepost.runbooks")


def register(mcp: MCPServer) -> None:
    runbooks = sorted(
        (path for path in RUNBOOKS.iterdir() if path.name.endswith(".md")),
        key=lambda path: path.name,
    )
    for path in runbooks:
        service = path.name.removesuffix(".md")
        mcp.resource(
            f"flarepost://runbooks/{service}",
            name=f"runbook-{service}",
            title=f"Runbook for {service}",
            description=f"What to check and do when {service} is failing.",
            mime_type="text/markdown",
        )(_reader(path))


def _reader(path: Traversable):
    def read_runbook() -> str:
        return path.read_text(encoding="utf-8")

    return read_runbook