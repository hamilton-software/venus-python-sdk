"""Transfer a mastermix from 4 Eppendorf tubes to every well of a 384-well plate.

Uses 50 uL tips, picked up once and reused for the whole run (a single
reagent, so there is no cross-contamination to guard against), and only
single, low-level commands (``tip_pickup`` / ``aspirate`` / ``dispense`` /
``tip_eject``), to control the 384-well dispense order described below.
(``add_reagent(reagent_source="Tubes@1:4", ...)`` draws from the tubes the same
way -- channels 1-4 from tubes 1-4, then 5-8 -- but not with this dispense order.)

The channels are 9 mm apart but 384-well plate wells are only 4.5 mm apart,
so a single 8-channel dispense can only reach every *other* well in a column.
This script is laid out around that:

- Destination wells are resolved with ``channel_pitch_mm`` so the SDK's
  spacing-aware interleaving groups them as A1, C1, ... O1 (the odd-row set)
  and B1, D1, ... P1 (the even-row set). Every group of 8 wells is one
  simultaneous dispense on all 8 channels: 384 wells take 48 dispenses, and no
  dispense is ever narrower than 8 channels.
- The dispenses are ordered to keep head movement to a minimum: all 24
  odd-row groups first, sweeping across columns 1-24, then all 24 even-row
  groups. Consecutive dispenses only step one column (4.5 mm) in X, and the
  head shifts in Y once (4.5 mm) for the whole plate, instead of on every
  dispense as it would going column by column.
- Each channel therefore stays on one row per sweep (channel 1: A then B,
  channel 2: C then D ... channel 8: O then P), so it multi-dispenses: it
  aspirates enough for as many wells as the tip holds (tip capacity // volume
  per well), dispenses them one after another, and only then goes back to the
  tubes. The last dispense of each aspiration is an empty-tip dispense, so
  nothing is left in the tip.
- Only 4 tubes hold mastermix and two channels can't share a tube, so each
  aspiration is two steps: channels 1-4 draw from tubes 1-4, then channels
  5-8 draw from the same 4 tubes.
"""

from __future__ import annotations

import logging
import math

from hamilton_venus import StarClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML
from hamilton_venus.models import AspirateSettings, DispenseSettings, Position, WellOrder, normalize_positions
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_50UL
TIP_POOL = "50uLTips"
TIP_CARRIER_TRACK = 1  # TIP_CAR_480BC occupies tracks 1-6

TUBE_CARRIER = LABWARE.TUBE_RACK.SMP_CAR_32_EPIL  # 32 positions, 1.5 mL Eppendorf tubes
TUBE_CARRIER_ID = "MastermixTubes"
TUBE_CARRIER_TRACK = 7
# Carrier positions holding the mastermix (same mastermix in each). Positions
# are 15 mm apart, so one channel per tube; channels 5-8 reuse the same tubes
# after channels 1-4 have drawn from them.
SOURCE_TUBES = ["1", "2", "3", "4"]

PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_MTP  # carrier for 96/384-well plates
PLATE_CARRIER_TRACK = 10
PLATE = LABWARE.PLATE.COS_384_SQ
PLATE_ID = "Plate384"

CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
TIP_CAPACITY_UL = 50.0
MASTERMIX_VOLUME_UL = 5.0  # per well -- 384 * 5 = 1920 uL, ~480 uL from each tube
DISPENSES_PER_ASPIRATE = int(TIP_CAPACITY_UL // MASTERMIX_VOLUME_UL)
DISPENSE_HEIGHT_MM = 3.0  # above the well bottom

ASPIRATE_LIQUID_CLASS = (
    LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_50UL.PCRMASTERMIX.JET_PART.X1_50TIP_B_PCRMASTERMIX_J_P
)

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MAX,
    submerge_depth=2.0,
    liquid_following=True,
)
# Part-volume dispenses keep the rest of the aspirated liquid in the tip for
# the next well; the final dispense of each aspiration empties the tip.
dispense_settings_part = DispenseSettings(
    dispense_mode=DispenseMode.JET_PART_VOLUME,
    fixed_height=DISPENSE_HEIGHT_MM,
    liquid_following=False,
)
dispense_settings_empty = DispenseSettings(
    dispense_mode=DispenseMode.DRAIN_TIP_JET_MODE,
    fixed_height=DISPENSE_HEIGHT_MM,
    liquid_following=False,
)

if not 0 < MASTERMIX_VOLUME_UL <= TIP_CAPACITY_UL:
    raise SystemExit(f"Volume per well must be between 0 and {TIP_CAPACITY_UL} uL")

