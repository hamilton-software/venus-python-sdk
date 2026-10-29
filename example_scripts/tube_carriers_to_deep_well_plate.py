"""Transfer samples from 24-position tube carriers to a deep well plate.

Asks how many samples to transfer (1-96), adds the minimum number of
24-position tube carriers needed (up to 4, for up to 96 tubes total), and
transfers each tube's sample into its own well of a deep well plate using
300 uL tips. Uses only single, low-level commands (``tip_pickup`` /
``aspirate`` / ``dispense`` / ``tip_eject``) in batches of all 8 channels --
no compound commands (``replicate_samples`` etc.).

Demonstrates simulated firmware error injection (VENUS simulation mode only,
via ``hamilton_venus.error_simulator``) with NO automatic recovery -- the
point is to show an operator what an injected error looks like and let them
resolve it themselves (e.g. through Script Manager's own error-recovery
modal), not to auto-clear it out from under them. Registering multiple
simulated errors at once (before any of them has actually fired) confuses
VENUS's own simulator; the SDK now guards against this (each ``simulate_error``
clears any previously injected one), and this script also registers each on
the first loop iteration, immediately before the specific command it targets:

- Right before the first tip pickup: a simulated "no tip picked up" error, on
  channels 1-4 only -- channels 5-8 pick up normally in that same call.
- Right before the first aspiration: a simulated "insufficient liquid level"
  error (VENUS's own "not enough liquid between liquid surface and bottom
  submerge depth" firmware error), across whichever channels aspirate first.

Resolving each one (repeat, exclude, abort, ...) is left entirely to
whoever's running this -- there is no ``on_operator_error_escalation``
callback and no log-driven auto-clear here.
"""

from __future__ import annotations

import logging
import math
import tkinter as tk
from contextlib import nullcontext
from tkinter import messagebox, simpledialog

from hamilton_venus import StarClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry
from hamilton_venus.error_simulator import Module
from hamilton_venus.error_simulator._generated_errors import StarChannels1MlError
from hamilton_venus.error_simulator._generated_steps import StarStep
from hamilton_venus.models import AspirateSettings, DispenseSettings, Position, WellOrder, normalize_positions
from hamilton_venus.models.enums import CapacitiveLLD
from hamilton_venus.models.error_types import AspirateError

# Scoped to the very first aspiration below via star.use_error_profile(...) --
# no retry actions for a liquid-level error on aspirate, so it skips straight
# to operator escalation instead of the standard profile's usual one retry
# first. Every other error type/operation still falls through to
# STANDARD_PROFILE's own rules (this only overrides the one entry).
NO_RETRY_ASPIRATE_LIQUID_LEVEL_PROFILE = STANDARD_PROFILE.with_overrides(
    name="NoRetryAspirateLiquidLevel",
    operations={
        "aspirate": {
            AspirateError.LIQUID_LEVEL: ErrorEntry(actions=(), max_retries=0, allow_operator=True),
        },
    },
)

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
TIP_POOL = "300uLTips"
TIP_RACK_SITES = 2  # 2 * 96 = 192 tips available -- enough for 96 samples plus the injected retry

SAMPLE_CARRIER = LABWARE.TUBE_RACK.SMP_CAR_24_15X100
SAMPLE_CARRIER_POSITIONS = 24
SAMPLE_CARRIER_FIRST_TRACK = 7  # TIP_CARRIER (TIP_CAR_480BC) occupies tracks 1-6
SAMPLE_CARRIER_TRACK_WIDTH = 1  # MlStarCarWidthAsT for SMP_CAR_24_15x100
MAX_SAMPLE_CARRIERS = 4
MAX_SAMPLES = SAMPLE_CARRIER_POSITIONS * MAX_SAMPLE_CARRIERS  # 96

PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_DWP
PLATE_CARRIER_TRACK = 11
PLATE = LABWARE.PLATE.COS_96_DW_1ML

CHANNELS_PER_BATCH = 8  # all 8 pipetting channels
TRANSFER_VOLUME_UL = 200.0
LIQUID_CLASS = (
    LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY
)

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MAX,
    submerge_depth=2.0,
    liquid_following=True,
)
dispense_settings = DispenseSettings(
    liquid_following=False,
)


def ask_sample_count() -> int:
    root = tk.Tk()
    root.withdraw()
    count = simpledialog.askinteger(
        title="Tube to Deep Well Plate Setup",
        prompt=f"How many samples (1-{MAX_SAMPLES})?",
        minvalue=1,
        maxvalue=MAX_SAMPLES,
    )
    root.destroy()
    if count is None:
        messagebox.showwarning("Cancelled", "Setup was cancelled. Exiting.")
        raise SystemExit(0)
    return count


