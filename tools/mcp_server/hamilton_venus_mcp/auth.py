"""Bearer-token check for a network-reachable spoke (streamable-http / sse).

With HAMILTON_MCP_AUTH_TOKEN set, every HTTP request must carry
``Authorization: Bearer <token>`` -- otherwise anyone who can reach the spoke's port could
drive the instrument. Unset, the spoke behaves exactly as before (and warns at startup when
it listens on the network). Only /ping stays open: hub discovery needs it, and it returns no
more than the spoke's name and whether a token is required.

stdio never goes through here: a stdio spoke is a child process of its one client, with no
network endpoint to protect.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

AUTH_TOKEN_ENV = "HAMILTON_MCP_AUTH_TOKEN"

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def configured_token() -> str | None:
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    return token or None


def bearer_matches(header_value: str | None, token: str) -> bool:
    """Constant-time check of an ``Authorization`` header against *token*."""
    if not header_value:
        return False
    scheme, _, supplied = header_value.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.strip().encode(), token.encode())


class BearerTokenMiddleware:
    """ASGI middleware: 401 for any HTTP request without the right bearer token, except the
    paths in *open_paths*. Lifespan and other non-HTTP scopes pass straight through."""

    def __init__(self, app: ASGIApp, token: str, *, open_paths: frozenset[str] = frozenset({"/ping"})) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware needs a non-empty token.")
        self.app = app
        self.token = token
        self.open_paths = open_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") in self.open_paths:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if bearer_matches(headers.get("authorization"), self.token):
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {"error": "unauthorized", "message": "This MCP server requires 'Authorization: Bearer <token>'."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="hamilton-venus-mcp"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
