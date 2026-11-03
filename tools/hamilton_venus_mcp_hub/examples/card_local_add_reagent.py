#!/usr/bin/env python
"""Card: Add reagent to a plate -- orchestrator on the instrument PC, through a local spoke.

Same sequence as card_add_reagent.py (pick up tips, then aspirate from a reservoir and
dispense into each destination with the same tips, then eject), but for an orchestrator that
runs on the instrument PC itself: Instrument.local() connects to a spoke on 127.0.0.1 only,
starting it in the background if it isn't running yet. Nothing else on the network can
reach it, so no URL, token or firewall rule is needed.

If no session is open yet (no separate connect card ran), this card opens one first, with
hold_on_error and the cancel_all error profile -- an instrument error then holds the step
instead of failing the card (see card_stop.py / card_recovery_action.py / card_resume.py),
and this card waits until it is resumed. Run card_local_terminate.py at the end of the
workflow. Prints a list of each step's result as one JSON line to stdout.
"""

from __future__ import annotations

import json
import sys

# orchestrator_client is a real importable package -- either pip-installed in this
# environment, or, for a real card deployment, copied as a bare sibling directory next
# to this script (Python auto-adds a running script's own directory to sys.path, so the
# sibling package resolves with no manual sys.path code needed).
from orchestrator_client import Instrument, InstrumentType, OrchestratorCallError

# ============================================================================
# Edit these for this card.
# ============================================================================

# Local port of the spoke (127.0.0.1 only). Every local card of this workflow uses the same.
PORT = 8000

# Opening a session when none is open yet (ignored when one already is).
OPEN_SESSION_IF_NEEDED = True
SIMULATE = True  # False drives the real instrument
INSTRUMENT_TYPE = InstrumentType.VANTAGE  # or InstrumentType.STAR
LOAD_PREVIOUS_DECK = True  # the deck layout VENUS last had open
DECK_NAME = None  # or a saved deck's name (instead of LOAD_PREVIOUS_DECK)

# HTTP timeout for each call, in seconds.
CALL_TIMEOUT_S = 60.0

# The reagent addition itself -- edit for this card's reservoir, plate, volume and liquid class.
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
TIP_POOL = "tips1000"
SOURCE_POSITIONS = "washbuffer@all"
DEST_POSITIONS = ["cellplate@A1", "cellplate@A2"]  # one aspirate + dispense per entry
VOLUME = 50.0
LIQUID_CLASS = "HighVolume_Water_DispenseJet_Empty"

# ============================================================================


def _held(result: dict) -> None:
    """Called once when a step is held -- tell whoever needs to recover the instrument."""
    hold = result.get("hold") or {}
    print(
        f"HELD at step {result.get('step')} ({result.get('command')}, {hold.get('reason')}): "
        f"waiting for recovery and resume. {hold.get('message') or ''}",
        file=sys.stderr,
        flush=True,
    )


def main() -> int:
    results = []
    try:
        instrument = Instrument.local(PORT, call_timeout_s=CALL_TIMEOUT_S, on_held=_held)

        if not instrument.status().get("session_active"):
            if not OPEN_SESSION_IF_NEEDED:
                print("card_local_add_reagent: no session is open -- run the connect card first.", file=sys.stderr)
                return 1
            session = instrument.start(
                simulate=SIMULATE,
                instrument_type=INSTRUMENT_TYPE,
                load_previous_deck=LOAD_PREVIOUS_DECK,
                deck_name=DECK_NAME,
                hold_on_error=False,
            )
            results.append({"opened_session": session.get("connection_id")})

        results.append(instrument.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL))
        for destination in DEST_POSITIONS:
            results.append(
                instrument.aspirate(
                    positions=SOURCE_POSITIONS,
                    channels=CHANNELS,
                    volumes=VOLUME,
                    liquid_class=LIQUID_CLASS,
                )
            )
            results.append(instrument.dispense(positions=destination, channels=CHANNELS, volumes=VOLUME))
        results.append(instrument.tip_eject(channels=CHANNELS, eject_mode="waste"))
    except OrchestratorCallError as exc:
        print(f"card_local_add_reagent failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
