"""Runs validated scripts as subprocesses and tracks them: state, events, prompts, controls.

One script runs at a time. ``start_run`` re-validates the script's *current* text, copies exactly
that text into a per-run folder, and runs the copy, so what runs is what was validated. The child
(``child_bootstrap``) reports over stdout; this module turns those events into a bounded ring of
numbered events (for cursor-based polling), running totals for what the run touched (labware,
tips, liquid seen), and a list of prompts that need a human.

Nothing here decides how a prompt is answered: ``resolve_prompt`` only checks the answer against
the options the prompt offered and passes it to the child. Who is allowed to call it is the
``OperatorGate``'s job.

State is guarded by one re-entrant lock: events arrive on reader threads, tools run on the MCP
event loop, and the operator HTTP page runs on its own thread.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hamilton_workflow_framework.run_summary import RunLogError, load_run_log, summarize_run

from hamilton_venus_mcp import venus_api
from hamilton_venus_mcp.script_runs.consumables_config import ConsumablesConfigStore
from hamilton_venus_mcp.script_runs.consumables_from_summary import usage_from_summary
from hamilton_venus_mcp.script_runs.consumables_ledger import ConsumablesLedger, RunRecord
from hamilton_venus_mcp.script_runs.protocol import decode_line, prompt_response_line
from hamilton_venus_mcp.script_validator import validate_bytes
from hamilton_venus_mcp.scripts_store import ScriptStore, sha256_of

# VENUS prints the serial in its trace at method start; the SDK run log is named
# ``<method>_<runGuid>_SdkRunLog.json`` once VENUS has assigned the run its GUID.
_SERIAL_RE = re.compile(r"Serial number of Instrument:\s*(\S+)")
_GUID_IN_LOG_NAME_RE = re.compile(r"_([0-9a-fA-F]{32})_SdkRunLog\.json$")

OPERATOR_TOKEN_ENV = "HAMILTON_MCP_OPERATOR_TOKEN"
ALLOW_HARDWARE_ENV = "HAMILTON_MCP_ALLOW_HARDWARE"
PROMPT_ABORT_AFTER_ENV = "HAMILTON_MCP_PROMPT_ABORT_AFTER_S"
COMMAND_TIMEOUT_ENV = "HAMILTON_MCP_COMMAND_TIMEOUT_S"
DEFAULT_COMMAND_TIMEOUT_S = 1800.0

EVENT_RING_SIZE = 5000
EVENTS_FILE = "events.jsonl"
TEXT_LIMIT = 2000
KILL_GRACE_S = 20.0
MAX_TRACKED = 500
RECENT_RUNS_KEPT = 30
_CHILD_SCRIPT = Path(__file__).with_name("child_bootstrap.py")
_FINISHED = {"completed", "failed", "stopped"}


class RunError(RuntimeError):
    """A request the run manager refuses, with a message meant for the caller."""


def guid_from_log(log: dict[str, Any]) -> str | None:
    """The VENUS run GUID the SDK recorded inside its run log (a ``run_guid_linked`` entry), in the
    hyphen-less form VENUS uses elsewhere. The file name only carries it once the log has been
    finalized -- a run that was aborted or killed leaves an unfinalized log whose name has none."""
    for entry in log.get("log") or []:
        if isinstance(entry, dict) and entry.get("type") == "run_guid_linked":
            guid = (entry.get("payload") or {}).get("run_guid")
            if guid:
                return str(guid).replace("-", "")
    return None


def _iso(timestamp: float | None) -> str | None:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else None


def _truncate(text: str, limit: int = TEXT_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more characters]"


@dataclass
class RunEvent:
    seq: int
    ts: float
    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "time": _iso(self.ts), "type": self.type, **self.data}


class Run:
    """Everything known about one run. Mutated only under ``self.lock``."""

    def __init__(self, run_id: str, script: str, sha256: str, simulate: bool, max_runtime_s: float | None) -> None:
        self.lock = threading.RLock()
        self.run_id = run_id
        self.script = script
        self.sha256 = sha256
        self.simulate = simulate
        self.max_runtime_s = max_runtime_s
        self.status = "starting"  # starting | running | paused | completed | failed | stopped
        self.paused = False
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.exit_code: int | None = None
        self.error: dict[str, Any] | None = None
        self.error_line: int | None = None
        self.current_line: int | None = None
        self.stop_requested = False
        self.timed_out = False
        self.acknowledged = False
        self.proc: subprocess.Popen[bytes] | None = None
        self.run_dir: Path | None = None
        self.log_file: str | None = None
        self.sim_mode: dict[str, Any] | None = None
        self.venus_run_guid: str | None = None
        self.instrument_serial: str | None = None
        self.clients: list[dict[str, Any]] = []
        self.labware: list[dict[str, Any]] = []
        self.tips: dict[str, dict[str, Any]] = {}
        self.reagents: dict[str, dict[str, Any]] = {}
        self.reloads: list[dict[str, Any]] = []
        self.consumable_warnings: list[dict[str, Any]] = []
        self.summary: dict[str, Any] | None = None
        self.prompts: dict[str, dict[str, Any]] = {}
        self.exit_info: dict[str, Any] | None = None
        self.events: deque[RunEvent] = deque(maxlen=EVENT_RING_SIZE)
        self.next_seq = 1

    # -- events ----------------------------------------------------------------------------

    def add_event(self, event_type: str, ts: float | None = None, **data: Any) -> RunEvent:
        with self.lock:
            event = RunEvent(self.next_seq, ts or time.time(), event_type, data)
            self.next_seq += 1
            self.events.append(event)
            return event

    def events_since(self, since_seq: int, max_items: int, types: set[str] | None) -> tuple[list[dict[str, Any]], int, int]:
        """(events, next_seq_to_ask_for, dropped): events with seq > since_seq, oldest first;
        ``dropped`` counts events the ring has already discarded that the caller never saw."""
        with self.lock:
            oldest = self.events[0].seq if self.events else self.next_seq
            dropped = max(0, oldest - (since_seq + 1))
            matching = [e for e in self.events if e.seq > since_seq and (types is None or e.type in types)]
            picked = matching[:max_items]
            # Everything that matched was returned, so the cursor can skip to the end (past any
            # events a type filter hid); if the page was cut short it stops at the last one shown.
            last = picked[-1].seq if len(matching) > len(picked) else max(since_seq, self.next_seq - 1)
            return [e.to_dict() for e in picked], last, dropped

    # -- child events ----------------------------------------------------------------------

    def apply_child_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type"))
        ts = event.get("ts") if isinstance(event.get("ts"), (int, float)) else None
        data = {k: v for k, v in event.items() if k not in ("type", "ts")}
        with self.lock:
            if kind == "started" and self.status == "starting":
                self.status = "running"
            elif kind == "sim_mode":
                self.sim_mode = data
            elif kind == "client":
                self.clients.append(data)
            elif kind == "state":
                self.paused = data.get("state") == "paused"
                if self.status in ("running", "paused"):
                    self.status = "paused" if self.paused else "running"
            elif kind == "line":
                self.current_line = data.get("line")
                return  # line changes are state, not history: they would flood the event ring
            elif kind == "labware":
                if len(self.labware) < MAX_TRACKED:
                    self.labware.append(data)
            elif kind == "tips":
                self._apply_tips(data, ts)
            elif kind == "aspirate":
                self._apply_aspirate(data, ts)
            elif kind == "reload":
                if len(self.reloads) < MAX_TRACKED:
                    self.reloads.append({**data, "at": _iso(ts)})
            elif kind == "consumable_warning":
                if len(self.consumable_warnings) < MAX_TRACKED:
                    self.consumable_warnings.append({**data, "at": _iso(ts)})
            elif kind == "prompt":
                self._apply_prompt(data, ts)
            elif kind == "script_exit":
                self.exit_info = data
            self.add_event(kind, ts, **data)

    def _apply_tips(self, data: dict[str, Any], ts: float | None) -> None:
        pool = str(data.get("tip_pool"))
        entry = self.tips.setdefault(
            pool, {"tip_pool": pool, "remaining": None, "capacity": None, "picked_up": 0, "pickups": 0}
        )
        if data.get("remaining") is not None:
            entry["remaining"] = data["remaining"]
        if data.get("capacity") is not None:
            entry["capacity"] = data["capacity"]
        entry["picked_up"] += int(data.get("picked_up") or 0)
        entry["pickups"] += 1
        entry["last_updated"] = _iso(ts)

    def _apply_aspirate(self, data: dict[str, Any], ts: float | None) -> None:
        for reading in data.get("readings", []):
            # "key" (added once the reading's source is a tracked one) is the same pooled-
            # reservoir-vs-per-well convention consumables_config.reagent_key uses; a reading
            # from an untracked position carries no "key" at all, and is recorded here for
            # visibility (raw aspirate numbers) without contributing to a tracked source.
            key = reading.get("key") or f"{reading.get('labware')}@{reading.get('well')}"
            if key not in self.reagents and len(self.reagents) >= MAX_TRACKED:
                continue
            entry = self.reagents.setdefault(
                key,
                {
                    "key": key,
                    "labware": reading.get("labware"),
                    "well": reading.get("well"),
                    "aspirated_ul": 0.0,
                    "aspirates": 0,
                    "total_volume_ul": None,
                    "percent_full": None,
                    "remaining_volume_ul": None,
                },
            )
            entry["aspirated_ul"] += float(reading.get("aspirated_ul") or 0.0)
            entry["aspirates"] += 1
            if reading.get("liquid_volume_ul"):
                entry["last_liquid_volume_ul"] = reading["liquid_volume_ul"]
            if reading.get("liquid_level_mm"):
                entry["last_liquid_level_mm"] = reading["liquid_level_mm"]
            if "remaining_volume_ul" in reading:
                entry["remaining_volume_ul"] = reading["remaining_volume_ul"]
            if "total_volume_ul" in reading:
                entry["total_volume_ul"] = reading["total_volume_ul"]
            if "percent_full" in reading:
                entry["percent_full"] = reading["percent_full"]
            entry["last_updated"] = _iso(ts)

    def _apply_prompt(self, data: dict[str, Any], ts: float | None) -> None:
        prompt_id = str(data.get("prompt_id"))
        self.prompts[prompt_id] = {
            **data,
            "status": "pending",
            "created_at": _iso(ts),
            "resolved_at": None,
            "resolution": None,
        }

    # -- views -----------------------------------------------------------------------------

    def elapsed_s(self) -> float:
        return round((self.ended_at or time.time()) - self.started_at, 1)

    def pending_prompts(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(p) for p in self.prompts.values() if p["status"] == "pending"]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "run_id": self.run_id,
                "script": self.script,
                "sha256": self.sha256,
                "simulate": self.simulate,
                "status": self.status,
                "paused": self.paused,
                "started_at": _iso(self.started_at),
                "ended_at": _iso(self.ended_at),
                "elapsed_s": self.elapsed_s(),
                "exit_code": self.exit_code,
                "error": self.error,
                "error_line": self.error_line,
                "current_line": self.current_line,
                "stop_requested": self.stop_requested,
                "acknowledged": self.acknowledged,
                "system_simulation_mode": self.sim_mode,
                "venus_run_guid": self.venus_run_guid,
                "instrument_serial": self.instrument_serial,
                "clients": list(self.clients),
                "labware": list(self.labware),
                "tips": {k: dict(v) for k, v in self.tips.items()},
                "reagents": {k: dict(v) for k, v in self.reagents.items()},
                "reloads": list(self.reloads),
                "consumable_warnings": list(self.consumable_warnings),
                "pending_prompts": [dict(p) for p in self.prompts.values() if p["status"] == "pending"],
                "prompt_history": [dict(p) for p in self.prompts.values() if p["status"] != "pending"],
                "run_log_file": self.log_file,
                "summary": self.summary,
                "event_count": self.next_seq - 1,
            }


class RunManager:
    def __init__(
        self,
        store: ScriptStore,
        *,
        python: str | None = None,
        child_script: Path | None = None,
        consumables_config: ConsumablesConfigStore | None = None,
        ledger: ConsumablesLedger | None = None,
    ) -> None:
        self._store = store
        self._python = python or sys.executable
        self._child_script = Path(child_script) if child_script is not None else _CHILD_SCRIPT  # tests inject a fake
        self._lock = threading.RLock()
        self._active: Run | None = None
        self._runs: dict[str, Run] = {}
        self._last_finished: Run | None = None
        # Public: server.py's consumables tools read/write these same instances directly
        # (one sqlite connection to the ledger file, rather than one per caller).
        self.consumables_config = consumables_config or ConsumablesConfigStore.default()
        self.ledger = ledger or ConsumablesLedger.default()
        self._sync_thresholds_to_ledger()
        self._mark_interrupted_runs()

    def _sync_thresholds_to_ledger(self) -> None:
        """Push every configured threshold into the ledger's own config table, so
        current_levels()/low_items() (which only ever read from there) agree with what
        set_tip_threshold/register_reagent last set -- including thresholds set in a
        previous process, before this RunManager (and its ledger connection) existed."""
        snapshot = self.consumables_config.snapshot()
        for pool, entry in snapshot.get("tip_pools", {}).items():
            self.ledger.set_config("tip", pool, low_threshold=float(entry["low_threshold"]))
        for key, entry in snapshot.get("reagents", {}).items():
            self.ledger.set_config("reagent", key, label=entry.get("label") or None, low_threshold=float(entry["low_percent"]))

    # -- policy ----------------------------------------------------------------------------

    @staticmethod
    def operator_gate_configured() -> bool:
        return bool(os.environ.get(OPERATOR_TOKEN_ENV, "").strip())

    @staticmethod
    def hardware_runs_allowed() -> bool:
        return os.environ.get(ALLOW_HARDWARE_ENV, "").strip() == "1"

    # -- lifecycle -------------------------------------------------------------------------

    def has_active_run(self) -> bool:
        with self._lock:
            return self._active is not None and self._active.status not in _FINISHED

    async def start_run(
        self,
        script: str,
        *,
        simulate: bool = True,
        max_runtime_s: float | None = None,
        preflight: Callable[[], Awaitable[str | None]] | None = None,
    ) -> Run:
        # No blanket refusal when the operator token isn't set: a script still runs, and an
        # instrument error just defers to VENUS's own local operator dialog instead of trying
        # (and failing) to reach a remote human -- see child_bootstrap._on_operator_escalation's
        # operator_gate_configured branch. Nobody could answer a prompt through this token-less
        # spoke remotely, but that's exactly VENUS's own baseline behavior with no automation
        # involved at all, not a new risk this spoke introduces.
        if not simulate and not self.hardware_runs_allowed():
            raise RunError(
                f"This spoke does not allow real-hardware runs. Set {ALLOW_HARDWARE_ENV}=1 in the spoke's own "
                "environment to enable them (it cannot be enabled through a tool call)."
            )
        if max_runtime_s is not None and max_runtime_s <= 0:
            raise RunError("max_runtime_s must be positive.")

        try:
            data = self._store.read_bytes(script)
        except ValueError as exc:
            raise RunError(str(exc)) from exc
        report = validate_bytes(data, script)
        self._store.record_validation(script, report.to_dict())
        if not report.ok:
            first = "; ".join(
                f"L{i.line}: [{i.rule}] {i.message}" if i.line else f"[{i.rule}] {i.message}" for i in report.errors[:6]
            )
            raise RunError(
                f"{script} does not pass validation ({len(report.errors)} error(s)): {first}. "
                "Fix it and import it again (validate_script shows the full report)."
            )

        if preflight is not None:
            problem = await preflight()
            if problem:
                raise RunError(problem)

        with self._lock:
            if self._active is not None and self._active.status not in _FINISHED:
                raise RunError(
                    f"Run {self._active.run_id} ({self._active.script}) is still {self._active.status}; "
                    "only one script runs at a time."
                )
            run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"
            run = Run(run_id, script, sha256_of(data), simulate, max_runtime_s)
            self._active = run
            self._runs[run_id] = run
            self._prune()
        try:
            self._launch(run, data)
        except Exception as exc:
            run.error = {"type": type(exc).__name__, "message": f"Could not start the script: {exc}"}
            self._finish(run, "failed")
            raise RunError(run.error["message"]) from exc
        return run

    def _launch(self, run: Run, data: bytes) -> None:
        run_dir = self._store.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run.run_dir = run_dir
        script_copy = run_dir / run.script
        script_copy.write_bytes(data)  # run exactly what was just validated
        run_log_dir = run_dir / "runlogs"
        config = {
            "script_path": str(script_copy),
            "simulate": run.simulate,
            "run_log_dir": str(run_log_dir),
            "api_base": venus_api.api_base(),
            "run_id": run.run_id,
            "consumables": self.consumables_config.snapshot(),
            # Lets the child decide, per _on_operator_escalation, whether a remote human could
            # ever answer a prompt -- if not, it defers straight to VENUS's own local dialog
            # (selected_action_id=-1) instead of blocking on _await_prompt indefinitely.
            "operator_gate_configured": self.operator_gate_configured(),
            # Per-command time limit inside the SDK, including the time a person takes to answer
            # an instrument-error prompt (the SDK's own default is 300 s).
            "command_timeout_s": self._command_timeout_s(),
        }
        config_path = run_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k != OPERATOR_TOKEN_ENV}  # a script must never see the token
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        run.proc = subprocess.Popen(
            [self._python, "-u", str(self._child_script), str(config_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(run_dir),
            env=env,
            creationflags=creationflags,
        )
        readers = [
            threading.Thread(target=self._read_stdout, args=(run,), name=f"run-{run.run_id}-out", daemon=True),
            threading.Thread(target=self._read_stderr, args=(run,), name=f"run-{run.run_id}-err", daemon=True),
        ]
        for reader in readers:
            reader.start()
        threading.Thread(target=self._wait, args=(run, readers), name=f"run-{run.run_id}-wait", daemon=True).start()
        if run.max_runtime_s:
            threading.Thread(target=self._watchdog, args=(run,), name=f"run-{run.run_id}-limit", daemon=True).start()
        threading.Thread(target=self._prompt_timeout_watch, args=(run,), name=f"run-{run.run_id}-prompts", daemon=True).start()
        threading.Thread(target=self._watch_venus_run_guid, args=(run,), name=f"run-{run.run_id}-guid", daemon=True).start()
        threading.Thread(target=self._persist_while_running, args=(run,), name=f"run-{run.run_id}-save", daemon=True).start()
        run.add_event("run_started", script=run.script, simulate=run.simulate, sha256=run.sha256)

    _PERSIST_INTERVAL_S = 10.0

    def _persist_while_running(self, run: Run) -> None:
        """Keep the run's record and trace on disk while it runs, not only when it finishes, so a run
        that is cut short (the spoke killed or crashed) still leaves something to look at afterwards."""
        last_seen = -1
        while run.status not in _FINISHED:
            with run.lock:
                seen = run.next_seq
            if seen != last_seen:
                last_seen = seen
                self._persist(run)
            time.sleep(self._PERSIST_INTERVAL_S)

    def _mark_interrupted_runs(self) -> None:
        """A record still saying starting/running/paused belongs to a run whose spoke died before it
        finished (this manager has none in memory yet). Say so, instead of leaving it looking alive."""
        runs_dir = self._store.runs_dir
        if not runs_dir.is_dir():
            return
        for path in runs_dir.glob("*/record.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("status") not in ("starting", "running", "paused"):
                continue
            record["status"] = "interrupted"
            record["error"] = record.get("error") or {
                "type": "Interrupted",
                "message": "The spoke stopped while this run was in progress; how it ended is unknown.",
            }
            try:
                path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            except OSError:
                pass

    def _watch_venus_run_guid(self, run: Run) -> None:
        """Learn VENUS's own GUID for this run from ``GET execution/current-run-data`` (its
        ``runGuid``) as soon as the method is executing, so it is known while the run is still
        going -- and for a run that is aborted or killed, whose SDK run log never gets the GUID in
        its name. Only a method whose name matches the script counts, so another method running on
        the same VENUS is never mistaken for this one."""
        wanted = Path(run.script).stem.lower()
        began = time.monotonic()
        announced = False
        serial_deadline: float | None = None
        while run.status not in _FINISHED:
            try:
                data = venus_api.get_current_run_data()
            except Exception:  # noqa: BLE001 - VENUS being unreachable just means "not yet"
                data = None
            if isinstance(data, dict):
                guid = str(data.get("runGuid") or "").replace("-", "")
                method = re.split(r"[\\/]", str(data.get("methodName") or ""))[-1]
                method_stem = method.rsplit(".", 1)[0].lower() if method else ""
                if guid and (not method_stem or method_stem == wanted):
                    serial = next(
                        (
                            str(item["instrumentSerialNumber"])
                            for item in data.get("instruments") or []
                            if isinstance(item, dict) and item.get("instrumentSerialNumber")
                        ),
                        None,
                    )
                    with run.lock:
                        run.venus_run_guid = guid
                        if serial:
                            run.instrument_serial = serial
                    if not announced:
                        announced = True
                        # data_keys: what VENUS actually returned, so a missing serial can be diagnosed.
                        run.add_event(
                            "venus_run_guid", run_guid=guid, data_keys=sorted(data), after_s=round(time.monotonic() - began, 1)
                        )
                        serial_deadline = time.monotonic() + self._SERIAL_WAIT_S
                    if serial:
                        run.add_event(
                            "instrument_serial", serial=serial, source="current-run-data", after_s=round(time.monotonic() - began, 1)
                        )
                        return
            # The GUID is known from the moment the method starts; the serial only appears in VENUS's
            # run data once the script has connected to the instrument. Keep asking for it on its own
            # (the trace text may supply it first, which says nothing about run-data), for a while.
            if announced and (serial_deadline is None or time.monotonic() > serial_deadline):
                return
            time.sleep(1.0)

    # -- child output ----------------------------------------------------------------------

    def _read_stdout(self, run: Run) -> None:
        assert run.proc is not None and run.proc.stdout is not None
        for raw in iter(run.proc.stdout.readline, b""):
            text, event = decode_line(raw.decode("utf-8", errors="replace"))
            if text.strip():
                run.add_event("stdout", text=_truncate(text.rstrip()))
            if event is not None:
                run.apply_child_event(event)

    def _read_stderr(self, run: Run) -> None:
        assert run.proc is not None and run.proc.stderr is not None
        for raw in iter(run.proc.stderr.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip()
            if text:
                run.add_event("stderr", text=_truncate(text))
                serial = _SERIAL_RE.search(text)
                if serial and run.instrument_serial is None:
                    run.instrument_serial = serial.group(1)
                    run.add_event(
                        "instrument_serial", serial=serial.group(1), source="trace", after_s=round(time.time() - run.started_at, 1)
                    )

    def _wait(self, run: Run, readers: list[threading.Thread]) -> None:
        assert run.proc is not None
        exit_code = run.proc.wait()
        for reader in readers:
            reader.join(timeout=5.0)
        if run.proc.stdin is not None:
            try:
                run.proc.stdin.close()
            except OSError:
                pass
        run.exit_code = exit_code
        info = run.exit_info or {}
        if info.get("error_line"):
            run.error_line = info["error_line"]
        if run.stop_requested:
            status = "stopped"
            if run.timed_out:
                status = "failed"
                run.error = {"type": "Timeout", "message": f"Exceeded max_runtime_s={run.max_runtime_s}."}
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"
            run.error = info.get("error") or {"type": "ExitCode", "message": f"The script exited with code {exit_code}."}
        self._stop_leftover_venus_method(run)
        self._finish(run, status)

    @staticmethod
    def _command_timeout_s() -> float:
        try:
            value = float(os.environ.get(COMMAND_TIMEOUT_ENV, "") or DEFAULT_COMMAND_TIMEOUT_S)
        except ValueError:
            return DEFAULT_COMMAND_TIMEOUT_S
        return value if value > 0 else DEFAULT_COMMAND_TIMEOUT_S

    _LEFTOVER_STATES = {"RUNNING", "PAUSING", "PAUSED", "STARTING"}
    _SERIAL_WAIT_S = 120.0  # how long to keep asking VENUS's run data for the serial after the GUID appears
    _LEFTOVER_GRACE_S = 5.0  # how long VENUS gets to tear the method down on its own
    _LEFTOVER_ABORT_WAIT_S = 10.0  # how long we wait for an abort we sent to take effect

    def _venus_state_name(self) -> str | None:
        try:
            return (venus_api.get_run_state() or {}).get("name")
        except Exception:  # noqa: BLE001 - VENUS unreachable: nothing to clean up from here
            return None

    def _stop_leftover_venus_method(self, run: Run) -> None:
        """The script's process is gone, so nothing may still be running on VENUS for it. A clean
        exit leaves VENUS tearing the method down within moments; but when the SDK's own attempt
        to terminate it fails (seen after a command timed out with an operator prompt open), VENUS
        is left RUNNING with no script behind it and a person has to abort it by hand. If it is
        still running after a short grace period and is *this run's* method, abort it. A method
        that is not ours (different GUID or name) is never touched."""
        deadline = time.monotonic() + self._LEFTOVER_GRACE_S
        name = self._venus_state_name()
        while name in self._LEFTOVER_STATES and time.monotonic() < deadline:
            time.sleep(0.5)
            name = self._venus_state_name()
        if name not in self._LEFTOVER_STATES:
            return
        try:
            data = venus_api.get_current_run_data()
        except Exception:  # noqa: BLE001
            data = None
        if not isinstance(data, dict):
            return
        guid = str(data.get("runGuid") or "").replace("-", "")
        method = re.split(r"[\\/]", str(data.get("methodName") or ""))[-1].rsplit(".", 1)[0].lower()
        ours = (run.venus_run_guid and guid == run.venus_run_guid) or (
            not run.venus_run_guid and method == Path(run.script).stem.lower()
        )
        if not ours:
            return
        try:
            venus_api.abort()
        except Exception as exc:  # noqa: BLE001
            run.add_event("venus_method_abort_failed", state=name, error=str(exc))
            return
        end = time.monotonic() + self._LEFTOVER_ABORT_WAIT_S
        after = self._venus_state_name()
        while after in self._LEFTOVER_STATES and time.monotonic() < end:
            time.sleep(0.5)
            after = self._venus_state_name()
        run.add_event("venus_method_aborted", reason="script exited but VENUS was still running its method", state_before=name, state_after=after)

    def _finish(self, run: Run, status: str) -> None:
        log_dir = (run.run_dir / "runlogs") if run.run_dir else None
        log_path = self._resolve_run_log_path(log_dir) if log_dir is not None else None
        run.log_file = str(log_path) if log_path is not None else None
        if log_path is not None:
            guid = _GUID_IN_LOG_NAME_RE.search(log_path.name)
            if guid:
                run.venus_run_guid = guid.group(1)
        if log_path is not None:
            try:
                log = load_run_log(log_path)  # raises RunLogError for a missing/unreadable/non-JSON log
                if run.venus_run_guid is None:
                    run.venus_run_guid = guid_from_log(log)
                run.summary = summarize_run(log, line_timeline=self._load_line_timeline(log_dir))
            except Exception as exc:  # noqa: BLE001 - a broken log must never block finishing the run
                run.add_event("summary_error", error=str(exc))
        with run.lock:
            run.status = status
            run.paused = False
            run.ended_at = time.time()
        run.add_event("run_finished", status=status, exit_code=run.exit_code, error=run.error, error_line=run.error_line)
        # Recording to the ledger and persisting the run record happen before the active slot
        # clears (not right after run.status flips) -- has_active_run() becoming false is the
        # signal this run's post-processing is actually done, so a caller waiting on it (a test,
        # or another start_run) never observes a "finished" run whose consumables/record aren't
        # written yet.
        self._record_consumables(run, status)
        self._persist(run)
        with self._lock:
            if self._active is run:
                self._active = None
            self._last_finished = run

    @staticmethod
    def _resolve_run_log_path(log_dir: Path) -> Path | None:
        if not log_dir.is_dir():
            return None
        finalized = sorted(log_dir.glob("*_SdkRunLog.json"), key=lambda p: p.stat().st_mtime)
        if finalized:
            return finalized[-1]
        # No finalized log -- the child was killed mid-run (StarClient.__exit__ never ran, so
        # RunLog.finalize() never converted the streaming .jsonl). Recover it into the same
        # finalized shape so the summary and consumables ledger still see whatever was captured
        # up to that point, instead of losing the run's data entirely.
        unfinalized = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not unfinalized:
            return None
        from hamilton_venus._internal._run_log import RunLog

        try:
            return RunLog.recover(unfinalized[-1])
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _load_line_timeline(log_dir: Path) -> list[Any] | None:
        try:
            return json.loads((log_dir / "line_timeline.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _record_consumables(self, run: Run, status: str) -> None:
        """Write this run's consumption to the ledger exactly once (see
        ConsumablesLedger.record_run's run_id uniqueness). Never lets a ledger problem hide the
        run itself -- any failure is reported as an event, not raised."""
        try:
            usage = usage_from_summary(run.summary) if run.summary else []
            record = RunRecord(
                run_id=run.run_id,
                script=run.script,
                sha256=run.sha256,
                started_at=_iso(run.started_at),
                ended_at=_iso(run.ended_at),
                status=status,
                simulate=run.simulate,
                instrument_serial=run.instrument_serial,
                venus_run_guid=run.venus_run_guid,
                partial=(status != "completed"),
            )
            levels: list[dict[str, Any]] = []
            # A simulated run consumes nothing: keep its usage row (reports exclude it by
            # default) but never let it move current levels, thresholds or reload history.
            tracked_tips = {} if run.simulate else run.tips
            tracked_reagents = {} if run.simulate else run.reagents
            for pool, entry in tracked_tips.items():
                if entry.get("remaining") is not None:
                    levels.append(
                        {"kind": "tip", "item_key": pool, "level": entry["remaining"], "capacity": entry.get("capacity"), "source": "run_end"}
                    )
            for key, entry in tracked_reagents.items():
                if entry.get("remaining_volume_ul") is not None:
                    levels.append(
                        {
                            "kind": "reagent",
                            "item_key": key,
                            "level": entry["remaining_volume_ul"],
                            "capacity": entry.get("total_volume_ul"),
                            "source": "run_end",
                        }
                    )
                # A reservoir the script never registered ahead of time is still tracked live
                # (child_bootstrap._should_track_reagent), but that tracking is in-memory only --
                # persist it here so get_consumables_levels/list_low_consumables carry the same
                # default threshold the live warning already used, instead of showing "low: false"
                # forever for an item nobody explicitly registered.
                config_entry = self.consumables_config.record_auto_discovered_reagent(
                    key, entry.get("labware", key), entry.get("well", "all")
                )
                self.ledger.set_config("reagent", config_entry.key, label=config_entry.label or None, low_threshold=float(config_entry.low_percent))
            self.ledger.record_run(record, usage, levels)
            for reload_event in [] if run.simulate else run.reloads:
                self.ledger.add_event(
                    reload_event.get("kind", "unknown"), reload_event.get("item_key", "unknown"), "reload",
                    run_id=run.run_id, ts=reload_event.get("at"),
                )
        except Exception as exc:  # noqa: BLE001 - the run's own outcome must never depend on this
            run.add_event("ledger_error", error=str(exc))

    def _persist(self, run: Run) -> None:
        if run.run_dir is None:
            return
        record = run.snapshot()
        with run.lock:
            all_events = [e.to_dict() for e in run.events]
        record["events_tail"] = all_events[-200:]
        try:
            (run.run_dir / "record.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            # The full trace, so a run's history page still has it after this spoke restarts
            # (the in-memory ring is gone by then). One JSON event per line.
            (run.run_dir / EVENTS_FILE).write_text(
                "\n".join(json.dumps(e, default=str) for e in all_events), encoding="utf-8"
            )
        except OSError:
            pass

    def _prune(self) -> None:
        finished = [r for r in self._runs.values() if r.status in _FINISHED]
        for run in finished[: max(0, len(self._runs) - RECENT_RUNS_KEPT)]:
            self._runs.pop(run.run_id, None)

    # -- watchdogs -------------------------------------------------------------------------

    def _watchdog(self, run: Run) -> None:
        assert run.max_runtime_s is not None
        deadline = run.started_at + run.max_runtime_s
        while run.status not in _FINISHED:
            if time.time() >= deadline:
                run.timed_out = True
                run.add_event("run_timeout", max_runtime_s=run.max_runtime_s)
                self._abort_quietly(run)
                return
            time.sleep(0.5)

    def _abort_quietly(self, run: Run) -> None:
        try:
            self.abort(run.run_id)
        except RunError:
            pass  # it finished on its own between the check and the abort

    def _prompt_timeout_watch(self, run: Run) -> None:
        """Optional safety valve (off by default): abort a run whose prompt nobody answered."""
        try:
            limit = float(os.environ.get(PROMPT_ABORT_AFTER_ENV, "") or 0)
        except ValueError:
            limit = 0
        if limit <= 0:
            return
        while run.status not in _FINISHED:
            now = time.time()
            for prompt in run.pending_prompts():
                created = datetime.fromisoformat(prompt["created_at"]).timestamp() if prompt.get("created_at") else now
                if now - created >= limit:
                    run.add_event("prompt_timeout", prompt_id=prompt["prompt_id"], after_s=limit)
                    self._abort_quietly(run)
                    return
            time.sleep(1.0)

    # -- controls --------------------------------------------------------------------------

    def _live(self, run_id: str | None) -> Run:
        with self._lock:
            run = self._runs.get(run_id) if run_id else self._active
        if run is None:
            raise RunError("No run is active." if run_id is None else f"No run {run_id!r} in memory.")
        if run.status in _FINISHED:
            raise RunError(f"Run {run.run_id} has already {run.status}.")
        return run

    @staticmethod
    def _send(run: Run, line: str) -> None:
        proc = run.proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            raise RunError("The script's process is no longer running.")
        try:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RunError(f"Could not reach the script's process: {exc}") from exc

    def pause(self, run_id: str | None = None) -> dict[str, Any]:
        run = self._live(run_id)
        self._send(run, "PAUSE\n")
        run.add_event("pause_requested")
        return {"run_id": run.run_id, "requested": "pause"}

    def resume(self, run_id: str | None = None) -> dict[str, Any]:
        run = self._live(run_id)
        self._send(run, "RESUME\n")
        run.add_event("resume_requested")
        return {"run_id": run.run_id, "requested": "resume"}

    def abort(self, run_id: str | None = None) -> dict[str, Any]:
        run = self._live(run_id)
        run.stop_requested = True
        run.add_event("abort_requested")
        try:
            self._send(run, "STOP\n")
        except RunError:
            pass
        threading.Thread(target=self._kill_after_grace, args=(run,), name=f"run-{run.run_id}-kill", daemon=True).start()
        return {"run_id": run.run_id, "requested": "abort", "hard_kill_after_s": KILL_GRACE_S}

    def _kill_after_grace(self, run: Run) -> None:
        proc = run.proc
        if proc is None:
            return
        try:
            proc.wait(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            run.add_event(
                "hard_kill",
                note="The script did not stop in time and was killed; VENUS may still hold a running method "
                "(see venus_abort).",
            )
            proc.kill()
            # A hard kill skips the child's own clean shutdown entirely, which is the only place
            # that unregisters this run's client as VENUS's error handler -- left stuck, VENUS
            # never surfaces its own operator dialog for a later run's -1 defer either (confirmed
            # live). This process is still alive and can still reach VENUS's Web API, so clean up
            # after the run we just killed rather than leaving that for whoever hits it next.
            venus_api.clear_error_handler()

    # -- prompts ---------------------------------------------------------------------------

    def resolve_prompt(
        self,
        run_id: str | None,
        prompt_id: str,
        *,
        action: str | None = None,
        channel_actions: dict[str, int] | None = None,
        operator: str | None = None,
        source: str = "operator",
    ) -> dict[str, Any]:
        """Pass a human's answer to the child. Only checks it against the prompt's own options."""
        run = self._live(run_id)
        with run.lock:
            prompt = run.prompts.get(prompt_id)
            if prompt is None or prompt["status"] != "pending":
                raise RunError(f"No pending prompt {prompt_id!r} on run {run.run_id}.")
            options = [str(o).lower() for o in prompt.get("options", [])]
            kind = prompt.get("kind")
            if channel_actions:
                if kind != "operator_error":
                    raise RunError("Per-channel choices only apply to instrument-error prompts.")
                try:
                    picks = {str(k): int(v) for k, v in channel_actions.items()}
                except (TypeError, ValueError) as exc:
                    raise RunError("channel_actions must map a detail uuid to a numeric action id.") from exc
                self._check_channel_picks(prompt, picks)
                response: dict[str, Any] = {"kind": "channels", "channel_actions": picks}
                chosen = "per-channel selection"
                choices = self._describe_channel_picks(prompt, picks)
            else:
                if not action or action.lower() not in options:
                    raise RunError(f"'{action}' is not one of this prompt's options: {', '.join(options)}.")
                chosen = action.lower()
                choices = None
                response = {"kind": "action", "action": chosen} if kind == "operator_error" else {"kind": chosen}
            self._send(run, prompt_response_line(prompt_id, response))
            prompt["status"] = "resolved"
            prompt["resolved_at"] = _iso(time.time())
            prompt["resolution"] = {"action": chosen, "operator": operator or None, "source": source}
            if choices:
                prompt["resolution"]["choices"] = choices
        run.add_event(
            "prompt_resolved", prompt_id=prompt_id, action=chosen, operator=operator or None, source=source,
            **({"choices": choices} if choices else {}),
        )
        return {"run_id": run.run_id, "prompt_id": prompt_id, "resolved": True, "action": chosen}

    @staticmethod
    def _describe_channel_picks(prompt: dict[str, Any], picks: dict[str, int]) -> list[dict[str, Any]]:
        """What a per-channel answer actually chose, by name: one entry per error group, so the
        record says "channels 1-8: Repeat" rather than only "per-channel selection"."""
        described: list[dict[str, Any]] = []
        for row in prompt.get("channel_errors", []):
            names = {int(a["id"]): str(a.get("name", a["id"])) for a in row.get("actions", []) if "id" in a}
            chosen = sorted({names.get(picks[u], str(picks[u])) for u in row.get("detail_uuids", []) if str(u) in picks})
            described.append({"channels": row.get("channels"), "message": row.get("message"), "actions": chosen})
        return described

    @staticmethod
    def _check_channel_picks(prompt: dict[str, Any], picks: dict[str, int]) -> None:
        """A per-channel answer may only use error details, and action ids, the prompt itself
        listed (each error group advertises its own actions), and must cover every one of them."""
        allowed: dict[str, set[int]] = {}
        for row in prompt.get("channel_errors", []):
            ids = {int(a["id"]) for a in row.get("actions", []) if "id" in a}
            for detail_uuid in row.get("detail_uuids", []):
                allowed[str(detail_uuid)] = ids
        if not allowed:
            raise RunError("This prompt offers no per-channel choices; pick one of its options.")
        unknown = sorted(set(picks) - set(allowed))
        if unknown:
            raise RunError(f"Not part of this error: {', '.join(unknown)}.")
        missing = sorted(set(allowed) - set(picks))
        if missing:
            raise RunError(f"A choice is needed for every channel error; missing {len(missing)}.")
        for detail_uuid, action_id in picks.items():
            if action_id not in allowed[detail_uuid]:
                raise RunError(f"Action {action_id} is not one of the options offered for {detail_uuid}.")

    # -- views -----------------------------------------------------------------------------

    def _find(self, run_id: str | None) -> Run | None:
        with self._lock:
            if run_id:
                return self._runs.get(run_id)
            return self._active or self._last_finished

    def get_run(self, run_id: str | None = None) -> dict[str, Any]:
        run = self._find(run_id)
        if run is not None:
            return run.snapshot()
        if run_id:
            record = self._read_record(run_id)
            if record is not None:
                return record
        raise RunError("No such run." if run_id else "No run has happened yet.")

    def get_run_summary(self, run_id: str | None = None) -> dict[str, Any]:
        """The finished run's summary (see hamilton_workflow_framework.run_summary): result,
        duration, step/error counts, failed steps with their script line, instrument errors,
        tips/plates/lids/reservoir volumes used, TADM totals. Computed once when the run
        finishes; a run still in progress has none yet."""
        run = self._find(run_id)
        if run is not None:
            if run.status not in _FINISHED:
                raise RunError(f"Run {run.run_id} is still {run.status}; no summary until it finishes.")
            if run.summary is not None:
                return {"run_id": run.run_id, "script": run.script, "summary": run.summary}
            raise RunError(f"Run {run.run_id} finished with no summary (see its summary_error event).")
        record = self._read_record(run_id) if run_id else None
        if record is not None:
            if record.get("summary") is not None:
                return {"run_id": run_id, "script": record.get("script"), "summary": record["summary"]}
            raise RunError(f"Run {run_id} has no recorded summary.")
        raise RunError("No such run." if run_id else "No run has happened yet.")

    def _read_record(self, run_id: str) -> dict[str, Any] | None:
        if not run_id or any(ch in run_id for ch in "/\\.") or not self._store.runs_dir.is_dir():
            return None
        path = self._store.runs_dir / run_id / "record.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _read_saved_events(self, run_id: str) -> tuple[list[dict[str, Any]], bool] | None:
        """(events, partial) for a finished run that is no longer in memory. ``partial`` is True
        when only the last few events were saved (runs from before the full trace was kept)."""
        if not run_id or any(ch in run_id for ch in "/\\.") or not self._store.runs_dir.is_dir():
            return None
        try:
            lines = (self._store.runs_dir / run_id / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines if line.strip()], False
        except (OSError, ValueError):
            pass
        record = self._read_record(run_id)
        tail = record.get("events_tail") if record else None
        return (tail, True) if tail else None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent first: runs in memory, then records left by earlier server processes."""
        rows: dict[str, dict[str, Any]] = {}
        with self._lock:
            for run in self._runs.values():
                rows[run.run_id] = self._summary(run.snapshot())
        runs_dir = self._store.runs_dir
        if runs_dir.is_dir():
            for path in sorted(runs_dir.glob("*/record.json"), reverse=True)[: max(limit * 2, 20)]:
                run_id = path.parent.name
                if run_id in rows:
                    continue
                try:
                    rows[run_id] = self._summary(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
        return sorted(rows.values(), key=lambda r: r.get("started_at") or "", reverse=True)[:limit]

    @staticmethod
    def _summary(snapshot: dict[str, Any]) -> dict[str, Any]:
        keys = ("run_id", "script", "status", "simulate", "started_at", "ended_at", "elapsed_s", "exit_code", "acknowledged")
        row = {k: snapshot.get(k) for k in keys}
        row["error"] = (snapshot.get("error") or {}).get("message") if snapshot.get("error") else None
        return row

    async def get_events(
        self,
        run_id: str | None = None,
        *,
        since_seq: int = 0,
        max_items: int = 200,
        wait_s: float = 0.0,
        types: set[str] | None = None,
    ) -> dict[str, Any]:
        """Events after *since_seq*, waiting up to *wait_s* for one to arrive (long poll)."""
        run = self._find(run_id)
        if run is None:
            saved = self._read_saved_events(run_id) if run_id else None
            if saved is None:
                raise RunError("No such run in memory." if run_id else "No run has happened yet.")
            events, partial = saved
            max_items = max(1, min(int(max_items), 1000))
            matching = [e for e in events if e.get("seq", 0) > since_seq and (types is None or e.get("type") in types)]
            picked = matching[:max_items]
            last = picked[-1]["seq"] if len(matching) > len(picked) else max([since_seq] + [e.get("seq", 0) for e in events])
            return {
                "run_id": run_id,
                "status": "finished",
                "events": picked,
                "next_since_seq": last,
                "dropped": 0,
                "finished": True,
                "from_disk": True,
                "partial": partial,
            }
        max_items = max(1, min(int(max_items), 1000))
        deadline = time.monotonic() + max(0.0, wait_s)
        while True:
            events, last, dropped = run.events_since(since_seq, max_items, types)
            if events or run.status in _FINISHED or time.monotonic() >= deadline:
                return {
                    "run_id": run.run_id,
                    "status": run.status,
                    "events": events,
                    "next_since_seq": last,
                    "dropped": dropped,
                    "finished": run.status in _FINISHED,
                }
            await asyncio.sleep(0.2)

    def acknowledge(self, run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id) if run_id else self._last_finished
        if run is None:
            raise RunError("No such run.")
        if run.status not in _FINISHED:
            raise RunError(f"Run {run.run_id} is still {run.status}.")
        run.acknowledged = True
        run.add_event("acknowledged")
        self._persist(run)
        return {"run_id": run.run_id, "acknowledged": True}

    # -- spoke state -----------------------------------------------------------------------

    def state(self, *, session_active: bool = False, venus_run_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """The one-word answer the hub shows for this spoke: ``idle`` | ``running`` | ``error``.

        ``error`` means a human is needed: a prompt is waiting, or the last run failed and nobody
        has acknowledged it yet (a new run clears that).
        """
        with self._lock:
            active = self._active if self._active is not None and self._active.status not in _FINISHED else None
            last = self._last_finished
        pending = [{**p, "run_id": active.run_id} for p in active.pending_prompts()] if active is not None else []
        state, error_kind, detail = "idle", None, None
        if pending:
            state, error_kind = "error", "prompt_pending"
            detail = pending[0].get("title") or "An instrument error needs an operator's decision."
        elif active is not None:
            state = "running"
            detail = f"{active.script} ({'paused' if active.paused else 'running'})"
        elif last is not None and last.status == "failed" and not last.acknowledged:
            state, error_kind = "error", "run_failed"
            detail = (last.error or {}).get("message") or f"{last.script} failed."
        run_view = None
        if active is not None:
            run_view = {
                "run_id": active.run_id,
                "script": active.script,
                "simulate": active.simulate,
                "status": active.status,
                "elapsed_s": active.elapsed_s(),
                "current_line": active.current_line,
            }
        last_view = None
        if last is not None:
            last_view = {
                "run_id": last.run_id,
                "script": last.script,
                "status": last.status,
                "ended_at": _iso(last.ended_at),
                "acknowledged": last.acknowledged,
                "error": (last.error or {}).get("message"),
            }
        return {
            "state": state,
            "error_kind": error_kind,
            "detail": detail,
            "paused": bool(active.paused) if active is not None else False,
            "run": run_view,
            "pending_prompts": pending,
            "last_run": last_view,
            "session_active": session_active,
            "venus_run_state": venus_run_state,
            "operator_gate_configured": self.operator_gate_configured(),
            "hardware_runs_allowed": self.hardware_runs_allowed(),
        }
