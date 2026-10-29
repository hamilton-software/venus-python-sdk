"""Wash adherent cells on a tilted plate: remove media from the deep side, add buffer down the high side.

Tilting the plate pools the media at the low side of each well, so it can be removed
almost completely from the deepest point without the tips touching the cells in the
middle of the well. Fresh buffer then goes in at the opposite, high side of each well
so it runs down the wall instead of hitting the cell layer.

Deck (Vantage):

* Track 11: TIP_CAR_480BC, 300 uL tips in sites 1 and 2.
* Track 46: PLT_CAR_L5_MTP.
  * site 1 -- Costar 96 flat-bottom cell plate ("CellPlate"), 150 uL media per well.
  * site 3 -- the tilt location. On a real deck this is the tilt module's site.
* Track 59: RGT_CAR_5R60, 60 mL troughs: wash buffer in site 1, spent-media waste in site 2.
* QCG at its default deck location.

Flow:

1. The QCG moves the cell plate from site 1 to the tilt location (site 3).
2. ``tilt_labware`` offsets every well in the deck layout for a 7 degree tilt (hinge on the
   left edge, right side up), aimed at each well's DEEPEST_POINT. It does not move the tilt
   hardware: on a real deck, tilt the module to the same angle first.
3. Eight channels remove the media from each column at the deepest point and discard it
   into the waste trough.
4. ``tilt_labware`` again at the same angle, aimed at each well's HIGHEST_POINT. Calls do
   not add up -- each one is computed from the flat plate -- so this only moves the target.
5. Eight channels add buffer to each column at the high side, high in the well.
6. Transport refuses to move the plate while it is tilted (``LabwareTiltedError``).
7. ``tilt_labware(..., 0)`` returns the wells to nominal (sample tracking is kept), and the
   QCG returns the plate to site 1.

Liquid level detection and liquid following assume vertical wells, so every step uses a
fixed height with both off. Only plates can be tilted, 0 to 10 degrees.

The deepest / highest aims are as close to the wall as a tip fits, given the fixed height
the tip end sits at (``tip_end_height_mm``) and a margin to each wall. 96-well wells are
narrow, so this script passes margins below the 1.0 / 2.0 mm defaults (and the default
1000 uL tip shape is wider than the 300 uL tips used): check them on your instrument.

Runs against the simulator (``simulate=True``).
"""

from __future__ import annotations

from hamilton_venus import LabwareTiltedError, VantageClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings, QCGType, TiltPivotPoint, TiltWellPosition
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

SIMULATE = True

# --- Deck -----------------------------------------------------------------------
TIP_CARRIER_ID = "TipCarrier"
PLATE_CARRIER_ID = "PlateCarrier"
REAGENT_CARRIER_ID = "ReagentCarrier"
TIP_CARRIER_TRACK = 11
PLATE_CARRIER_TRACK = 46
REAGENT_CARRIER_TRACK = 59

CELL_PLATE_ID = "CellPlate"
BUFFER_ID = "WashBuffer"
WASTE_ID = "MediaWaste"
TIP_POOL = "300uLTips"

PLATE_SITE = "1"
TILT_SITE = "3"  # the tilt module's site on a real deck

PLATE = LABWARE.PLATE.COS_96_FL
GRIP_HEIGHT_MM = 8.0  # QCG grip height above the plate bottom

# --- Tilt ------------------------------------------------------------------------
TILT_DEGREES = 7
PIVOT = TiltPivotPoint.LEFT_EDGE

# --- Wash ------------------------------------------------------------------------
CHANNELS = list(range(1, 9))
COLUMNS = range(1, 13)
MEDIA_VOLUME_UL = 150.0
REMOVE_VOLUME_UL = 140.0  # leave a thin film so the cells never dry out
BUFFER_VOLUME_UL = 150.0
LIQUID_CLASS = (
    LIQUID_CLASSES.VANTAGE.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY
    .STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY
)

# Removal: just above the floor at the deepest point, where the media pools.
# Tip end heights above the well floor; tilt_labware aims for them too (tip_end_height_mm).
REMOVE_HEIGHT_MM = 0.5
ADD_HEIGHT_MM = 8.0

remove_settings = AspirateSettings(capacitive_lld=CapacitiveLLD.OFF, fixed_height=REMOVE_HEIGHT_MM, liquid_following=False)
waste_settings = DispenseSettings(dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=20.0, liquid_following=False)
# Addition: buffer from the trough, released high on the well wall at the highest point.
buffer_settings = AspirateSettings(capacitive_lld=CapacitiveLLD.OFF, fixed_height=2.0, liquid_following=False)
add_settings = DispenseSettings(dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=ADD_HEIGHT_MM, liquid_following=False)

# Gap kept between the tip and the low / high wall of each tilted well (defaults 1.0 / 2.0 mm).
MARGINS = {"wall_margin_mm": 0.5, "high_wall_margin_mm": 1.0}


def column(col: int) -> str:
    return f"{CELL_PLATE_ID}@col:{col}"


