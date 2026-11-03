#!/usr/bin/env python
"""Card: Add reagent to plate -- several typed Instrument calls in one card.

card_action.py's NAME/KWARGS style calls exactly one SDK command per card -- fine for
"show tip counter" or "move plate", but a real "add reagent to plate" step is usually a
short *sequence*: pick up tips, aspirate from a reservoir, dispense into the plate, eject
the tips. This card shows that pattern using Instrument (see orchestrator_client/
instrument.py) instead of run() directly: one typed method per step, each with the exact
keyword arguments the real StarClient/VantageClient method takes, chained in order on one
Instrument instance within this one card's process. Still no command-line arguments --
edit the settings below directly for what this specific card should do (copy this file
per card, same as the others). Prints a list of each step's result as one JSON line to
stdout.

Use this as a template for any card that needs more than one related call -- the
sequence itself (which commands, in what order) is the part to change per card; the
Instrument plumbing (construction, CONNECTION_ID, error handling) stays the same.
"""

from __future__ import annotations

import json
import sys

# orchestrator_client is a real importable package -- either pip-installed in this
# environment, or, for a real card deployment, copied as a bare sibling directory next
# to this script (Python auto-adds a running script's own directory to sys.path, so the
# sibling package resolves with no manual sys.path code needed).
from orchestrator_client import Instrument, OrchestratorCallError

# ============================================================================
# Edit these for this card.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# From card_connect.py's printed "connection_id" (or a fresh get_session_status call --
# see orchestrator_session.py's module docstring). Recommended: set this so the card
# fails clearly instead of silently acting on a different workflow's session if it's
# been replaced since. None skips the check.
CONNECTION_ID = None

# HTTP/hub-relay timeout for each call, in seconds.
CALL_TIMEOUT_S = 60.0

# The reagent-addition sequence itself -- this is the part that makes this card do
# whatever it's meant to do. Edit these for the actual reservoir/plate/volume/liquid
# class this card should use.
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
TIP_POOL = "Tips1000"
SOURCE_POSITIONS = "Trough1@all"
DEST_POSITIONS = "Plate1@col:1"
VOLUME = 100.0
LIQUID_CLASS = "StandardVolume_Water_DispenseJet_Empty"

# ============================================================================


def main() -> int:
    instrument = Instrument(URL, SPOKE_ID, connection_id=CONNECTION_ID, call_timeout_s=CALL_TIMEOUT_S)
    results = []
    try:
        results.append(instrument.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL))
        results.append(
            instrument.aspirate(
                positions=SOURCE_POSITIONS,
                channels=CHANNELS,
                volumes=VOLUME,
                liquid_class=LIQUID_CLASS,
            )
        )
        
        results.append(instrument.dispense(positions=DEST_POSITIONS, channels=CHANNELS, volumes=VOLUME))
        results.append(instrument.tip_eject(channels=CHANNELS, eject_mode="waste"))
    except OrchestratorCallError as exc:
        print(f"card_add_reagent failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
