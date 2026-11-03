#!/usr/bin/env python
"""Card: Stop -- hold the workflow at its next command, without aborting VENUS.

The command running right now (if any) finishes; the next one the workflow sends is held
on the spoke before it runs, and the card that sent it waits (see orchestrator_session.run).
Then send recovery commands with card_recovery_action.py and continue with card_resume.py.
Prints the spoke's stop/resume state as one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys

from orchestrator_client import OrchestratorCallError, stop

# ============================================================================
# Edit these for this card.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# ============================================================================


def main() -> int:
    try:
        result = stop(URL, SPOKE_ID)
    except OrchestratorCallError as exc:
        print(f"card_stop failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
