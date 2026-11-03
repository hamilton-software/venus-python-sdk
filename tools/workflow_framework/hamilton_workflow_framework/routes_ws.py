"""Generic WebSocket endpoint factory: one connection = one WorkflowSession = one
StarClient lifecycle.

Apps assemble their own router by calling ``build_ws_router()`` with their own
registry, session/engine factories, and (optionally) extension hooks for
app-specific message types:

- ``pre_dispatch``: tried before the generic dispatch chain, with the parsed
  message and any per-connection ``extra_state`` -- lets an app veto/short-circuit
  a base message (e.g. demo_app rejects ConnectWithDeck while its script tab has
  its own instrument connection open). Return True if it fully handled the message.
- ``extra_dispatch``: tried, in order, only when nothing else (generic or
  pre_dispatch) matched -- for message types the framework doesn't define at all
  (e.g. demo_app's GetTipPools, or a consumables/monitoring module's own messages).
- ``make_extra_state`` / ``cleanup_extra_state``: per-connection app state (e.g.
  demo_app's ScriptRunner) that pre_dispatch/extra_dispatch handlers can use,
  created on connect and torn down on disconnect alongside the session.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from hamilton_workflow_framework.execution_engine import ExecutionEngine, SendFn, Step
from hamilton_workflow_framework.registry import CommandRegistry
from hamilton_workflow_framework.session import BUSY_RUN_STATES, WorkflowSession
from hamilton_workflow_framework.ws_protocol import (
    ConnectWithDeck,
    Disconnect,
    LoadSteps,
    OperatorPromptResponse,
    Pause,
    Ping,
    Resume,
    Run,
    RunControlBusyResponse,
    RunFrom,
    RunImmediate,
    Stop,
)

_logger = logging.getLogger("hamilton_workflow_framework.ws")

DispatchHandler = Callable[[Any, WorkflowSession, ExecutionEngine, WebSocket, Any], Awaitable[bool]]
PreDispatchHandler = Callable[[Any, WorkflowSession, WebSocket, Any], Awaitable[bool]]

# Tracks every WorkflowSession currently attached to an open WS connection, so a
# clean process shutdown (see routes_http.build_generic_http_router's /api/shutdown)
# can tear each one down properly -- StarClient.__exit__() must run to terminate/
# unload the method on the instrument side, or a stale method is left behind for
# the next connection attempt to trip over.
_active_sessions: set[WorkflowSession] = set()


async def close_all_sessions() -> None:
    for session in list(_active_sessions):
        try:
            await session.close()
        except Exception:
            _logger.exception("Error closing session during shutdown")


async def _drain_log_queue(session: WorkflowSession, websocket: WebSocket) -> None:
    while True:
        message = await session.log_queue.get()
        try:
            await websocket.send_json(message)
        except Exception:
            return


async def _confirm_if_run_control_busy(
    session: WorkflowSession,
    websocket: WebSocket,
    context: str,
    pending: dict[str, "asyncio.Future[str]"],
) -> bool:
    """Gate a connect/disconnect against the SDK's silent stale-method abort.

    Checks VENUS's real run-state first; if it's actually busy (see
    BUSY_RUN_STATES), pushes a run_control_busy prompt and blocks until the
    matching RunControlBusyResponse arrives (resolved by _dispatch below, or by
    ws_endpoint's cleanup on disconnect) -- there is deliberately no timeout,
    since proceeding without an answer is exactly the silent-abort behavior
    this exists to prevent. Returns True if it's safe to proceed (nothing was
    busy, or the operator picked "abort" and abort_and_clear_run_control()
    finished); False if the operator picked "cancel" (or the connection
    dropped while waiting) -- the caller must not proceed in that case.
    """
    state = await session.check_run_state()
    if state is None or state not in BUSY_RUN_STATES:
        return True

    # Disconnecting ("Terminate") is expected to end this session's own run if
    # it's the one running -- that's the whole point of the button, not a
    # silent-abort risk. Only prompt here when the busy run belongs to someone
    # else (owns_current_run() returning None -- guid check itself failed --
    # falls through to the prompt too, same fail-safe direction as everywhere
    # else in this gate: better to ask than to silently abort an unknown run).
    if context == "disconnect" and await session.owns_current_run():
        return True

    prompt_id = uuid.uuid4().hex
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    pending[prompt_id] = future
    await websocket.send_json({"type": "run_control_busy", "prompt_id": prompt_id, "context": context, "state": state.name})
    try:
        action = await future
    finally:
        pending.pop(prompt_id, None)

    if action != "abort":
        return False
    await session.abort_and_clear_run_control()
    return True


async def _guarded_run(coro: Awaitable[None]) -> None:
    """Swallow+log exceptions from a background run task.

    engine.run()/run_from()/run_immediate() already funnel per-step failures into
    step_result messages (see ExecutionEngine._execute_step's own try/except), so
    this is only a backstop for something failing outside that -- e.g.
    websocket.send_json itself raising because the client disconnected mid-run.
    """
    try:
        await coro
    except Exception:
        _logger.exception("Unhandled error in background run task")


async def _run_full(engine: ExecutionEngine, websocket: WebSocket) -> None:
    await websocket.send_json({"type": "run_state", "state": "running"})
    await engine.run()
    await websocket.send_json({"type": "run_state", "state": "completed"})


async def _run_from(engine: ExecutionEngine, websocket: WebSocket, step_id: str) -> None:
    await websocket.send_json({"type": "run_state", "state": "running"})
    try:
        await engine.run_from(step_id)
    except KeyError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.send_json({"type": "run_state", "state": "idle"})
        return
    await websocket.send_json({"type": "run_state", "state": "completed"})


def build_ws_router(
    *,
    session_factory: Callable[[], WorkflowSession],
    engine_factory: Callable[[WorkflowSession, SendFn], ExecutionEngine],
    registry: CommandRegistry,
    parse_message: Callable[[dict], Any],
    pre_dispatch: list[PreDispatchHandler] | None = None,
    extra_dispatch: list[DispatchHandler] | None = None,
    make_extra_state: Callable[[WorkflowSession, WebSocket], Any] | None = None,
    cleanup_extra_state: Callable[[Any], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter()
    pre_dispatch = pre_dispatch or []
    extra_dispatch = extra_dispatch or []

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        session = session_factory()
        _active_sessions.add(session)
        engine = engine_factory(session, websocket.send_json)
        extra_state = make_extra_state(session, websocket) if make_extra_state else None
        pending_run_control: dict[str, asyncio.Future[str]] = {}

        send_task = asyncio.create_task(_drain_log_queue(session, websocket))

        await websocket.send_json({
            "type": "hello",
            "session_id": session.session_id,
            "simulate": session.simulate,
            "connected": False,
        })
        await websocket.send_json({"type": "commands_catalog", **registry.catalog_payload()})

        try:
            while True:
                raw = await websocket.receive_json()
                await _dispatch(
                    raw, session, engine, websocket, parse_message, pre_dispatch, extra_dispatch, extra_state, pending_run_control
                )
        except WebSocketDisconnect:
            pass
        except Exception:
            _logger.exception("Unhandled error in WS loop")
        finally:
            send_task.cancel()
            # Mirrors WorkflowSession._fail_pending_operator_prompts: a dropped
            # connection must not leave _confirm_if_run_control_busy awaiting a
            # response that will now never arrive.
            for future in pending_run_control.values():
                if not future.done():
                    future.set_result("cancel")
            if cleanup_extra_state is not None and extra_state is not None:
                await cleanup_extra_state(extra_state)
            await session.close()
            _active_sessions.discard(session)

    return router


async def _dispatch(
    raw: dict,
    session: WorkflowSession,
    engine: ExecutionEngine,
    websocket: WebSocket,
    parse_message: Callable[[dict], Any],
    pre_dispatch: list[PreDispatchHandler],
    extra_dispatch: list[DispatchHandler],
    extra_state: Any,
    pending_run_control: dict[str, "asyncio.Future[str]"],
) -> None:
    try:
        message = parse_message(raw)
    except ValidationError as exc:
        await websocket.send_json({"type": "error", "message": "Invalid message", "detail": str(exc)})
        return

    for handler in pre_dispatch:
        if await handler(message, session, websocket, extra_state):
            return

    if isinstance(message, ConnectWithDeck):
        if not await _confirm_if_run_control_busy(session, websocket, "connect", pending_run_control):
            await websocket.send_json({"type": "connection_state", "simulate": message.simulate, "state": "cancelled", "detail": None})
            return
        await websocket.send_json({"type": "connection_state", "simulate": message.simulate, "state": "connecting", "detail": None})
        try:
            await session.start_session(message.simulate)
            await session.load_deck(message.deck, message.previous)
            await session.connect_instrument(initialize=False)
            await websocket.send_json({"type": "connection_state", "simulate": session.simulate, "state": "connected", "detail": None})
        except Exception as exc:  # noqa: BLE001 - surface any connection failure to the UI
            _logger.exception("Failed to connect instrument")
            await websocket.send_json({"type": "connection_state", "simulate": message.simulate, "state": "error", "detail": str(exc)})
            return

        try:
            response = await asyncio.to_thread(session.star.instrument_get_serial_number)
            await websocket.send_json({"type": "serial_number", "serial_number": response.return_parameters.serial_number})
        except Exception as exc:  # noqa: BLE001 - surface any serial-number fetch failure to the UI
            _logger.exception("Failed to fetch instrument serial number")
            await websocket.send_json({"type": "serial_number", "serial_number": None})

    elif isinstance(message, Disconnect):
        if not await _confirm_if_run_control_busy(session, websocket, "disconnect", pending_run_control):
            await websocket.send_json({"type": "connection_state", "simulate": session.simulate, "state": "cancelled", "detail": None})
            return
        await websocket.send_json({"type": "connection_state", "simulate": session.simulate, "state": "disconnecting", "detail": None})
        await session.close()
        await websocket.send_json({"type": "connection_state", "simulate": session.simulate, "state": "disconnected", "detail": None})

    elif isinstance(message, LoadSteps):
        engine.load_steps(
            [Step(step_id=s.step_id, command_id=s.command_id, params=s.params, enabled=s.enabled) for s in message.steps]
        )

    elif isinstance(message, Run):
        if not session.is_connected():
            await websocket.send_json({"type": "error", "message": "Not connected. Set connection mode first."})
            return
        if not engine.spawn(lambda: _guarded_run(_run_full(engine, websocket))):
            await websocket.send_json({"type": "error", "message": "A run is already in progress."})

    elif isinstance(message, RunFrom):
        if not session.is_connected():
            await websocket.send_json({"type": "error", "message": "Not connected. Set connection mode first."})
            return
        step_id = message.step_id
        if not engine.spawn(lambda: _guarded_run(_run_from(engine, websocket, step_id))):
            await websocket.send_json({"type": "error", "message": "A run is already in progress."})

    elif isinstance(message, Stop):
        engine.request_stop()
        await websocket.send_json({"type": "run_state", "state": "stopped"})

    elif isinstance(message, Pause):
        if not engine.is_running or engine.is_paused:
            await websocket.send_json({"type": "error", "message": "Nothing running to pause."})
            return
        engine.request_pause()
        # Transient: the in-flight step still has to finish before the engine
        # actually suspends (see ExecutionEngine.request_pause) -- the app's
        # on_pause hook, once it runs, is what sends the real "paused" state.
        await websocket.send_json({"type": "run_state", "state": "pausing"})

    elif isinstance(message, Resume):
        if not engine.is_paused:
            await websocket.send_json({"type": "error", "message": "Not currently paused."})
            return
        engine.request_resume()

    elif isinstance(message, RunImmediate):
        if not session.is_connected():
            await websocket.send_json({"type": "error", "message": "Not connected. Set connection mode first."})
            return
        command_id, params = message.command_id, message.params
        if not engine.spawn(lambda: _guarded_run(engine.run_immediate(command_id, params))):
            await websocket.send_json({"type": "error", "message": "A run is already in progress."})

    elif isinstance(message, Ping):
        await websocket.send_json({"type": "pong"})

    elif isinstance(message, OperatorPromptResponse):
        if not session.resolve_operator_prompt(message.error_uuid, message.action, message.channel_actions):
            _logger.warning("operator_prompt_response for unknown/already-resolved uuid=%s", message.error_uuid)

    elif isinstance(message, RunControlBusyResponse):
        future = pending_run_control.get(message.prompt_id)
        if future is None or future.done():
            _logger.warning("run_control_busy_response for unknown/already-resolved prompt_id=%s", message.prompt_id)
        else:
            future.set_result(message.action)

    else:
        for handler in extra_dispatch:
            if await handler(message, session, engine, websocket, extra_state):
                return
        _logger.warning("No handler matched message type=%r", getattr(message, "type", type(message)))
