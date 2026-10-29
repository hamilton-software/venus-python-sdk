"""Structured JSON run log engine.

This module is internal and not part of the public API.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hamilton_venus.config import RunLogConfig

_logger = logging.getLogger(__name__)

_REDACT_HEADERS = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
})

_REDACT_EXACT_KEYS = frozenset({
    "password",
    "client_secret",
    "access_token",
    "refresh_token",
    "api_key",
})

_REDACT_SUFFIXES = ("_password", "_secret", "_token")

_BEARER_RE = re.compile(r"^Bearer\s+.+")

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.\-]")

_SCHEMA_VERSION = "1.0"

# Descriptor suffix on the finalized run-log filename, mirroring the way VENUS
# tags its own run artifacts (e.g. ``..._Trace.trc``). Keeps the SDK log
# self-identifying and sortable next to the VENUS trace/database files.
_RUN_LOG_DESCRIPTOR = "SdkRunLog"


def _sanitize_filename(name: str) -> str:
    """Make *name* safe to embed in a filename (GUIDs are already safe)."""
    return _UNSAFE_FILENAME_RE.sub("_", name)


def _utc_and_local(dt: datetime) -> tuple[str, str]:
    """``(utc_iso, local_iso)`` for *dt* (must be timezone-aware, normally UTC --
    every timestamp in this module comes from ``datetime.now(timezone.utc)``).

    ``local_iso`` is *dt* converted to the host machine's local timezone (via
    ``datetime.astimezone()``) as ISO 8601, offset and all.
    """
    return dt.isoformat(), dt.astimezone().isoformat()


def _redact(obj: Any) -> Any:
    """Recursively redact sensitive fields from a payload (operates on a copy)."""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            key_lower = key.lower()
            if (
                key_lower in _REDACT_HEADERS
                or key_lower in _REDACT_EXACT_KEYS
                or any(key_lower.endswith(suffix) for suffix in _REDACT_SUFFIXES)
            ):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact(value)
        return result
    elif isinstance(obj, list):
        return [_redact(item) for item in obj]
    elif isinstance(obj, str) and _BEARER_RE.match(obj):
        return "Bearer [REDACTED]"
    return obj


class RunLog:
    """Append-only structured run log that streams entries as NDJSON.

    **Initialization & Resource Management:**
    - If any initialization step fails (e.g., directory creation, metadata write, file open),
      the instance transitions to a disabled state (`self._disabled = True`) and safely logs a warning.
    - The file handle is always initialized (to `None` or an open file) to avoid AttributeError.
    - Callers must call :meth:`finalize` or :meth:`close` when the session ends to ensure
      the file handle is properly closed.
    - If initialization raises an exception, the instance is still safe to use; it will silently
      ignore all :meth:`record` calls.
    """

    def __init__(self, config: RunLogConfig, session_id: str, sdk_version: str) -> None:
        self._config = config
        self._session_id = session_id
        self._sdk_version = sdk_version
        self._lock = threading.Lock()
        self._sequence = 0
        self._started_at = datetime.now(UTC)
        self._closed = False
        self._disabled = False
        self._script_name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "unknown"
        self._file_handle = None
        self._run_guid: str | None = None
        self._method_name: str | None = None

        # An explicit output_dir is used as given. Unset, the log goes to VENUS's
        # LogFiles directory, or to the working directory when that can't be written.
        if config.output_dir:
            candidates = [config.output_dir]
        else:
            from hamilton_venus._internal._com_trace import default_logfiles_dir

            candidates = [default_logfiles_dir(), os.getcwd()]

        timestamp_str = self._started_at.strftime("%Y%m%d_%H%M%S")
        base_name = f"run_{session_id}_{timestamp_str}"
        started_utc, started_local = _utc_and_local(self._started_at)
        meta = {
            "schema_version": _SCHEMA_VERSION,
            "session_id": session_id,
            "sdk_version": sdk_version,
            "started_at": started_utc,
            "started_at_local": started_local,
            "script_name": self._script_name,
        }

        # Write the metadata sidecar before opening the NDJSON file; the first
        # directory where that works is the log's.
        for output_dir in candidates:
            self._output_dir = Path(output_dir)
            self._jsonl_path = self._output_dir / f"{base_name}.jsonl"
            self._meta_path = self._output_dir / f"{base_name}.meta.json"
            try:
                os.makedirs(output_dir, exist_ok=True)
                self._meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                break
            except OSError as exc:
                _logger.warning("RunLog: cannot write to %r: %s", output_dir, exc)
        else:
            _logger.warning("RunLog: no writable output directory, disabling run log")
            self._disabled = True
            return

        # Open NDJSON file for append.
        # Note: This uses open() instead of a context manager because the file must
        # remain open for streaming writes throughout the session lifetime.
        # The file is closed by finalize() or close() when the session ends.
        try:
            self._file_handle = open(self._jsonl_path, "a", encoding="utf-8")  # noqa: SIM115 - file kept open for streaming writes
        except OSError as exc:
            _logger.warning("RunLog: cannot open log file: %s", exc)
            self._disabled = True
            self._file_handle = None

    @property
    def entry_count(self) -> int:
        """Number of entries recorded so far."""
        return self._sequence

    @property
    def output_dir(self) -> Path:
        """Directory the log is written to."""
        return self._output_dir

    @property
    def script_name(self) -> str:
        """Name of the Python script that created this run log."""
        return self._script_name

    def record(self, source: str, direction: str, type: str, payload: dict[str, Any]) -> None:
        """Record a single log entry. Thread-safe. Never raises."""
        if self._disabled or self._closed:
            return
        try:
            # Apply redaction on a copy
            safe_payload = _redact(payload) if self._config.redact_auth else copy.deepcopy(payload)

            # Check payload size and truncate if needed
            if self._config.max_payload_bytes > 0:
                payload_json = json.dumps(safe_payload, default=str)
                payload_bytes = len(payload_json.encode("utf-8"))
                if payload_bytes > self._config.max_payload_bytes:
                    safe_payload = {"_truncated": True, "_original_bytes": payload_bytes}

            with self._lock:
                self._sequence += 1
                utc_iso, local_iso = _utc_and_local(datetime.now(UTC))
                entry = {
                    "timestamp": utc_iso,
                    "timestamp_local": local_iso,
                    "sequence": self._sequence,
                    "source": source,
                    "direction": direction,
                    "type": type,
                    "payload": safe_payload,
                }
                line = json.dumps(entry, default=str)
                if self._file_handle is not None:
                    self._file_handle.write(line + "\n")
                    self._file_handle.flush()
        except Exception as exc:
            _logger.warning("RunLog.record failed: %s", exc)

    def set_run_guid(self, run_guid: str | None, method_name: str | None = None) -> None:
        """Associate a VENUS run control GUID with this run log.

        The GUID (``runGuid`` from ``GET /execution/current-run-data``) is the
        identifier VENUS run control uses to track a run.  Recording it here
        lets SDK run-log files be correlated with VENUS run control and run
        history.  When a GUID is provided, the finalized ``.json`` file is
        named to sit alongside the VENUS trace/database files for the same run
        (``<methodName>_<guid>_SdkRunLog.json``); otherwise the SDK session id
        and script name are used as a fallback.

        *method_name* is VENUS's ``methodName`` for the run; when omitted the
        run log falls back to the invoking script name.

        Thread-safe. Never raises. No-op when disabled, closed, or the GUID is
        empty.
        """
        if self._disabled or self._closed or not run_guid:
            return
        with self._lock:
            self._run_guid = run_guid
            if method_name:
                self._method_name = method_name
            # Refresh the metadata sidecar so the GUID survives a crash (the
            # sidecar is read back by finalize/recover). Best-effort only.
            try:
                if self._meta_path.is_file():
                    meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                    meta["run_guid"] = run_guid
                    if method_name:
                        meta["method_name"] = method_name
                    self._meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            except (OSError, ValueError) as exc:
                _logger.warning("RunLog.set_run_guid: cannot update metadata sidecar: %s", exc)
        self.record("SDK", "In", "run_guid_linked", {"run_guid": run_guid, "method_name": method_name})

    def _build_final_name(self, run_guid: str | None, method_name: str | None) -> str:
        """Build the finalized run-log basename (without extension).

        Mirrors the VENUS artifact convention ``<methodName>_<guid>_<tag>`` so
        the SDK log sits next to the VENUS trace/database files for the run.
        VENUS reports ``methodName`` as a full path (e.g.
        ``C:\\Program Files (x86)\\HAMILTON\\...\\main.hsl``); only its base
        name without directory or extension is used (``main``) to match the
        VENUS trace/database filenames.  The GUID is normalized to hyphen-less
        form to match VENUS's filenames; when no GUID is available the SDK
        session id is used instead.
        """
        raw_name = method_name or self._script_name
        # Reduce a possibly path-like name to its base (handle Windows and
        # POSIX separators regardless of the host OS) and drop the extension.
        raw_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        name_part = _sanitize_filename(Path(raw_name).stem)
        if not name_part or name_part == "unknown":
            name_part = "VENUS_SDK_Session"
        if run_guid:
            unique_part = _sanitize_filename(run_guid.replace("-", ""))
        else:
            unique_part = _sanitize_filename(self._session_id)
        return f"{name_part}_{unique_part}_{_RUN_LOG_DESCRIPTOR}"

    def finalize(self, reason: str = "normal") -> Path:
        """Wrap entries with metadata and write the final .json file."""
        ended_at = datetime.now(UTC)

        if self._file_handle is not None and not self._file_handle.closed:
            self._file_handle.close()
        self._closed = True

        # Read sidecar metadata
        meta: dict[str, Any]
        if self._meta_path.is_file():
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
        else:
            started_utc, started_local = _utc_and_local(self._started_at)
            meta = {
                "schema_version": _SCHEMA_VERSION,
                "session_id": self._session_id,
                "sdk_version": self._sdk_version,
                "started_at": started_utc,
                "started_at_local": started_local,
                "script_name": self._script_name,
            }

        # Read all entries
        entries: list[dict[str, Any]] = []
        if self._jsonl_path.is_file():
            with open(self._jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))

        run_guid = self._run_guid or meta.get("run_guid")
        method_name = self._method_name or meta.get("method_name")
        ended_utc, ended_local = _utc_and_local(ended_at)

        final = {
            "schema_version": meta["schema_version"],
            "session_id": meta["session_id"],
            "run_guid": run_guid,
            "method_name": method_name,
            "sdk_version": meta["sdk_version"],
            "script_name": meta.get("script_name", "unknown"),
            "started_at": meta["started_at"],
            "started_at_local": meta.get("started_at_local"),
            "ended_at": ended_utc,
            "ended_at_local": ended_local,
            "reason": reason,
            "log": entries,
        }

        final_path = self._output_dir / f"{self._build_final_name(run_guid, method_name)}.json"
        final_path.write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")

        # Clean up temp files
        if self._jsonl_path.is_file():
            self._jsonl_path.unlink()
        if self._meta_path.is_file():
            self._meta_path.unlink()

        return final_path

    def close(self) -> None:
        """Close the file handle without finalizing (crash path)."""
        self._closed = True
        if self._file_handle is not None and not self._file_handle.closed:
            self._file_handle.close()

    @classmethod
    def recover(cls, jsonl_path: str | Path) -> Path:
        """Convert a crash .jsonl file into the finalized .json format.

        Raises:
            FileNotFoundError: If the .jsonl file does not exist.
            ValueError: If the file contains zero valid lines.
        """
        jsonl_path = Path(jsonl_path)
        if not jsonl_path.is_file():
            raise FileNotFoundError(f"Run log file not found: {jsonl_path}")

        # Read entries
        entries: list[dict[str, Any]] = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        if not entries:
            raise ValueError(f"Run log file contains zero valid entries: {jsonl_path}")

        # Try reading sidecar
        meta_path = jsonl_path.with_suffix(".meta.json")
        stem = jsonl_path.stem  # e.g. run_a1b2c3d4_20260505_194010
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            # Synthesize metadata from filename
            parts = stem.split("_", 1)
            session_id = parts[1].rsplit("_", 2)[0] if len(parts) > 1 else "unknown"
            # Extract timestamp from the first entry (already enriched with
            # timestamp_local if it was recorded post-local-timestamp-support;
            # older entries just won't have that key, and .get() below
            # leaves the corresponding field absent rather than guessing).
            first_entry = entries[0]
            started_at = first_entry.get("timestamp", datetime.now(UTC).isoformat())
            meta = {
                "schema_version": _SCHEMA_VERSION,
                "session_id": session_id,
                "sdk_version": "unknown",
                "started_at": started_at,
                "started_at_local": first_entry.get("timestamp_local"),
                "script_name": "unknown",
            }

        # ended_at = last entry timestamp
        last_entry = entries[-1]
        ended_at = last_entry.get("timestamp", datetime.now(UTC).isoformat())

        final = {
            "schema_version": meta["schema_version"],
            "session_id": meta["session_id"],
            "run_guid": meta.get("run_guid"),
            "method_name": meta.get("method_name"),
            "sdk_version": meta["sdk_version"],
            "script_name": meta.get("script_name", "unknown"),
            "started_at": meta["started_at"],
            "started_at_local": meta.get("started_at_local"),
            "ended_at": ended_at,
            "ended_at_local": last_entry.get("timestamp_local"),
            "log": entries,
        }

        # Unlike finalize(), the recovered file is named from the .jsonl stem
        # (session-id based), since the streaming file was created before any
        # run GUID was known; the GUID is still preserved in the JSON content.
        final_path = jsonl_path.with_suffix(".json")
        final_path.write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")

        # Remove temp files
        jsonl_path.unlink()
        if meta_path.is_file():
            meta_path.unlink()

        return final_path

