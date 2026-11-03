"""Runs a flow through the MCP bridge: the interpreter walks the cards, one `call_sdk_command` per SDK card.

Which cards run is a *selection* by card id in document order (see flow.select): all, this card
only, from here, up to here, or a start..end range. Loops run their body per iteration; a card picked
inside a loop runs one pass. Disabled cards are reported as skipped. Stop and Pause take effect
between cards (a command already sent finishes first, as VENUS cannot take one back); an error stops
the run at the failing card, which is held on the spoke when hold-on-error is on, so Retry / Stop run
can continue it.

Events (published as dicts): {"type": "run", "state", ...} and {"type": "step", "id", "status", ...}
where a loop card also reports "iteration" / "total", and a Prompt card has status "prompt".
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from backend import flow, params as params_mod, variables as variables_mod
from backend.command_catalog import STUDIO_CONNECT
from backend.mcp_bridge import BridgeError

MODES = ("all", "only", "from", "to", "range")
_MAX_RESPONSE_CHARS = 20_000


class RunError(Exception):
    """The run cannot start (bad selection, nothing to run, already running)."""


def select_steps(steps: list[dict[str, Any]], mode: str, start_id: str | None = None, end_id: str | None = None) -> list[dict[str, Any]]:
    """The cards a run covers, in document order. `start_id` / `end_id` are card ids."""
    if mode not in MODES:
        raise RunError(f"Unknown run mode {mode!r}")
    try:
        picked = flow.select(steps, mode, start_id, end_id)
    except flow.FlowError as exc:
        raise RunError(str(exc)) from exc
    order = flow.flat(steps)
    return order if picked is None else [s for s in order if s["id"] in picked]


def missing_required(step: dict[str, Any], command: dict[str, Any] | None) -> str | None:
    """A message when the card cannot be sent as it stands, else None."""
    if command is None:
        return f"{step.get('command')} is not available on this instrument"
    absent = [p["label"] for p in command["params"] if p["required"] and p["name"] not in step.get("params", {})]
    return f"Missing required: {', '.join(absent)}" if absent else None


def _summarize(result: Any) -> Any:
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)[:_MAX_RESPONSE_CHARS]
    if len(text) <= _MAX_RESPONSE_CHARS:
        return json.loads(text)
    return {"truncated": True, "preview": text[:_MAX_RESPONSE_CHARS]}


def validate(
    steps: list[dict[str, Any]],
    values: dict[str, Any],
    included: set[str] | None,
    find_command: Callable[[str], dict[str, Any] | None],
    extra_names: set[str] | None = None,
) -> list[tuple[str, str]]:
    """(card id, message) for everything that stops the selected cards from running. `extra_names` are
    variables set elsewhere in the flow (another tab) that these cards may use."""
    extra = extra_names or set()
    numbering = flow.labels(steps)
    order = flow.flat(steps)
    picked = [s for s in order if (included is None or s["id"] in included) and s.get("enabled", True)]
    problems: list[tuple[str, str]] = []
    for step in picked:
        message = missing_required(step, find_command(step["command"]))
        if message:
            problems.append((step["id"], f"Card {numbering[step['id']]}: {message}"))
    names = set(values) | extra | flow.provided_names(steps) | {"last"}
    for step in picked:
        undefined = sorted(variables_mod.find_refs(step.get("params", {})) - names)
        if undefined:
            problems.append((step["id"], f"Card {numbering[step['id']]}: undefined variable(s) " + ", ".join("{{" + n + "}}" for n in undefined)))
    for step in picked:
        wrong = sorted(variables_mod.bad_conversions(step.get("params", {})))
        if wrong:
            problems.append((step["id"], f"Card {numbering[step['id']]}: unknown conversion {', '.join('|' + w for w in wrong)} (use {', '.join('|' + c for c in variables_mod.CONVERSIONS)})"))
    touched = {s["id"] for s in picked}
    problems += [(sid, msg) for sid, msg in flow.problems(steps, set(values) | extra) if included is None or sid in touched]
    return problems


class FlowRunner:
    def __init__(
        self,
        bridge: Any,
        publish: Callable[[dict[str, Any]], None],
        find_command: Callable[[str], dict[str, Any] | None],
    ) -> None:
        self._bridge = bridge
        self._publish = publish
        self._find_command = find_command
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._resume_gate = threading.Event()
        self._resume_gate.set()
        self._answer = threading.Event()
        self._answer_value: str | None = None
        self._stop = False
        self._held = False  # the running card is held on the spoke after an instrument error
        self.state = "idle"  # idle | running | paused | stopped | done | error
        self.message: str | None = None  # why the last run ended in error
        self.run_id: str | None = None
        self.step_status: dict[str, dict[str, Any]] = {}
        self._values: dict[str, Any] = {}

    # -- control -------------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.state in ("running", "paused")

    def start(
        self,
        steps: list[dict[str, Any]],
        mode: str = "all",
        start_id: str | None = None,
        end_id: str | None = None,
        variables: list[dict[str, Any]] | None = None,
        overrides: dict[str, Any] | None = None,
        subflows: list[dict[str, Any]] | None = None,
        main: list[dict[str, Any]] | None = None,
    ) -> str:
        with self._lock:
            if self.active:
                raise RunError("A run is already in progress")
            if mode not in MODES:
                raise RunError(f"Unknown run mode {mode!r}")
            try:
                steps = flow.expand(steps, subflows)  # a Run Subflow card now holds the cards it runs
                included = flow.select(steps, mode, start_id, end_id)
                values = variables_mod.values_of(variables or [], overrides)
            except (flow.FlowError, variables_mod.VariableError) as exc:
                raise RunError(str(exc)) from exc
            picked = [s for s in flow.flat(steps) if (included is None or s["id"] in included) and s.get("enabled", True)]
            if not picked:
                raise RunError("Nothing to run: every selected card is skipped")
            problems = validate(steps, values, included, self._find_command, flow.names_elsewhere(main, subflows))
            if problems:
                raise RunError(f"{len(problems)} problem(s) stop this run. {problems[0][1]}")
            self._values = values
            self.run_id = uuid.uuid4().hex[:8]
            self._stop = False
            self._resume_gate.set()
            self._answer.clear()
            self.step_status = {}
            self.message = None
            self.state = "running"
            self._thread = threading.Thread(target=self._run, args=(steps, included), name=f"studio-run-{self.run_id}", daemon=True)
            self._thread.start()
            return self.run_id

    def pause(self) -> None:
        if self.state == "running":
            self._resume_gate.clear()
            self._set_state("paused")

    def unpause(self) -> None:
        if self.state == "paused":
            self._set_state("running")
            self._resume_gate.set()

    def stop(self) -> None:
        """Stop after the card that is running now. A card held on an error is released (cancelled)
        on the spoke, or the worker would wait on the hold forever and the session stay locked."""
        if self.active:
            self._stop = True
            self._resume_gate.set()
            self._answer.set()
            if self._held:
                try:
                    self._bridge.release_hold("Stopped from SDK Studio")
                except BridgeError:
                    pass  # the hold may have been released or retried meanwhile

    def answer(self, value: str | None) -> None:
        """The person's reply to a Prompt card (None = cancel, which stops the run)."""
        if value is None:
            self.stop()
            return
        self._answer_value = value
        self._answer.set()

    # -- worker --------------------------------------------------------------------------------

    def _set_state(self, state: str, **extra: Any) -> None:
        self.state = state
        self._publish({"type": "run", "state": state, "run_id": self.run_id, **extra})

    def _event(self, event: dict[str, Any]) -> None:
        if "status" in event:
            record = {"type": "step", "run_id": self.run_id, **event}
        else:  # a note about the card (what it saved): added to its record, not a new status
            record = {**self.step_status.get(event["id"], {"status": "success"}), **event, "type": "step", "run_id": self.run_id}
        self.step_status[event["id"]] = record
        self._publish(record)

    def _run(self, steps: list[dict[str, Any]], included: set[str] | None) -> None:
        ids = [s["id"] for s in flow.flat(steps) if included is None or s["id"] in included]
        self._publish({"type": "run", "state": "running", "run_id": self.run_id, "ids": ids})
        hooks = flow.Hooks(leaf=self._leaf, event=self._event, checkpoint=self._checkpoint, prompt=self._prompt, wait=self._wait)
        interpreter = flow.Interpreter(hooks, self._values, included)
        try:
            interpreter.run(steps)
        except flow.Stopped:
            self._set_state("stopped")
        except flow.StepFailed as exc:
            if self.step_status.get(exc.step_id, {}).get("status") != "error":
                self._event({"id": exc.step_id, "status": "error", "message": exc.message})
            if self._stop:  # the person stopped the run (releasing a held card fails it): not an error
                self._set_state("stopped")
                return
            self.message = exc.message
            self._set_state("error", step_id=exc.step_id, message=exc.message)
        except flow.FlowError as exc:
            self.message = str(exc)
            self._set_state("error", message=self.message)
        except Exception as exc:  # noqa: BLE001 - a worker thread must report, never die silently
            self.message = f"{type(exc).__name__}: {exc}"
            self._set_state("error", message=self.message)
        else:
            self._set_state("done")

    def _checkpoint(self) -> None:
        self._resume_gate.wait()
        if self._stop:
            raise flow.Stopped

    def _wait(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._checkpoint()
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _prompt(self, step: dict[str, Any], message: str) -> str | None:
        self._answer.clear()
        self._answer_value = None
        self._event({"id": step["id"], "status": "prompt", "message": message, "ask": bool(step.get("params", {}).get("store_in"))})
        self._answer.wait()
        if self._stop:
            raise flow.Stopped
        return self._answer_value

    def _leaf(self, step: dict[str, Any], params: dict[str, Any]) -> Any:
        step_id = step["id"]
        started = time.monotonic()

        def held(info: dict[str, Any]) -> None:
            hold = info.get("hold") if isinstance(info.get("hold"), dict) else {}
            text = hold.get("message") or info.get("message") or "Held after an instrument error"
            self._held = True
            self._event({"id": step_id, "status": "held", "message": str(text), "hold": hold or None})

        try:
            if step["command"] == STUDIO_CONNECT:
                result = self._bridge.connect_instrument(initialize=params.get("initialize", True))
            else:
                fitted = params_mod.coerce_references(step.get("params", {}), params, self._find_command(step["command"]))
                result = self._bridge.run_command(step["command"], fitted, on_held=held)
        except BridgeError as exc:
            message = str(exc)
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
        else:
            self._held = False
            self._event({"id": step_id, "status": "success", "response": _summarize(result), "duration_ms": int((time.monotonic() - started) * 1000)})
            return result
        self._held = False
        self._event({"id": step_id, "status": "error", "message": message, "duration_ms": int((time.monotonic() - started) * 1000)})
        raise flow.StepFailed(step_id, message)

    def snapshot(self) -> dict[str, Any]:
        return {"type": "snapshot", "state": self.state, "run_id": self.run_id, "steps": self.step_status, "message": self.message}
