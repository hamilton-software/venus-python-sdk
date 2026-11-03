#!/usr/bin/env python
"""Card: Finish -- orchestrator on the instrument PC, through a local spoke.

Closes the session on the local spoke (127.0.0.1): ends the VENUS method cleanly and turns
the instrument's status light off. Always run it at the end of a workflow, even on failure --
nothing else releases a session.

With STOP_LOCAL_SERVER the local spoke itself is stopped too. Leaving it running (the
default) costs nothing -- it is reachable from this PC only -- and saves the few seconds it
takes the next workflow's first Instrument.local() to start it again.

Never starts a spoke: if none is running, there is nothing to close. Prints the result as
one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from orchestrator_client import Instrument, OrchestratorCallError

# ============================================================================
# Edit these for this workflow.
# ============================================================================

# Local port of the spoke -- the same one the workflow's other local cards use.
PORT = 8000

# Also stop the local spoke after closing the session.
STOP_LOCAL_SERVER = True

# From the card that opened the session (its "opened_session" / connection_id), to refuse
# closing a different workflow's session. None skips the check.
CONNECTION_ID = None

# Closing a session can take a while on real hardware.
CONNECT_TIMEOUT_S = 200.0

# ============================================================================


def main() -> int:
    if not Instrument.local_status(PORT)["running"]:
        print(json.dumps({"closed": False, "detail": f"No local spoke is running on port {PORT}."}))
        return 0
    try:
        instrument = Instrument(f"http://127.0.0.1:{PORT}/mcp", connection_id=CONNECTION_ID)
        closed = False
        if instrument.status().get("session_active"):
            instrument.finish(connect_timeout_s=CONNECT_TIMEOUT_S)
            closed = True
        result: dict[str, Any] = {"closed": closed}
        if STOP_LOCAL_SERVER:
            result["server"] = Instrument.stop_local(PORT)
    except OrchestratorCallError as exc:
        print(f"card_local_terminate failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
