"""Recent VENUS runs and their files, read through the Vector API (this PC or another).

A run's SDK log sits in VENUS's LogFiles folder as ``<method>_<runGuid>_SdkRunLog.json``,
next to ``<method>_<runGuid>_ScriptLines.json`` (Script Manager runs) -- both fetched through
the API's asset endpoint -- while VENUS's own trace comes from its trace endpoint. A VENUS
method that was not run from Python has a trace but no SDK log, so the run list leaves it out.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hamilton_venus.exceptions import VenusError
from hamilton_venus.venus_client import VenusClient

DEFAULT_PORT = 42400
# An SDK log's top-level "reason" sits before its "log" list, within the first few hundred bytes.
_HEAD_BYTES = 4096
_REASON_RE = re.compile(r'"reason"\s*:\s*"([^"]*)"')
# The session_start entry (first in "log") records whether the SDK ran in simulation.
_SIMULATE_RE = re.compile(r'"simulate"\s*:\s*(true|false)')
# Newer VenusClient methods the run list uses when available (see sdk_update_note).
_RUN_LIST_METHODS = ("get_file_asset_head", "get_run_details")
# Pages of VENUS's run history list_runs reads at most per call while skipping trace-only runs.
_MAX_PAGES = 5
# (base URL, run GUID) -> live, from VENUS's run details; a finished run's never changes.
_LIVE_FROM_DETAILS: dict[tuple[str, str], bool | None] = {}


def base_url_for(host: str) -> str:
    """``"localhost"``, ``"pc-name:42400"`` or a full URL -> ``"http://host:port"``."""
    host = (host or "localhost").strip().rstrip("/")
    if "://" not in host:
        host = f"http://{host}"
    scheme, _, rest = host.partition("://")
    if ":" not in rest.split("/", 1)[0]:
        host = f"{scheme}://{rest}:{DEFAULT_PORT}"
    return host


def _run_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_guid": raw.get("runGuid"),
        "method": raw.get("methodDisplayName"),
        "method_path": raw.get("methodName"),
        "started_at": raw.get("startTime"),
        "ended_at": raw.get("endTime"),
        "state": raw.get("runState"),
        "duration_seconds": raw.get("duration"),
        "computer": raw.get("computerName"),
    }


def _is_this_pc(host: str) -> bool:
    hostname = (urlsplit(base_url_for(host)).hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1", socket.gethostname().lower()}


def _outcome_from_head(head: bytes | None) -> str:
    """``"error"``, ``"ok"``, ``"other"`` (any other reason, e.g. a recovered crash log) or
    ``"no_log"``, from the start of an SDK log -- its ``reason`` comes before the ``log`` list."""
    if head is None:
        return "no_log"
    match = _REASON_RE.search(head.decode("utf-8", errors="replace"))
    if match is None:
        return "other"
    return {"error": "error", "normal": "ok"}.get(match.group(1), "other")


def _live_from_head(head: bytes | None) -> bool | None:
    """``True`` for a run on the instrument, ``False`` for a simulated one, ``None`` if the
    log head does not say."""
    if head is None:
        return None
    match = _SIMULATE_RE.search(head.decode("utf-8", errors="replace"))
    return None if match is None else match.group(1) == "false"


def _live_from_details(details: dict[str, Any]) -> bool | None:
    flags = [i.get("instrumentSimulation") for i in details.get("instruments") or [] if isinstance(i, dict)]
    flags = [f for f in flags if isinstance(f, bool)]
    return None if not flags else not all(flags)


async def _run_facts(venus: VenusClient, host: str, runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per run: ``outcome`` and ``live``, both from the first few KB of the SDK log
    (``"no_log"`` for a plain VENUS method). A log that says nothing about simulation, or
    could not be read, gets ``live`` from VENUS's own run details."""
    log_files = (await venus.get_system_paths()).get("LogFiles", "")
    local = _is_this_pc(host) and Path(log_files).is_dir()
    limit = asyncio.Semaphore(8)

    async def head_of(name: str) -> tuple[bytes | None, bool]:
        """(head, read_ok); head is None when there is no SDK log."""
        if local:
            try:
                with open(Path(log_files) / name, "rb") as handle:
                    return handle.read(_HEAD_BYTES), True
            except OSError:
                return None, True
        if not hasattr(venus, "get_file_asset_head"):
            return None, False  # an older SDK: see sdk_update_note()
        async with limit:
            try:
                return await venus.get_file_asset_head(f"{log_files}\\{name}", _HEAD_BYTES), True
            except VenusError:
                return None, False

    async def facts(run: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        head, read_ok = await head_of(f"{run['method']}_{run['run_guid']}_SdkRunLog.json")
        if read_ok and head is None:
            return run["run_guid"], {"outcome": "no_log", "live": None}
        outcome = _outcome_from_head(head) if read_ok else "unknown"
        live = _live_from_head(head)
        cache_key = (base_url_for(host), run["run_guid"])
        if live is None and cache_key in _LIVE_FROM_DETAILS:
            live = _LIVE_FROM_DETAILS[cache_key]
        elif live is None and hasattr(venus, "get_run_details"):
            async with limit:
                try:
                    live = _live_from_details(await venus.get_run_details(run["run_guid"]))
                except VenusError:
                    return run["run_guid"], {"outcome": outcome, "live": None}
            if run.get("state") == "Finished":
                _LIVE_FROM_DETAILS[cache_key] = live
        return run["run_guid"], {"outcome": outcome, "live": live}

    pairs = await asyncio.gather(*(facts(r) for r in runs if r.get("run_guid") and r.get("method")))
    return dict(pairs)


async def list_runs(host: str, *, limit: int = 50, offset: int = 1) -> dict[str, Any]:
    """Newest first, the runs that have an SDK log: ``{"runs": [...], "next_offset": int,
    "has_more": bool, "notes": [...]}``. A VENUS method not run from Python (trace only) is
    left out, so this reads further pages of VENUS's history -- up to ``_MAX_PAGES`` --
    until it has ``limit`` runs; ``next_offset`` is where the next call continues.

    Each run carries ``outcome``: ``"error"`` when its SDK log says the run ended in an
    error, ``"ok"``, or ``"other"``/``"unknown"`` (a remote log that could not be read is
    kept); and ``live``: ``True`` when it ran on the instrument, ``False`` in simulation,
    ``None`` if unknown."""
    runs: list[dict[str, Any]] = []
    has_more = False
    async with VenusClient(base_url=base_url_for(host), max_retries=0, timeout=15.0) as venus:
        for _ in range(_MAX_PAGES):
            history = await venus.get_run_history(limit=limit, offset=offset)
            rows = [r for r in history.get("subList") or [] if isinstance(r, dict)]
            page = [_run_row(r) for r in rows]
            facts = await _run_facts(venus, host, page)
            for run in page:
                run.update(facts.get(run["run_guid"], {"outcome": "unknown", "live": None}))
            runs += [run for run in page if run["outcome"] != "no_log"]
            offset += len(rows)
            total = history.get("spanCount") or history.get("cacheTotalCount") or 0
            has_more = bool(rows) and offset <= total
            if not has_more or len(runs) >= limit:
                break
    note = sdk_update_note()
    return {"runs": runs, "next_offset": offset, "has_more": has_more, "notes": [note] if note else []}


def sdk_update_note() -> str | None:
    """Say so when the installed SDK predates the VenusClient methods this module uses --
    e.g. an app reinstalled without "Set up / update VENUS SDK", which updates
    workflow_framework but not the SDK. The run list still works, with less detail."""
    missing = [name for name in _RUN_LIST_METHODS if not hasattr(VenusClient, name)]
    if not missing:
        return None
    return (
        "The installed VENUS Python SDK is older than this viewer (no VenusClient."
        + ", VenusClient.".join(missing)
        + "), so some runs' error and live markers are unknown. Re-run the installer with "
        "\"Set up / update VENUS SDK\" ticked to update it."
    )


async def fetch_run_bundle(host: str, run_guid: str, method: str) -> dict[str, Any]:
    """The SDK log (or ``None``), the script-line timeline (or ``None``) and VENUS's trace
    for one run. ``notes`` says what was not available."""
    notes: list[str] = []
    log: dict[str, Any] | None = None
    line_timeline: list[Any] | None = None
    trace_lines: list[str] = []
    async with VenusClient(base_url=base_url_for(host), max_retries=0, timeout=60.0) as venus:
        log_files = (await venus.get_system_paths()).get("LogFiles", "")
        stem = f"{log_files}\\{method}_{run_guid}"
        try:
            data = json.loads(await venus.get_file_asset(f"{stem}_SdkRunLog.json"))
            log = data if isinstance(data, dict) else None
        except VenusError:
            notes.append("No SDK log for this run (a VENUS method not run from Python, or the log was removed).")
        except ValueError:
            notes.append("The SDK log for this run is not valid JSON.")
        if log is not None:
            try:
                data = json.loads(await venus.get_file_asset(f"{stem}_ScriptLines.json"))
                line_timeline = data if isinstance(data, list) else None
            except (VenusError, ValueError):
                pass  # only Script Manager runs have one
        try:
            trace_lines = await venus.get_trace(method, run_guid)
        except VenusError:
            notes.append("VENUS returned no trace for this run.")
    return {
        "log": log,
        "line_timeline": line_timeline,
        "trace_lines": trace_lines,
        "log_name": f"{method}_{run_guid}_SdkRunLog.json" if log is not None else None,
        "notes": notes,
    }
