"""Runs one stored script inside its own process, under the MCP server's control.

Started by ``RunManager`` as ``python -u child_bootstrap.py <config.json>``. It does not edit the
script. Instead, before running it (``runpy``), it patches ``StarClient``/``VantageClient`` --
the same technique Script Manager's runner uses -- so that whichever one the script builds:

* runs with the *run's* simulate setting, whatever the script says (VENUS's system-wide
  simulation mode is synced to match);
* records a structured SDK run log;
* hands every error the SDK cannot recover from by itself, and every tip/liquid reload
  request, to a human through the parent, and waits for the answer -- nothing is ever
  resolved automatically;
* reports labware added, tips picked up, and the liquid level seen at each aspirate.

The parent talks to this process over stdin/stdout (see ``protocol``). While the script runs,
``sys.monitoring``, restricted to the script's own file, tracks the current line so a pause takes effect at the next line boundary as well as at VENUS's own
command granularity, and the failing line can be reported.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import runpy
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from hamilton_venus_mcp import instrument_guard
from hamilton_venus_mcp.script_runs.container_volume import LabwareGeometryCache
from hamilton_venus_mcp.script_runs.protocol import encode_event

_config: dict[str, Any] = {}
_emit_lock = threading.Lock()

_captured_clients: list[Any] = []
_pause_requested = threading.Event()
_resume_now = threading.Event()
_stop_requested = threading.Event()
_finished = threading.Event()  # set once the script has ended and its exit event is out
_prompt_events: dict[str, threading.Event] = {}
_prompt_responses: dict[str, Any] = {}
_answered: dict[str, int] = {}  # instrument-error uuid -> how many times a person has been asked
_reasking: set[str] = set()  # error uuids whose "is it still pending?" check is under way
_deferred_notified: set[str] = set()  # error uuids already reported via operator_error_deferred
_state_lock = threading.Lock()
_state = "running"
_status_listener_registered: set[int] = set()

_script_path = ""
_current_line = 0
_error_line: int | None = None
_line_timeline: list[tuple[float, int]] = []  # (line start epoch_seconds, line), for the summary
_line_started_at = 0.0
# A line is only added to _line_timeline if it ran at least this long. Recording every executed
# line kept millions of samples for a loop; anything that issues an instrument command takes
# longer than this, and that is all the summary's command-to-line lookup needs.
_TIMELINE_MIN_SECONDS = 0.002

# -- consumables tracking state ---------------------------------------------------------------
# Populated from config.json's "consumables" block (see manager.RunManager._launch), written by
# ConsumablesConfigStore.snapshot(): {"tip_pools": {pool: {"low_threshold": n}}, "reagents":
# {key: {"labware":..., "well":..., "low_percent":...}}}. Empty/missing sections mean "no
# configured threshold for anything" -- tracking (and reservoir_labware log entries) still
# happens, just without a low-level warning ever firing.
_tip_thresholds: dict[str, int] = {}
_reagent_thresholds: dict[str, float] = {}
_reagent_capacities: dict[str, float] = {}  # per-reagent capacity overrides (uL), from register_reagent
_geometry: LabwareGeometryCache | None = None
_reagent_state: dict[str, dict[str, float | None]] = {}  # key -> {"remaining_ul", "total_ul"}
_reagent_below_threshold: set[str] = set()  # edge-trigger guard for consumable_warning
_tip_below_threshold: set[str] = set()
_tip_capacity_cache: dict[str, int | None] = {}
_reservoir_logged: set[str] = set()  # labware ids already written as a reservoir_labware entry


def emit(event_type: str, **data: Any) -> None:
    line = encode_event(event_type, **data)
    with _emit_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def _log(level: str, message: str) -> None:
    emit("log", level=level, source="runner", message=message)


def _set_state(new_state: str) -> None:
    global _state
    with _state_lock:
        if new_state == _state:
            return
        _state = new_state
    emit("state", state=new_state)


# -- VENUS system-wide simulation mode -------------------------------------------------------


def _sync_system_simulation_mode(simulate: bool) -> None:
    """``StarClient(simulate=...)`` only changes how VENUS *executes* a method; which instrument
    (real or simulated) answers is this separate, system-wide VENUS setting. Set it to match
    the run, and report what it was, so the change is never a surprise."""
    url = _config["api_base"].rstrip("/") + "/system/configuration/simulation"
    headers = {"accept": "text/plain; x-api-version=3.0"}
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            previous = response.text.strip().strip('"').lower() == "true"
            changed = previous != simulate
            if changed:
                put = client.put(url, headers=headers, params={"simulationMode": str(simulate).lower()})
                put.raise_for_status()
        emit("sim_mode", previous=previous, current=simulate, changed=changed)
    except Exception as exc:  # noqa: BLE001 - reported; the run can still proceed
        _log("WARNING", f"Could not sync VENUS system-wide simulation mode: {exc}")
        emit("sim_mode", previous=None, current=None, changed=False, error=str(exc))


# -- operator prompts ------------------------------------------------------------------------


def _await_prompt(prompt_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Emit a prompt and block this thread until the parent relays a human's answer (or the
    run is stopped, which answers ``None``)."""
    event = threading.Event()
    _prompt_events[prompt_id] = event
    emit("prompt", prompt_id=prompt_id, **payload)
    event.wait()
    _prompt_events.pop(prompt_id, None)
    return _prompt_responses.pop(prompt_id, None)


