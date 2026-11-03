"""Connection and run routes, plus the WebSocket that streams run events to the page."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from orchestrator_client import local_spoke

from backend import capabilities, instrument, service, venus_state
from backend.mcp_bridge import BridgeError
from backend.runner import MODES, RunError

router = APIRouter()


class ConnectBody(BaseModel):
    simulate: bool = True
    # None = blank deck; "__last__" = the last layout; otherwise a saved layout name.
    deck: str | None = None
    # False = open the session only; the user connects later (Connect button or a Connect Instrument card).
    connect_instrument: bool = True
    initialize: bool = True
    # Connect even though VENUS is running another method (which the connect aborts).
    force: bool = False


class InstrumentConnectBody(BaseModel):
    initialize: bool = True


class RunBody(BaseModel):
    steps: list[dict[str, Any]]
    mode: str = "all"
    start_id: str | None = None
    end_id: str | None = None
    variables: list[dict[str, Any]] = []
    # Answers to "ask before each run" variables, by name.
    overrides: dict[str, Any] = {}
    # The other tabs: every subflow a Run Subflow card may name, and the main flow (for the variables it sets).
    subflows: list[dict[str, Any]] = []
    main: list[dict[str, Any]] | None = None


def _connection() -> dict[str, Any]:
    bridge = service.bridge
    return {
        "session": bridge.connection_id is not None,
        "instrument_connected": bridge.instrument_connected,
        "capabilities": bridge.capabilities,
        "capabilities_text": capabilities.describe(bridge.capabilities),
        "simulate": bridge.simulate,
        "instrument_type": bridge.instrument_type,
        "serial_number": bridge.serial_number,
        "connection_id": bridge.connection_id,
        "spoke_running": local_spoke.local_spoke_status(service.config.spoke_port).get("running", False) if bridge.is_local else True,
    }


def _spoke_session_open() -> bool:
    """Whether the spoke Studio uses already has a session open (so a busy VENUS may be ours)."""
    if not service.bridge.is_local or not local_spoke.local_spoke_status(service.config.spoke_port).get("running"):
        return False
    try:
        return bool(service.bridge.status().get("session_active"))
    except BridgeError:
        return False


@router.get("/api/status")
def status() -> dict[str, Any]:
    return {**_connection(), "run": service.runner.snapshot(), "venus": venus_state.run_state()}


@router.get("/api/deck/loaded")
def deck_is_loaded() -> dict[str, bool]:
    """Whether VENUS has a deck layout loaded; the Deck button stays hidden until it does."""
    return {"loaded": venus_state.deck_loaded()}


@router.get("/api/decks")
def decks() -> dict[str, list[str]]:
    """Saved deck layouts (VENUS keeps each as <name>.json), for the connect dialog."""
    folder = service.config.deck_layout_dir
    return {"decks": sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []}


@router.post("/api/connect")
async def connect(body: ConnectBody) -> dict[str, Any]:
    if service.runner.active:
        raise HTTPException(409, detail="A run is in progress. Stop it before reconnecting.")
    if not body.force:
        state = await asyncio.to_thread(venus_state.run_state)
        if state.get("busy"):
            # 409 + code: the page asks the user, then retries with force=true.
            own = await asyncio.to_thread(_spoke_session_open)
            message = (
                "A session on Studio's own MCP spoke is still open (an earlier Studio window or a script). "
                "Connecting replaces it and stops whatever it is doing."
                if own else
                "VENUS is running a method (another application or the AI Assistant). Connecting would abort it."
            )
            raise HTTPException(409, detail={"code": "venus_busy", "run_state": state["run_state"], "own_session": own, "message": message})
    try:
        result = await asyncio.to_thread(
            service.bridge.connect,
            simulate=body.simulate,
            instrument_type=instrument.instrument_type(),
            deck_name=body.deck if body.deck not in (None, "__last__") else None,
            load_previous_deck=body.deck == "__last__",
            connect_instrument=body.connect_instrument,
            initialize=body.initialize,
        )
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    service.broadcaster.publish({"type": "connection", **_connection()})
    return {**_connection(), "result": result}


@router.post("/api/instrument/connect")
async def connect_instrument_now(body: InstrumentConnectBody) -> dict[str, Any]:
    """Connect the instrument for the open session (the Connect button; a Connect Instrument card does the same)."""
    if service.bridge.connection_id is None:
        raise HTTPException(409, detail="Start a session first.")
    if service.runner.active:
        raise HTTPException(409, detail="A run is in progress.")
    try:
        await asyncio.to_thread(service.bridge.connect_instrument, initialize=body.initialize)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    service.broadcaster.publish({"type": "connection", **_connection()})
    return _connection()


@router.post("/api/disconnect")
async def disconnect() -> dict[str, Any]:
    if service.runner.active:
        raise HTTPException(409, detail="A run is in progress. Stop it first.")
    try:
        await asyncio.to_thread(service.bridge.disconnect)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    service.broadcaster.publish({"type": "connection", **_connection()})
    return _connection()


@router.post("/api/run")
def run(body: RunBody) -> dict[str, Any]:
    if service.bridge.connection_id is None:
        raise HTTPException(409, detail="Start a session first.")
    if body.mode not in MODES:
        raise HTTPException(422, detail=f"Unknown run mode {body.mode!r}")
    try:
        run_id = service.runner.start(body.steps, body.mode, body.start_id, body.end_id, body.variables, body.overrides, body.subflows, body.main)
    except RunError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"run_id": run_id}


class AnswerBody(BaseModel):
    value: str | None = None


class PreviewBody(RunBody):
    pass


@router.post("/api/preview")
def preview(body: PreviewBody) -> dict[str, Any]:
    """What the selected cards would send, without running anything, plus anything that would stop the run."""
    from backend import flow, variables as variables_mod
    from backend.runner import validate

    try:
        steps = flow.expand(body.steps, body.subflows)
        included = flow.select(steps, body.mode, body.start_id, body.end_id)
        values = variables_mod.values_of(body.variables, body.overrides)
    except (flow.FlowError, variables_mod.VariableError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    problems = [msg for _, msg in validate(steps, values, included, lambda name: service.catalog.command(name, instrument.instrument_type()),
                                           flow.names_elsewhere(body.main, body.subflows))]
    result = flow.preview(steps, values, included)
    if result["error"] and not problems:
        problems.append(result["error"])
    return {**result, "problems": problems}


@router.post("/api/run/answer")
def answer(body: AnswerBody) -> dict[str, str]:
    """The reply to a Prompt card (a null value cancels, which stops the run)."""
    service.runner.answer(body.value)
    return {"state": service.runner.state}


class OperatorBody(BaseModel):
    error_uuid: str
    action: str | None = None  # one choice for the whole error (abort, cancel, an access action, ...)
    channel_actions: dict[str, int] | None = None  # or one recovery per failed channel: detail uuid -> action id


@router.post("/api/run/operator")
async def answer_operator(body: OperatorBody) -> dict[str, bool]:
    """The person's answer to the operator prompt a card is blocked on."""
    if not body.action and not body.channel_actions:
        raise HTTPException(422, detail="Choose an action.")
    try:
        await asyncio.to_thread(service.prompts.answer, body.error_uuid, body.action, body.channel_actions)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/api/run/stop")
def stop() -> dict[str, str]:
    service.runner.stop()
    return {"state": service.runner.state}


@router.post("/api/run/pause")
def pause() -> dict[str, str]:
    service.runner.pause()
    return {"state": service.runner.state}


@router.post("/api/run/continue")
def continue_run() -> dict[str, str]:
    service.runner.unpause()
    return {"state": service.runner.state}


@router.post("/api/run/retry")
async def retry_held() -> dict[str, Any]:
    """Re-run the held card (after the operator fixed the cause); the waiting run then carries on."""
    try:
        return await asyncio.to_thread(service.bridge.resume)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc


@router.post("/api/run/release")
async def release_held() -> dict[str, Any]:
    """Give up on the held card: the run stops there with an error."""
    try:
        return await asyncio.to_thread(service.bridge.release_hold)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc


@router.websocket("/ws")
async def events(socket: WebSocket) -> None:
    await socket.accept()
    queue = service.broadcaster.subscribe()
    try:
        await socket.send_json({"type": "connection", **_connection()})
        await socket.send_json(service.runner.snapshot())
        for prompt in service.prompts.pending():
            await socket.send_json(prompt)
        while True:
            await socket.send_json(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        service.broadcaster.unsubscribe(queue)
