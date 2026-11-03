"""Entry point: ``python -m hamilton_venus_mcp_hub`` or the ``hamilton-venus-mcp-hub``
console script.

HAMILTON_MCP_SPOKES=id1=url1,id2=url2,... (each url pointing at a hamilton_venus_mcp spoke's
streamable-http endpoint, e.g. http://192.168.1.11:8000/mcp) pre-configures spokes at startup,
but it's optional -- unset or blank, the hub starts with whatever spokes were persisted from a
previous session (see hamilton_venus_mcp_hub.spoke_store), or zero if there's no persisted file
yet, and they're added at runtime instead, via the add_spoke tool, discover_spokes (scans the
network for one instead of typing its URL by hand), or the dashboard's "Add spoke"/"Search for
spokes" UI (see hamilton_venus_mcp_hub.spokes.spokes_from_env and _merged_startup_spokes below).
A spoke sourced from HAMILTON_MCP_SPOKES always wins over a persisted entry with the same id, and
is itself never persisted. Runs over streamable-http by default (a hub is only useful if it's
network-reachable) -- override with HAMILTON_MCP_TRANSPORT/HAMILTON_MCP_HOST/HAMILTON_MCP_PORT
the same way hamilton_venus_mcp's own __main__ does.

Connects every spoke before serving, in its own asyncio.run() rather than FastMCP's own
mcp.run()/lifespan= mechanism -- FastMCP's lifespan is scoped to each *client session
connecting to this hub* (entered/exited per MCP session), not to the hub process's own
startup/shutdown, so it's the wrong hook for "connect once when the hub starts."
"""

from __future__ import annotations

import asyncio
import logging
import os

from mcp.server.transport_security import TransportSecuritySettings

from hamilton_venus_mcp_hub import server as hub_server
from hamilton_venus_mcp_hub import spoke_store
from hamilton_venus_mcp_hub.auth import AUTH_TOKEN_ENV, McpBearerMiddleware, configured_token
from hamilton_venus_mcp_hub.server import mcp, poll_spoke_states, run_state_poller, set_spokes
from hamilton_venus_mcp_hub.spokes import SpokeConfig, SpokeGroup, spokes_from_env

_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def _merged_startup_spokes() -> tuple[list[SpokeConfig], frozenset[str]]:
    """HAMILTON_MCP_SPOKES (scripted/pinned deployments) plus whatever was persisted from a
    previous runtime add_spoke/discovery-connect (see spoke_store). On an id collision the
    env var wins -- it's the operator's explicit, deliberate signal for this particular
    launch, over whatever a previous session happened to save. Returns the merged list plus
    which ids came from the env var, so SpokeGroup knows never to persist those (see its
    own env_ids parameter)."""
    persisted = {d["id"]: SpokeConfig(id=d["id"], url=d["url"]) for d in spoke_store.load()}
    env = {s.id: s for s in spokes_from_env()}
    return list({**persisted, **env}.values()), frozenset(env)


async def _async_main(transport: str, spokes: SpokeGroup) -> None:
    await spokes.connect_all()
    await poll_spoke_states()
    # Keeps every spoke's idle/running/error state fresh for list_spokes and the dashboard.
    state_poller = asyncio.create_task(run_state_poller(), name="spoke-state-poller")
    try:
        token = configured_token() if transport != "stdio" else None
        if transport == "stdio":
            await mcp.run_stdio_async()
        elif token is not None:
            await _serve_with_token(transport, token)
        elif transport == "sse":
            await mcp.run_sse_async()
        else:
            await mcp.run_streamable_http_async()
    finally:
        state_poller.cancel()
        await asyncio.gather(state_poller, return_exceptions=True)
        await spokes.aclose()


_logger = logging.getLogger("hamilton_venus_mcp_hub")


async def _serve_with_token(transport: str, token: str) -> None:
    """mcp.run_*_async(), with the MCP endpoint (/mcp) requiring 'Authorization: Bearer
    <token>' (see hamilton_venus_mcp_hub.auth). The dashboard and its /api routes stay open."""
    import uvicorn

    app = mcp.streamable_http_app() if transport == "streamable-http" else mcp.sse_app()
    protected = ("/mcp",) if transport == "streamable-http" else ("/sse", "/messages")
    _logger.info("Bearer token required on the hub's MCP endpoint %s (%s is set).", protected, AUTH_TOKEN_ENV)
    config = uvicorn.Config(
        McpBearerMiddleware(app, token, protected_prefixes=protected),
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    await uvicorn.Server(config).serve()


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    transport = os.getenv("HAMILTON_MCP_TRANSPORT", "streamable-http").strip().lower()
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"Unsupported HAMILTON_MCP_TRANSPORT={transport!r}. Use one of {_VALID_TRANSPORTS}.")

    if transport == "stdio":
        # No HTTP endpoint for spokes to push events to -- the dashboard falls back to polling.
        hub_server.EVENT_PUSH_ENABLED = False
    else:
        mcp.settings.host = os.getenv("HAMILTON_MCP_HOST", mcp.settings.host)
        mcp.settings.port = int(os.getenv("HAMILTON_MCP_PORT", mcp.settings.port))
        # FastMCP() locked transport_security to a loopback-only allowed_hosts list at
        # construction time, based on the *default* host ("127.0.0.1") -- before the
        # override above ever ran. Left as-is, any client reaching this hub by its LAN
        # IP/hostname (the whole point of a hub) gets rejected with 421 Invalid Host
        # header. Re-derive it now that the real bind host is known, same loopback
        # check FastMCP itself uses.
        if mcp.settings.host not in ("127.0.0.1", "localhost", "::1"):
            mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    spoke_configs, env_ids = _merged_startup_spokes()
    spokes = SpokeGroup(spoke_configs, spokes_file=spoke_store.default_spokes_file(), env_ids=env_ids)
    set_spokes(spokes)
    asyncio.run(_async_main(transport, spokes))


if __name__ == "__main__":
    main()
