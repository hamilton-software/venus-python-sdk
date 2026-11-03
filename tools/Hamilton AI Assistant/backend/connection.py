"""Which hamilton-venus MCP server the agent talks to, and which VENUS PC the deck viewer and
status read (Settings > Instrument connection).

- local: the spoke on this PC, started by the agent engine over stdio. It is told to POST
  its status changes (idle / running / error / hold / paused / terminated) to this backend
  (HAMILTON_MCP_HOLD_WEBHOOKS), so the status panel follows it without polling.
- spoke: a network spoke (mcp-guide Mode B) at http://<pc>:8000/mcp with its bearer token.
- hub: a hub (Mode C). Instrument tools are relayed with call_tool_on / broadcast_tool_call;
  the status comes from the hub's own /api/status.json.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from backend.config import BackendConfig
from backend.secret_store import SecretStore
from backend.tool_policy import HUB_SERVER_NAME, SERVER_NAME

SPOKE_EVENTS_PATH = "/api/spoke-events"
WEBHOOKS_ENV = "HAMILTON_MCP_HOLD_WEBHOOKS"  # hamilton_venus_mcp.server.COMMAND_EVENT_WEBHOOKS_ENV
LOCAL_OPERATOR_URL = "http://127.0.0.1:8765/operator"  # the spoke's operator page default


def describe(settings: dict[str, Any]) -> str:
    connection = settings.get("connection", "local")
    if connection == "spoke":
        return f"Network spoke {urlparse(settings.get('spoke_url') or '').hostname or '(not set)'}"
    if connection == "hub":
        return f"Hub {urlparse(settings.get('hub_url') or '').hostname or '(not set)'}"
    return "This PC"


def mcp_server(
    settings: dict[str, Any], config: BackendConfig, tokens: dict[str, SecretStore]
) -> tuple[str, dict[str, Any]]:
    """(server name, the engine's MCP server config) for the chosen connection."""
    connection = settings.get("connection", "local")
    if connection == "local":
        if not config.mcp_server_exe.is_file():
            raise RuntimeError(
                f"The Hamilton MCP server is not installed ({config.mcp_server_exe} is missing). "
                "Re-run the SDK installer with 'Install MCP server for AI agents' ticked."
            )
        webhook = f"http://127.0.0.1:{config.port}{SPOKE_EVENTS_PATH}"
        return SERVER_NAME, {"type": "stdio", "command": str(config.mcp_server_exe), "env": {WEBHOOKS_ENV: webhook}}
    url = settings.get(f"{connection}_url") or ""
    if not url:
        what = "network spoke" if connection == "spoke" else "hub"
        raise RuntimeError(f"Enter the {what}'s address under Settings > Instrument connection.")
    token = tokens[connection].get()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return (SERVER_NAME if connection == "spoke" else HUB_SERVER_NAME), {"type": "http", "url": url, "headers": headers}


def hub_status_url(settings: dict[str, Any]) -> str | None:
    parsed = urlparse(settings.get("hub_url") or "")
    return f"{parsed.scheme}://{parsed.netloc}/api/status.json" if parsed.netloc else None


def hub_dashboard_url(settings: dict[str, Any]) -> str | None:
    parsed = urlparse(settings.get("hub_url") or "")
    return f"{parsed.scheme}://{parsed.netloc}/dashboard" if parsed.netloc else None


def deck_spoke(settings: dict[str, Any], focus: str | None) -> str | None:
    """Hub mode: the spoke whose deck to show -- the one chosen in Settings, else the one the
    assistant is working on."""
    return settings.get("hub_spoke") or focus or None


def deck_host(settings: dict[str, Any], hub_spokes: list[dict[str, Any]] | None = None, focus: str | None = None) -> str | None:
    """The VENUS PC (host name) for the deck viewer and the run state, or None if not known yet.
    The deck_host override only applies to a network spoke or hub: this PC's VENUS is local."""
    connection = settings.get("connection", "local")
    if connection == "local":
        return "localhost"
    if settings.get("deck_host"):
        return settings["deck_host"]
    if connection == "spoke":
        return urlparse(settings.get("spoke_url") or "").hostname
    spoke_id = deck_spoke(settings, focus)
    for spoke in hub_spokes or []:
        if spoke.get("id") == spoke_id:
            return urlparse(str(spoke.get("url") or "")).hostname
    return None
