"""What the status panel shows besides the conversation's own sessions: VENUS's run state on
the instrument PC (Vector API, the same port 42400 the deck viewer uses) and, through a hub,
the fleet's status (the hub's /api/status.json). Both are read on demand with short timeouts
and cached for a moment, so the page can poll without loading VENUS or the hub.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from hamilton_venus.models.enums import RunState

VECTOR_API_PORT = 42400
_VECTOR_API_HEADERS = {"accept": "text/plain; x-api-version=3.0"}
CACHE_S = 1.5
TIMEOUT_S = 4.0  # VENUS can be slow to answer while it is busy

# The spoke status words and the instrument's front light for each (mcp-guide, section 6).
STATUS_LIGHT = {"idle": "white", "running": "green", "error": "red", "hold": "blue", "paused": None, "terminated": "off"}

_BUSY = {RunState.RUNNING, RunState.ABORTING, RunState.PAUSING, RunState.PAUSED, RunState.STARTING, RunState.TERMINATING}
# What VENUS run control's state means to a person at the instrument.
_LABELS = {
    RunState.NOT_INITIALIZED: "Idle",
    RunState.INITIALIZED: "Idle",
    RunState.RUNNING: "Running a method",
    RunState.ABORTING: "Aborting",
    RunState.ABORTED: "Idle (last run aborted)",
    RunState.PROCESSED: "Idle (last run finished)",
    RunState.PAUSING: "Pausing",
    RunState.PAUSED: "Paused",
    RunState.STARTING: "Starting a method",
    RunState.TERMINATING: "Ending a method",
    RunState.TERMINATED: "Idle",
    RunState.UNKNOWN: "Unknown",
}


class _Cached:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._values.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < CACHE_S else None

    def put(self, key: str, value: Any) -> Any:
        self._values[key] = (time.monotonic(), value)
        return value


_cache = _Cached()


async def venus_run_state(host: str | None) -> dict[str, Any] | None:
    """{"host", "run_state" (RunState name, lower case), "label", "busy", "deck"} or {"host", "error"};
    None when there is no host to ask yet. *deck*: VENUS has a deck layout loaded (a runtime
    device) -- the same thing the deck viewer waits for before it can show anything."""
    if not host:
        return None
    key = f"venus:{host}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    url = f"http://{host}:{VECTOR_API_PORT}/api/vector/v3/execution/run-state"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.get(url, headers=_VECTOR_API_HEADERS)
            resp.raise_for_status()
            state = RunState.from_api_value(int(resp.text.strip().strip('"')))
            deck = await _has_deck(client, host)
    except (httpx.HTTPError, ValueError):
        return _cache.put(key, {"host": host, "error": "VENUS is not reachable"})
    return _cache.put(key, {"host": host, "run_state": state.name.lower(), "label": _LABELS[state],
                            "busy": state in _BUSY, "deck": deck})


async def _has_deck(client: httpx.AsyncClient, host: str) -> bool:
    """Is a deck layout loaded? VENUS lists the runtime device once an instrument is connected
    (HTTP 400 until then, even while the session's method is already running)."""
    try:
        resp = await client.get(f"http://{host}:{VECTOR_API_PORT}/api/v1/vector/devices/runtime")
        if resp.status_code != 200:
            return False
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return False
    first = data[0] if isinstance(data, list) and data else data
    return (isinstance(first, dict) and bool(first.get("deviceId") or first.get("id"))
            and first.get("hasDeckLayout") is not False)


async def hub_status(url: str | None) -> dict[str, Any] | None:
    """The hub's spokes and pending interventions, or {"error"}; None without a hub URL."""
    if not url:
        return None
    cached = _cache.get(url)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return _cache.put(url, {"error": "The hub is not reachable", "spokes": []})
    spokes = [
        {k: spoke.get(k) for k in ("id", "url", "connected", "state", "state_detail", "status",
                                   "pending_prompt_count", "session_active")}
        for spoke in (data.get("spokes") or []) if isinstance(spoke, dict)
    ]
    return _cache.put(url, {
        "spokes": spokes,
        "pending_interventions": len(data.get("pending_interventions") or []),
        "operator_gate_configured": bool((data.get("hub") or {}).get("operator_gate_configured")),
    })
