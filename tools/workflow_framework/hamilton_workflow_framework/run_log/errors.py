"""Error breakdown for root-cause work: the run's outcome, then one incident per failure.

An incident gathers what is otherwise spread across a log: the command that was running
(its channels, positions, volumes), the VENUS error decoded to module / main error / detail,
what each channel reported, the recoveries offered and the one chosen on each attempt
(a *Repeat* that failed again stays in the same incident), the script line, and the
commands, VENUS trace and firmware lines around it. A short hint names the usual causes.

Instrument errors and their chosen recoveries come from ``run_summary.summarize_run`` so the
two views always agree.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any, Iterable

from hamilton_workflow_framework.run_log._common import (
    Command,
    CommandIndex,
    compact_positions,
    entry_time,
    index_commands,
    iso,
    log_entries,
    payload_of,
    run_timezone,
)
from hamilton_workflow_framework.run_log.trace import build_trace
from hamilton_workflow_framework.run_summary import _line_at_timestamp, summarize_run

CONTEXT_BEFORE = timedelta(seconds=10)
CONTEXT_AFTER = timedelta(seconds=2)
CONTEXT_COMMANDS = 5
CONTEXT_LINE_LIMIT = 40

# "P1:08/78", "R0:01/34", "H0:..": module prefix, channel/unit, main error, detail.
_CODE_RE = re.compile(r"(?P<prefix>R0|H0|D0|I0|I1|[PLNW])(?P<unit>[0-9A-Fa-f]?):?\s*(?P<main>\d{2})/(?P<detail>\d{2})")
# A firmware reply that reports an error: "C0TPid0234er99/00 P108/78" (anything but er00/00).
_FIRMWARE_ERROR_RE = re.compile(r"er(?!00/00)\d{2}/\d{2}")

# Usual causes, matched against the decoded/VENUS error text (first match wins).
_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("no tip", "wrong tip", "tip type", "tip not", "tip already", "tip present"),
     "Tip pickup or eject failed. Check that the tip rack is on the deck and not empty, that the tip "
     "counter (tip pool) matches what is really loaded, and that the tip type matches the rack "
     "definition (volume, filter / no filter)."),
    (("not enough liquid", "submerge depth", "liquid following"),
     "Liquid was found, but too little for the aspirate. Check the volume in the well against the "
     "aspirate volume, the submerge depth and liquid following, and the labware definition's heights."),
    (("liquid level not found", "liquid level error", "level detection", "lld"),
     "No liquid surface was detected. Check that the right labware and well were targeted and contain "
     "liquid, the LLD settings in the liquid class (cLLD needs conductive liquid), and the labware "
     "definition's heights."),
    (("clot",),
     "A clot or blockage was detected. Check the sample for clots or particles and the liquid class."),
    (("tadm",),
     "The pressure curve left its TADM tolerance band. Look for bubbles, clots, a missing or loose tip, "
     "or a liquid class whose TADM bands do not fit this liquid."),
    (("barcode",),
     "A barcode could not be read. Check that the label faces the reader and is clean, and the barcode "
     "settings of the carrier or labware."),
    (("cover", "door"),
     "The front cover was open or not locked."),
    (("out of permitted area", "position out", "collision", "step loss", "obstacle", "not reached", "drive"),
     "A move failed or went out of range. Check the deck layout against the real deck (carrier tracks, "
     "sites, labware heights), anything blocking the arm, and taught positions."),
    (("grip", "plate not found", "no plate", "labware not"),
     "A gripper did not find or hold the labware. Check the labware is where the layout says, the grip "
     "height and width, and the gripper fingers."),
)
_GENERIC_HINT = "Read the VENUS trace and firmware lines below, around the time of the error."


@lru_cache(maxsize=1)
def _error_tables() -> dict[str, Any]:
    try:
        text = resources.files("hamilton_venus.error_simulator").joinpath("data/error_simulator.json").read_text(
            encoding="utf-8"
        )
        return json.loads(text)
    except (FileNotFoundError, ModuleNotFoundError, ValueError, OSError):
        return {"modules": [], "tables": {}}


def decode_error_code(code: Any) -> list[dict[str, Any]]:
    """Each ``prefix+unit:main/detail`` segment of *code*, with its module and descriptions
    from the SDK's firmware error tables (STAR first, then Vantage)."""
    if not isinstance(code, str):
        return []
    data = _error_tables()
    # On a STAR "P" is both the X1 and the 1 mL channels; the 1 mL table wins, X1 is the fallback.
    modules = sorted(data.get("modules", []), key=lambda m: m.get("table") == "X1")
    decoded = []
    for match in _CODE_RE.finditer(code):
        prefix, main, detail = match.group("prefix"), match.group("main"), match.group("detail")
        entry: dict[str, Any] = {
            "segment": match.group(0),
            "prefix": prefix,
            "unit": match.group("unit") or None,
            "main": main,
            "detail": detail,
            "module": None,
            "description": None,
        }
        for instrument in ("STAR", "VANTAGE"):
            for module in modules:
                if (module.get("prefix") or {}).get(instrument) != prefix:
                    continue
                table = data.get("tables", {}).get(f"{instrument}-{module.get('table')}", {})
                for row in table.get("error", []):
                    if row.get("code") == detail and row.get("main") == main:
                        entry["module"] = module.get("description")
                        entry["description"] = row.get("description")
                        break
                if entry["description"]:
                    break
            if entry["description"]:
                break
        decoded.append(entry)
    return decoded


