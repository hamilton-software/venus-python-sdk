#!/usr/bin/env python
"""Card: Resume / Resume From / Release -- continue a held workflow after recovery.

- RESUME_FROM_STEP = None: Resume -- re-run the held command (e.g. the aspirate that ran
  the reservoir dry, after it was refilled). The workflow's waiting call gets its result
  and the loop carries on.
- RESUME_FROM_STEP = K: Resume From -- first replay the steps from K up to the held one
  that succeeded the first time (e.g. add the reagent again after replacing damaged tips),
  then re-run the held command. Recovery commands are never replayed. PRINT_JOURNAL = True
  lists the step numbers instead of resuming.
- RELEASE = True: give up -- the waiting call fails instead.

Prints the spoke's result as one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys

from orchestrator_client import OrchestratorCallError, journal, release_hold, resume, resume_from

# ============================================================================
# Edit these for this card.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# None = Resume the held command; a step number = Resume From that step.
RESUME_FROM_STEP: int | None = None

# True = only print the journal (to pick RESUME_FROM_STEP), don't resume.
PRINT_JOURNAL = False

# True = release the hold (fail the held command) instead of resuming.
RELEASE = False

# Every replayed step runs within this one call, so allow plenty of time.
CALL_TIMEOUT_S = 600.0

# ============================================================================


def main() -> int:
    try:
        if PRINT_JOURNAL:
            result = journal(URL, SPOKE_ID)
        elif RELEASE:
            result = release_hold(URL, SPOKE_ID)
        elif RESUME_FROM_STEP is None:
            result = resume(URL, SPOKE_ID, call_timeout_s=CALL_TIMEOUT_S)
        else:
            result = resume_from(URL, SPOKE_ID, RESUME_FROM_STEP, call_timeout_s=CALL_TIMEOUT_S)
    except OrchestratorCallError as exc:
        print(f"card_resume failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
