"""Entry point: ``python -m hamilton_venus_mcp`` or the ``hamilton-venus-mcp`` console script.

Defaults to stdio -- a local subprocess pipe, spawned by whatever MCP client launches it --
exactly as before. Set HAMILTON_MCP_TRANSPORT=streamable-http (plus, optionally,
HAMILTON_MCP_HOST/HAMILTON_MCP_PORT) to run this as a network-reachable spoke that a
hamilton_venus_mcp_hub instance on another PC can connect to instead.
"""

from __future__ import annotations

import logging
import os

import anyio
from mcp.server.transport_security import TransportSecuritySettings

from hamilton_venus_mcp.auth import AUTH_TOKEN_ENV, BearerTokenMiddleware, configured_token
from hamilton_venus_mcp.memory_profile import start_if_requested as start_memory_profile_if_requested
from hamilton_venus_mcp.script_runs.manager import OPERATOR_TOKEN_ENV, RunManager
from hamilton_venus_mcp.server import close_session_on_exit, mcp, start_operator_ui

_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")

_logger = logging.getLogger("hamilton_venus_mcp")


def _start_operator_page() -> None:
    """Scripts can only run when a human can answer their errors: with the operator token set,
    serve the operator page; without it, say so once at startup instead of on the first refusal."""
    if not RunManager.operator_gate_configured():
        _logger.warning(
            "%s is not set: run_script is disabled (errors during a run need a human operator, "
            "and there is no token for them to answer with).",
            OPERATOR_TOKEN_ENV,
        )
        return
    ui = start_operator_ui()
    if ui.listening:
        _logger.info("Operator page: %s", ui.url)
    else:
        _logger.warning("Operator page could not start (%s); prompts cannot be answered.", ui.error)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    start_memory_profile_if_requested()
    _start_operator_page()

    transport = os.getenv("HAMILTON_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"Unsupported HAMILTON_MCP_TRANSPORT={transport!r}. Use one of {_VALID_TRANSPORTS}.")

    if transport != "stdio":
        mcp.settings.host = os.getenv("HAMILTON_MCP_HOST", mcp.settings.host)
        mcp.settings.port = int(os.getenv("HAMILTON_MCP_PORT", mcp.settings.port))
        # FastMCP() locked transport_security to a loopback-only allowed_hosts list at
        # construction time, based on the *default* host ("127.0.0.1") -- before the
        # override above ever ran. Left as-is, a hub (or any client) reaching this spoke
        # by its LAN IP/hostname gets rejected with 421 Invalid Host header. Re-derive it
        # now that the real bind host is known, same loopback check FastMCP itself uses.
        if mcp.settings.host not in ("127.0.0.1", "localhost", "::1"):
            mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

        token = configured_token()
        if token is not None:
            _serve_with_token(transport, token)
            return
        if mcp.settings.host not in ("127.0.0.1", "localhost", "::1"):
            _logger.warning(
                "%s is not set: anyone who can reach %s:%s can send commands to this instrument. "
                "Set it (and give the same token to the hub / orchestrators) to require a bearer token.",
                AUTH_TOKEN_ENV,
                mcp.settings.host,
                mcp.settings.port,
            )

    if transport == "stdio":
        anyio.run(_run_stdio)
        return
    mcp.run(transport=transport)


async def _run_stdio() -> None:
    """stdio serves one client for the life of the process. When it goes (stdin closed), close
    any session it left open, on the same event loop it ran on. Network transports keep their
    session across MCP connections (a hub reconnects), so they don't do this."""
    try:
        await mcp.run_stdio_async()
    finally:
        await close_session_on_exit()


def _serve_with_token(transport: str, token: str) -> None:
    """mcp.run() for streamable-http / sse, with every request but /ping checked for
    'Authorization: Bearer <token>' (see hamilton_venus_mcp.auth)."""
    import uvicorn

    app = mcp.streamable_http_app() if transport == "streamable-http" else mcp.sse_app()
    _logger.info("Bearer token required on %s:%s (%s is set).", mcp.settings.host, mcp.settings.port, AUTH_TOKEN_ENV)
    uvicorn.run(
        BearerTokenMiddleware(app, token),
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