def _on_operator_escalation(context: Any) -> Any:
    """``StarClient(on_operator_error_escalation=...)``: runs on the SDK's escalation worker
    thread, so blocking here is fine. Returning None means ABORT to the SDK.

    Only ever registered (see ``_patch_client_class``) when the spoke's operator gate is
    configured -- when it isn't, the client is built with no callback at all, so the SDK's own
    resolver submits its well-formed legacy-dialog fallback itself, untouched by this function.
    """
    from hamilton_workflow_framework.session import (
        _describe_error,
        _known_action_names,
        recovery_from_operator_response,
    )

    from hamilton_venus.error_handling.access_actions import access_actions

    error = context.error
    title, channel_errors = _describe_error(error)
    options = _known_action_names(context.top_level_actions)
    if "abort" not in options:
        options.append("abort")  # always available: an unanswered/None result is an abort anyway
    # Unlock/lock door, raise/lower load tray: answering with one does not resolve the error --
    # the SDK submits it and calls this again (a new attempt, its own audited prompt) with the
    # republished error, which then lists the opposite action.
    access = access_actions(error)
    options.extend(item["key"] for item in access)
    error_uuid = str(error.uuid)
    attempt = _answered.get(error_uuid, 0) + 1
    _answered[error_uuid] = attempt
    response = _await_prompt(
        error_uuid if attempt == 1 else f"{error_uuid}#{attempt}",  # each ask is its own audited prompt
        {
            "kind": "operator_error",
            "code": error.code,
            "title": title,
            "channel_errors": channel_errors,
            "options": options,
            "access_actions": access,
            "attempt": attempt,
        },
    )
    return recovery_from_operator_response(error, response, lambda text: _log("WARNING", text))


def _find_unhandled(client: Any, error_uuid: str) -> Any:
    for error in client._run(client._connected_instrument.venus.get_unhandled_errors()):
        if error.uuid == error_uuid:
            return error
    return None


def _ask_again_if_still_pending(client: Any, error_uuid: str) -> None:
    """After a person's answer, VENUS re-notifies the same error when the fix did not take (a
    repeat that fails again). The SDK only follows that up for retries it tracks itself, not for
    a payload a callback submitted, so nobody would be asked and VENUS would wait forever. Give
    VENUS a moment to settle; if the error is still unhandled, hand it back to the SDK's resolver
    as the new occurrence it is, which runs it through the same profile and operator callback."""
    try:
        time.sleep(2.0)
        pending = None
        for _ in range(5):
            if _stop_requested.is_set() or _finished.is_set():
                return
            try:
                pending = _find_unhandled(client, error_uuid)
            except RuntimeError:
                return  # the script finished and closed its client while we were waiting
            if pending is None:
                return  # VENUS moved on: the fix worked
            time.sleep(1.0)
        _log("WARNING", f"Error {error_uuid} is still unhandled after the operator's answer; asking again.")
        client._run(client._connected_instrument._error_resolver.on_instrument_error(pending))
    except Exception as exc:  # noqa: BLE001
        if not (_stop_requested.is_set() or _finished.is_set()):
            _log("WARNING", f"Could not re-raise error {error_uuid} to the operator: {exc}")
    finally:
        _reasking.discard(error_uuid)


def _report_deferred_error(client: Any, error_uuid: str) -> None:
    """Best-effort visibility for an error the spoke never tried to decide on its own behalf
    (no operator token configured -- see _on_error_notification). VENUS's own resolver has
    already submitted its legacy-dialog fallback by the time this runs; this only looks up what
    the error was so it shows up in get_run_events/the dashboard, purely informational."""
    from hamilton_workflow_framework.session import _describe_error

    try:
        error = _find_unhandled(client, error_uuid)
    except Exception:  # noqa: BLE001 - never let a lookup failure affect the run
        error = None
    if error is None:
        # Already resolved (VENUS's own dialog, or the fallback cleared it) by the time we
        # looked -- still worth a line in the trace that *something* happened here.
        emit("operator_error_deferred", code=None, title=f"Instrument error {error_uuid} (already resolved locally)", channel_errors=[])
        return
    title, channel_errors = _describe_error(error)
    emit("operator_error_deferred", code=error.code, title=title, channel_errors=channel_errors)


def _on_tip_reload_prompt(context: Any) -> bool:
    response = _await_prompt(
        f"tip_reload:{uuid.uuid4().hex[:12]}",
        {
            "kind": "tip_reload",
            "title": (
                f"Tip pool {context.tip_pool!r} is short on tips: {context.available} available, "
                f"{context.required} needed ({context.command}). Reload the tip rack, then continue."
            ),
            "detail": {
                "tip_pool": context.tip_pool,
                "required": context.required,
                "available": context.available,
                "command": context.command,
                "attempt": context.attempt,
            },
            "options": ["continue", "abort"],
        },
    )
    continued = bool(response and response.get("kind") == "continue")
    if continued:
        # An operator reload, not usage -- the consumables ledger records this as a reload
        # event against the pool, not as tips consumed.
        emit("reload", kind="tip", item_key=context.tip_pool, command=context.command)
    return continued


def _on_liquid_reload_prompt(context: Any) -> bool:
    response = _await_prompt(
        f"liquid_reload:{uuid.uuid4().hex[:12]}",
        {
            "kind": "liquid_reload",
            "title": (
                f"Liquid source {context.active_source!r} is running low: about {context.available} uL "
                f"per channel left, {context.required} uL needed ({context.command}). "
                "Refill it, then continue."
            ),
            "detail": {
                "active_source": context.active_source,
                "sources": list(context.sources),
                "required": context.required,
                "available": context.available,
                "command": context.command,
                "attempt": context.attempt,
            },
            "options": ["continue", "abort"],
        },
    )
    continued = bool(response and response.get("kind") == "continue")
    if continued:
        labware = str(context.active_source).partition("@")[0]
        emit("reload", kind="reagent", item_key=labware, command=context.command)
        _reagent_state.pop(labware, None)  # the refill invalidates any running estimate for it
    return continued


# -- control channel (parent -> child) -------------------------------------------------------


def _call_on_clients(what: str, make_coro: Any) -> None:
    for client in list(_captured_clients):
        try:
            client._run(make_coro(client))
        except Exception as exc:  # noqa: BLE001
            _log("WARNING", f"{what} failed: {exc}")