TOTAL_SAMPLES = ask_sample_count()
NUM_SAMPLE_CARRIERS = math.ceil(TOTAL_SAMPLES / SAMPLE_CARRIER_POSITIONS)

logging.getLogger("hamilton_venus").setLevel(logging.INFO)

try:
    with StarClient(simulate=True) as star:
        print("Connected - building deck layout")

        star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
        for site in range(1, TIP_RACK_SITES + 1):
            star.add_tip_rack(
                labware_definition=TIP_RACK,
                carrier_id="TipCarrier",
                site=str(site),
                tip_pool=TIP_POOL,
            )

        sample_carrier_ids = [f"TubeRack{i + 1}" for i in range(NUM_SAMPLE_CARRIERS)]
        for i, carrier_id in enumerate(sample_carrier_ids):
            star.add_tube_carrier(
                labware_definition=SAMPLE_CARRIER,
                left_track=SAMPLE_CARRIER_FIRST_TRACK + i * SAMPLE_CARRIER_TRACK_WIDTH,
                labware_id=carrier_id,
            )

        star.add_carrier(labware_definition=PLATE_CARRIER, left_track=PLATE_CARRIER_TRACK, labware_id="PlateCarrier")
        star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site="1", plate_id="DeepWellPlate")

        star.tip_pool_initialize_tip_counter(tip_pool=TIP_POOL)
        star.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)

        print(f"Deck built: {NUM_SAMPLE_CARRIERS} tube carrier(s) for {TOTAL_SAMPLES} sample(s)")

        # One Position per sample: tube source (carrier@1..24, wrapping across
        # carriers) and its matching deep-well-plate destination, in order.
        source_positions: list[Position] = []
        remaining = TOTAL_SAMPLES
        for carrier_id in sample_carrier_ids:
            count = min(remaining, SAMPLE_CARRIER_POSITIONS)
            source_positions += [Position(labwareId=carrier_id, wellId=str(tube)) for tube in range(1, count + 1)]
            remaining -= count

        dest_positions = normalize_positions(
            "DeepWellPlate@all", well_order=WellOrder.COL_ASC, total_wells=TOTAL_SAMPLES
        )

        for batch_start in range(0, TOTAL_SAMPLES, CHANNELS_PER_BATCH):
            batch_sources = source_positions[batch_start : batch_start + CHANNELS_PER_BATCH]
            batch_dests = dest_positions[batch_start : batch_start + CHANNELS_PER_BATCH]
            channels = list(range(1, len(batch_sources) + 1))

            print(f"Batch: samples {batch_start + 1}-{batch_start + len(batch_sources)} (channels {channels})")

            if batch_start == 0:
                print("Registering simulated 'no tip picked up' error for this tip pickup (channels 1-4)")
                star.simulate_error(
                    Module.CHANNELS_1ML,
                    StarStep.TIP_PICK_UP,
                    StarChannels1MlError.TIP_HANDLING_NO_TIP_OR_WRONG_TIP_TYPE_DETECTED,
                    channels=[1, 2, 3, 4],
                )
            star.tip_pickup(channels=channels, tip_pool=TIP_POOL)

            if batch_start == 0:
                print("Registering simulated 'insufficient liquid level' error for this aspiration")
                star.simulate_error(
                    Module.CHANNELS_1ML,
                    StarStep.ASPIRATE,
                    StarChannels1MlError.LEVEL_DETECTION_NOT_ENOUGH_LIQUID_BETWEEN_LIQUID_SURFACE_AND_BOTTOM_SUBMERGE_DEPTH_OR_LIQUID_FOLLOWING_DISTANCE_TOO_HIGH,
                )
                print("Using a no-retry error profile for this aspiration -- push straight to the operator")

            # Only the very first aspiration skips the standard profile's usual
            # one retry for a liquid-level error -- every later batch aspirates
            # under the client's normal (unscoped) active profile.
            error_profile_override = star.use_error_profile(NO_RETRY_ASPIRATE_LIQUID_LEVEL_PROFILE) if batch_start == 0 else nullcontext()
            with error_profile_override:
                star.aspirate(
                    batch_sources,
                    channels=channels,
                    volumes=TRANSFER_VOLUME_UL,
                    liquid_class=LIQUID_CLASS,
                    settings=aspirate_settings,
                )

            star.dispense(
                batch_dests,
                channels=channels,
                volumes=TRANSFER_VOLUME_UL,
                settings=dispense_settings,
            )

            star.tip_eject(channels=channels)

        print(f"Transferred {TOTAL_SAMPLES} sample(s) to DeepWellPlate")

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
