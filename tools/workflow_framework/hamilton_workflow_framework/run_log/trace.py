"""A run log (and optionally VENUS's own trace) as one chronological list of trace lines.

Each line is ``{"timestamp", "category", "source", "text"}`` with the Script Manager trace
pane's categories, so its TraceView renders them unchanged:

- ``terminal`` -- the script's own console output (bootstrap markers removed).
- ``venus`` -- VENUS trace lines: the ``.trc`` when given, else the live ``runtime_trace`` events.
- ``communication`` -- SDK commands (request and result) and VENUS's command status messages.
- ``comtrace`` -- the firmware COM trace.
- ``info`` -- session start/end, run state changes.
- ``debug`` -- raw HTTP, SignalR housekeeping, progress, labware events.
- ``error`` -- failed commands, instrument errors, a run that ended in error.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, tzinfo
from typing import Any, Iterable

from hamilton_workflow_framework.run_log._common import (
    compact_positions,
    entry_time,
    iso,
    log_entries,
    marker_json,
    payload_of,
    run_timezone,
)

# Bootstrap markers that carry data for other views, not trace text.
_HIDDEN_MARKERS = {"SAMPLE", "SAMPLE_LABWARE_INFO", "TADM", "CONSUMABLE", "CONSUMABLE_WARNING", "SERIAL", "LINE", "ERRLINE"}

_EXECUTOR_EVENTS = {
    0: "Undefined", 1: "Initialized", 2: "Initialize failed", 3: "Terminated", 4: "Aborted", 5: "Paused",
    6: "Running", 7: "Unloaded", 8: "Starting", 9: "Processed", 10: "Aborting",
}

_VENUS_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:[.,](\d+))?\s")
_COM_LINE_RE = re.compile(r"^(?:[<>!] |  )(\d{2}):(\d{2}):(\d{2})\.(\d{3}) ")

# Request parameters worth showing on a command's trace line, in this order.
_KEY_PARAMETERS = (
    "labwareName", "labwareId", "labwareDefinition", "carrier", "site", "tipPool", "channels", "volumes",
    "volume", "liquidClass", "mphSelection", "deck", "barcode", "track",
)


def decode_trace_bytes(raw: bytes) -> str:
    """VENUS writes .trc files in the system code page (cp1252); accept UTF-8/16 too."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_venus_trace(lines: Iterable[str], tz: tzinfo) -> list[tuple[datetime | None, str]]:
    """``(local time, line)`` for each VENUS trace line; a line without its own timestamp
    (a continuation) takes the previous line's time."""
    parsed: list[tuple[datetime | None, str]] = []
    last: datetime | None = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        match = _VENUS_LINE_RE.match(line)
        if match:
            fraction = (match.group(3) or "0")[:6].ljust(6, "0")
            try:
                last = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}.{fraction}").replace(tzinfo=tz)
            except ValueError:
                pass
        parsed.append((last, line))
    return parsed


def _line(moment: datetime | None, category: str, source: str, text: str) -> dict[str, Any]:
    return {"timestamp": iso(moment), "category": category, "source": source, "text": text}


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _request_summary(parameters: dict[str, Any]) -> str:
    parts = []
    positions = compact_positions(parameters.get("positions"))
    if positions:
        parts.append(f"positions={positions}")
    for key in _KEY_PARAMETERS:
        if key in parameters and parameters[key] not in (None, "", []):
            parts.append(f"{key}={_short(parameters[key], 80)}")
    return " ".join(parts)


def _com_time(line: str, day: datetime, tz: tzinfo) -> datetime | None:
    """A COM-trace line carries only HH:MM:SS.mmm; place it on the run's local day."""
    match = _COM_LINE_RE.match(line)
    if not match:
        return None
    hours, minutes, seconds, millis = (int(g) for g in match.groups())
    local_day = day.astimezone(tz)
    return local_day.replace(hour=hours, minute=minutes, second=seconds, microsecond=millis * 1000)