def likely_cause(*texts: Any) -> str:
    haystack = " ".join(t for t in texts if isinstance(t, str)).lower()
    for keywords, hint in _HINTS:
        if any(keyword in haystack for keyword in keywords):
            return hint
    return _GENERIC_HINT


def describe_command(command: Command | None, line_timeline: list[Any] | None = None) -> dict[str, Any] | None:
    if command is None:
        return None
    parameters = command.parameters
    channels = parameters.get("channels") if isinstance(parameters.get("channels"), list) else []
    result = "running" if command.response is None else ("success" if command.success else "failed")
    return {
        "command_id": command.command_id,
        "action": command.action,
        "category": command.category,
        "requested_at": iso(command.requested_at),
        "responded_at": iso(command.responded_at),
        "result": result,
        "return_code": (command.response or {}).get("returnCode"),
        "message": command.message,
        "channels": channels,
        "positions": compact_positions(parameters.get("positions")),
        "labware": parameters.get("labwareName") or parameters.get("labwareId"),
        "volumes": parameters.get("volumes", parameters.get("volume")),
        "liquid_class": parameters.get("liquidClass"),
        "tip_pool": parameters.get("tipPool"),
        "parameters": parameters,
        "line": _line_at_timestamp(line_timeline, command.requested_at.timestamp() if command.requested_at else None),
    }


