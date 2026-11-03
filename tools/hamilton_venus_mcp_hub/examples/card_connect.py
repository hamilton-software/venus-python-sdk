#!/usr/bin/env python
"""Card: Initialize -- opens a session and connects the instrument.

One standalone card's whole script, no command-line arguments -- edit the settings
below directly for a given workflow (copy this file per workflow if different ones
need different settings). Prints its result, including "connection_id", as one JSON
line to stdout -- wire that into later cards' CONNECTION_ID setting if your
orchestrator can pass one card's output into a later card's input (see
orchestrator_session.py's module docstring for the fallback if it can't).
"""

from __future__ import annotations

import json
import sys

# orchestrator_client is a real importable package -- either pip-installed in this
# environment, or, for a real card deployment, copied as a bare sibling directory next
# to this script (Python auto-adds a running script's own directory to sys.path, so the
# sibling package resolves with no manual sys.path code needed).
from orchestrator_client import InstrumentType, OrchestratorCallError, start

# ============================================================================
# Edit these for this workflow.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode
# (URL is the hub, and every call is relayed through the hub's own call_tool_on).
SPOKE_ID = None

# True talks to VENUS's simulator, never real hardware. Only set this False when real
# hardware is explicitly wanted.
SIMULATE = True

# Load this saved deck layout instead of rebuilding it with add_carrier/add_plate/
# add_tip_rack calls. Mutually exclusive with LOAD_PREVIOUS_DECK. None loads a blank
# deck. See card_action.py with NAME = "deck_get_saved" to discover a saved name, and
# NAME = "deck_save", KWARGS = {"deck_name": ..., "overwrite": True} to save one.
DECK_NAME = "ngs_star_moa"

# Load the last-used deck instead of a blank one. Mutually exclusive with DECK_NAME.
LOAD_PREVIOUS_DECK = False

# InstrumentType.STAR or InstrumentType.VANTAGE -- a constant, so a typo can't slip
# through to the spoke.
INSTRUMENT_TYPE = InstrumentType.STAR

# Also run instrument initialization (arm homing etc.) as part of connecting -- this is
# the expensive step (often a minute or more on real hardware) the whole card model
# exists to pay only once, not once per action. False is rarely what you want.
INITIALIZE = True

# HTTP/hub-relay timeout for this call, in seconds -- generous by default since
# connect_instrument(initialize=True) can block for a while.
CONNECT_TIMEOUT_S = 200.0

# ============================================================================


def main() -> int:
    try:
        result = start(
            URL,
            SPOKE_ID,
            simulate=SIMULATE,
            deck_name=DECK_NAME,
            load_previous_deck=LOAD_PREVIOUS_DECK,
            instrument_type=INSTRUMENT_TYPE,
            initialize=INITIALIZE,
            connect_timeout_s=CONNECT_TIMEOUT_S,
        )
    except OrchestratorCallError as exc:
        print(f"card_connect failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