def _do_pause() -> None:
    _pause_requested.set()
    # VENUS's own executor pause takes effect at its command granularity, so a compound
    # command notices a pause without running to the end of its internal loop; the line
    # trace covers pure-Python stretches with no VENUS call in flight.
    _call_on_clients("pause_method()", lambda c: c._connected_instrument.venus.pause_method())


def _do_resume() -> None:
    _resume_now.set()
    # A resume also settles any pause request that had not been seen yet, or the next traced
    # line would read it as a fresh pause and silently block the script again.
    _pause_requested.clear()
    _call_on_clients("resume_method()", lambda c: c._connected_instrument.venus.resume_method())


def _release_waiters() -> None:
    for prompt_id, event in list(_prompt_events.items()):
        _prompt_responses[prompt_id] = None
        event.set()
    _resume_now.set()


# How long STOP waits for the SDK's instrument_terminate() before moving on. It can block for a long
# time when a command is still waiting on an operator prompt (seen live: the terminate attempt failed
# ~30 s later), and everything after it -- clearing VENUS's error handler above all -- must still run.
_TERMINATE_WAIT_S = 15.0
_UNWIND_GRACE_S = 10.0  # after the MCP server is gone: time for the script's `with` block to unwind, then exit


def _terminate_clients() -> None:
    def terminate(client: Any) -> None:
        try:
            client.instrument_terminate()
        except Exception as exc:  # noqa: BLE001
            _log("WARNING", f"instrument_terminate() failed: {exc}")

    workers = [
        threading.Thread(target=terminate, args=(client,), name="stop-terminate", daemon=True)
        for client in list(_captured_clients)
    ]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + _TERMINATE_WAIT_S
    for worker in workers:
        worker.join(max(0.0, deadline - time.monotonic()))
        if worker.is_alive():
            _log("WARNING", f"instrument_terminate() did not return within {_TERMINATE_WAIT_S:g} s; continuing.")


def _do_stop(reason: str) -> None:
    _stop_requested.set()
    _log("WARNING", f"Stopping ({reason}).")
    # A hard kill would leave VENUS with a method it thinks is still running; terminate through
    # the SDK first so VENUS tears it down, letting the script's own `with` block exit cleanly.
    _terminate_clients()
    _release_waiters()
    # instrument_terminate() does not unregister this client as VENUS's error handler -- only a
    # clean __aexit__ does, and if the script's own `with` block doesn't unwind in time (still
    # blocked on something), RunManager's hard kill will skip that entirely. Best-effort attempt
    # it here too, before that's even a possibility -- see venus_api.clear_error_handler's own
    # note for why a stuck registration matters (VENUS won't show its own operator dialog for a
    # later run while it's stuck true).
    try:
        from hamilton_venus_mcp import venus_api

        venus_api.clear_error_handler()
    except Exception as exc:  # noqa: BLE001
        _log("WARNING", f"clear_error_handler() failed: {exc}")


def _detach_control_channel() -> Any:
    """Move the parent's control pipe off the process's standard input and point stdin at NUL.

    The control reader sits in a blocking read on this pipe for the whole run. On Windows, while
    a synchronous read is pending on a pipe handle, every other operation on that handle --
    GetFileType, DuplicateHandle -- blocks until the read completes. Library imports touch the
    standard handles (numpy/pandas via ``platform`` and ``subprocess``), so a script doing
    ``import numpy`` hung until the next control line arrived, which in practice was the STOP.
    Keeping the pipe on a private fd nobody else knows about avoids that."""
    control_fd = os.dup(sys.stdin.fileno())
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    sys.stdin = open(0, encoding="utf-8", errors="replace", closefd=False)  # noqa: SIM115
    return open(control_fd, encoding="utf-8", errors="replace")  # noqa: SIM115


def _control_reader(control: Any) -> None:
    for raw in control:
        command = raw.strip()
        if command == "PAUSE":
            _do_pause()
        elif command == "RESUME":
            _do_resume()
        elif command == "STOP":
            _do_stop("stop requested")
        elif command.startswith("PROMPT_RESPONSE "):
            _, _, rest = command.partition(" ")
            prompt_id, _, payload = rest.partition(" ")
            try:
                response = json.loads(payload)
            except ValueError:
                response = None  # malformed -> treated as no answer -> abort
            _prompt_responses[prompt_id] = response if isinstance(response, dict) else None
            event = _prompt_events.get(prompt_id)
            if event is not None:
                event.set()
    if _finished.is_set():
        return  # the script already ended; the parent closing stdin now is just cleanup
    # stdin closed mid-run: the MCP server is gone, so nobody can answer a prompt or stop this
    # run. Fail safe instead of carrying on unsupervised.
    _do_stop("the MCP server disconnected")
    time.sleep(_UNWIND_GRACE_S)
    os._exit(3)


# -- VENUS pause/resume seen from outside ----------------------------------------------------


def _register_status_listener(client: Any) -> None:
    """Follow VENUS's own runtime status, so the run's state stays right when someone pauses or
    resumes from VENUS's Run Control panel instead of through the MCP server."""
    if id(client) in _status_listener_registered:
        return
    _status_listener_registered.add(id(client))
    try:
        from hamilton_venus.models.enums import ExecutorEvent

        async def _on_status(event: Any) -> None:
            if event.event == ExecutorEvent.PAUSED:
                _set_state("paused")
            elif event.event == ExecutorEvent.RUNNING and _state == "paused":
                _resume_now.set()
                _pause_requested.clear()
                _set_state("running")

        async def _on_error_notification(notification: Any) -> None:
            error_uuid = str(notification).strip()
            if not _config.get("operator_gate_configured") and error_uuid not in _deferred_notified:
                # No callback is registered in this mode (see _patch_client_class), so nothing
                # here decides the recovery -- the SDK's own resolver already submitted its
                # legacy-dialog fallback on its own. This is purely visibility: look up what the
                # error actually was so get_run_events/the dashboard shows it happened, without
                # touching the decision VENUS already has in hand.
                _deferred_notified.add(error_uuid)
                threading.Thread(
                    target=_report_deferred_error, args=(client, error_uuid), name="error-deferred-report", daemon=True
                ).start()
            if error_uuid not in _answered or error_uuid in _reasking or _stop_requested.is_set():
                return
            _reasking.add(error_uuid)
            threading.Thread(
                target=_ask_again_if_still_pending, args=(client, error_uuid), name="error-reask", daemon=True
            ).start()

        listener = client._connected_instrument._listener
        listener.on_runtime_status(_on_status)
        listener.on_instrument_error_notification(_on_error_notification)
    except Exception as exc:  # noqa: BLE001
        _log("WARNING", f"Could not follow VENUS pause/resume and error state: {exc}")


