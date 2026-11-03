"""Every SDK command of a run: a light list, and on request one command's full detail --
its request, its response, VENUS's status messages for it, the instrument errors raised
while it ran, and the VENUS trace and firmware (COM trace) lines from its time window."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from hamilton_workflow_framework.run_log._common import (
    Command,
    compact_positions,
    entry_time,
    index_commands,
    iso,
    log_entries,
    payload_of,
)
from hamilton_workflow_framework.run_summary import _line_at_timestamp

# A command with no response ran until the run ended: its window ends at the log's last entry,
# capped at this much after its start.
UNFINISHED_WINDOW = timedelta(minutes=10)


def _result(command: Command) -> str:
    if command.response is None:
        return "running"
    return "success" if command.success else "failed"


def _row(command: Command, line_timeline: list[Any] | None, error_count: int) -> dict[str, Any]:
    parameters = command.parameters
    duration = (
        (command.responded_at - command.requested_at).total_seconds()
        if command.responded_at and command.requested_at
        else None
    )
    summary = compact_positions(parameters.get("positions")) or next(
        (f"{key}={parameters[key]}" for key in ("labwareName", "labwareId", "tipPool", "deck", "carrier") if parameters.get(key)),
        "",
    )
    return {
        "command_id": command.command_id,
        "sequence": command.sequence,
        "action": command.action,
        "category": command.category,
        "requested_at": iso(command.requested_at),
        "responded_at": iso(command.responded_at),
        "duration_seconds": round(duration, 3) if duration is not None else None,
        "result": _result(command),
        "return_code": (command.response or {}).get("returnCode"),
        "message": command.message,
        "summary": summary,
        "channels": parameters.get("channels") if isinstance(parameters.get("channels"), list) else None,
        "error_count": error_count,
        "line": _line_at_timestamp(line_timeline, command.requested_at.timestamp() if command.requested_at else None),
    }


def _log_end(log: dict[str, Any]) -> datetime | None:
    times = [t for t in (entry_time(e) for e in log_entries(log)[-20:]) if t is not None]
    return max(times) if times else None


def _window(command: Command, log_end: datetime | None) -> tuple[datetime, datetime] | None:
    if command.requested_at is None:
        return None
    if command.responded_at is not None:
        return command.requested_at, command.responded_at
    cap = command.requested_at + UNFINISHED_WINDOW
    return command.requested_at, min(log_end, cap) if log_end and log_end > command.requested_at else cap


def _instrument_errors(log: dict[str, Any]) -> list[tuple[datetime | None, dict[str, Any]]]:
    return [
        (entry_time(e), payload_of(e)) for e in log_entries(log) if e.get("type") == "instrument_error"
    ]


def build_command_list(log: dict[str, Any], line_timeline: list[Any] | None = None) -> list[dict[str, Any]]:
    """One row per SDK command, in the order they were sent."""
    errors = _instrument_errors(log)
    log_end = _log_end(log)
    rows = []
    for command in index_commands(log).commands:
        window = _window(command, log_end)
        count = sum(1 for moment, _ in errors if window and moment and window[0] <= moment <= window[1])
        rows.append(_row(command, line_timeline, count))
    return rows


def build_command_detail(
    log: dict[str, Any],
    command_id: str,
    trace: list[dict[str, Any]],
    line_timeline: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Everything about one command; *trace* is ``build_trace``'s output for the same log."""
    command = index_commands(log).by_id.get(command_id)
    if command is None:
        return None
    window = _window(command, _log_end(log))

    communication = []
    for entry in log_entries(log):
        if entry.get("type") != "command_communication":
            continue
        data = payload_of(entry).get("data")
        if isinstance(data, dict) and data.get("id") == command_id and data.get("status"):
            communication.append({"timestamp": iso(entry_time(entry)), "status": data["status"]})

    errors = []
    for moment, payload in _instrument_errors(log):
        if window and moment and window[0] <= moment <= window[1]:
            errors.append({
                "timestamp": iso(moment),
                "code": payload.get("code"),
                "title": payload.get("title"),
                "details": [
                    {
                        "message": d.get("message"),
                        "code": d.get("code"),
                        "channel": next(
                            (a.get("value") for a in d.get("attributes") or [] if isinstance(a, dict) and a.get("name") == "channel"),
                            None,
                        ),
                    }
                    for d in payload.get("detailed_errors") or []
                    if isinstance(d, dict)
                ],
            })

    def lines(category: str) -> list[dict[str, Any]]:
        if window is None:
            return []
        picked = []
        for line in trace:
            if line["category"] != category or not line["timestamp"]:
                continue
            moment = datetime.fromisoformat(line["timestamp"])
            if window[0] <= moment <= window[1]:
                picked.append({"timestamp": line["timestamp"], "text": line["text"]})
        return picked

    return {
        **_row(command, line_timeline, len(errors)),
        "parameters": command.parameters,
        "response": command.response,
        "communication": communication,
        "errors": errors,
        "venus": lines("venus"),
        "comtrace": lines("comtrace"),
    }
