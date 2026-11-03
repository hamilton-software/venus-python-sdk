"""Thin synchronous wrapper over VENUS's own Web API (v3, ``localhost:42400`` by default).

The SDK's clients start and drive a VENUS method themselves; this module is for looking at, and
controlling, what VENUS is doing regardless of who started it: the run state, the running
method's data, pause / resume / abort, run history, and the system-wide simulation mode.
Everything returns plain JSON-safe data; VENUS's own answers are passed through untouched.

Blocking (``httpx.Client``), so async callers should use ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE_ENV = "HAMILTON_MCP_VENUS_API_BASE"
DEFAULT_API_BASE = "http://localhost:42400/api/vector/v3"
_HEADERS = {"accept": "application/json; x-api-version=3.0"}
_TIMEOUT_S = 10.0


class VenusApiError(RuntimeError):
    """VENUS's Web API could not be reached, or answered with an error."""


def api_base() -> str:
    return os.environ.get(API_BASE_ENV, "").strip().rstrip("/") or DEFAULT_API_BASE


def _request(
    method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None, timeout: float = _TIMEOUT_S
) -> Any:
    url = f"{api_base()}/{path.lstrip('/')}"
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, headers=_HEADERS, params=clean, json=json)
    except httpx.HTTPError as exc:
        raise VenusApiError(f"VENUS Web API not reachable at {url}: {exc}") from exc
    if response.status_code == 204 or not response.content:
        return None
    if response.status_code >= 400:
        raise VenusApiError(f"VENUS Web API {method} {path} -> {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError:
        return response.text.strip().strip('"')


def _run_state_name(value: int) -> str | None:
    try:
        from hamilton_venus.models import RunState

        return RunState.from_api_value(value).name
    except Exception:  # noqa: BLE001 - a name is a convenience, the number is the truth
        return None


# -- run state ---------------------------------------------------------------------------------


def get_run_state() -> dict[str, Any]:
    raw = _request("GET", "execution/run-state")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return {"value": None, "name": None, "raw": raw}
    return {"value": value, "name": _run_state_name(value)}


def get_current_run_data() -> Any:
    """Detailed runtime information for the method running right now, or ``None`` when no
    method is running (VENUS answers 400 "not available" then, which is not an error)."""
    try:
        return _request("GET", "execution/current-run-data")
    except VenusApiError as exc:
        if "not available" in str(exc):
            return None
        raise


def get_loaded_method() -> Any:
    return _request("GET", "execution/loaded-method")


def get_realtime_schedule() -> Any:
    return _request("GET", "execution/realtime-schedule")


# -- control -----------------------------------------------------------------------------------


def pause() -> Any:
    return _request("POST", "execution/pause")


def resume() -> Any:
    return _request("POST", "execution/resume")


def abort() -> Any:
    return _request("POST", "execution/abort")


# -- history -----------------------------------------------------------------------------------


def list_run_history(
    *,
    limit: int = 25,
    offset: int = 0,
    sort_property: str | None = None,
    sort_order: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    run_state: str | None = None,
) -> Any:
    return _request(
        "GET",
        "files/run-history-data",
        params={
            "recordLimit": limit,
            "startOffset": offset,
            "sortProperty": sort_property,
            "sortOrder": sort_order,
            "startDateRange": start_date,
            "endDateRange": end_date,
            "runState": run_state,
        },
    )


def get_run_detail(run_guid: str) -> Any:
    return _request("GET", f"files/detailed-run-data/{run_guid}")


def get_run_trace(run_guid: str | None = None, method_name: str | None = None) -> Any:
    return _request("GET", "files/trace", params={"runGuid": run_guid, "methodName": method_name}, timeout=30.0)


# -- system-wide simulation mode ---------------------------------------------------------------


def get_simulation_mode() -> bool:
    raw = _request("GET", "system/configuration/simulation")
    return raw is True or str(raw).strip().lower() == "true"


def set_simulation_mode(simulate: bool) -> None:
    _request("PUT", "system/configuration/simulation", params={"simulationMode": str(bool(simulate)).lower()})


# -- error handler -------------------------------------------------------------------------------
#
# Every hamilton_venus client registers under the same hardcoded key ("hamiltonvenussdk", see
# _async_instrument_client._ERROR_HANDLER_KEY) -- not per-process, so VENUS itself has no idea
# whether the process that last registered it is still alive. The SDK only unregisters on a
# clean StarClient/VantageClient __aexit__ (see _async_instrument_client.stop());
# instrument_terminate() (used by a script's STOP handling) does not, and neither does a hard
# kill -- so a run that never unwinds its own `with` block cleanly leaves this flag stuck at
# true forever afterward, for every later run, regardless of whether that later run's client
# even wants a callback. Confirmed directly: this is what left a real instrument stuck showing
# no operator dialog after a run was hard-killed. Callers here only ever clear it as their own
# best-effort cleanup on their own run ending (never proactively "steal" it at run start, since
# a different legitimate process could genuinely own it at that moment).

ERROR_HANDLER_KEY = "hamiltonvenussdk"


def get_error_handler_registered() -> bool:
    raw = _request("GET", "error-handler")
    return raw is True or str(raw).strip().lower() == "true"


def clear_error_handler(key: str = ERROR_HANDLER_KEY) -> None:
    """Best-effort: never raises. Safe to call even if nothing is registered, or if this
    process never registered it itself -- see the module note above for why that's the case
    worth handling, not a bug to guard against."""
    try:
        _request("DELETE", "error-handler", json=key)
    except VenusApiError:
        pass
