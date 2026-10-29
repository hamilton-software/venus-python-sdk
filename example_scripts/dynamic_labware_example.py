"""Build a plate and a tube definition from scratch, use them on the deck, then delete them.

1. Build a 96-well plate and a sample tube with ``hamilton_venus.labware_builder``
   and register both with ``labware_add_definition``.
2. Deck layout:
     - Tracks 1-6:   TIP_CAR_480BC, 300 uL tips in site 1
     - Track 7:      RGT_CAR_5R60, 60 mL trough (buffer) in site 5
     - Tracks 8-13:  PLT_CAR_L5_MTP, the generated plate in site 5
     - Track 14:     SMP_CAR_24_17X75, the generated tube in positions 1-3
3. Delete both definitions again with ``labware_delete_definition`` -- the labware
   already placed on the deck stays in the layout.
4. Add buffer to every well of the generated plate.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.labware_builder import (
    body_segment,
    build_labware_definition,
    build_tube_definition,
    round_well,
)
from hamilton_venus.models import AspirateSettings
from hamilton_venus.models.enums import CapacitiveLLD

SIMULATE = True  # set False to run on the instrument

PLATE_DEFINITION = "Example_96_Flat"
TUBE_DEFINITION = "Example_Tube_17x75"

TIP_POOL = "300uLTips"
TROUGH_ID = "BufferTrough"
PLATE_ID = "ExamplePlate"
TUBE_CARRIER_ID = "TubeCarrier"
TUBE_POSITIONS = ["1", "2", "3"]

VOLUME_UL = 100.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MID,
    submerge_depth=2.0,
    liquid_following=True,
)

# 96-well flat-bottom plate with 9 mm pitch (the default). The footprint is left at the default
# 127 x 86 mm that a standard carrier site requires; the measured outer shape of the plate goes
# into body_segments (top down), which VENUS uses for its default grip parameters.
plate_definition = build_labware_definition(
    PLATE_DEFINITION,
    height=14.4,
    rows=8,
    columns=12,
    first_well_center=(14.0, 11.5),
    well=round_well(diameter=6.9, depth=11.3),
    body_segments=[
        body_segment(height=11.9, width=124.0, depth=82.0),
        body_segment(height=2.5, width=127.76, depth=85.48),
    ],
)

# 17 x 75 mm round-bottom sample tube.
tube_definition = build_tube_definition(
    TUBE_DEFINITION,
    tube=round_well(
        diameter=14.3,
        depth=73.8,
        bottom="round",
        bottom_wall_thickness=1.1,
        max_pipetting_depth=1.0,
    ),
)

with StarClient(simulate=SIMULATE) as star:
    # Adding fails if a definition with the same name exists, e.g. left over from an aborted run.
    for name in (PLATE_DEFINITION, TUBE_DEFINITION):
        try:
            star.labware_delete_definition(name)
            print(f"Removed leftover definition {name}")
        except VenusCommandFailedError:
            pass

    star.labware_add_definition(PLATE_DEFINITION, plate_definition)
    star.labware_add_definition(TUBE_DEFINITION, tube_definition)
    print(f"Added definitions {PLATE_DEFINITION} and {TUBE_DEFINITION}")

    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="TipCarrier")
    star.add_carrier(labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=7, labware_id="ReagentCarrier")
    star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=8, labware_id="PlateCarrier")
    star.add_tube_carrier(
        labware_definition=LABWARE.TUBE_RACK.SMP_CAR_24_17X75,
        left_track=14,
        labware_id=TUBE_CARRIER_ID,
    )

    star.add_tip_rack(
        labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
        carrier_id="TipCarrier",
        site="1",
        tip_pool=TIP_POOL,
    )
    star.add_reservoir(
        labware_definition=LABWARE.RESERVOIR.RGT_CONT_60ML,
        carrier_id="ReagentCarrier",
        site="5",
        labware_id=TROUGH_ID,
    )

    # The generated definitions are used by name, exactly like a shipped one.
    star.add_plate(
        labware_definition=PLATE_DEFINITION,
        carrier_id="PlateCarrier",
        site="5",
        plate_id=PLATE_ID,
    )
    tubes = star.add_tubes_to_carrier(
        labware_name=TUBE_CARRIER_ID,
        positions=[{"position": position, "tube": TUBE_DEFINITION} for position in TUBE_POSITIONS],
    )
    for tube in tubes.return_parameters.positions:
        print(f"Tube at position {tube.position}: x={tube.x}, y={tube.y}, z={tube.z}")

    # The labware is on the deck now, so the definitions can be removed from the labware folder.
    for name in (PLATE_DEFINITION, TUBE_DEFINITION):
        star.labware_delete_definition(name)
        print(f"Deleted definition {name}")

    star.instrument_init()

    result = star.add_reagent(
        reagent_source=TROUGH_ID,
        dest_plate=PLATE_ID,
        volume=VOLUME_UL,
        tip_pool=TIP_POOL,
        liquid_class=LIQUID_CLASS,
        reuse_tips=True,
        aspirate_settings=aspirate_settings,
    )
    print(f"Filled {result.wells_filled} wells with {VOLUME_UL:.0f} uL in {result.iterations} iterations")

print("Done")
