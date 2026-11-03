#!/usr/bin/env python
"""Card: Finish -- closes the session, disconnecting the instrument.

One standalone card's whole script, no command-line arguments -- edit the settings
below directly for this workflow. Always run this at the end of a workflow, even on
failure -- nothing else releases a session (see orchestrator_session.py's module
docstring's "nothing cleans up a session left open" note).
"""

from __future__ import annotations

import json
import sys

# orchestrator_client is a real importable package -- either pip-installed in this
# environment, or, for a real card deployment, copied as a bare sibling directory next
# to this script (Python auto-adds a running script's own directory to sys.path, so the
# sibling package resolves with no manual sys.path code needed).
from orchestrator_client import OrchestratorCallError, finish

# ============================================================================
# Edit these for this workflow.
# ============================================================================

# A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
URL = "http://localhost:8000/mcp"

# None for direct mode (URL is a spoke). A spoke id (e.g. "FM STARlet") for hub mode.
SPOKE_ID = None

# From card_connect.py's printed "connection_id" (or a fresh get_session_status call).
# Recommended: refuses (without closing anything) if a different session is open now
# than the one meant to be closed. None skips the check.
CONNECTION_ID = None

# HTTP/hub-relay timeout for this call, in seconds.
CONNECT_TIMEOUT_S = 200.0

# ============================================================================


def main() -> int:
    try:
        finish(URL, SPOKE_ID, expected_connection_id=CONNECTION_ID, connect_timeout_s=CONNECT_TIMEOUT_S)
    except OrchestratorCallError as exc:
        print(f"card_terminate failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"closed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
