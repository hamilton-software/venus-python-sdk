"""Sequential/immediate execution of a step list against a live StarClient session.

Generalized from the hamilton-star-demo-app's original execution_engine.py: this
module knows nothing about STAR-specific concepts like liquid-handling settings
profiles. Anything app-specific plugs in via three extension points supplied to
``ExecutionEngine.__init__``:

- ``kwargs_builder``: resolves an entry's raw form params into real Python kwargs.
- ``on_settings_profile`` / ``reset_state``: optional hooks for apps that have their
  own notion of a named, in-session "profile" pseudo-step (see demo_app's
  aspirate/dispense settings profiles) -- the engine only knows to call these at the
  right moments, not what a profile *is*.
- ``step_observers``: fire after a step's SDK call succeeds, with the exact kwargs
  sent and the raw result -- this is the hook consumables/monitoring tracking plugs
  into (see hamilton_workflow_framework.consumables / .monitoring).
- ``on_pause`` / ``on_resume``: optional hooks for apps that need a physical or
  procedural safety action at a pause boundary (see :meth:`ExecutionEngine.request_pause`) --
  e.g. unlocking the front cover for an operator to intervene, then re-locking it
  before the run continues. The engine only knows *when* to call these, never what
  they do.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Coroutine, Protocol

from hamilton_venus.exceptions import VenusCommandFailedError, VenusError
from hamilton_venus.models import CommandResponse

from hamilton_workflow_framework.registry import CommandRegistry, RegistryEntry
from hamilton_workflow_framework.session import WorkflowSession

_logger = logging.getLogger("hamilton_workflow_framework.execution")

SendFn = Callable[[dict], Awaitable[None]]
KwargsBuilder = Callable[[RegistryEntry, dict[str, Any]], dict[str, Any]]


@dataclass
class Step:
    step_id: str
    command_id: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class StepObserver(Protocol):
    """Observes successful step executions to maintain app-level tracking state
    (tip/reagent consumption, sample status, liquid-level/TADM readings, ...).

    Only called after a step's SDK call has succeeded -- observer state should
    reflect reality, not attempted-but-failed calls. Exceptions raised here are
    logged and swallowed; a tracking bug must never fail the step itself.
    """

    async def after_step(
        self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step, send: SendFn
    ) -> None: ...


def _default_kwargs_builder(entry: RegistryEntry, raw_params: dict[str, Any]) -> dict[str, Any]:
    """Trivial passthrough kwargs builder: resolves enum params by member name,
    drops unset/empty values, passes everything else through as-is. Apps with
    richer needs (settings-profile objects, DSL position splitting, ...) supply
    their own ``kwargs_builder`` instead.
    """
    kwargs: dict[str, Any] = {}
    for spec in entry.params:
        value = raw_params.get(spec.name, spec.default)
        if value is None or value == "":
            continue
        if spec.type == "enum" and spec.enum_cls is not None and not isinstance(value, spec.enum_cls):
            kwargs[spec.name] = spec.enum_cls[str(value)]
        else:
            kwargs[spec.name] = value
    return kwargs


def _response_to_json(result: Any) -> dict[str, Any] | None:
    if isinstance(result, CommandResponse):
        return result.model_dump(mode="json", by_alias=True)
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json", by_alias=True)
    if isinstance(result, bool):
        return {"result": result}
    if result is None:
        return None
    return {"result": result}


class ExecutionEngine:
    def __init__(
        self,
        session: WorkflowSession,
        send: SendFn,
        registry: CommandRegistry,
        *,
        kwargs_builder: KwargsBuilder = _default_kwargs_builder,
        on_settings_profile: Callable[[RegistryEntry, dict[str, Any]], None] | None = None,
        reset_state: Callable[[], None] | None = None,
        step_observers: list[StepObserver] | None = None,
        on_pause: Callable[[], Awaitable[None]] | None = None,
        on_resume: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._send = send
        self._registry = registry
        self._kwargs_builder = kwargs_builder
        self._on_settings_profile = on_settings_profile
        self._reset_state = reset_state
        self._step_observers = step_observers or []
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._steps: list[Step] = []
        self._stop_requested = False
        self._pause_requested = False
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._active_task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Whether a run()/run_from()/run_immediate() background task is in flight.

        routes_ws.py dispatches those as background tasks (via spawn()) instead of
        awaiting them inline in the WS receive loop -- inline, the loop couldn't call
        receive_json() again while a command sat blocked on operator escalation,
        deadlocking the connection against its own operator_prompt_response. This
        guard replaces the serialization that inline awaiting used to provide for free.
        """
        return self._active_task is not None and not self._active_task.done()

    @property
    def is_paused(self) -> bool:
        """Whether the active run is currently suspended between steps (see
        :meth:`request_pause`). ``is_running`` stays True while paused -- it's
        still the same run, just holding at a step boundary.
        """
        return self._paused

    def spawn(self, coro_factory: Callable[[], Coroutine[Any, Any, None]]) -> bool:
        """Schedule the coroutine from *coro_factory* as the tracked background run task.

        Takes a zero-arg factory rather than an already-built coroutine so that
        nothing is constructed (and then silently discarded, which Python warns
        about as "coroutine was never awaited") when a run is already active.

        Returns False (scheduling nothing) if a run is already active.
        """
        if self.is_running:
            return False
        self._active_task = asyncio.create_task(coro_factory())
        return True

    def load_steps(self, steps: list[Step]) -> None:
        self._steps = steps

    def request_stop(self) -> None:
        self._stop_requested = True

    def request_pause(self) -> None:
        """Ask the active run to suspend once the in-flight step finishes.

        Never interrupts a step that's already running (mid-flight instrument
        calls are never aborted by this) -- it only holds the *next* step back
        until :meth:`request_resume` is called. No-op if nothing is running.
        """
        if self.is_running:
            self._pause_requested = True

    def request_resume(self) -> None:
        """Release a run suspended by :meth:`request_pause`. No-op if not paused --
        callers should gate this on :attr:`is_paused` to avoid a resume arriving
        before the pause has actually taken effect racing ahead of it.
        """
        if self._paused:
            self._resume_event.set()

    async def _maybe_pause(self) -> None:
        if not self._pause_requested:
            return
        self._pause_requested = False
        self._paused = True
        self._resume_event.clear()
        if self._on_pause is not None:
            await self._on_pause()
        await self._resume_event.wait()
        self._paused = False
        if self._on_resume is not None:
            await self._on_resume()

    async def run(self) -> None:
        if self._reset_state is not None:
            self._reset_state()
        await self._run_steps(self._steps)

    async def run_from(self, start_step_id: str) -> None:
        """Run the loaded steps starting at start_step_id (inclusive), skipping
        everything before it. Used to resume a queue after fixing a parameter
        that caused an earlier run to stop on error, without re-running steps
        that already succeeded.

        Any settings-profile-style steps before the resume point are replayed
        (silently, no instrument calls) so their profiles are still available to
        steps at or after start_step_id that reference them.
        """
        start_index = next((i for i, s in enumerate(self._steps) if s.step_id == start_step_id), None)
        if start_index is None:
            raise KeyError(f"Unknown step_id: {start_step_id!r}")

        if self._reset_state is not None:
            self._reset_state()
        if self._on_settings_profile is not None:
            for step in self._steps[:start_index]:
                if not step.enabled:
                    continue
                try:
                    entry = self._registry.get_entry(step.command_id)
                except KeyError:
                    continue
                if entry.is_settings_profile:
                    self._on_settings_profile(entry, step.params)

        await self._run_steps(self._steps[start_index:])

    async def _run_steps(self, steps: list[Step]) -> None:
        self._stop_requested = False
        self._pause_requested = False
        for step in steps:
            if self._stop_requested:
                break
            succeeded = await self._execute_step(step)
            if not succeeded:
                break
            await self._maybe_pause()

    async def run_immediate(self, command_id: str, params: dict[str, Any]) -> None:
        step = Step(step_id=f"immediate-{uuid.uuid4().hex[:8]}", command_id=command_id, params=params)
        await self._execute_step(step)

    async def _notify_observers(self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step) -> None:
        for observer in self._step_observers:
            try:
                await observer.after_step(entry, kwargs, result, step, self._send)
            except Exception:
                _logger.exception("Step observer failed for %s (step_id=%s)", entry.command_id, step.step_id)

    async def _execute_step(self, step: Step) -> bool:
        if not step.enabled:
            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "skipped",
                "response": None,
                "error": None,
                "message": "Skipped (step disabled).",
            })
            return True

        try:
            entry = self._registry.get_entry(step.command_id)
        except KeyError as exc:
            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "error",
                "response": None,
                "error": {"type": "UnknownCommand", "message": str(exc)},
                "message": str(exc),
            })
            return False

        await self._send({
            "type": "step_result",
            "step_id": step.step_id,
            "command_id": step.command_id,
            "status": "running",
            "response": None,
            "error": None,
            "message": f"Running {entry.label}...",
        })

        started_at = time.monotonic()

        try:
            kwargs: dict[str, Any] = {}
            if entry.is_settings_profile:
                if self._on_settings_profile is not None:
                    self._on_settings_profile(entry, step.params)
                result = None
                message = f"Defined settings profile {step.params.get('profile_name', '')!r}."
            elif entry.is_raw:
                category = step.params.get("category", "")
                action_name = step.params.get("action_name", "")
                parameters = json.loads(step.params.get("parameters_json") or "{}")
                result = await asyncio.to_thread(self._session.star.send_command, category, action_name, parameters)
                message = f"{entry.label} completed."
            else:
                kwargs = self._kwargs_builder(entry, step.params)
                method = getattr(self._session.resolve_command_target(entry.method_name), entry.method_name)
                result = await asyncio.to_thread(lambda: method(**kwargs))
                message = f"{entry.label} completed."

            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "success",
                "response": _response_to_json(result),
                "error": None,
                "message": message,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            })
            if not entry.is_settings_profile and not entry.is_raw:
                await self._notify_observers(entry, kwargs, result, step)
            return True
        except VenusCommandFailedError as exc:
            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "error",
                "response": exc.response.model_dump(mode="json", by_alias=True),
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "message": str(exc),
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            })
            return False
        except VenusError as exc:
            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "error",
                "response": None,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "message": str(exc),
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            })
            return False
        except Exception as exc:  # noqa: BLE001 - surface any unexpected error to the UI, not just SDK errors
            _logger.exception("Unexpected error executing step %s", step.command_id)
            await self._send({
                "type": "step_result",
                "step_id": step.step_id,
                "command_id": step.command_id,
                "status": "error",
                "response": None,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "message": str(exc),
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            })
            return False
