"""Stop / Resume / Resume From for commands sent one at a time through call_sdk_command.

An external orchestrator (see orchestrator_client) drives the spoke one command per call,
usually from inside its own loop, so the spoke never sees "the workflow" -- only a stream of
commands. RunControl turns that stream into a numbered journal and adds a *hold*:

- An instrument error that ends in Cancel (VenusCommandFailedError) leaves the VENUS method
  alive and listening for the next command. With hold_on_error on, the failed step is held
  instead of reported as an error: the caller gets {"status": "held", "step": N} and waits
  with await_step(N), so the orchestrator's loop just sees one slow call.
- stop() holds the *next* normal command before it runs (a command already in flight
  finishes normally).
- While held, recovery commands (recovery=True -- door unlock/lock, tip eject/pickup, ...)
  run straight away and are journaled without a step number, so they are never replayed.
  Any other normal command is refused until the hold is resolved.
- resume() re-runs the held step and hands its result to the waiting caller. resume_from(K)
  first replays the steps K..N-1 that succeeded, in order, then runs the held step N.
  A failure during either re-holds at that point; resume() then continues from there.
- release_hold() gives up: the waiting caller gets an error.

An ABORT (VenusCommandAbortedError) ends the VENUS method, so it is never held.

The executor passed in does the actual work (catalog lookup, coercion, locking, calling the
client) and returns call_sdk_command's usual {"status": "success"|"error", ...} envelope.
Steps are journaled with their raw JSON kwargs, so a replay coerces them again exactly as
the original call did.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

Executor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
EventSink = Callable[[dict[str, Any]], None]

RUNNING = "running"
STOP_REQUESTED = "stop_requested"
HELD = "held"
RESUMING = "resuming"

# Only a Cancel leaves the VENUS method alive to take the recovery commands and the re-run.
HOLDABLE_ERROR_TYPES = frozenset({"VenusCommandFailedError"})

_MAX_WAIT_S = 25.0
_BRIEF_MESSAGE_CHARS = 400
_MAX_EVENTS = 500
_MAX_ERRORS = 200
# Journal entries kept per session. The oldest finished ones go first, so resume_from can only
# reach back this many commands; a long-running session doesn't grow without limit.
_MAX_JOURNAL = 2000
_POLL_S = 0.1


class RunControlError(RuntimeError):
    """A run-control request that doesn't fit the current state (e.g. resume with nothing
    held, or a normal command sent while a step is held)."""


@dataclass
class JournalEntry:
    step: int | None  # None for a recovery command -- never replayed
    name: str
    kwargs: dict[str, Any]
    recovery: bool = False
    status: str = "running"  # running | held | success | error
    envelope: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "name": self.name,
            "kwargs": self.kwargs,
            "recovery": self.recovery,
            "status": self.status,
            "created_at": self.created_at,
            "attempts": self.attempts,
        }


@dataclass
class _Hold:
    step: int
    reason: str  # "error" | "stop"
    command: str = ""
    error: dict[str, Any] | None = None
    # Steps still to replay before the held step, in order (set by resume_from, or left over
    # from a replay that failed part way).
    replay_pending: list[int] = field(default_factory=list)
    since: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {**self.brief(), "error": self.error}

    def brief(self) -> dict[str, Any]:
        """The hold without the full error response -- small enough for events, webhooks
        and the spoke/hub state."""
        error = self.error or {}
        message = error.get("message")
        return {
            "step": self.step,
            "reason": self.reason,
            "command": self.command,
            "error_type": error.get("error_type"),
            "message": message[:_BRIEF_MESSAGE_CHARS] if isinstance(message, str) else message,
            "error_step": error.get("step", self.step) if error else None,
            "replay_pending": list(self.replay_pending),
            "since": self.since,
        }


class RunControl:
    def __init__(self, on_event: EventSink | None = None) -> None:
        self._on_event = on_event
        # Kept across resets (sessions), so a subscriber's since_seq stays valid.
        self._events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
        self._event_seq = 0
        # Failed commands and operator prompts, kept across resets like the events: a hold that
        # has since cleared, or a failure nobody was holding, is still on record for the hub.
        self._errors: deque[dict[str, Any]] = deque(maxlen=_MAX_ERRORS)
        # The session the events belong to (set by the server when a session starts).
        self.session_id: str | None = None
        self._emit_lock = threading.Lock()
        self.reset()

    # -- state ----------------------------------------------------------------------------

    def reset(self, *, hold_on_error: bool = False) -> None:
        """Forget the journal and any hold. Called whenever a session starts or closes."""
        self.hold_on_error = hold_on_error
        self._journal: list[JournalEntry] = []
        self._steps: dict[int, JournalEntry] = {}
        self._next_step = 1
        self._trimmed_through = 0  # highest step dropped from the journal to stay under _MAX_JOURNAL
        self._state = RUNNING
        self._hold: _Hold | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def hold(self) -> dict[str, Any] | None:
        return self._hold.to_dict() if self._hold else None

    @property
    def hold_brief(self) -> dict[str, Any] | None:
        return self._hold.brief() if self._hold else None

    @property
    def last_event_seq(self) -> int:
        return self._event_seq

    def events_since(self, since_seq: int) -> list[dict[str, Any]]:
        """Hold / resume / release events with seq > since_seq, oldest first."""
        return [e for e in self._events if e["seq"] > since_seq]

    def recent_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        """The last *limit* command failures, holds and operator prompts, oldest first. Each is
        the event as it was published (seq, at, session_id, command, step, message, ...)."""
        return list(self._errors)[-limit:] if limit > 0 else []

    def summary(self, journal_tail: int = 20) -> dict[str, Any]:
        return {
            "state": self._state,
            "hold_on_error": self.hold_on_error,
            "hold": self.hold,
            "last_step": self._next_step - 1,
            "journal": [e.to_dict() for e in self._journal[-journal_tail:]] if journal_tail > 0 else [],
        }

    def journal(self, since_step: int = 0, include_recovery: bool = True) -> list[dict[str, Any]]:
        out = []
        for entry in self._journal:
            if entry.recovery:
                if include_recovery:
                    out.append(entry.to_dict())
            elif entry.step is not None and entry.step > since_step:
                out.append(entry.to_dict())
        return out

    # -- commands ---------------------------------------------------------------------------

    async def submit(self, name: str, kwargs: dict[str, Any], execute: Executor) -> dict[str, Any]:
        """A normal (journaled, replayable) command."""
        if self._state in (HELD, RESUMING):
            raise RunControlError(
                f"Step {self._hold.step if self._hold else '?'} is held ({self._state}). Send recovery "
                "commands with recovery=True, then resume / resume_from / release_hold before sending "
                f"{name!r} as a normal command."
            )
        entry = self._new_step(name, kwargs)
        if self._state == STOP_REQUESTED:
            entry.status = HELD
            self._enter_hold(_Hold(step=entry.step, reason="stop"))
            return self._held_envelope(entry)

        # A stop() that arrives while this runs lets it finish; the next normal command holds.
        envelope = await self._attempt(entry, execute, kind="original")
        if entry.status == HELD:
            return self._held_envelope(entry)
        return envelope

    async def run_recovery(self, name: str, kwargs: dict[str, Any], execute: Executor) -> dict[str, Any]:
        """A recovery command: runs whatever the hold state, journaled but never replayed."""
        entry = JournalEntry(step=None, name=name, kwargs=dict(kwargs), recovery=True)
        self._journal.append(entry)
        self._trim_journal()
        try:
            envelope = await execute(name, kwargs)
        except Exception as exc:
            entry.status = "error"
            entry.attempts.append({"kind": "recovery", "at": time.time(), "status": "error", "message": str(exc)})
            raise
        entry.status = envelope.get("status", "error")
        entry.envelope = envelope
        entry.attempts.append(_attempt_record("recovery", envelope))
        return envelope

    async def await_step(self, step: int, wait_s: float = 20.0) -> dict[str, Any]:
        """The final envelope of *step* once it is done, or a fresh "held" envelope if it is
        still waiting after wait_s (clamped to 25 s, so a relayed HTTP call never times out)."""
        entry = self._steps.get(step)
        if entry is None:
            raise RunControlError(f"No step {step} in this session's journal.")
        # A short poll rather than an asyncio.Condition: this object lives at module level and
        # outlives any one event loop, which a Condition would be bound to.
        deadline = time.monotonic() + max(0.0, min(float(wait_s), _MAX_WAIT_S))
        while not self._is_final(entry) and time.monotonic() < deadline:
            await asyncio.sleep(_POLL_S)
        if self._is_final(entry):
            return entry.envelope or {"command": entry.name, "status": entry.status, "step": step}
        return self._held_envelope(entry)

    # -- control ------------------------------------------------------------------------------

    def request_stop(self) -> dict[str, Any]:
        if self._state == RUNNING:
            self._state = STOP_REQUESTED
            self._emit({"type": "run_control", "event": "stop_requested"})
        return self.summary(journal_tail=0)

    async def resume(self, execute: Executor) -> dict[str, Any]:
        """Re-run the held step (after any replays still pending) and release its caller."""
        if self._state == STOP_REQUESTED:
            self._state = RUNNING  # nothing was held yet: just cancel the stop
            self._emit({"type": "run_control", "event": "resumed"})
            return self.summary(journal_tail=0)
        self._check_held()
        return await self._run_hold(execute)

    async def resume_from(self, step: int, execute: Executor) -> dict[str, Any]:
        """Replay the successful normal steps step..held-1, in order, then re-run the held step."""
        if self._state == STOP_REQUESTED:
            # Stopped between commands with nothing held: replay up to the last step, then run on.
            last = self._next_step - 1
            self._check_replay_start(step, last + 1)
            self._state = RESUMING
            try:
                for replay_step in self._replayable(step, last + 1):
                    envelope = await self._attempt(self._steps[replay_step], execute, kind="replay", replay=True)
                    if envelope.get("status") != "success":
                        # No caller is waiting on anything: stay stopped so the next command holds.
                        self._state = STOP_REQUESTED
                        return {**self.summary(journal_tail=0), "result": envelope}
            except BaseException:
                self._state = STOP_REQUESTED
                raise
            self._state = RUNNING
            self._emit({"type": "run_control", "event": "resumed", "from_step": step})
            return self.summary(journal_tail=0)
        self._check_held()
        self._check_replay_start(step, self._hold.step)
        self._hold.replay_pending = self._replayable(step, self._hold.step)
        return await self._run_hold(execute)

    def release_hold(self, message: str | None = None) -> dict[str, Any]:
        """Fail the held step so its waiting caller gets an error, and go back to running."""
        if self._hold is None:
            if self._state == STOP_REQUESTED:
                self._state = RUNNING
                self._emit({"type": "run_control", "event": "released", "step": None})
                return self.summary(journal_tail=0)
            raise RunControlError(f"Nothing is held (state {self._state}).")
        if self._state == RESUMING:
            raise RunControlError("A resume is in progress; wait for it to finish or hold again.")
        entry = self._steps[self._hold.step]
        text = message or "Released by the operator without completing the step."
        entry.status = "error"
        entry.envelope = {
            "command": entry.name,
            "status": "error",
            "step": entry.step,
            "error_type": "HoldReleased",
            "message": text,
            "last_error": self._hold.error,
            "timestamp": time.time(),
        }
        entry.attempts.append({"kind": "release", "at": time.time(), "status": "error", "message": text})
        self._hold = None
        self._state = RUNNING
        self._emit({"type": "run_control", "event": "released", "step": entry.step})
        return self.summary(journal_tail=0)

    # -- internals ----------------------------------------------------------------------------

    def _new_step(self, name: str, kwargs: dict[str, Any]) -> JournalEntry:
        entry = JournalEntry(step=self._next_step, name=name, kwargs=dict(kwargs))
        self._next_step += 1
        self._journal.append(entry)
        self._steps[entry.step] = entry
        self._trim_journal()
        return entry

    def _trim_journal(self) -> None:
        """Drop the oldest finished entries beyond _MAX_JOURNAL. The held step and the steps
        still queued for replay are never dropped."""
        excess = len(self._journal) - _MAX_JOURNAL
        if excess <= 0:
            return
        protected = set(self._hold.replay_pending) if self._hold else set()
        if self._hold:
            protected.add(self._hold.step)
        kept: list[JournalEntry] = []
        for index, entry in enumerate(self._journal):
            if excess > 0 and self._is_final(entry) and entry.step not in protected:
                excess -= 1
                if entry.step is not None:
                    del self._steps[entry.step]
                    self._trimmed_through = max(self._trimmed_through, entry.step)
            else:
                kept.append(entry)
                if excess <= 0:
                    kept.extend(self._journal[index + 1 :])
                    break
        self._journal = kept

    def _replayable(self, start: int, stop: int) -> list[int]:
        return [s for s in range(start, stop) if s in self._steps and self._steps[s].status == "success"]

    def _check_held(self) -> None:
        if self._state == RESUMING:
            raise RunControlError("A resume is already in progress.")
        if self._state != HELD or self._hold is None:
            raise RunControlError(f"Nothing is held (state {self._state}).")

    def _check_replay_start(self, step: int, held_step: int) -> None:
        if step < 1 or step > held_step:
            raise RunControlError(f"resume_from step must be between 1 and {held_step} (the held step); got {step}.")
        if step <= self._trimmed_through:
            raise RunControlError(
                f"Step {step} is no longer in the journal (only the last {_MAX_JOURNAL} commands are kept; "
                f"steps up to {self._trimmed_through} were dropped), so the replay would skip steps. "
                "Pick a later step."
            )

    async def _run_hold(self, execute: Executor) -> dict[str, Any]:
        assert self._hold is not None
        hold = self._hold
        self._state = RESUMING
        self._emit({"type": "run_control", "event": "resuming", "step": hold.step, "replay": list(hold.replay_pending)})
        try:
            while hold.replay_pending:
                replay_step = hold.replay_pending[0]
                envelope = await self._attempt(self._steps[replay_step], execute, kind="replay", replay=True)
                if self._state == HELD or self._hold is None:
                    # Held again at this replay step, or failed beyond recovery (the waiting
                    # step has been failed too).
                    return {**self.summary(journal_tail=0), "result": envelope}
                hold.replay_pending.pop(0)
            entry = self._steps[hold.step]
            self._hold = None
            envelope = await self._attempt(entry, execute, kind="resume")
            if entry.status == HELD:
                return {**self.summary(journal_tail=0), "result": envelope}
            if self._state == RESUMING:
                self._state = RUNNING
            self._emit({"type": "run_control", "event": "resumed", "step": entry.step, "status": entry.status})
            return {**self.summary(journal_tail=0), "result": envelope}
        except BaseException:
            # The executor itself raised (not an instrument error): stay held so nothing is lost.
            if self._hold is None:
                self._hold = hold
            self._state = HELD
            raise

    async def _attempt(
        self, entry: JournalEntry, execute: Executor, *, kind: str, replay: bool = False
    ) -> dict[str, Any]:
        """Run *entry* once. On a holdable error, hold: a replayed step holds the *original*
        held step (keeping the rest of the replay queued), any other step holds itself."""
        try:
            envelope = await execute(entry.name, entry.kwargs)
        except Exception as exc:
            entry.attempts.append({"kind": kind, "at": time.time(), "status": "error", "message": str(exc)})
            if not replay and entry.status != HELD:
                entry.status = "error"
            self._emit_command_error(entry, type(exc).__name__, str(exc), kind=kind)
            raise
        envelope = {**envelope, "step": entry.step}
        entry.attempts.append(_attempt_record(kind, envelope))

        if envelope.get("status") == "success":
            if not replay:
                entry.status = "success"
                entry.envelope = envelope
            return envelope

        holdable = envelope.get("error_type") in HOLDABLE_ERROR_TYPES
        error = {k: v for k, v in envelope.items() if k not in ("command", "status", "step")}
        if replay:
            # The replayed step's own earlier success stands; the hold stays on the waiting step.
            if holdable and self._hold is not None:
                self._hold.error = {"step": entry.step, "replay": True, **error}
                self._state = HELD
                self._emit({"type": "run_hold", **self._hold.brief(), "failed_command": entry.name})
            else:
                # Abort or other non-recoverable failure mid-replay: fail the waiting step too.
                self._fail_hold(envelope, entry)
            return envelope

        if holdable and (self.hold_on_error or kind == "resume"):
            # Once a step has been held, a failed re-run stays held whatever hold_on_error says.
            entry.status = HELD
            self._enter_hold(_Hold(step=entry.step, reason="error", error=error))
            return envelope

        entry.status = "error"
        entry.envelope = envelope
        self._emit_command_error(entry, envelope.get("error_type"), envelope.get("message"), kind=kind)
        return envelope

    def _emit_command_error(self, entry: JournalEntry, error_type: Any, message: Any, *, kind: str) -> None:
        """Publish a failure nobody is holding, so subscribers hear about it without polling."""
        self._emit(
            {
                "type": "command_error",
                "step": entry.step,
                "command": entry.name,
                "attempt": kind,
                "recovery": entry.recovery,
                "error_type": error_type,
                "message": message[:_BRIEF_MESSAGE_CHARS] if isinstance(message, str) else message,
                "held": False,
            }
        )

    def _fail_hold(self, envelope: dict[str, Any], failed: JournalEntry) -> None:
        hold = self._hold
        if hold is None:
            return
        waiting = self._steps[hold.step]
        waiting.status = "error"
        waiting.envelope = {
            **envelope,
            "command": waiting.name,
            "step": waiting.step,
            "message": f"Replay of step {failed.step} ({failed.name}) failed: {envelope.get('message')}",
        }
        self._hold = None
        self._state = RUNNING
        self._emit({"type": "run_control", "event": "replay_failed", "step": waiting.step, "failed_step": failed.step})

    def _enter_hold(self, hold: _Hold) -> None:
        hold.command = self._steps[hold.step].name
        self._hold = hold
        self._state = HELD
        self._emit({"type": "run_hold", **hold.brief(), "failed_command": hold.command})

    def _held_envelope(self, entry: JournalEntry) -> dict[str, Any]:
        return {
            "command": entry.name,
            "status": "held",
            "step": entry.step,
            "state": self._state,
            "hold": self.hold,
            "timestamp": time.time(),
        }

    @staticmethod
    def _is_final(entry: JournalEntry) -> bool:
        return entry.status in ("success", "error")

    def emit(self, event: dict[str, Any]) -> None:
        """Add an outside event (e.g. a spoke status change) to the same numbered stream."""
        self._emit(event)

    def _emit(self, event: dict[str, Any]) -> None:
        with self._emit_lock:
            self._event_seq += 1
            event = {
                "seq": self._event_seq,
                "at": time.time(),
                "state": self._state,
                "session_id": self.session_id,
                **event,
            }
            self._events.append(event)
            if _is_error_event(event):
                self._errors.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                pass


def _is_error_event(event: dict[str, Any]) -> bool:
    kind = event.get("type")
    return kind in ("command_error", "operator_prompt") or (kind == "run_hold" and event.get("reason") == "error")


def _attempt_record(kind: str, envelope: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {"kind": kind, "at": time.time(), "status": envelope.get("status")}
    if envelope.get("status") != "success":
        record["error_type"] = envelope.get("error_type")
        record["message"] = envelope.get("message")
    return record
