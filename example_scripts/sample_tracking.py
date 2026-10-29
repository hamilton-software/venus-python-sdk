"""Exercise the four Sample Tracking commands around a real pipetting step.

Sample tracking only knows about labware once something has happened to it
(loading, pipetting, transporting, ...), so the query commands report nothing
for a freshly built deck. This script therefore:

  1. queries the plate before any action   -> expect a "not loaded / not tracked" message
  2. sets a starting volume on the whole plate        (set_labware_volume)
  3. adds 100 uL of buffer to the plate     (the action that puts the plate into tracking)
  4. assigns plate and well barcodes        (set_barcodes)
  5. looks the barcodes up again            (get_barcode_locations)
  6. reads back the tracked details         (get_labware_details, selected wells and all wells)

Deck layout:
  - Tracks 1-6:  TIP_CAR_480BC, 300 uL tips in site 1
  - Track 7:     RGT_CAR_5R60, 60 mL trough (buffer) in site 5
  - Tracks 8-13: PLT_CAR_L5_MTP, Nunc 96 flat-bottom plate in site 5
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings,TrackingLabwareVolume
from hamilton_venus.models.enums import CapacitiveLLD, TrackedLabwareType

SIMULATE = True  # set False to run on the instrument

TIP_POOL = "300uLTips"
TROUGH_ID = "BufferTrough"
PLATE_ID = "NuncPlate"

PRELOADED_WELLS = f"{PLATE_ID}@col:1"  # no wells = the whole plate
PRELOADED_VOLUME_UL = 20.0
VOLUME_UL = 100.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

PLATE_BARCODE = "PLATE0001"
WELL_BARCODES = {"A1": "SAMPLE0001", "B1": "SAMPLE0002", "C1": "SAMPLE0003"}
UNKNOWN_BARCODE = "NOT_ON_DECK"


def print_labware_details(title: str, response) -> None:
    print(f"\n{title}")
    if not response.success:
        print(f"  command failed: {response.return_parameters}")
        return
    if not response.return_parameters.labware:
        print("  (no labware returned)")
    for labware in response.return_parameters.labware:
        if labware.message:
            print(f"  {labware.labware_id}: {labware.message}")
            continue
        print(
            f"  {labware.labware_id}: type={labware.type!r} barcode={labware.barcode!r} "
            f"x={labware.x:.1f} y={labware.y:.1f} z={labware.z:.1f} wells={len(labware.wells)}"
        )
        for well in labware.wells:
            if well.message:
                print(f"    {well.message}")
                continue
            volume = "not tracked" if well.volume is None else f"{well.volume:.1f} uL"
            state = "not tracked" if well.labware_state is None else repr(well.labware_state)
            barcode = "not tracked" if well.barcode is None else repr(well.barcode)
            print(
                f"    {well.id}: barcode={barcode} volume={volume} state={state} "
                #f"x={well.x:.1f} y={well.y:.1f} z={well.z:.1f}"
            )


with StarClient(simulate=SIMULATE) as star:
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="TipCarrier"
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=7, labware_id="ReagentCarrier"
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=8, labware_id="PlateCarrier"
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
    star.add_plate(
        labware_definition=LABWARE.PLATE.NUN_96_FL,
        carrier_id="PlateCarrier",
        site="5",
        plate_id=PLATE_ID,
    )

    star.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)
    star.instrument_init()

    # 1. Nothing has touched the plate yet, so tracking has nothing to report.
    print_labware_details(
        "Before any action (expect a 'not tracked yet' message):",
        star.get_labware_details([PLATE_ID]),
    )

    # 2. Tell tracking that every well of the destination plate already holds sample.
    #    (Reservoirs, tip racks and carriers have no tracked volume, so the trough is skipped.)
    volume_result = star.set_labware_volume(PRELOADED_WELLS, PRELOADED_VOLUME_UL)
    print(
        f"\nset_labware_volume({PRELOADED_WELLS}, {PRELOADED_VOLUME_UL:.0f} uL): "
        f"success={volume_result.success}"
    )
    print_labware_details(
        "Plate after set_labware_volume:", star.get_labware_details(PRELOADED_WELLS)
    )
   
    # 3. The action: pipetting puts the trough and the plate into sample tracking.
    result = star.add_reagent(
        reagent_source=TROUGH_ID,
        dest_plate=f"{PLATE_ID}@col:1",
        volume=VOLUME_UL,
        tip_pool=TIP_POOL,
        liquid_class=LIQUID_CLASS,
        reuse_tips=True,
        aspirate_settings=AspirateSettings(
            capacitive_lld=CapacitiveLLD.MID,
            submerge_depth=2.0,
            liquid_following=True,
        ),
    )
    print(f"\nadd_reagent: filled {result.wells_filled} wells with {VOLUME_UL:.0f} uL")

    # 4. Barcode the plate itself and three of its wells.
    barcode_result = star.set_barcodes(
        [
            {
                "labwareId": PLATE_ID,
                "barcode": PLATE_BARCODE,
                "wells": [
                    {"id": well, "barcode": barcode} for well, barcode in WELL_BARCODES.items()
                ],
            }
        ]
    )
    counts = barcode_result.return_parameters
    print(
        f"\nset_barcodes: {counts.total_labware_barcodes_set} labware barcode(s), "
        f"{counts.total_well_barcodes_set} well barcode(s) set"
    )

    # 5. Find the barcodes again; one of them was never assigned.
    locations = star.get_barcode_locations([PLATE_BARCODE, *WELL_BARCODES.values(), UNKNOWN_BARCODE])
    found = locations.return_parameters
    print(f"\nget_barcode_locations: {found.total_barcodes_found} found")
    for entry in found.barcodes:
        where = f"{entry.labware_id} / {entry.well}" if entry.well else entry.labware_id
        print(f"  {entry.barcode}: {where} ({entry.labware_type})")
    print(f"  not found: {found.not_found}")

    # The same result as position selectors, ready for an aspirate/dispense step.
    # Passing the barcodes keeps worklist order; the labware type filters wells / racks / carriers.
    sample_positions = locations.to_positions(barcodes=list(WELL_BARCODES.values()))
    print(f"  well positions: {sample_positions}")
    print(f"  rack positions: {locations.to_positions(TrackedLabwareType.RACK)}")

    # 6. Read the tracked state back: selected wells, then every loaded well.
    print_labware_details(
        "Selected wells after pipetting and barcoding:",
        star.get_labware_details(f"{PLATE_ID}@{','.join(WELL_BARCODES)}"),
    )
    print_labware_details(
        "Trough and whole plate (no wells given = all loaded wells):",
        star.get_labware_details(f"{PLATE_ID}@all"),
    )
