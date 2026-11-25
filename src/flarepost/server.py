"""Flarepost MCP server: creates the server and plugs in every tool, resource and prompt."""

import argparse
import hmac
import os
from contextlib import asynccontextmanager

import anyio
import uvicorn
from mcp.server import CacheHint, MCPServer
from mcp.server.mcpserver import RequestStateSecurity

from flarepost import completions
from flarepost.events import RedisSubscriptionBus
from flarepost.prompts import postmortem
from flarepost.resources import incidents as incident_resources
from flarepost.resources import runbooks
from flarepost.tools import incidents as incident_tools
from flarepost.tools import notify, timeline

REQUEST_STATE_KEY_ENV = "FLAREPOST_REQUEST_STATE_KEY"
REDIS_URL_ENV = "FLAREPOST_REDIS_URL"
TOKEN_ENV = "FLAREPOST_TOKEN"
UNAUTHORIZED = b'{"error": "This server needs an Authorization: Bearer <token> header."}'


def request_state_security() -> RequestStateSecurity | None:
    """Seal MRTR requestState with a key every instance shares, if one is set.

    Without it each process makes up its own key, so a retry that reaches a
    different instance fails with "Invalid or expired requestState".
    """
    key = os.environ.get(REQUEST_STATE_KEY_ENV)
    return RequestStateSecurity(keys=[key]) if key else None


def subscription_bus() -> RedisSubscriptionBus | None:
    """Share subscription events through Redis, if a URL is set.

    Without it the SDK keeps them in memory, which only reaches the listen
    streams open in the same process.
    """
    url = os.environ.get(REDIS_URL_ENV)
    return RedisSubscriptionBus(url) if url else None


BUS = subscription_bus()


@asynccontextmanager
async def lifespan(server: MCPServer):
    """While the server runs, relay events from Redis to this instance's listeners."""
    if BUS is None:
        yield
        return
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(BUS.relay)
        yield
        tasks.cancel_scope.cancel()


mcp = MCPServer(
    "Flarepost",
    cache_hints={
        # These lists only change when we deploy and are the same for every
        # user, so clients may reuse them for five minutes. resources/read is
        # left uncached on purpose: incidents change all the time.
        "tools/list": CacheHint(ttl_ms=300_000, scope="public"),
        "resources/list": CacheHint(ttl_ms=300_000, scope="public"),
        "resources/templates/list": CacheHint(ttl_ms=300_000, scope="public"),
        "prompts/list": CacheHint(ttl_ms=300_000, scope="public"),
    },
    request_state_security=request_state_security(),
    subscriptions=BUS,
    lifespan=lifespan,
)

incident_tools.register(mcp)
timeline.register(mcp)
notify.register(mcp)
runbooks.register(mcp)
incident_resources.register(mcp)
postmortem.register(mcp)
completions.register(mcp)


class RequireToken:
    """Refuse every HTTP request without the shared token, before MCP sees it.

    Over stdio only the process that started the server can talk to it. Over
    HTTP any process on the machine can, so a local server needs a token.
    """

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            # compare_digest takes the same time whatever part of the token is
            # wrong, so timing the answers reveals nothing about it.
            if not hmac.compare_digest(given, self.expected):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
                })
                await send({"type": "http.response.body", "body": UNAUTHORIZED})
                return
        await self.app(scope, receive, send)


def http_app():
    """The Streamable HTTP app. With several workers, uvicorn builds one in each process.

    With FLAREPOST_TOKEN set, every request must carry it; without it, the app is open.
    """
    app = mcp.streamable_http_app()
    token = os.environ.get(TOKEN_ENV)
    return RequireToken(app, token) if token else app


def main() -> None:
    """Start the server over stdio, or over Streamable HTTP with --http."""
    parser = argparse.ArgumentParser(description="The Flarepost MCP server.")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="address for --http to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port for --http (default: 8000)")
    parser.add_argument("--workers", type=int, default=1, help="processes for --http (default: 1)")
    args = parser.parse_args()
    if args.http:
        # --host only changes where uvicorn listens; in a container it must be
        # 0.0.0.0 so Docker can forward the port. The app still accepts only
        # localhost Host and Origin headers, which protects it from DNS rebinding.
        # uvicorn needs the app's import path, not the app, to start workers.
        uvicorn.run(
            "flarepost.server:http_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=args.workers,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()