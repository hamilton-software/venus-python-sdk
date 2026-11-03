"""Bearer tokens for the hub: the one it requires from its own MCP clients, and the ones it
sends to spokes that require one.

- HAMILTON_MCP_AUTH_TOKEN: when set, the hub's MCP endpoint (/mcp) needs
  ``Authorization: Bearer <token>`` -- otherwise a protected spoke could still be driven by
  anyone on the network through the hub. The dashboard pages and their /api routes stay open
  (a browser cannot send a bearer header); keep the hub on a trusted network for those.
- HAMILTON_MCP_SPOKE_TOKEN: the token sent to every spoke (each spoke's own
  HAMILTON_MCP_AUTH_TOKEN). HAMILTON_MCP_SPOKE_TOKENS="id1=token1,id2=token2" overrides it
  for particular spokes. Tokens live only in the hub's environment -- never in spokes.json,
  and never passed through a tool call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

AUTH_TOKEN_ENV = "HAMILTON_MCP_AUTH_TOKEN"
SPOKE_TOKEN_ENV = "HAMILTON_MCP_SPOKE_TOKEN"
SPOKE_TOKENS_ENV = "HAMILTON_MCP_SPOKE_TOKENS"

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def configured_token() -> str | None:
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    return token or None


def spoke_token(spoke_id: str) -> str | None:
    """The bearer token to send to *spoke_id*, or None if it needs none."""
    for entry in os.environ.get(SPOKE_TOKENS_ENV, "").split(","):
        sid, sep, token = entry.partition("=")
        if sep and sid.strip() == spoke_id and token.strip():
            return token.strip()
    token = os.environ.get(SPOKE_TOKEN_ENV, "").strip()
    return token or None


def spoke_headers(spoke_id: str | None) -> dict[str, str] | None:
    token = spoke_token(spoke_id) if spoke_id is not None else None
    return {"Authorization": f"Bearer {token}"} if token else None


def callback_key(spoke_id: str) -> str | None:
    """A per-spoke secret for the URL a spoke pushes its events to, so nobody else can post
    fake statuses for it. Derived from a token this hub already holds (its own, or the
    spoke's), so it stays the same across hub restarts. None when no token is configured."""
    secret = configured_token() or spoke_token(spoke_id)
    if not secret:
        return None
    return hmac.new(secret.encode(), f"spoke-events:{spoke_id}".encode(), hashlib.sha256).hexdigest()[:32]


def bearer_matches(header_value: str | None, token: str) -> bool:
    if not header_value:
        return False
    scheme, _, supplied = header_value.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.strip().encode(), token.encode())


class McpBearerMiddleware:
    """ASGI middleware: 401 for a request to the MCP endpoint (paths under *protected_prefixes*:
    /mcp for streamable-http, /sse and /messages for sse) without the right bearer token.
    Everything else -- the dashboard and its /api routes -- passes."""

    def __init__(self, app: ASGIApp, token: str, *, protected_prefixes: tuple[str, ...] = ("/mcp",)) -> None:
        if not token:
            raise ValueError("McpBearerMiddleware needs a non-empty token.")
        self.app = app
        self.token = token
        self.protected_prefixes = protected_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path") or ""
        if scope.get("type") != "http" or not path.startswith(self.protected_prefixes):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if bearer_matches(headers.get("authorization"), self.token):
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {"error": "unauthorized", "message": "This MCP hub requires 'Authorization: Bearer <token>'."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="hamilton-venus-mcp-hub"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
