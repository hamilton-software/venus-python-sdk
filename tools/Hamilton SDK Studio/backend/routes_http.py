"""HTTP routes: health and shutdown (the shell's contract), plus the local MCP spoke's state."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException

from orchestrator_client import local_spoke

from backend import instrument, service

router = APIRouter()
_config = service.config


# Echoes the token the Photino shell generated for this launch, so the shell's
# health check only accepts the backend it started itself -- not another app
# that happens to be listening on the same port (see BackendProcessManager.cs).
@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "instance": os.environ.get("HAMILTON_APP_INSTANCE_TOKEN", "")}


@router.get("/api/spoke")
def spoke_status() -> dict[str, Any]:
    """Whether the local MCP spoke is up (it is started on connect, not at launch)."""
    return local_spoke.local_spoke_status(_config.spoke_port)


@router.post("/api/shutdown")
async def shutdown() -> dict[str, str]:
    async def _exit_soon() -> None:
        await asyncio.sleep(0.1)
        # The shell posts this when the window closes: end the run and the instrument session first,
        # off the event loop (closing waits on the instrument), then exit.
        await asyncio.to_thread(service.close_everything)
        os._exit(0)  # noqa: SLF001 - deliberate hard exit once the session is closed

    asyncio.create_task(_exit_soon())
    return {"status": "shutting_down"}


# -- command catalog -----------------------------------------------------------------------------

_catalog = service.catalog


@router.get("/api/instrument")
def get_instrument() -> dict[str, Any]:
    """The instrument this PC has (STAR or Vantage), read from the VENUS install."""
    return instrument.detect()


@router.get("/api/commands")
def commands() -> dict[str, Any]:
    """The palette: SDK commands merged with the overlay JSON, for this PC's instrument."""
    return _catalog.payload(instrument.instrument_type())


@router.post("/api/commands/reload")
def reload_commands() -> dict[str, int]:
    """Re-read the overlay files (after editing command_defs/ or the user's overlay folder)."""
    _catalog.reload()
    return {"overlays": len(_catalog.overlays)}