def build_trace(log: dict[str, Any], venus_trace_lines: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Every entry of *log* worth reading, plus *venus_trace_lines*, sorted by time."""
    tz = run_timezone(log)
    entries = log_entries(log)
    lines: list[dict[str, Any]] = []
    actions: dict[str, tuple[str, datetime | None]] = {}  # command_id -> (action, requested_at)
    have_com_trace_chunks = any(e.get("type") == "com_trace" for e in entries)
    use_runtime_trace = venus_trace_lines is None

    for entry in entries:
        if not isinstance(entry.get("payload"), dict):
            continue  # every real entry has an object payload; anything else is damage
        kind = entry.get("type")
        payload = payload_of(entry)
        moment = entry_time(entry)
        source = str(entry.get("source") or "")

        if kind == "script_output":
            message = payload.get("message")
            if not isinstance(message, str):
                continue
            if message.startswith("\x00"):
                name, _, rest = message[1:].partition("\x00")
                if name == "COMTRACE" and not have_com_trace_chunks and moment is not None:
                    data = marker_json(rest) or {}
                    for com_line in data.get("lines") or []:
                        if isinstance(com_line, str):
                            lines.append(_line(_com_time(com_line, moment, tz) or moment, "comtrace", "COM", com_line))
                elif name == "STATE":
                    lines.append(_line(moment, "info", "Script Manager", f"Run state: {rest.strip()}"))
                elif name not in _HIDDEN_MARKERS and name != "COMTRACE":
                    lines.append(_line(moment, "debug", "Script Manager", f"{name}: {_short(rest)}"))
                continue
            for text in message.splitlines() or [""]:
                lines.append(_line(moment, "terminal", "Console", text))

        elif kind == "runtime_trace" and use_runtime_trace:
            text = payload.get("trace")
            if isinstance(text, str):
                for text_line in text.splitlines():
                    lines.append(_line(moment, "venus", "VENUS", text_line))

        elif kind == "com_trace":
            for com_line in payload.get("lines") or []:
                if isinstance(com_line, str) and moment is not None:
                    lines.append(_line(_com_time(com_line, moment, tz) or moment, "comtrace", "COM", com_line))

        elif kind == "command_request":
            action = str(payload.get("action_name") or "")
            command_id = payload.get("command_id")
            if isinstance(command_id, str):
                actions[command_id] = (action, moment)
            parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
            summary = _request_summary(parameters)
            lines.append(_line(moment, "communication", "SDK", f"→ {action}" + (f" {summary}" if summary else "")))

        elif kind == "command_response":
            action, requested_at = actions.get(payload.get("id"), ("(unknown command)", None))
            ok = payload.get("returnCode") == 0 and payload.get("returnStatus") == "Success"
            took = f" in {(moment - requested_at).total_seconds():.2f} s" if moment and requested_at else ""
            text = f"← {action} {payload.get('returnStatus') or payload.get('status') or '?'}{took}"
            if not ok:
                return_parameters = payload.get("returnParameters")
                message = return_parameters.get("message") if isinstance(return_parameters, dict) else None
                text += f" (return code {payload.get('returnCode')})" + (f": {message}" if message else "")
            lines.append(_line(moment, "communication" if ok else "error", "SDK", text))

        elif kind == "command_communication":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            status = data.get("status")
            if status:
                command = data.get("command")
                prefix = f"{command}: " if command else ""
                lines.append(_line(moment, "communication", "VENUS", f"Communication message: {prefix}{status}"))

        elif kind == "instrument_error":
            details = [
                d.get("message") for d in payload.get("detailed_errors") or [] if isinstance(d, dict) and d.get("message")
            ]
            detail = "; ".join(dict.fromkeys(details)) or payload.get("message") or ""
            lines.append(_line(
                moment, "error", "VENUS",
                f"Instrument error {payload.get('code') or ''}: {payload.get('title') or ''}"
                + (f" — {detail}" if detail else ""),
            ))

        elif kind == "device_error_handled":
            lines.append(_line(moment, "error", "VENUS", f"Error recovery submitted: {payload.get('recovery_action') or '?'}"))

        elif kind == "runtime_status":
            event = _EXECUTOR_EVENTS.get(payload.get("executor_event"), str(payload.get("executor_event")))
            message = payload.get("message")
            lines.append(_line(moment, "info", "VENUS", f"Method {event}" + (f": {message}" if message else "")))

        elif kind == "session_start":
            simulate = payload.get("simulate")
            mode = "" if simulate is None else (" (simulation)" if simulate else " (instrument)")
            lines.append(_line(moment, "info", "SDK", f"Session started: {payload.get('script_name') or ''}{mode}"))

        elif kind == "session_end":
            reason = payload.get("reason")
            text = f"Session ended: {reason}, {payload.get('duration_seconds')} s"
            if payload.get("error_type"):
                text += f" — {payload.get('error_type')}: {payload.get('error_message') or ''}"
            lines.append(_line(moment, "error" if reason == "error" else "info", "SDK", text))

        elif kind == "run_guid_linked":
            lines.append(_line(moment, "info", "SDK", f"Run GUID {payload.get('run_guid')} ({payload.get('method_name')})"))

        elif kind == "http_response":
            status = payload.get("status_code")
            category = "error" if isinstance(status, int) and status >= 400 else "debug"
            lines.append(_line(moment, category, "HTTP", f"{payload.get('method')} {payload.get('path')} → {status}"))

        elif kind == "http_request":
            lines.append(_line(moment, "debug", "HTTP", f"{payload.get('method')} {payload.get('path')}"))

        elif kind in ("reservoir_labware", "com_trace_snapshot"):
            continue

        elif kind:
            lines.append(_line(moment, "debug", source or "Log", f"{kind}: {_short(payload)}"))

    if venus_trace_lines is not None:
        for moment, text in parse_venus_trace(venus_trace_lines, tz):
            lines.append(_line(moment, "venus", "VENUS", text))

    # Every time in the run's local zone (so the strings sort), then a stable sort: lines
    # without a time keep their place after the previous timed line.
    keyed: list[tuple[str, int, dict[str, Any]]] = []
    last_key = ""
    for order, line in enumerate(lines):
        key = last_key
        if line["timestamp"]:
            key = line["timestamp"] = datetime.fromisoformat(line["timestamp"]).astimezone(tz).isoformat()
        last_key = key
        keyed.append((key, order, line))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, line in keyed]
