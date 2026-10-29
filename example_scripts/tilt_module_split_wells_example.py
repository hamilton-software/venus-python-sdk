"""Media exchange in a tilted 6-well plate, four channels per well.

Shows the three tilt features working together:

* ``TiltModuleClient`` moves the MFX Tilt Module **hardware** (RS-232, no VENUS).
* ``tilt_labware`` tells VENUS the plate is tilted, so the channels go to the tilted
  wells (the **deck layout**). It does not move anything.
* ``split_wells`` places channel-pitch slots in each large well, so four 1 mL channels
  pipette side by side in one well instead of one at a time.

Keep the hardware and the layout in step: tilt the hardware, then the layout; flatten
the layout, then the hardware. A tilted plate cannot be transported until
``tilt_labware(..., 0)``.

Deck (plate carrier):

* site 1 -- where the cell plate (Greiner 6-well) starts.
* site 3 -- the tilt module's site. On a real deck the module sits here; the QCG moves
  the plate onto it and back.

Steps:

1. The QCG moves the cell plate onto the tilt module (site 3).
2. The module tilts to 10 degrees, then ``tilt_labware`` tilts the plate in the layout,
   aimed at each well's deepest point for tips 0.5 mm above the floor.
3. ``split_wells`` gives each well as many slots as fit, as close to the deepest point as
   they fit: three on this plate, keeping 1 mm from the low wall.
4. Channels 1-3 remove the media from every well, three slots at a time, into a waste trough.
5. ``tilt_labware`` re-aims at the highest point, for tips dispensing 10 mm above the floor.
   The splits are rebuilt for it: four slots fit there.
6. Fresh tips add buffer on the high side of every well, away from the cells pooled at the
   low side, four channels per well. The high wall leans over the tips, and keeps a 2 mm
   margin, so four slots sit only a couple of millimetres off centre there. To dispense
   closer to the high wall, use fewer channels for this step (e.g. ``fit=2`` or a single
   channel): more passes, but nearer the wall.
7. The layout, then the module, go back to flat, and the QCG returns the plate to site 1.

LLD and liquid following assume vertical wells, so every step uses a fixed height with
both off. Runs against the simulators (``SIMULATE``); for a real run, set
``SIMULATE = False`` and fill in ``TILT_COM_PORT`` / ``TILT_MODULE`` (read the module name
with ``hamilton-tilt-module --probe COMn``).
"""

from __future__ import annotations

from hamilton_venus import TiltModuleClient, VantageClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    AspirateSettings,
    DispenseSettings,
    QCGType,
    SplitChannelType,
    SplitWellFit,
    TiltWellPosition,
)
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

SIMULATE = True

# Tilt module: system 1 is one COM port; the module's two-character name on it.
TILT_SYSTEM = 1
TILT_COM_PORT = 1
TILT_MODULE = "T1"
TILT_DEGREES = 10

TIP_CARRIER_ID = "TipCarrier"
PLATE_CARRIER_ID = "PlateCarrier"
REAGENT_CARRIER_ID = "ReagentCarrier"
CELL_PLATE_ID = "CellPlate"
BUFFER_ID = "WashBuffer"
WASTE_ID = "MediaWaste"
TIP_POOL = "Tips1000"

PLATE_SITE = "1"
TILT_SITE = "3"  # the tilt module's site
GRIP_HEIGHT_MM = 8.0  # QCG grip height above the plate bottom

WELLS = ["A1", "B1", "A2", "B2", "A3", "B3"]
REMOVE_CHANNELS = [1, 2, 3]  # one per slot: channel c goes to slot c
ADD_CHANNELS = [1, 2, 3, 4]
MEDIA_PER_WELL_UL = 2000.0
REMOVE_PER_CHANNEL_UL = 600.0  # 3 x 600 = 1800 uL: leaves a thin film so the cells never dry out
BUFFER_PER_CHANNEL_UL = 500.0  # 4 x 500 = 2000 uL per well

LIQUID_CLASS = (
    LIQUID_CLASSES.VANTAGE.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.SURFACE_EMPTY.HIGHVOLUME_WATER_DISPENSESURFACE_EMPTY
)

