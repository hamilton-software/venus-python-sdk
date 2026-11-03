#!/usr/bin/env python
"""Card: do one SDK action -- e.g. "show tip counter", "add reagent to plate", "move
plate". One standalone card's whole script, no command-line arguments -- edit the
settings below directly for what this specific card should do (copy this file per card;
which action a given card performs is just its own NAME/KWARGS). Prints the SDK
command's own result as one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys

# orchestrator_client is a real importable package -- either pip-installed in this
# environment, or, for a real card deployment, copied as a bare sibling directory next
# to this script (Python auto-adds a running script's own directory to sys.path, so the
# sibling package resolves with no manual sys.path code needed).
from orchestrator_client import OrchestratorCallError, run

# ============================================================================
# Edit these for this card.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# The SDK command this card calls (see list_sdk_commands/describe_sdk_command), and its
# keyword arguments. This is the part that makes this card do whatever it's meant to do
# -- e.g. for a "Show tip counter" card:
#     NAME = "tip_pool_show_tip_counter"
#     KWARGS = {"tip_pool": "Tips1000"}
# or an "Add reagent to plate" card:
#     NAME = "aspirate"
#     KWARGS = {"positions": "Trough1@all", "volumes": 100.0, "liquid_class": "..."}
NAME = "instrument_get_configuration"
KWARGS: dict = {}

# From card_connect.py's printed "connection_id" (or a fresh get_session_status call --
# see orchestrator_session.py's module docstring). Recommended: set this so the card
# fails clearly instead of silently acting on a different workflow's session if it's
# been replaced since. None skips the check.
CONNECTION_ID = None

# HTTP/hub-relay timeout for this call, in seconds.
CALL_TIMEOUT_S = 60.0

# ============================================================================


def main() -> int:
    try:
        result = run(
            URL,
            SPOKE_ID,
            NAME,
            expected_connection_id=CONNECTION_ID,
            call_timeout_s=CALL_TIMEOUT_S,
            **KWARGS,
        )
    except OrchestratorCallError as exc:
        print(f"card_action failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
