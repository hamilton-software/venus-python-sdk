"""Single WebSocket endpoint for the script manager app.

Unlike demo_app/sample_transfer_app, this app has no persistent StarClient
session -- each run launches its own subprocess with its own
`with StarClient(...) as star:` block (see script_runner.py) -- so it doesn't
build on hamilton_workflow_framework's WorkflowSession/ExecutionEngine/
build_ws_router, which model a *shared*, long-lived StarClient session
driving a step list. This is a plain FastAPI WebSocket route instead.

There is one ScriptRunner for the whole backend, not one per connection: a run
outlives the connection that started it. If the Photino window crashes mid-run,
the shell's supervisor relaunches it, and the new connection attaches to the
same runner and gets the run replayed (see ScriptRunner.attach). A dropped
connection never stops a run; only Stop or /api/shutdown (close_all_runs) does.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import BackendConfig, load_backend_config
from backend.consumables_store import ConsumablesStore
from backend.script_runner import ScriptRunner
from backend.settings_store import SettingsStore
from backend.shortcuts_store import ShortcutsStore, ShortcutsStoreError
from backend.ws_protocol import (
    AddReservoir,
    ConsumableReloadAction,
    CreateFolder,
    CreateShortcut,
    DeleteFolder,
    DeleteShortcut,
    GetScript,
    ListShortcuts,
    MoveItem,
    OperatorPromptResponse,
    Pause,
    Ping,
    RenameFolder,
    ResyncShortcut,
    Resume,
    RunControlBusyResponse,
    RunShortcut,
    SetTipThreshold,
    Stop,
    TkDialogResponse,
    TkFileDialogResponse,
    UpdateSettings,
    UpdateShortcut,
    UserInputResponse,
    parse_client_message,
)

__all__ = ["router", "close_all_runs"]

_logger = logging.getLogger("backend.ws")

router = APIRouter()

_runner: ScriptRunner | None = None


def _get_runner(config: BackendConfig) -> ScriptRunner:
    global _runner
    if _runner is None:
        _runner = ScriptRunner(
            run_log_root=config.run_log_root,
            consumables_store=ConsumablesStore(config),
            settings_store=SettingsStore(config),
        )
    return _runner


async def close_all_runs() -> None:
    """Stop any in-progress script subprocess -- called from /api/shutdown so a
    running instrument method isn't left orphaned when the app closes."""
    if _runner is not None:
        await _runner.request_stop()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    config = load_backend_config()
    async def _safe_send(payload: dict) -> None:
        # A script's own subprocess keeps streaming log/state messages after the
        # browser disconnects (e.g. mid-run) until the finally block below
        # detaches this connection -- swallow send failures instead of raising out
        # of the ScriptRunner's own run() loop, which already logs to _logger separately.
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    store = ShortcutsStore(config)
    consumables_store = ConsumablesStore(config)
    settings_store = SettingsStore(config)
    runner = _get_runner(config)

    async def send_tree() -> None:
        await websocket.send_json({"type": "shortcuts_tree", **store.list_tree()})

    async def send_consumables_config() -> None:
        await websocket.send_json({"type": "consumables_config", **consumables_store.list_config()})

    async def send_settings() -> None:
        await websocket.send_json({"type": "settings", **settings_store.get_settings()})

    try:
        await send_tree()
        await send_consumables_config()
        await send_settings()
        # "idle", or the current/last run replayed -- this connection may be a
        # relaunched window reattaching to a run that's still going.
        await runner.attach(_safe_send)

        while True:
            raw = await websocket.receive_json()
            try:
                message = parse_client_message(raw)
            except Exception as exc:  # noqa: BLE001 - surface malformed messages instead of dropping the connection
                await websocket.send_json({"type": "error", "message": f"Bad message: {exc}"})
                continue

            try:
                if isinstance(message, Ping):
                    await websocket.send_json({"type": "pong"})
                elif isinstance(message, ListShortcuts):
                    await send_tree()
                elif isinstance(message, CreateFolder):
                    store.create_folder(message.name, message.parent_id)
                    await send_tree()
                elif isinstance(message, RenameFolder):
                    store.rename_folder(message.folder_id, message.name)
                    await send_tree()
                elif isinstance(message, DeleteFolder):
                    store.delete_folder(message.folder_id)
                    await send_tree()
                elif isinstance(message, CreateShortcut):
                    store.create_shortcut(message.name, message.source_path, message.folder_id)
                    await send_tree()
                elif isinstance(message, UpdateShortcut):
                    store.update_shortcut(message.shortcut_id, name=message.name)
                    await send_tree()
                elif isinstance(message, ResyncShortcut):
                    store.resync_shortcut(message.shortcut_id)
                    await send_tree()
                elif isinstance(message, DeleteShortcut):
                    store.delete_shortcut(message.shortcut_id)
                    await send_tree()
                elif isinstance(message, MoveItem):
                    store.move_item(message.item_id, message.item_type, message.new_parent_id, message.new_index)
                    await send_tree()
                elif isinstance(message, GetScript):
                    shortcut = store.get_shortcut(message.shortcut_id)
                    source = store.read_script(message.shortcut_id)
                    sync_status = store.check_sync_status(message.shortcut_id)
                    await websocket.send_json({
                        "type": "script_loaded",
                        "shortcut_id": shortcut.id,
                        "name": shortcut.name,
                        "source": source,
                        **sync_status,
                    })
                elif isinstance(message, RunShortcut):
                    if runner.is_running():
                        await websocket.send_json({"type": "error", "message": "A script is already running."})
                    else:
                        script_path = store.get_script_copy_path(message.shortcut_id)
                        asyncio.create_task(runner.run(script_path, message.simulate, message.shortcut_id))
                elif isinstance(message, Pause):
                    await runner.request_pause()
                elif isinstance(message, Resume):
                    await runner.request_resume()
                elif isinstance(message, Stop):
                    await runner.request_stop()
                elif isinstance(message, OperatorPromptResponse):
                    await runner.resolve_operator_prompt(
                        message.error_uuid, message.action, message.channel_actions, message.channel_inputs
                    )
                elif isinstance(message, RunControlBusyResponse):
                    await runner.resolve_run_control_prompt(message.prompt_id, message.action)
                elif isinstance(message, AddReservoir):
                    consumables_store.add_reservoir(message.labware, message.well, message.label)
                    await send_consumables_config()
                    await runner.push_add_reservoir(message.labware, message.well, message.label)
                elif isinstance(message, SetTipThreshold):
                    consumables_store.set_tip_threshold(message.tip_pool, message.threshold)
                    await send_consumables_config()
                    await runner.push_set_tip_threshold(message.tip_pool, message.threshold)
                elif isinstance(message, ConsumableReloadAction):
                    await runner.resolve_consumable_reload_action(message.reload_uuid, message.action)
                elif isinstance(message, UserInputResponse):
                    await runner.resolve_user_input(message.uuid, message.value, message.cancelled)
                elif isinstance(message, TkDialogResponse):
                    await runner.resolve_tk_dialog(message.uuid, message.value)
                elif isinstance(message, TkFileDialogResponse):
                    await runner.resolve_tk_filedialog(message.uuid, message.value)
                elif isinstance(message, UpdateSettings):
                    settings_store.update_settings(**message.model_dump(exclude={"type"}))
                    await send_settings()
            except ShortcutsStoreError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        if runner.detach(_safe_send):
            runner.fail_pending_run_control()
