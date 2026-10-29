"""Inject a simulated firmware error and watch it surface, then clear it.

Works against a simulated ``StarClient`` or ``VantageClient`` (pass
``--instrument``). ``simulate_error`` writes the chosen error into the running
instrument's ``<...>_Simulator.cfg`` so the simulated firmware returns it on the
next matching command; the injection is one-shot (the simulator resets the
command to "no error" after returning it once), and the SDK's error profile then
recovers it -- for the default profile, ``NO_TIP`` on tip pickup is retried and
the retry succeeds. This script attaches a log handler so you can see the
injected error actually fire.

Requires VENUS in simulation mode.
"""

from __future__ import annotations

import argparse
import logging

from hamilton_venus import StarClient, VantageClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.error_simulator import Module
from hamilton_venus.error_simulator._generated_errors import StarChannels1MlError, VantageChannels1MlError
from hamilton_venus.error_simulator._generated_steps import StarStep, VantageStep
from hamilton_venus.exceptions import VenusError

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
TIP_POOL = "300uLTips"
CHANNELS = [1]


class _InjectedErrorWatcher(logging.Handler):
    """Captures the SDK's 'Instrument error: ... code=...' lines."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.hits: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "Instrument error:" in msg:
            self.hits.append(msg)


def run(instrument: str) -> None:
    is_star = instrument == "star"
    client_cls = StarClient if is_star else VantageClient
    step = StarStep.TIP_PICK_UP if is_star else VantageStep.TIP_PICK_UP
    # A typed constant -> exact match; the commented string -> fuzzy keyword match.
    error = (
        StarChannels1MlError.TIP_HANDLING_NO_TIP_PICKED_UP
        if is_star
        else VantageChannels1MlError.TIP_HANDLING_NO_TIP_PICKED_UP
    )
    # error = "no tip picked up"

    watcher = _InjectedErrorWatcher()
    logging.getLogger("hamilton_venus").addHandler(watcher)
    logging.getLogger("hamilton_venus").setLevel(logging.INFO)

    with client_cls(simulate=True) as client:
        client.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
        client.add_tip_rack(
            labware_definition=TIP_RACK, carrier_id="TipCarrier", site="1", tip_pool=TIP_POOL
        )
        client.instrument_init()

        print(f"[1] injecting: {Module.CHANNELS_1ML} / {step!s} / {error!s}")
        client.simulate_error(Module.CHANNELS_1ML, step, error, channels=CHANNELS)

        print("[2] running tip pickup")
        before = len(watcher.hits)
        try:
            client.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
            outcome = "recovered by the error profile"
        except VenusError as exc:
            outcome = f"raised {type(exc).__name__}"
        fired = watcher.hits[before:]
        if fired:
            print(f"    -> injected error fired: {fired[0]}")
            print(f"    -> step outcome: {outcome}")
        else:
            print("    -> no injected error observed (check instrument registration / sim mode)")

        try:
            client.tip_eject(channels=CHANNELS, tip_pool=TIP_POOL)
        except VenusError:
            pass

        print("[3] clearing simulated errors")
        client.clear_simulated_errors()

        print("[4] tip pickup again -- clean")
        before = len(watcher.hits)
        client.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
        print("    -> fired again:" if watcher.hits[before:] else "    -> no error, as expected")
        try:
            client.tip_eject(channels=CHANNELS, tip_pool=TIP_POOL)
        except VenusError:
            pass

    logging.getLogger("hamilton_venus").removeHandler(watcher)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", choices=("star", "vantage"), default="star")
    run(parser.parse_args().instrument)
    print("Done")


if __name__ == "__main__":
    main()
