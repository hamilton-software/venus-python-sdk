#!/usr/bin/env python
"""Card: recovery while the workflow is held -- e.g. replace damaged tips.

Recovery commands are the same typed Instrument methods as every other card (see
card_add_reagent.py), called on a recovery handle, instrument.recovery(): each one runs
straight away even though a step is held (a normal command would be refused), and
resume_from never replays it. Edit the sequence in main() for what this card should
recover -- e.g. unlock the cover so someone can refill a reservoir, or eject and pick up
tips -- then continue the workflow with card_resume.py. Prints a list of each step's result
as one JSON line to stdout.
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

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode). Prefer the spoke's own URL:
# it skips the hub relay hop on every command.
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# See card_action.py. None skips the check.
CONNECTION_ID = None

# HTTP/hub-relay timeout for each call, in seconds.
CALL_TIMEOUT_S = 60.0

CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
TIP_POOL = "Tips1000"

# ============================================================================


def main() -> int:
    instrument = Instrument(URL, SPOKE_ID, connection_id=CONNECTION_ID, call_timeout_s=CALL_TIMEOUT_S)
    recover = instrument.recovery()
    results = []
    try:
        # Replace damaged tips: the same calls a root SDK script would make.
        results.append(recover.tip_eject(channels=CHANNELS, eject_mode="waste"))
        results.append(recover.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL))

        # Or, to let someone at the instrument refill a reservoir / inspect the plate:
        #     results.append(recover.front_cover_unlock())
        #     ... and in a later card, once they are done:
        #     results.append(recover.front_cover_lock())
    except OrchestratorCallError as exc:
        print(f"card_recovery_action failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
