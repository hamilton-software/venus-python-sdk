"""orchestrator_client: stdlib-only MCP client library for orchestrator "card" workflows.

Re-exports the public surface of orchestrator_session.py and instrument.py for
convenient ``from orchestrator_client import Instrument`` access. See
orchestrator_session.py's module docstring for the full card-model explanation
(direct mode vs. hub mode, connection_id) and instrument.py's module docstring
for the typed Instrument wrapper.
"""

from __future__ import annotations

from .instrument import Instrument
from .local_spoke import local_spoke_health, local_spoke_status, start_local_spoke, stop_local_spoke
from .orchestrator_session import (
    STAR,
    VANTAGE,
    InstrumentType,
    OrchestratorCallError,
    finish,
    hold_status,
    journal,
    recovery_call,
    release_hold,
    resume,
    resume_from,
    run,
    run_command,
    set_auth_token,
    start,
    status,
    stop,
    subscribe_command_events,
    wait_for_command_event,
)

__all__ = [
    "STAR",
    "VANTAGE",
    "Instrument",
    "InstrumentType",
    "OrchestratorCallError",
    "finish",
    "hold_status",
    "journal",
    "local_spoke_health",
    "local_spoke_status",
    "recovery_call",
    "release_hold",
    "resume",
    "resume_from",
    "run",
    "run_command",
    "set_auth_token",
    "start",
    "start_local_spoke",
    "status",
    "stop",
    "stop_local_spoke",
    "subscribe_command_events",
    "wait_for_command_event",
]