with VantageClient(simulate=SIMULATE) as vantage:
    vantage.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=TIP_CARRIER_TRACK, labware_id=TIP_CARRIER_ID)
    vantage.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=PLATE_CARRIER_TRACK, labware_id=PLATE_CARRIER_ID)
    vantage.add_carrier(labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=REAGENT_CARRIER_TRACK, labware_id=REAGENT_CARRIER_ID)
    for site in ("1", "2"):
        vantage.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
            carrier_id=TIP_CARRIER_ID,
            site=site,
            tip_pool=TIP_POOL,
            labware_id=f"TipRack_{site}",
        )
    vantage.add_plate(labware_definition=PLATE, carrier_id=PLATE_CARRIER_ID, site=PLATE_SITE, plate_id=CELL_PLATE_ID)
    vantage.add_reservoir(labware_definition=LABWARE.RESERVOIR.RGT_CONT_60ML, carrier_id=REAGENT_CARRIER_ID, site="1", labware_id=BUFFER_ID)
    vantage.add_reservoir(labware_definition=LABWARE.RESERVOIR.RGT_CONT_60ML, carrier_id=REAGENT_CARRIER_ID, site="2", labware_id=WASTE_ID)
    vantage.add_qcg(qcg_type=QCGType.QCG)
    vantage.instrument_init()

    # Tip counters: the operator confirms the loaded tips; a simulation starts from full racks.
    if vantage.simulate:
        vantage.tip_pool_reset_tip_counter(TIP_POOL)
        vantage.tip_pool_initialize_tip_counter(TIP_POOL)
        vantage.set_labware_volume(CELL_PLATE_ID, MEDIA_VOLUME_UL)
    else:
        vantage.tip_pool_show_tip_counters([TIP_POOL])

    # 1. Move the plate to the tilt location.
    vantage.core_transport(CELL_PLATE_ID, PLATE_CARRIER_ID, TILT_SITE, GRIP_HEIGHT_MM, eject_grip=True)
    print(f"{CELL_PLATE_ID} moved to site {TILT_SITE}")

    # 2. Tilt, aiming at the deepest point of each well.
    vantage.tilt_labware(
        CELL_PLATE_ID,
        TILT_DEGREES,
        PIVOT,
        well_position=TiltWellPosition.DEEPEST_POINT,
        tip_end_height_mm=REMOVE_HEIGHT_MM,
        **MARGINS,
    )
    print(f"Tilted {TILT_DEGREES} degrees, aimed at the deepest point")

    # 3. Remove the media from the deep side into the waste trough.
    vantage.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    for col in COLUMNS:
        vantage.aspirate(column(col), channels=CHANNELS, volumes=REMOVE_VOLUME_UL, liquid_class=LIQUID_CLASS, settings=remove_settings)
        vantage.dispense(f"{WASTE_ID}@all", channels=CHANNELS, volumes=REMOVE_VOLUME_UL, settings=waste_settings)
    vantage.tip_eject(channels=CHANNELS, tip_pool=TIP_POOL)
    print(f"Removed {REMOVE_VOLUME_UL:.0f} uL of media per well")

    # 4. Same angle, now aimed at the highest point of each well.
    vantage.tilt_labware(
        CELL_PLATE_ID,
        TILT_DEGREES,
        PIVOT,
        well_position=TiltWellPosition.HIGHEST_POINT,
        tip_end_height_mm=ADD_HEIGHT_MM,
        **MARGINS,
    )
    print("Re-aimed at the highest point")

    # 5. Add buffer down the high side. Fresh tips; they never touch the liquid in the wells.
    vantage.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    for col in COLUMNS:
        vantage.aspirate(f"{BUFFER_ID}@all", channels=CHANNELS, volumes=BUFFER_VOLUME_UL, liquid_class=LIQUID_CLASS, settings=buffer_settings)
        vantage.dispense(column(col), channels=CHANNELS, volumes=BUFFER_VOLUME_UL, settings=add_settings)
    vantage.tip_eject(channels=CHANNELS, tip_pool=TIP_POOL)
    print(f"Added {BUFFER_VOLUME_UL:.0f} uL of buffer per well")

    # 6. A tilted plate cannot be transported.
    try:
        vantage.core_transport(CELL_PLATE_ID, PLATE_CARRIER_ID, PLATE_SITE, GRIP_HEIGHT_MM, eject_grip=True)
    except LabwareTiltedError as exc:
        print(f"Transport refused: {exc}")

    # 7. Back to flat (tilt the module back to 0 as well), then return the plate.
    vantage.tilt_labware(CELL_PLATE_ID, 0)
    vantage.core_transport(CELL_PLATE_ID, PLATE_CARRIER_ID, PLATE_SITE, GRIP_HEIGHT_MM, eject_grip=True)
    print(f"{CELL_PLATE_ID} flat again and returned to site {PLATE_SITE}")

    details = vantage.get_labware_details(f"{CELL_PLATE_ID}@A1,H12").return_parameters
    for labware in details.labware:
        for well in labware.wells:
            print(f"  {well.id}: {well.volume} uL tracked")

print("Done")
