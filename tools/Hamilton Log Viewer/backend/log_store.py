"""Opened run logs, held in memory, with each view computed on first request.

A log is opened from a file (its ``_ScriptLines.json`` and VENUS ``_Trace.trc`` siblings
are picked up when present) or from a VENUS run through the Vector API. The trace, summary,
error and sample views come from ``hamilton_workflow_framework`` -- the same code the
Script Manager's Summary tab uses -- and are cached per log.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hamilton_workflow_framework.run_log import (
    analyze_errors,
    build_command_detail,
    build_command_list,
    build_sample_tracking,
    build_trace,
)
from hamilton_workflow_framework.run_log.trace import decode_trace_bytes
from hamilton_workflow_framework.run_summary import summarize_run

SDK_LOG_SUFFIX = "_SdkRunLog.json"


class LogOpenError(Exception):
    """The file is missing, unreadable, or not an SDK run log."""


@dataclass
class OpenLog:
    id: str
    name: str
    origin: dict[str, Any]
    log: dict[str, Any] | None
    line_timeline: list[Any] | None
    trace_lines: list[str] | None
    notes: list[str] = field(default_factory=list)
    _views: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self, name: str) -> Any:
        with self._lock:
            if name not in self._views:
                self._views[name] = self._compute(name)
            return self._views[name]

    def _compute(self, name: str) -> Any:
        log = self.log or {"log": []}
        if name == "trace":
            return build_trace(log, self.trace_lines)
        if name == "summary":
            return summarize_run(log, line_timeline=self.line_timeline) if self.log is not None else None
        if name == "errors":
            return analyze_errors(log, line_timeline=self.line_timeline, venus_trace_lines=self.trace_lines)
        if name == "samples":
            return build_sample_tracking(log)
        if name == "commands":
            return build_command_list(log, line_timeline=self.line_timeline)
        raise KeyError(name)

    def command_detail(self, command_id: str) -> dict[str, Any] | None:
        if self.log is None:
            return None
        return build_command_detail(self.log, command_id, self.view("trace"), line_timeline=self.line_timeline)

    def header(self) -> dict[str, Any]:
        log = self.log or {}
        session_start = next(
            (e.get("payload") or {} for e in log.get("log") or [] if isinstance(e, dict) and e.get("type") == "session_start"),
            {},
        )
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin,
            "has_sdk_log": self.log is not None,
            "has_venus_trace": self.trace_lines is not None,
            "has_script_lines": self.line_timeline is not None,
            "script_name": log.get("script_name"),
            "method_name": log.get("method_name"),
            "run_guid": log.get("run_guid"),
            "sdk_version": log.get("sdk_version"),
            "simulate": session_start.get("simulate") if isinstance(session_start, dict) else None,
            "started_at": log.get("started_at_local") or log.get("started_at"),
            "ended_at": log.get("ended_at_local") or log.get("ended_at"),
            "reason": log.get("reason"),
            "entry_count": len(log.get("log") or []),
            "notes": self.notes,
        }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise LogOpenError(f"Could not read {path}: {exc}") from exc
    except ValueError as exc:
        raise LogOpenError(f"{path.name} is not valid JSON: {exc}") from exc


def _sibling(path: Path, suffix: str) -> Path | None:
    if not path.name.endswith(SDK_LOG_SUFFIX):
        return None
    candidate = path.with_name(path.name[: -len(SDK_LOG_SUFFIX)] + suffix)
    return candidate if candidate.is_file() else None


class LogStore:
    def __init__(self, max_open: int) -> None:
        self._max_open = max_open
        self._logs: OrderedDict[str, OpenLog] = OrderedDict()
        self._lock = threading.Lock()

    def _add(self, opened: OpenLog) -> OpenLog:
        with self._lock:
            self._logs[opened.id] = opened
            while len(self._logs) > self._max_open:
                self._logs.popitem(last=False)
        return opened

    def get(self, log_id: str) -> OpenLog | None:
        with self._lock:
            opened = self._logs.get(log_id)
            if opened is not None:
                self._logs.move_to_end(log_id)
            return opened

    def open_file(self, path_text: str) -> OpenLog:
        path = Path(path_text)
        if not path.is_file():
            raise LogOpenError(f"File not found: {path}")
        log = _read_json(path)
        if not isinstance(log, dict) or not isinstance(log.get("log"), list):
            raise LogOpenError(f"{path.name} is not an SDK run log (no \"log\" list).")
        notes: list[str] = []
        line_timeline = None
        lines_path = _sibling(path, "_ScriptLines.json")
        if lines_path is not None:
            try:
                data = _read_json(lines_path)
                line_timeline = data if isinstance(data, list) else None
            except LogOpenError:
                notes.append(f"{lines_path.name} could not be read; script line numbers are not shown.")
        trace_lines = None
        trace_path = _sibling(path, "_Trace.trc")
        if trace_path is not None:
            try:
                trace_lines = decode_trace_bytes(trace_path.read_bytes()).splitlines()
            except OSError:
                notes.append(f"{trace_path.name} could not be read; the VENUS trace comes from the SDK log only.")
        else:
            notes.append("No VENUS trace (_Trace.trc) next to this log; VENUS lines come from the SDK log only.")
        return self._add(OpenLog(
            id=uuid.uuid4().hex,
            name=path.name,
            origin={"kind": "file", "path": str(path)},
            log=log,
            line_timeline=line_timeline,
            trace_lines=trace_lines,
            notes=notes,
        ))

    def open_dropped(self, files: list[dict[str, str]], known_dirs: list[Path]) -> OpenLog:
        """Files dragged onto the window: ``[{"name", "data" (base64)}]``. A browser hands
        over contents, never paths -- so when the run log is also in one of *known_dirs*
        (byte-for-byte the same), that copy is opened, which brings its VENUS trace and
        script lines along. Otherwise the dropped files are used as they are."""
        contents: dict[str, bytes] = {}
        for item in files:
            try:
                contents[Path(str(item.get("name") or "")).name] = base64.b64decode(item.get("data") or "")
            except (ValueError, TypeError) as exc:
                raise LogOpenError(f"Could not read the dropped file {item.get('name')!r}.") from exc
        names = sorted(contents, key=lambda n: not n.endswith(SDK_LOG_SUFFIX))
        log_name = next((n for n in names if n.lower().endswith(".json") and not n.endswith("_ScriptLines.json")), None)
        if log_name is None:
            raise LogOpenError("Drop an SDK run log (*_SdkRunLog.json); its _Trace.trc and _ScriptLines.json may come with it.")
        raw = contents[log_name]

        for folder in known_dirs:
            candidate = folder / log_name
            try:
                if candidate.is_file() and candidate.stat().st_size == len(raw) and candidate.read_bytes() == raw:
                    return self.open_file(str(candidate))
            except OSError:
                continue

        try:
            log = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise LogOpenError(f"{log_name} is not valid JSON: {exc}") from exc
        if not isinstance(log, dict) or not isinstance(log.get("log"), list):
            raise LogOpenError(f"{log_name} is not an SDK run log (no \"log\" list).")

        stem = log_name[: -len(SDK_LOG_SUFFIX)] if log_name.endswith(SDK_LOG_SUFFIX) else None
        notes: list[str] = []
        trace_lines = line_timeline = None
        trace_raw = contents.get(f"{stem}_Trace.trc") if stem else None
        if trace_raw is None:
            trace_raw = next((data for name, data in contents.items() if name.lower().endswith(".trc")), None)
        if trace_raw is not None:
            trace_lines = decode_trace_bytes(trace_raw).splitlines()
        else:
            notes.append("Dropped without its VENUS trace (_Trace.trc); drop it together with the log to include it.")
        lines_raw = contents.get(f"{stem}_ScriptLines.json") if stem else None
        if lines_raw is not None:
            try:
                data = json.loads(lines_raw.decode("utf-8-sig"))
                line_timeline = data if isinstance(data, list) else None
            except (UnicodeDecodeError, ValueError):
                notes.append("The dropped _ScriptLines.json could not be read; script line numbers are not shown.")
        return self._add(OpenLog(
            id=uuid.uuid4().hex,
            name=log_name,
            origin={"kind": "dropped", "files": sorted(contents)},
            log=log,
            line_timeline=line_timeline,
            trace_lines=trace_lines,
            notes=notes,
        ))

    def open_bundle(self, host: str, run: dict[str, Any], bundle: dict[str, Any]) -> OpenLog:
        """A run fetched through the Vector API (``venus_runs.fetch_run_bundle``)."""
        return self._add(OpenLog(
            id=uuid.uuid4().hex,
            name=bundle.get("log_name") or f"{run.get('method')}_{run.get('run_guid')}",
            origin={"kind": "venus", "host": host, "run": run},
            log=bundle.get("log"),
            line_timeline=bundle.get("line_timeline"),
            trace_lines=bundle.get("trace_lines") or None,
            notes=list(bundle.get("notes") or []),
        ))
