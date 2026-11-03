"""Backend-level settings shared by every workflow app (not part of the hamilton_venus SDK config)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hamilton_venus.models import InstrumentType


@dataclass(frozen=True)
class WorkflowBackendConfig:
    host: str = "127.0.0.1"
    port: int = 8734
    static_dir: Path = Path(".")
    run_log_root: Path = Path(r"C:\Program Files (x86)\HAMILTON\LogFiles")
    default_simulate: bool = True
    # Embed VENUS's firmware COM trace (.trc) into each session's SDK run log
    # (RunLogConfig.include_com_trace). Off by default -- it roughly doubles the
    # run-log size and only helps low-level firmware debugging. When on, the
    # trace's LogFiles directory is resolved from VENUS's own system/paths API.
    com_trace_enabled: bool = False
    # VENUS stores each saved deck layout as <name>.json here. Listing this
    # directory directly is a fast, local stand-in for deck.getSavedDecks --
    # querying the live instrument for that would mean waiting on a full
    # StarClient session start just to populate the connect dialog's dropdown.
    deck_layout_dir: Path = Path(r"C:\Program Files (x86)\HAMILTON\SDK\layout")
    # Which SDK client class WorkflowSession.start_session() constructs when the
    # caller doesn't pass an explicit instrument_type -- the deployment-time default
    # for apps that are single-instrument for their whole process lifetime (e.g. one
    # demo_app build per instrument). Callers that want per-session choice (e.g.
    # mcp_server) pass instrument_type explicitly to start_session() instead.
    default_instrument_type: InstrumentType = InstrumentType.STAR
