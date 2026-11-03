#!/usr/bin/env python
"""Card: manage the spoke on this same PC -- for an orchestrator that runs on the instrument PC.

The local spoke listens on 127.0.0.1 only, so nothing else on the network can reach the
instrument. Other cards get an Instrument for it with Instrument.local(), which also starts
the spoke if it isn't running -- so a separate "start" card is optional. Use this card for:

    ACTION = "start"   start the local spoke if it isn't running (otherwise leave it alone)
    ACTION = "status"  is it running? pid, url, uptime, log file -- never starts it
    ACTION = "health"  process, /ping, MCP round trip and VENUS reachability, plus the
                       spoke's status (idle / running / error / hold / paused / terminated);
                       exits 1 if anything is unhealthy
    ACTION = "stop"    close any open session (ends the VENUS method cleanly, light off),
                       then stop the spoke

Prints the result as one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys

from orchestrator_client import (
    OrchestratorCallError,
    local_spoke_health,
    local_spoke_status,
    start_local_spoke,
    stop_local_spoke,
)

# ============================================================================
# Edit these for this card.
# ============================================================================

ACTION = "health"  # "start" | "status" | "health" | "stop"

# Local port the spoke listens on (127.0.0.1 only).
PORT = 8000

# ============================================================================


def main() -> int:
    try:
        if ACTION == "start":
            result = start_local_spoke(PORT)
        elif ACTION == "status":
            result = local_spoke_status(PORT)
        elif ACTION == "health":
            result = local_spoke_health(PORT)
        elif ACTION == "stop":
            result = stop_local_spoke(PORT)
        else:
            print(f"card_local_server: unknown ACTION {ACTION!r}", file=sys.stderr)
            return 2
    except OrchestratorCallError as exc:
        print(f"card_local_server {ACTION} failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, default=str))
    return 1 if ACTION == "health" and not result["healthy"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
