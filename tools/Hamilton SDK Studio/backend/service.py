"""The app's shared objects: one catalog, one MCP bridge (one instrument session), one runner."""

from __future__ import annotations

import logging
import threading

from backend.command_catalog import CommandCatalog
from backend.config import load_backend_config
from backend.events import Broadcaster
from backend.instrument import instrument_type
from backend.mcp_bridge import SpokeBridge
from backend.operator_prompts import PromptWatcher
from backend.runner import FlowRunner

config = load_backend_config()
catalog = CommandCatalog([config.command_defs_dir, config.user_command_defs_dir])
bridge = SpokeBridge(spoke_port=config.spoke_port)
broadcaster = Broadcaster()


_logger = logging.getLogger(__name__)

SHUTDOWN_RUN_WAIT_S = 30.0


def close_everything(run_wait_s: float = SHUTDOWN_RUN_WAIT_S) -> None:
    """End the run and the instrument session. Called when the app closes, so a session is never left
    open on the spoke (where VENUS would keep the method running with nobody to drive it).

    A run is stopped after the command that is running; a card held after an error is released so the run
    can end. Never raises: closing has to finish even if the spoke is already gone."""
    if runner.active:
        runner.stop()
        try:
            bridge.release_hold()
        except Exception:  # noqa: BLE001 - nothing was held, or the spoke is unreachable
            pass
        thread = runner._thread  # noqa: SLF001
        if thread is not None and thread is not threading.current_thread():
            thread.join(run_wait_s)
    try:
        bridge.disconnect()
    except Exception:  # noqa: BLE001
        _logger.warning("Could not close the instrument session on exit", exc_info=True)


layout_cache: dict[str, dict] = {}  # labware name (lower case) -> its well layout, read when the person picks it
deck_cache: dict | None = None  # the last deck listing, served while a flow is running

runner = FlowRunner(bridge, broadcaster.publish, lambda name: catalog.command(name, instrument_type()))
prompts = PromptWatcher(bridge, broadcaster.publish, lambda: runner.active)