# -- tracking --------------------------------------------------------------------------------


def _wrap(cls: type, name: str, after: Any, impl_name: str | None = None) -> None:
    """Wrap ``cls.name`` so ``after(client, bound_arguments, result)`` runs on return. Tracking
    can never break the script: anything it raises is reported and swallowed."""
    original = getattr(cls, name, None)
    if original is None or getattr(original, "_hve_wrapped", False):
        return
    # The public channel commands are generic (self, *args, **kwargs) pass-throughs, so bind the
    # arguments against the real implementation's signature to recover them by name.
    template = getattr(cls, impl_name, None) if impl_name else None
    try:
        signature = inspect.signature(template if template is not None else original)
    except (TypeError, ValueError):
        signature = None

    @functools.wraps(original)
    def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        try:
            bound: dict[str, Any] = dict(kwargs)
            if signature is not None:
                try:
                    binding = signature.bind(self, *args, **kwargs)
                    binding.apply_defaults()
                    bound = dict(binding.arguments)
                except TypeError:
                    pass
            after(self, bound, result)
        except Exception as exc:  # noqa: BLE001
            emit("tracking_error", method=name, error=f"{type(exc).__name__}: {exc}")
        return result

    patched._hve_wrapped = True  # type: ignore[attr-defined]
    setattr(cls, name, patched)


def _return_parameters(result: Any) -> Any:
    return getattr(result, "return_parameters", None)


def _track_labware(method: str) -> Any:
    def after(client: Any, bound: dict[str, Any], result: Any) -> None:
        params = _return_parameters(result)
        name = None
        if isinstance(params, dict):
            name = params.get("labwareName")
        else:
            name = getattr(params, "labware_name", None)
        # When VENUS echoes a name back (the `name` branch above), it is already lower-cased --
        # VENUS stores every labware id on the deck layout lower-cased regardless of the case
        # the script added it with. The `bound.get(...)` fallback (VENUS omitted labwareName)
        # keeps the script's own original casing instead. Either way, this event's
        # `labware_name` may not match the casing a script used in its own `positions=`
        # selector strings elsewhere -- see deck_labware_commands.py's module docstring.
        emit(
            "labware",
            method=method,
            definition=bound.get("labware_definition"),
            labware_name=name or bound.get("plate_id") or bound.get("labware_id"),
            carrier_id=bound.get("carrier_id"),
            site=bound.get("site"),
            left_track=bound.get("left_track"),
            tip_pool=bound.get("tip_pool"),
        )

    return after


def _tip_pool_capacity(client: Any, tip_pool: str) -> int | None:
    """Nominal rack capacity for *tip_pool*, resolved once and cached (fixed for the run,
    changes only via a reload -- see ``_on_tip_reload_prompt``, which does not clear this: the
    physical rack count a pool draws from does not change on a mid-run reload, only its fill
    level does).

    ``tipPool.getTipCounter``'s own response has no direct "capacity" field; reconstructed from
    ``totalAvailableTips + totalEmptyTips`` for a freshly-initialized pool, or (once real usage
    history makes that undercount) from how many distinct rack ids the counter has ever
    referenced across its available/empty lists, times the standard 96-tip rack size.
    """
    if tip_pool in _tip_capacity_cache:
        return _tip_capacity_cache[tip_pool]
    capacity = None
    try:
        params = client.tip_pool_get_tip_counter(tip_pool).return_parameters
        rack_ids: set[str] = set()
        for entry in params.available_tips:
            rack_ids.update(entry.keys())
        for entry in params.empty_tips:
            rack_ids.update(entry.keys())
        rack_count = len(rack_ids) + len(params.missing_racks)
        if rack_count:
            capacity = 96 * rack_count
    except Exception:  # noqa: BLE001 - capacity is advisory; never let it break a pickup
        capacity = None
    _tip_capacity_cache[tip_pool] = capacity
    return capacity


def _track_tip_pickup(client: Any, bound: dict[str, Any], result: Any) -> None:
    tip_pool = bound.get("tip_pool")
    if not tip_pool:
        return
    params = _return_parameters(result)
    remaining = params.get("remainingTips") if isinstance(params, dict) else getattr(params, "remaining_tips", None)
    channels = bound.get("channels") or getattr(client, "_DEFAULT_CHANNELS", None) or []
    capacity = _tip_pool_capacity(client, tip_pool)
    emit("tips", tip_pool=tip_pool, remaining=remaining, capacity=capacity, picked_up=len(channels))
    if isinstance(remaining, int):
        _check_tip_threshold(tip_pool, remaining)


def _check_tip_threshold(tip_pool: str, remaining: int) -> None:
    threshold = _tip_thresholds.get(tip_pool)
    if threshold is None:
        return
    now_low = remaining < threshold
    if now_low and tip_pool not in _tip_below_threshold:
        emit("consumable_warning", kind="tip", item_key=tip_pool, level=remaining, threshold=threshold)
    if now_low:
        _tip_below_threshold.add(tip_pool)
    else:
        _tip_below_threshold.discard(tip_pool)


