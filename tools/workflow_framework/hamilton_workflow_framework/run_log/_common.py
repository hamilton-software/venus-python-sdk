"""Shared plumbing for the run_log views: entry iteration, timestamps, the command
request/response index and the Script Manager's bootstrap markers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Iterator

# The Script Manager's bootstrap prints these to stdout ("\x00NAME\x00<payload>"); the
# SDK's console capture records them in "script_output" entries.
MARKER_PREFIX = "\x00"


def log_entries(log: dict[str, Any]) -> list[dict[str, Any]]:
    entries = log.get("log")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def payload_of(entry: dict[str, Any]) -> dict[str, Any]:
    payload = entry.get("payload")
    return payload if isinstance(payload, dict) else {}


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def entry_time(entry: dict[str, Any]) -> datetime | None:
    return parse_iso(entry.get("timestamp"))


_VENUS_LOCAL_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def run_timezone(log: dict[str, Any]) -> tzinfo:
    """The run PC's UTC offset: from ``timestamp_local`` (newer logs), else from a VENUS
    trace line's local clock against the entry's UTC time, else this PC's own zone."""
    entries = log_entries(log)
    for value in [log.get("started_at_local")] + [e.get("timestamp_local") for e in entries[:50]]:
        parsed = parse_iso(value)
        if parsed is not None and parsed.utcoffset() is not None:
            return timezone(parsed.utcoffset() or timedelta(0))
    for entry in entries:
        if entry.get("type") != "runtime_trace":
            continue
        match = _VENUS_LOCAL_TIME_RE.match(str(payload_of(entry).get("trace") or ""))
        received = entry_time(entry)
        if match is None or received is None:
            continue
        local = datetime.fromisoformat(match.group(1).replace(" ", "T"))
        offset = local - received.replace(tzinfo=None)
        quarter_hours = round(offset.total_seconds() / 900)  # real zones are whole quarter hours
        return timezone(timedelta(minutes=15 * quarter_hours))
    return datetime.now().astimezone().tzinfo or timezone.utc


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def markers(log: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str, str]]:
    """``(entry, name, payload_text)`` for every bootstrap marker in the console capture."""
    for entry in log_entries(log):
        if entry.get("type") != "script_output":
            continue
        message = payload_of(entry).get("message")
        if not isinstance(message, str) or not message.startswith(MARKER_PREFIX):
            continue
        name, sep, rest = message[1:].partition(MARKER_PREFIX)
        if sep:
            yield entry, name, rest


def marker_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


@dataclass
class Command:
    """One SDK command: its request and (when it arrived) its response."""

    command_id: str
    action: str
    category: str
    parameters: dict[str, Any]
    requested_at: datetime | None
    sequence: int
    response: dict[str, Any] | None = None
    responded_at: datetime | None = None

    @property
    def success(self) -> bool | None:
        if self.response is None:
            return None
        return self.response.get("returnCode") == 0 and self.response.get("returnStatus") == "Success"

    @property
    def return_parameters(self) -> dict[str, Any]:
        value = (self.response or {}).get("returnParameters")
        return value if isinstance(value, dict) else {}

    @property
    def message(self) -> str:
        value = self.return_parameters.get("message")
        return value.strip() if isinstance(value, str) else ""

    def active_at(self, moment: datetime) -> bool:
        """Whether *moment* falls between this command's request and its response."""
        if self.requested_at is None or moment < self.requested_at:
            return False
        return self.responded_at is None or moment <= self.responded_at


@dataclass
class CommandIndex:
    commands: list[Command] = field(default_factory=list)
    by_id: dict[str, Command] = field(default_factory=dict)

    def active_at(self, moment: datetime | None) -> Command | None:
        """The most recent command still running at *moment*."""
        if moment is None:
            return None
        running = [c for c in self.commands if c.active_at(moment)]
        return running[-1] if running else None

    def before(self, moment: datetime | None, count: int) -> list[Command]:
        if moment is None:
            return []
        earlier = [c for c in self.commands if c.requested_at is not None and c.requested_at <= moment]
        return earlier[-count:]


def index_commands(log: dict[str, Any]) -> CommandIndex:
    index = CommandIndex()
    for entry in log_entries(log):
        kind = entry.get("type")
        payload = payload_of(entry)
        if kind == "command_request":
            command_id = payload.get("command_id")
            if not isinstance(command_id, str):
                continue
            parameters = payload.get("parameters")
            command = Command(
                command_id=command_id,
                action=str(payload.get("action_name") or ""),
                category=str(payload.get("category") or ""),
                parameters=parameters if isinstance(parameters, dict) else {},
                requested_at=entry_time(entry),
                sequence=int(entry.get("sequence") or 0),
            )
            index.commands.append(command)
            index.by_id[command_id] = command
        elif kind == "command_response":
            command = index.by_id.get(payload.get("id"))
            if command is not None:
                command.response = payload
                command.responded_at = entry_time(entry)
    return index


def compact_positions(positions: Any, limit: int = 6) -> str:
    """``[{"labwareId": "P", "wellId": "A1"}, ...]`` -> ``"P@A1,B1; Q@1"``."""
    if not isinstance(positions, list):
        return ""
    groups: dict[str, list[str]] = {}
    for position in positions:
        if isinstance(position, dict):
            labware = str(position.get("labwareId") or position.get("labware") or "?")
            well = str(position.get("wellId") or position.get("well") or "?")
            groups.setdefault(labware, []).append(well)
    parts = [f"{labware}@{','.join(wells)}" for labware, wells in list(groups.items())[:limit]]
    if len(groups) > limit:
        parts.append(f"+{len(groups) - limit} more")
    return "; ".join(parts)
