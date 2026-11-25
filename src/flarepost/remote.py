"""Reach a running Flarepost over Streamable HTTP, sending its token if it needs one."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp.client.streamable_http import streamable_http_client

TOKEN_ENV = "FLAREPOST_TOKEN"
# Connecting, sending or waiting for a free connection should never take more
# than 30 seconds. A response can stay open much longer while a tool runs and
# reports progress, so reading may take up to 5 minutes.
TIMEOUT = httpx2.Timeout(30, read=300)


@asynccontextmanager
async def remote(url: str) -> AsyncIterator[tuple]:
    """A transport for Client: every request to url carries FLAREPOST_TOKEN, if it is set.

    We create the HTTP client, so we close it: the SDK only closes the clients it creates.
    """
    token = os.environ.get(TOKEN_ENV)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx2.AsyncClient(headers=headers, timeout=TIMEOUT) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            yield streams