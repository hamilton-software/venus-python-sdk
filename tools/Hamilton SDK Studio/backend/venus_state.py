"""VENUS's own run state, read from its Vector API on this PC.

Starting a session aborts whatever method VENUS is running -- including one started by the AI
Assistant or another MCP client on the same PC -- so Studio asks before it connects. This is the
same read-only call the AI Assistant's status panel makes.
"""

from __future__ import annotations

from typing import Any

import httpx
from hamilton_venus.models.enums import RunState

VECTOR_API_PORT = 42400
_HEADERS = {"accept": "text/plain; x-api-version=3.0"}
TIMEOUT_S = 4.0

_BUSY = {RunState.RUNNING, RunState.ABORTING, RunState.PAUSING, RunState.PAUSED, RunState.STARTING, RunState.TERMINATING}


def run_state(host: str = "localhost") -> dict[str, Any]:
    """{"run_state", "busy"} for VENUS on *host*, or {"error"} when it cannot be reached."""
    url = f"http://{host}:{VECTOR_API_PORT}/api/vector/v3/execution/run-state"
    try:
        response = httpx.get(url, headers=_HEADERS, timeout=TIMEOUT_S)
        response.raise_for_status()
        state = RunState.from_api_value(int(response.text.strip().strip('"')))
    except (httpx.HTTPError, ValueError):
        return {"error": "VENUS is not reachable"}
    return {"run_state": state.name.lower(), "busy": state in _BUSY}


def deck_loaded(host: str = "localhost") -> bool:
    """Is a deck layout loaded in VENUS? It lists the runtime device once an instrument is
    connected (HTTP 400 until then, even while a session's method is already running) -- the
    same thing the 3D deck viewer waits for before it can show anything."""
    url = f"http://{host}:{VECTOR_API_PORT}/api/v1/vector/devices/runtime"
    try:
        response = httpx.get(url, timeout=TIMEOUT_S)
        if response.status_code != 200:
            return False
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    first = data[0] if isinstance(data, list) and data else data
    return (
        isinstance(first, dict)
        and bool(first.get("deviceId") or first.get("id"))
        and first.get("hasDeckLayout") is not False
    )