# Removal: just above the floor at the deepest point, where the media pools.
# Tip end heights above the well floor; tilt_labware aims for them too (tip_end_height_mm).
REMOVE_HEIGHT_MM = 0.5
ADD_HEIGHT_MM = 10.0

remove_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.OFF, fixed_height=REMOVE_HEIGHT_MM, liquid_following=False
)
waste_settings = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=20.0, liquid_following=False
)
# Addition: buffer from the trough, released high in the well, on its high side.
buffer_settings = AspirateSettings(capacitive_lld=CapacitiveLLD.OFF, fixed_height=2.0, liquid_following=False)
add_settings = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=ADD_HEIGHT_MM, liquid_following=False
)


def show_splits(vantage: VantageClient) -> None:
    for site in vantage.get_split_wells(CELL_PLATE_ID):
        plan = site.plan
        print(
            f"  {site.parent_well}: {site.slot_count} slots ({site.split_labware}), "
            f"{abs(plan.x_shift_applied):.1f} mm from the well centre "
            f"(aimed at {abs(plan.requested_x_shift):.1f} mm)"
        )


with VantageClient(simulate=SIMULATE) as vantage, TiltModuleClient(simulate=SIMULATE) as tilt:
    # -- deck -------------------------------------------------------------------------
    vantage.add_carrier(LABWARE.CARRIER.TIP_CAR_480BC, left_track=11, labware_id=TIP_CARRIER_ID)
    vantage.add_carrier(LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=46, labware_id=PLATE_CARRIER_ID)
    vantage.add_carrier(LABWARE.CARRIER.RGT_CAR_5R60, left_track=59, labware_id=REAGENT_CARRIER_ID)
    for site in ("1", "2"):
        vantage.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
            carrier_id=TIP_CARRIER_ID,
            site=site,
            tip_pool=TIP_POOL,
            labware_id=f"TipRack_{site}",
        )
    vantage.add_plate(
        labware_definition=LABWARE.PLATE.GREINER_CULTURE_PLATE_6,
        carrier_id=PLATE_CARRIER_ID,
        site=PLATE_SITE,
        plate_id=CELL_PLATE_ID,
    )
    vantage.add_reservoir(LABWARE.RESERVOIR.RGT_CONT_60ML, REAGENT_CARRIER_ID, "1", labware_id=BUFFER_ID)
    vantage.add_reservoir(LABWARE.RESERVOIR.RGT_CONT_60ML, REAGENT_CARRIER_ID, "2", labware_id=WASTE_ID)
    vantage.add_qcg(qcg_type=QCGType.QCG)
    vantage.instrument_init()

    # Tip counters: the operator confirms the loaded tips; a simulation starts from full racks.
    if vantage.simulate:
        vantage.tip_pool_reset_tip_counter(TIP_POOL)
        vantage.tip_pool_initialize_tip_counter(TIP_POOL)
        vantage.set_labware_volume(CELL_PLATE_ID, MEDIA_PER_WELL_UL)
    else:
        vantage.tip_pool_show_tip_counters([TIP_POOL])

    # -- tilt module: open its COM port and home it (flat) -----------------------------
    tilt.tilt_module_connect(TILT_SYSTEM, TILT_COM_PORT)
    print(tilt.tilt_module_initialize(TILT_SYSTEM, TILT_MODULE).return_parameters.message)

    # 1. Plate onto the tilt module.
    vantage.core_transport(CELL_PLATE_ID, PLATE_CARRIER_ID, TILT_SITE, GRIP_HEIGHT_MM, eject_grip=True)
    print(f"{CELL_PLATE_ID} moved onto the tilt module (site {TILT_SITE})")

    # 2. Tilt: the hardware first, then the layout.
    tilt.tilt_module_move_to_position(TILT_SYSTEM, TILT_MODULE, TILT_DEGREES)
    vantage.tilt_labware(
        CELL_PLATE_ID,
        TILT_DEGREES,
        well_position=TiltWellPosition.DEEPEST_POINT,
        tip_end_height_mm=REMOVE_HEIGHT_MM,
    )
    print(f"Module and layout tilted {TILT_DEGREES} degrees, aimed at the deepest point")

    # 3. Several channels per well. The slots follow tilt_labware's aim (the deepest point),
    #    tip end height and margins; MAX_CHANNELS uses as many tips as fit, as close as they fit.
    vantage.split_wells(
        CELL_PLATE_ID, WELLS, channel_type=SplitChannelType.ONE_ML, fit=SplitWellFit.MAX_CHANNELS
    )
    show_splits(vantage)

    # 4. Remove the media: channels 1-3 on one well go to its three slots.
    vantage.tip_pickup(channels=REMOVE_CHANNELS, tip_pool=TIP_POOL)
    for well in WELLS:
        vantage.aspirate(
            f"{CELL_PLATE_ID}@{well}",
            channels=REMOVE_CHANNELS,
            volumes=REMOVE_PER_CHANNEL_UL,
            liquid_class=LIQUID_CLASS,
            settings=remove_settings,
        )
        vantage.dispense(
            f"{WASTE_ID}@all", channels=REMOVE_CHANNELS, volumes=REMOVE_PER_CHANNEL_UL, settings=waste_settings
        )
    vantage.tip_eject(channels=REMOVE_CHANNELS, tip_pool=TIP_POOL)
    print(f"Removed {len(REMOVE_CHANNELS) * REMOVE_PER_CHANNEL_UL:.0f} uL of media per well")

    # 5. Same angle, re-aimed at the high wall for the dispense height. The splits are rebuilt.
    vantage.tilt_labware(
        CELL_PLATE_ID,
        TILT_DEGREES,
        well_position=TiltWellPosition.HIGHEST_POINT,
        tip_end_height_mm=ADD_HEIGHT_MM,
    )
    print("Re-aimed at the highest point; splits rebuilt:")
    show_splits(vantage)

    # 6. Add buffer on the high side, away from the cells. Fresh tips; they never touch the
    #    liquid in the wells. Four tips sit only a few mm off centre here (see the docstring).
    vantage.tip_pickup(channels=ADD_CHANNELS, tip_pool=TIP_POOL)
    for well in WELLS:
        vantage.aspirate(
            f"{BUFFER_ID}@all",
            channels=ADD_CHANNELS,
            volumes=BUFFER_PER_CHANNEL_UL,
            liquid_class=LIQUID_CLASS,
            settings=buffer_settings,
        )
        vantage.dispense(
            f"{CELL_PLATE_ID}@{well}", channels=ADD_CHANNELS, volumes=BUFFER_PER_CHANNEL_UL, settings=add_settings
        )
    vantage.tip_eject(channels=ADD_CHANNELS, tip_pool=TIP_POOL)
    print(f"Added {len(ADD_CHANNELS) * BUFFER_PER_CHANNEL_UL:.0f} uL of buffer per well")

    # 7. Flat again: the layout first, then the hardware. Then the plate can move.
    #    consolidate_volumes moves the volume tracked in the slots back onto each well.
    vantage.remove_split_wells(CELL_PLATE_ID, consolidate_volumes=True)
    vantage.tilt_labware(CELL_PLATE_ID, 0)
    tilt.tilt_module_move_to_position(TILT_SYSTEM, TILT_MODULE, 0)
    vantage.core_transport(CELL_PLATE_ID, PLATE_CARRIER_ID, PLATE_SITE, GRIP_HEIGHT_MM, eject_grip=True)
    print(f"{CELL_PLATE_ID} flat again and returned to site {PLATE_SITE}")

    details = vantage.get_labware_details(f"{CELL_PLATE_ID}@{','.join(WELLS)}").return_parameters
    for labware in details.labware:
        for tracked in labware.wells:
            print(f"  {tracked.id}: {tracked.volume} uL tracked")

    # Leaving the with-block powers the module off (back to flat first) and closes its port.
    tilt.tilt_module_terminate_module(TILT_SYSTEM, TILT_MODULE)
    tilt.tilt_module_terminate_communication(TILT_SYSTEM)

print("Done")