def _window(lines: list[dict[str, Any]], category: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    picked = []
    for line in lines:
        if line["category"] != category or not line["timestamp"]:
            continue
        moment = datetime.fromisoformat(line["timestamp"])
        if start <= moment <= end:
            picked.append({
                "timestamp": line["timestamp"],
                "text": line["text"],
                "highlight": bool(_FIRMWARE_ERROR_RE.search(line["text"])) or "error" in line["text"].lower(),
            })
    if len(picked) > CONTEXT_LINE_LIMIT:
        # Keep the end of the window: the lines right before the error matter most.
        picked = picked[-CONTEXT_LINE_LIMIT:]
    return picked


def _context(
    index: CommandIndex, trace: list[dict[str, Any]], moment: datetime | None, line_timeline: list[Any] | None
) -> dict[str, Any]:
    if moment is None:
        return {"commands": [], "venus": [], "comtrace": []}
    start, end = moment - CONTEXT_BEFORE, moment + CONTEXT_AFTER
    return {
        "commands": [describe_command(c, line_timeline) for c in index.before(moment, CONTEXT_COMMANDS)],
        "venus": _window(trace, "venus", start, end),
        "comtrace": _window(trace, "comtrace", start, end),
    }


def _instrument_error_times(log: dict[str, Any]) -> dict[str, datetime | None]:
    times: dict[str, datetime | None] = {}
    for entry in log_entries(log):
        if entry.get("type") == "instrument_error":
            uuid = payload_of(entry).get("uuid")
            if isinstance(uuid, str) and uuid not in times:
                times[uuid] = entry_time(entry)
    return times


def _offered_recoveries(log: dict[str, Any]) -> dict[str, list[str]]:
    offered: dict[str, list[str]] = {}
    for entry in log_entries(log):
        if entry.get("type") != "instrument_error":
            continue
        payload = payload_of(entry)
        names: list[str] = []
        for source in [payload] + [d for d in payload.get("detailed_errors") or [] if isinstance(d, dict)]:
            for action in source.get("recovery_actions") or []:
                if isinstance(action, dict) and action.get("name") and action["name"] not in names:
                    names.append(action["name"])
        if isinstance(payload.get("uuid"), str):
            offered[payload["uuid"]] = names
    return offered


def _final_command(index: CommandIndex) -> Command | None:
    """The command a failed run stopped in: the last one without a response, else the last failure."""
    for command in reversed(index.commands):
        if command.response is None:
            return command
    for command in reversed(index.commands):
        if command.success is False:
            return command
    return None


def analyze_errors(
    log: dict[str, Any],
    line_timeline: list[Any] | None = None,
    venus_trace_lines: Iterable[str] | None = None,
) -> dict[str, Any]:
    """``{"outcome": {...}, "incidents": [...]}`` for *log*. Never raises on a malformed log."""
    venus_lines = list(venus_trace_lines) if venus_trace_lines is not None else None
    summary = summarize_run(log, line_timeline=line_timeline)
    index = index_commands(log)
    trace = build_trace(log, venus_lines)
    tz = run_timezone(log)
    error_times = _instrument_error_times(log)
    offered = _offered_recoveries(log)

    incidents: list[dict[str, Any]] = []
    by_command: dict[str, dict[str, Any]] = {}

    def incident_for(command: Command | None, moment: datetime | None, key: str) -> dict[str, Any]:
        group_key = command.command_id if command is not None else key
        incident = by_command.get(group_key)
        if incident is None:
            incident = {
                "id": f"incident-{len(incidents) + 1}",
                "kind": None,
                "title": "",
                "first_time": iso(moment),
                "last_time": iso(moment),
                "command": describe_command(command, line_timeline),
                "codes": [],
                "decoded": [],
                "details": [],
                "attempts": [],
                "recoveries_offered": [],
                "line": None,
                "hint": "",
                "context": _context(index, trace, moment, line_timeline),
            }
            incident["line"] = (incident["command"] or {}).get("line")
            by_command[group_key] = incident
            incidents.append(incident)
        elif moment is not None:
            incident["last_time"] = iso(moment)
        return incident

    # 1. Instrument errors, grouped by the command they interrupted.
    seen_uuids: dict[str, dict[str, Any]] = {}
    for error in summary.get("instrument_errors", []):
        uuid = error.get("uuid") or ""
        moment = error_times.get(uuid)
        command = index.active_at(moment)
        incident = incident_for(command, moment, f"error-{uuid}")
        incident["kind"] = "instrument_error"
        incident["title"] = incident["title"] or error.get("step") or "Instrument error"
        attempt = seen_uuids.get(uuid)
        if attempt is None:
            attempt = {"uuid": uuid, "time": iso(moment), "recovery": error.get("recovery_action"), "details": []}
            seen_uuids[uuid] = attempt
            incident["attempts"].append(attempt)
            for name in offered.get(uuid, []):
                if name not in incident["recoveries_offered"]:
                    incident["recoveries_offered"].append(name)
        attempt["details"].append({"channels": error.get("channels") or [], "message": error.get("detail"), "code": error.get("code")})
        detail_key = (error.get("detail"), error.get("code"))
        if detail_key not in [(d["message"], d["code"]) for d in incident["details"]]:
            incident["details"].append({"message": error.get("detail"), "code": error.get("code"), "channels": list(error.get("channels") or [])})
        else:
            for detail in incident["details"]:
                if (detail["message"], detail["code"]) == detail_key:
                    for channel in error.get("channels") or []:
                        if channel not in detail["channels"]:
                            detail["channels"].append(channel)

    # Raw VENUS codes ("P1:08/78") live on the instrument_error entries themselves.
    for entry in log_entries(log):
        if entry.get("type") != "instrument_error":
            continue
        payload = payload_of(entry)
        attempt_incident = next(
            (i for i in incidents if any(a["uuid"] == payload.get("uuid") for a in i["attempts"])), None
        )
        code = payload.get("code")
        if attempt_incident is not None and isinstance(code, str) and code not in attempt_incident["codes"]:
            attempt_incident["codes"].append(code)
            attempt_incident["decoded"].extend(decode_error_code(code))

    # 2. Failed commands with no instrument error of their own.
    for command in index.commands:
        if command.success is not False:
            continue
        incident = incident_for(command, command.responded_at or command.requested_at, command.command_id)
        if incident["kind"] is None:
            incident["kind"] = "failed_command"
            incident["title"] = f"{command.action} failed"
            if command.message:
                incident["details"].append({"message": command.message, "code": str((command.response or {}).get("returnCode")), "channels": []})

    # 3. How the run ended.
    reason = summary.get("result")
    final = _final_command(index) if reason == "error" else None
    final_incident = by_command.get(final.command_id) if final is not None else None
    session_end = next((e for e in reversed(log_entries(log)) if e.get("type") == "session_end"), None)
    ended_at = entry_time(session_end) if session_end else None
    if reason == "error" and final_incident is None:
        final_incident = incident_for(final, ended_at, "script-exception")
        final_incident["kind"] = final_incident["kind"] or "script_exception"
        final_incident["title"] = final_incident["title"] or (summary.get("error_type") or "Script error")
        if summary.get("error_message"):
            final_incident["details"].append({"message": summary["error_message"], "code": summary.get("error_type"), "channels": []})

    for incident in incidents:
        texts = [d.get("message") for d in incident["details"]] + [d.get("description") for d in incident["decoded"]]
        incident["hint"] = likely_cause(incident["title"], *texts)
        incident["ended_run"] = incident is final_incident

    incidents.sort(key=lambda i: i["first_time"] or "")
    return {
        "outcome": {
            "result": reason,
            "error_type": summary.get("error_type"),
            "error_message": summary.get("error_message"),
            "duration_seconds": summary.get("duration_seconds"),
            "started_at": summary.get("started_at"),
            "ended_at": iso(ended_at.astimezone(tz)) if ended_at else summary.get("ended_at"),
            "final_command": describe_command(final, line_timeline),
            "final_incident": final_incident["id"] if final_incident else None,
        },
        "incidents": incidents,
        "counts": {
            "incidents": len(incidents),
            "instrument_errors": len({a["uuid"] for i in incidents for a in i["attempts"]}),
            "failed_commands": sum(1 for c in index.commands if c.success is False),
        },
    }