# One aspirate call per group of channels, one tube per channel in the group.
ASPIRATE_CHANNEL_GROUPS = [
    CHANNELS[i : i + len(SOURCE_TUBES)] for i in range(0, len(CHANNELS), len(SOURCE_TUBES))
]

logging.getLogger("hamilton_venus").setLevel(logging.INFO)

try:
    with StarClient(simulate=True) as star:
        print("Connected - building deck layout")

        star.add_carrier(labware_definition=TIP_CARRIER, left_track=TIP_CARRIER_TRACK, labware_id="TipCarrier")
        star.add_tip_rack(labware_definition=TIP_RACK, carrier_id="TipCarrier", site="1", tip_pool=TIP_POOL)

        star.add_tube_carrier(
            labware_definition=TUBE_CARRIER,
            left_track=TUBE_CARRIER_TRACK,
            labware_id=TUBE_CARRIER_ID,
        )

        star.add_carrier(labware_definition=PLATE_CARRIER, left_track=PLATE_CARRIER_TRACK, labware_id="PlateCarrier")
        star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site="1", plate_id=PLATE_ID)

        star.tip_pool_initialize_tip_counter(tip_pool=TIP_POOL)
        star.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)

        # Interleaved order for the 9 mm channels on the 4.5 mm plate:
        # A1, C1, ... O1, B1, D1, ... P1, A2, ... -- 8 wells per dispense.
        dest_positions = normalize_positions(
            f"{PLATE_ID}@all",
            well_order=WellOrder.COL_ASC,
            get_spec=star.get_labware_spec,
            channel_pitch_mm=CHANNEL_PITCH_MM_1ML,
        )
        dispense_groups = [
            dest_positions[i : i + len(CHANNELS)] for i in range(0, len(dest_positions), len(CHANNELS))
        ]
        # The groups come out column by column, alternating between the odd-row
        # set (A, C, ... O) and the even-row set (B, D, ... P). Reorder them so
        # every odd-row group is dispensed first, sweeping across columns 1-24,
        # then every even-row group: each channel stays on its own row and
        # consecutive dispenses only step one column in X. The head shifts in Y
        # once for the whole plate instead of on every dispense.
        row_sets = star.get_labware_spec(PLATE_ID).rows // len(CHANNELS)
        dispense_groups = [
            group for row_set in range(row_sets) for group in dispense_groups[row_set::row_sets]
        ]
        tube_positions = [Position(labwareId=TUBE_CARRIER_ID, wellId=tube) for tube in SOURCE_TUBES]

        total_volume = MASTERMIX_VOLUME_UL * len(dest_positions)
        print(
            f"Deck built: {len(dest_positions)} wells x {MASTERMIX_VOLUME_UL} uL = {total_volume} uL "
            f"({total_volume / len(SOURCE_TUBES):.0f} uL needed from each tube, plus dead volume)"
        )
        print(
            f"{len(dispense_groups)} dispenses of {len(CHANNELS)} channels, "
            f"up to {DISPENSES_PER_ASPIRATE} per aspiration"
        )

        star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)

        round_count = math.ceil(len(dispense_groups) / DISPENSES_PER_ASPIRATE)
        for round_index, round_start in enumerate(range(0, len(dispense_groups), DISPENSES_PER_ASPIRATE), start=1):
            round_groups = dispense_groups[round_start : round_start + DISPENSES_PER_ASPIRATE]
            aspirate_volume = MASTERMIX_VOLUME_UL * len(round_groups)

            print(
                f"Round {round_index}/{round_count}: aspirate {aspirate_volume} uL per channel, "
                f"dispense to {round_groups[0][0].well}...{round_groups[-1][-1].well}"
            )

            for channel_group in ASPIRATE_CHANNEL_GROUPS:
                star.aspirate(
                    tube_positions[: len(channel_group)],
                    channels=channel_group,
                    volumes=aspirate_volume,
                    liquid_class=ASPIRATE_LIQUID_CLASS,
                    settings=aspirate_settings,
                )

            for i, wells in enumerate(round_groups):
                is_last = i == len(round_groups) - 1
                star.dispense(
                    wells,
                    channels=CHANNELS,
                    volumes=MASTERMIX_VOLUME_UL,
                    settings=dispense_settings_empty if is_last else dispense_settings_part,
                )

        star.tip_eject(channels=CHANNELS)

        print(f"Transferred mastermix to all {len(dest_positions)} wells of {PLATE_ID}")

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
