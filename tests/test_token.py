"""Over HTTP, Flarepost refuses any request without the shared token, before MCP sees it."""

import httpx
import pytest

from flarepost import server
from flarepost.server import RequireToken

pytestmark = pytest.mark.anyio

TOKEN = "a" * 64


async def reached(scope, receive, send):
    """Stands in for the MCP app: it only answers if the request got past the token check."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"reached"})


async def post(headers: dict[str, str] | None = None) -> httpx.Response:
    app = RequireToken(reached, TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
        return await http.post("/mcp", headers=headers or {})


async def test_without_a_token_the_request_never_reaches_mcp():
    response = await post()

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.text != "reached"


async def test_a_wrong_token_is_refused():
    response = await post({"Authorization": "Bearer " + "b" * 64})

    assert response.status_code == 401


async def test_the_right_token_goes_through():
    response = await post({"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.text == "reached"


async def test_without_flarepost_token_the_app_is_open(monkeypatch):
    monkeypatch.delenv("FLAREPOST_TOKEN", raising=False)

    assert not isinstance(server.http_app(), RequireToken)


async def test_with_flarepost_token_the_app_needs_it(monkeypatch):
    monkeypatch.setenv("FLAREPOST_TOKEN", TOKEN)

    assert isinstance(server.http_app(), RequireToken)