_DEFAULT_REAGENT_LOW_PERCENT = 0.10


def _should_track_reagent(key: str, labware: str) -> bool:
    # Already tracked (registered ahead of time, or auto-discovered earlier this run) -- keep
    # tracking it. Otherwise only auto-track labware whose own definition identifies it as a
    # reservoir -- avoids treating every one-off sample-plate well as a tracked source.
    if key in _reagent_state or key in _reagent_thresholds:
        return True
    return _geometry is not None and _geometry.is_reservoir(labware)


def _update_reagent_state(client: Any, key: str, labware: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Same algorithm as Script Manager's ``_update_reservoir``: a measured reading always
    overrides the running estimate (VENUS re-measures every aspirate); with no usable
    measurement, decrement the last known estimate by what was aspirated. Returns the reading
    to merge into the emitted event for this key."""
    is_new = key not in _reagent_state
    state = _reagent_state.setdefault(key, {"remaining_ul": None, "total_ul": None})
    if is_new and _geometry is not None:
        capacity = _reagent_capacities.get(key) or _geometry.max_volume_ul(labware)
        if capacity:
            state["total_ul"] = capacity
            state["remaining_ul"] = 0.0  # safe assumption pending a real measurement

    measured = [(r["liquid_level_mm"], r["liquid_volume_ul"]) for r in readings if r.get("liquid_volume_ul")]
    if measured:
        avg_volume = sum(v for _h, v in measured) / len(measured)
        state["remaining_ul"] = avg_volume
        capacity = _reagent_capacities.get(key) or (_geometry.max_volume_ul(labware) if _geometry is not None else None)
        if capacity:
            state["total_ul"] = capacity
    else:
        aspirated_sum = sum(r.get("aspirated_ul") or 0.0 for r in readings)
        if state["remaining_ul"] is not None:
            state["remaining_ul"] = max(0.0, state["remaining_ul"] - aspirated_sum)

    remaining = state["remaining_ul"]
    total = state["total_ul"]
    percent = min(1.0, remaining / total) if remaining is not None and total else None
    if percent is not None:
        low_percent = _reagent_thresholds.get(key, _DEFAULT_REAGENT_LOW_PERCENT)
        now_low = percent < low_percent
        if now_low and key not in _reagent_below_threshold:
            emit("consumable_warning", kind="reagent", item_key=key, level=percent, threshold=low_percent)
        if now_low:
            _reagent_below_threshold.add(key)
        else:
            _reagent_below_threshold.discard(key)
    return {"remaining_volume_ul": remaining, "total_volume_ul": total, "percent_full": percent}


def _log_reservoir_labware(client: Any, labware: str) -> None:
    """Write a ``reservoir_labware`` entry into the SDK's own run log the first time a
    reservoir-class labware is seen -- ``summarize_run`` (the run summary) can only recognize a
    reservoir from a fresh ``labware.addReservoir`` request or this entry; a reservoir that was
    already on a loaded deck never re-issues that request, so without this its volume would
    silently drop out of the summary's reservoir tally."""
    if labware in _reservoir_logged:
        return
    _reservoir_logged.add(labware)
    run_log = getattr(client, "_run_log", None)
    if run_log is not None:
        run_log.record("Bootstrap", "Out", "reservoir_labware", {"labware": labware})


def _track_aspirate(client: Any, bound: dict[str, Any], result: Any) -> None:
    channel_data = getattr(_return_parameters(result), "channels", None)
    if not channel_data:
        return
    from hamilton_venus.models.position import normalize_positions

    channels = bound.get("channels") or getattr(client, "_DEFAULT_CHANNELS", None) or []
    positions = normalize_positions(
        bound.get("positions"),
        channel_count=len(channels),
        get_spec=client.get_labware_spec,
        channel_pitch_mm=getattr(client, "_CHANNEL_PITCH_MM", None),
    )
    by_channel = dict(zip(channels, positions, strict=False))
    raw_readings: dict[str, list[dict[str, Any]]] = {}
    ordered_readings: list[dict[str, Any]] = []
    for data in channel_data:
        position = by_channel.get(data.channel)
        if position is None:
            continue
        reading = {
            "labware": position.labware,
            "well": position.well,
            "channel": data.channel,
            "liquid_volume_ul": data.liquid_volume_ul,
            "liquid_level_mm": data.liquid_level_mm,
            "aspirated_ul": data.aspirated_volume,
        }
        ordered_readings.append(reading)
        # A reservoir's several channel sub-positions are the SAME physical pool -- pooled by
        # bare labware id, so multi-channel readings from it are averaged as one source, not
        # fragmented into one tracked item per sub-position; anything else is tracked per well.
        pooled = _geometry is not None and _geometry.is_reservoir(position.labware)
        key = position.labware if pooled else f"{position.labware}@{position.well}"
        raw_readings.setdefault(key, []).append(reading)

    if not ordered_readings:
        return

    for key, group in raw_readings.items():
        labware = group[0]["labware"]
        if not _should_track_reagent(key, labware):
            continue
        if _geometry is not None and _geometry.is_reservoir(labware):
            _log_reservoir_labware(client, labware)
        state = _update_reagent_state(client, key, labware, group)
        for reading in group:
            reading.update(key=key, **state)

    emit("aspirate", readings=ordered_readings)


def _mph96_pickup_count(bound: dict[str, Any], *, full: bool) -> int:
    if full:
        return 96
    # A 96-well plate is 8 rows x 12 columns -- a column pickup grabs 8 tips per column, a row
    # pickup grabs 12 tips per row (same reasoning as Script Manager's own MPH96 tip tracking).
    mode = bound.get("mode")
    count = bound.get("count") or 0
    mode_value = str(getattr(mode, "value", mode)).lower()
    return count * 12 if mode_value == "rows" else count * 8


def _track_tip_pickup_mph96(*, full: bool) -> Any:
    def after(client: Any, bound: dict[str, Any], result: Any) -> None:
        tip_pool = bound.get("tip_pool")
        if not tip_pool:
            return
        params = _return_parameters(result)
        remaining = params.get("remainingTips") if isinstance(params, dict) else getattr(params, "remaining_tips", None)
        capacity = _tip_pool_capacity(client, tip_pool)
        emit(
            "tips",
            tip_pool=tip_pool,
            remaining=remaining,
            capacity=capacity,
            picked_up=_mph96_pickup_count(bound, full=full),
        )
        if isinstance(remaining, int):
            _check_tip_threshold(tip_pool, remaining)

    return after


def _track_aspirate_mph96(client: Any, bound: dict[str, Any], result: Any) -> None:
    """Same reagent-state tracking as ``_track_aspirate``, but the MPH96 head aspirates all 96
    positions in one operation with one liquid-level/volume reading for the whole head, not one
    per channel -- so this builds a single synthetic reading instead of one per position."""
    labware = bound.get("labware_id")
    if not labware:
        return
    params = _return_parameters(result)
    if isinstance(params, dict):
        level = params.get("liquidLevel_mm")
        detected = params.get("liquidVolume_uL")
    else:
        level = getattr(params, "liquid_level_mm", None)
        detected = getattr(params, "liquid_volume_ul", None)
    volume = bound.get("volume") or 0.0
    mph_pattern = bound.get("mph_pattern")
    channels_used = len(mph_pattern) if mph_pattern else 96

    pooled = _geometry is not None and _geometry.is_reservoir(labware)
    key = labware if pooled else f"{labware}@mph96"
    if not _should_track_reagent(key, labware):
        return
    if pooled:
        _log_reservoir_labware(client, labware)
    reading = {
        "labware": labware,
        "well": "all" if pooled else "mph96",
        "channel": "mph96",
        "liquid_volume_ul": detected,
        "liquid_level_mm": level,
        "aspirated_ul": channels_used * volume,
    }
    state = _update_reagent_state(client, key, labware, [reading])
    reading.update(key=key, **state)
    emit("aspirate", readings=[reading])


# -- dispense tracking -------------------------------------------------------------------------
#
# Live visibility only (a "dispense" event, mirroring "aspirate"'s reading shape) -- unlike
# aspirate, dispense does not feed the reagent-state machine or the consumables ledger: what
# matters for inventory is what left a source, not where it went. This is for the live trace
# and future reconciliation, not stock tracking.


def _track_dispense(client: Any, bound: dict[str, Any], result: Any) -> None:
    channel_data = getattr(_return_parameters(result), "channels", None)
    if not channel_data:
        return
    from hamilton_venus.models.position import normalize_positions

    channels = bound.get("channels") or getattr(client, "_DEFAULT_CHANNELS", None) or []
    positions = normalize_positions(
        bound.get("positions"),
        channel_count=len(channels),
        get_spec=client.get_labware_spec,
        channel_pitch_mm=getattr(client, "_CHANNEL_PITCH_MM", None),
    )
    by_channel = dict(zip(channels, positions, strict=False))
    readings: list[dict[str, Any]] = []
    for data in channel_data:
        position = by_channel.get(data.channel)
        if position is None:
            continue
        readings.append(
            {
                "labware": position.labware,
                "well": position.well,
                "channel": data.channel,
                "dispensed_ul": data.dispensed_volume,
            }
        )
    if readings:
        emit("dispense", readings=readings)


def _track_dispense_mph96(client: Any, bound: dict[str, Any], result: Any) -> None:  # noqa: ARG001
    labware = bound.get("labware_id")
    if not labware:
        return
    volume = bound.get("volume") or 0.0
    mph_pattern = bound.get("mph_pattern")
    channels_used = len(mph_pattern) if mph_pattern else 96
    emit(
        "dispense",
        readings=[{"labware": labware, "well": "all", "channel": "mph96", "dispensed_ul": channels_used * volume}],
    )


def _track_dispense_on_the_fly(client: Any, bound: dict[str, Any], result: Any) -> None:  # noqa: ARG001
    """dispense_on_the_fly has no positions selector at all -- it names a destination labware and
    dispenses while translating across it in one pass, with no per-well breakdown available. Only
    the labware-level total is tracked (per destination labware, not per well)."""
    labware = bound.get("labware_name")
    if not labware:
        return
    channels = bound.get("channels") or []
    volumes = bound.get("volumes")
    if isinstance(volumes, (int, float)):
        total = float(volumes) * len(channels)
    elif volumes:
        total = float(sum(volumes))
    else:
        total = 0.0
    emit("dispense", readings=[{"labware": labware, "well": None, "channel": "fly", "dispensed_ul": total}])


def _install_tracking(client_cls: type) -> None:
    for name in dir(client_cls):
        if not name.startswith("add_"):
            continue
        member = getattr(client_cls, name, None)
        try:
            parameters = inspect.signature(member).parameters
        except (TypeError, ValueError):
            continue
        if callable(member) and "labware_definition" in parameters:
            _wrap(client_cls, name, _track_labware(name))
    for name in ("tip_pickup", "tip_pickup_5ml"):
        _wrap(client_cls, name, _track_tip_pickup, "_tip_pickup_impl")
    for name in ("aspirate", "aspirate_5ml"):
        _wrap(client_cls, name, _track_aspirate, "_aspirate_impl")
    for name in ("dispense", "dispense_5ml"):
        _wrap(client_cls, name, _track_dispense, "_dispense_impl")
    for name in ("dispense_on_the_fly", "dispense_on_the_fly_5ml"):
        _wrap(client_cls, name, _track_dispense_on_the_fly, "_dispense_on_the_fly_impl")
    _wrap(client_cls, "tip_pick_up_mph96", _track_tip_pickup_mph96(full=True))
    _wrap(client_cls, "tip_pick_up_mph96_partial", _track_tip_pickup_mph96(full=False))
    _wrap(client_cls, "aspirate_mph96", _track_aspirate_mph96)
    _wrap(client_cls, "dispense_mph96", _track_dispense_mph96)


# -- client patching -------------------------------------------------------------------------


def _config_with_command_timeout() -> Any | None:
    """The SDK's default config with ``timeouts.command`` raised to this run's setting, or None to
    leave the SDK alone (no setting, or the config could not be loaded)."""
    seconds = _config.get("command_timeout_s")
    if not seconds:
        return None
    try:
        from hamilton_venus.config import load_config

        config = load_config()
        config.timeouts.command = float(seconds)
        return config
    except Exception as exc:  # noqa: BLE001 - a config problem must not stop the run
        _log("WARNING", f"Could not raise the command timeout: {exc}")
        return None


def _patch_client_class(client_cls: type) -> None:
    """Force this run's settings into every ``client_cls(...)`` the script builds."""
    from hamilton_venus.config import RunLogConfig

    original_init = client_cls.__init__
    original_enter = client_cls.__enter__
    original_connect = client_cls.instrument_connect
    simulate = bool(_config["simulate"])

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        # Even a script that got past validation (or built the class some way the validator can't
        # see) cannot drive the other instrument family than the one this spoke's VENUS is for.
        refused = instrument_guard.wrong_client_message(client_cls.__name__)
        if refused:
            raise RuntimeError(refused)
        kwargs["simulate"] = simulate
        # The SDK gives each command 300 s by default, and a command that stops on an instrument
        # error keeps that clock running while a person decides what to do (each Repeat that fails
        # again asks again inside the same command). Give it room, unless the script set its own config.
        if not args and "config" not in kwargs:
            config = _config_with_command_timeout()
            if config is not None:
                kwargs["config"] = config
        kwargs["logging_level"] = logging.INFO
        kwargs["venus_trace_logging"] = True
        kwargs["run_log"] = RunLogConfig(
            enabled=True,
            output_dir=_config["run_log_dir"],
            console_capture=True,
            include_http=True,
            include_signalr=True,
            include_cmd_comms=True,
        )
        # None here is NOT "no callback registered, fall back to abort" -- it means exactly the
        # opposite: the SDK's own resolver checks `on_operator_error_escalation is not None` to
        # decide whether ANY callback exists at all (_base_instrument_client.py), and only when
        # it's absent does the resolver submit its own well-formed legacy-dialog fallback
        # (selected_action_id=-1, selected_action_is_recovery=False) directly. Registering this
        # callback and having it *return* that same-shaped ErrorRecovery is NOT equivalent: the
        # resolver's callback-return path unconditionally forces selected_action_is_recovery to
        # True first (_error_profile_resolver.py's _escalate, "forcing True for recovery
        # submission") -- submitting id=-1 THAT way is not a valid action id, and VENUS is left
        # waiting on a decision that was never really made instead of showing its own dialog.
        # Confirmed directly: this is exactly what caused a real run to hang with no dialog ever
        # appearing. So when no one could ever answer a prompt anyway, skip the callback
        # entirely rather than trying to fake the no-callback outcome from inside one.
        kwargs["on_operator_error_escalation"] = (
            _on_operator_escalation if _config.get("operator_gate_configured") else None
        )
        kwargs["on_tip_reload_prompt"] = _on_tip_reload_prompt
        kwargs["on_liquid_reload_prompt"] = _on_liquid_reload_prompt
        original_init(self, *args, **kwargs)
        _captured_clients.append(self)
        global _geometry
        if _geometry is None:
            _geometry = LabwareGeometryCache(
                lambda labware_id, _c=self: _c.labware_get_params_from_id(labware_id).return_parameters.to_labware_definition()
            )
        emit("client", client=client_cls.__name__, simulate=simulate)

    def patched_enter(self: Any) -> Any:
        result = original_enter(self)
        _register_status_listener(self)
        return result

    def patched_connect(self: Any, *args: Any, **kwargs: Any) -> Any:
        response = original_connect(self, *args, **kwargs)
        _register_status_listener(self)
        return response

    client_cls.__init__ = patched_init
    client_cls.__enter__ = patched_enter
    client_cls.instrument_connect = patched_connect
    _install_tracking(client_cls)


# -- line tracing ----------------------------------------------------------------------------


def _handle_pause() -> None:
    _set_state("paused")
    _resume_now.clear()
    _resume_now.wait()
    if not _stop_requested.is_set():
        _set_state("running")


def _on_script_line(lineno: int) -> None:
    global _current_line, _line_started_at
    now = time.time()
    # Full-resolution-enough history for the run summary's failed-step-to-line lookup (see
    # run_summary._line_at_timestamp) -- separate from the once-a-second `line` events below,
    # which are only for live display and would be far too coarse for that lookup. The finished
    # line is recorded with its own start time, so the lookup stays exact.
    if _current_line and now - _line_started_at >= _TIMELINE_MIN_SECONDS:
        _line_timeline.append((_line_started_at, _current_line))
    # The previous line has fully finished by now, so pausing here never interrupts an
    # instrument call that is in flight.
    if _pause_requested.is_set():
        _pause_requested.clear()
        _handle_pause()
        now = time.time()
    _current_line = lineno
    _line_started_at = now


def _finish_line_timeline() -> None:
    """Record the line the script ended on, which no later line event closed."""
    if _current_line:
        _line_timeline.append((_line_started_at, _current_line))


def _on_script_exception(lineno: int, exc_value: BaseException) -> None:
    global _error_line
    rechained = exc_value.__cause__ is not None or exc_value.__context__ is not None
    # Keep the line where the failure first arose, not a re-raise in the script's cleanup.
    if _error_line is None or not rechained:
        _error_line = lineno


def _start_line_monitoring() -> int | None:
    """Follow the script's lines with sys.monitoring. Unlike sys.settrace, which is called for
    every function call anywhere, a LINE callback can return DISABLE for a location, which turns
    its instrumentation off for good -- so library code (pandas, numpy, the SDK) costs one
    callback per line location, once, then runs at full speed. Returns the tool id to release
    afterwards, or None if every tool id is already taken (the script then runs untracked)."""
    monitoring = sys.monitoring
    for tool_id in (4, 3, 2, 1):  # DEBUGGER_ID (0) stays free so a debugger can still attach
        try:
            monitoring.use_tool_id(tool_id, "script-run-line-trace")
            break
        except ValueError:
            continue
    else:
        _log("WARNING", "No free sys.monitoring tool id; running without line tracking.")
        return None
    events = monitoring.events
    script_path = _script_path
    disable = monitoring.DISABLE

    def on_line(code: Any, lineno: int) -> Any:
        if code.co_filename != script_path:
            return disable
        _on_script_line(lineno)
        return None

    def on_exception(code: Any, offset: int, exc: BaseException) -> None:
        # PY_UNWIND (leaving a script frame) and EXCEPTION_HANDLED (caught in one) together cover
        # every script frame an exception passes through. Frame 1 is that script frame.
        if code.co_filename == script_path:
            _on_script_exception(sys._getframe(1).f_lineno, exc)

    monitoring.register_callback(tool_id, events.LINE, on_line)
    monitoring.register_callback(tool_id, events.PY_UNWIND, on_exception)
    monitoring.register_callback(tool_id, events.EXCEPTION_HANDLED, on_exception)
    monitoring.set_events(tool_id, events.LINE | events.PY_UNWIND | events.EXCEPTION_HANDLED)
    return tool_id


def _stop_line_monitoring(tool_id: int | None) -> None:
    if tool_id is not None:
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.free_tool_id(tool_id)
    _finish_line_timeline()


def _heartbeat() -> None:
    last = 0
    while True:
        time.sleep(1.0)
        if _current_line != last:
            last = _current_line
            emit("line", line=last)


# -- entry point -----------------------------------------------------------------------------


def _run_script() -> tuple[str, int, dict[str, Any] | None]:
    """Run the script; returns (status, exit_code, error)."""
    monitoring_tool = _start_line_monitoring()
    try:
        runpy.run_path(_script_path, run_name="__main__")
        return "completed", 0, None
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            print(code, file=sys.stderr, flush=True)
            code = 1
        code = 0 if code is None else int(code) if isinstance(code, int) else 1
        return ("completed" if code == 0 else "failed"), code, ({"type": "SystemExit", "message": f"exit code {code}"} if code else None)
    except KeyboardInterrupt:
        return "stopped", 130, None
    except BaseException as exc:  # noqa: BLE001 - the whole point is to report any failure
        text = traceback.format_exc()
        print(text, file=sys.stderr, flush=True)
        return "failed", 1, {"type": type(exc).__name__, "message": str(exc), "traceback": text[-4000:]}
    finally:
        _stop_line_monitoring(monitoring_tool)


def main() -> None:
    global _script_path
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    _config.update(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    _script_path = str(_config["script_path"])
    # RunLog.__init__ names itself from sys.argv[0] (see hamilton_venus._internal._run_log) --
    # left as this file's own path, every run's finalized SdkRunLog.json would record
    # script_name="child_bootstrap.py" instead of the actual script. Must happen before any
    # StarClient/VantageClient is constructed (patched or otherwise), so set it now.
    sys.argv[0] = _script_path
    simulate = bool(_config["simulate"])
    emit("started", pid=os.getpid(), script=Path(_script_path).name, simulate=simulate, python=sys.version.split()[0])

    consumables = _config.get("consumables") or {}
    for pool, entry in (consumables.get("tip_pools") or {}).items():
        threshold = entry.get("low_threshold") if isinstance(entry, dict) else None
        if isinstance(threshold, (int, float)):
            _tip_thresholds[pool] = int(threshold)
    for key, entry in (consumables.get("reagents") or {}).items():
        low_percent = entry.get("low_percent") if isinstance(entry, dict) else None
        if isinstance(low_percent, (int, float)):
            _reagent_thresholds[key] = float(low_percent)
        capacity_ul = entry.get("capacity_ul") if isinstance(entry, dict) else None
        if isinstance(capacity_ul, (int, float)) and capacity_ul > 0:
            _reagent_capacities[key] = float(capacity_ul)

    _sync_system_simulation_mode(simulate)

    from hamilton_venus import StarClient, VantageClient

    for client_cls in (StarClient, VantageClient):
        _patch_client_class(client_cls)

    control = _detach_control_channel()
    threading.Thread(target=_control_reader, args=(control,), name="control-reader", daemon=True).start()
    threading.Thread(target=_heartbeat, name="heartbeat", daemon=True).start()

    status, exit_code, error = _run_script()
    if _stop_requested.is_set() and status != "completed":
        status = "stopped"
    _finished.set()
    _persist_line_timeline()
    emit("line", line=_current_line)
    emit("script_exit", status=status, exit_code=exit_code, error=error, error_line=_error_line)
    sys.stdout.flush()
    sys.exit(exit_code)


def _persist_line_timeline() -> None:
    """Write the full-resolution line timeline next to this run's log, so get_run_summary can
    look up which script line was executing when a given command fired -- see
    ``hamilton_workflow_framework.run_summary._line_at_timestamp``. Best effort: a run summary
    without this file simply has no "line" field on its failed steps."""
    if not _line_timeline:
        return
    try:
        run_log_dir = Path(_config["run_log_dir"])
        run_log_dir.mkdir(parents=True, exist_ok=True)
        (run_log_dir / "line_timeline.json").write_text(json.dumps(_line_timeline), encoding="utf-8")
    except OSError as exc:
        _log("WARNING", f"Could not write the script line timeline: {exc}")


if __name__ == "__main__":
    main()
