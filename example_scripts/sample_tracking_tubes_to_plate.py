"""Transfer barcoded tube samples into a plate and trace where each sample ended up.

Seventeen sample tubes sit in positions 1-17 of a 32-position tube carrier, each
holding 100 uL. The script:

  1. registers the tubes in sample tracking: a barcode and 100 uL per tube
     (set_barcodes / set_labware_volume)
  2. asks tracking where each sample barcode is (get_barcode_locations) and uses
     those positions as the transfer sources
  3. dispenses 150 uL of diluent into the 17 target wells
  4. transfers 50 uL of each sample from its tube into its target well
  5. barcodes each target well with its sample's ID (tracking follows volumes,
     not sample identity, through a transfer)
  6. traces every sample from tracking alone: its tube, its well, and the tracked
     volume on both sides (get_barcode_locations / get_labware_details)
  7. prints the plate map from the barcodes tracked on the plate

Deck layout:
  - Tracks 1-6:  TIP_CAR_480BC, 300 uL tips in sites 1-2
  - Track 7:     RGT_CAR_5R60, 60 mL trough (diluent) in site 5
  - Track 8:     SMP_CAR_32_12X100 sample tube carrier, tubes in positions 1-17
  - Tracks 12-17: PLT_CAR_L5_MTP, Nunc 96 flat-bottom plate in site 1
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    AspirateSettings,
    DispenseSettings,
    WellOrder,
    normalize_positions,
)
from hamilton_venus.models.command_types import TrackedWellDetail
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

SIMULATE = True  # set False to run on the instrument

TIP_POOL = "300uLTips"
TROUGH_ID = "Diluent"
TUBE_CARRIER_ID = "SampleTubes"
PLATE_ID = "TargetPlate"

SAMPLE_COUNT = 17
SAMPLE_START_VOLUME_UL = 100.0
SAMPLE_TRANSFER_VOLUME_UL = 50.0
DILUENT_VOLUME_UL = 150.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

SAMPLE_BARCODES = [f"SAMPLE{number:04d}" for number in range(1, SAMPLE_COUNT + 1)]
LOADED_TUBES = f"{TUBE_CARRIER_ID}@1:{SAMPLE_COUNT}"
DILUTION_SUFFIX = "-D1"  # barcode given to the plate well a sample is diluted into

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MID,
    submerge_depth=2.0,
    liquid_following=True,
)
sample_dispense_settings = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    fixed_height=2.0,
    liquid_following=False,
)


def tracked_wells(star: StarClient, labware) -> dict[tuple[str, str], TrackedWellDetail]:
    """Tracked well details keyed by (labware_id, well_id)."""
    wells = {}
    for item in star.get_labware_details(labware).return_parameters.labware:
        if item.message:
            print(f"  (no tracked details for {item.labware_id}: {item.message})")
            continue
        for well in item.wells:
            wells[(item.labware_id, well.id)] = well
    return wells


def volume_text(well: TrackedWellDetail | None) -> str:
    return "n/a" if well is None or well.volume is None else f"{well.volume:.0f} uL"


with StarClient(simulate=SIMULATE) as star:
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="TipCarrier"
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=7, labware_id="ReagentCarrier"
    )
    star.add_tube_carrier(
        labware_definition=LABWARE.TUBE_RACK.SMP_CAR_32_12X100,
        left_track=8,
        labware_id=TUBE_CARRIER_ID,
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=12, labware_id="PlateCarrier"
    )
    for site in ("1", "2"):
        star.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
            carrier_id="TipCarrier",
            site=site,
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
        site="1",
        plate_id=PLATE_ID,
    )

    star.instrument_init()

    # 1. Register the loaded tubes in sample tracking: one barcode and 100 uL each.
    #    (On an instrument the barcodes would come from an autoload scan instead.)
    barcodes_set = star.set_barcodes(LOADED_TUBES, SAMPLE_BARCODES).return_parameters
    star.set_labware_volume(LOADED_TUBES, SAMPLE_START_VOLUME_UL)
    print(
        f"Loaded {barcodes_set.total_well_barcodes_set} tubes "
        f"with {SAMPLE_START_VOLUME_UL:.0f} uL each"
    )

    # 2. Ask tracking where each sample is. From here on the script only works
    #    from barcodes; it never assumes which tube position holds which sample.
    samples = star.get_barcode_locations(SAMPLE_BARCODES)
    if samples.return_parameters.not_found:
        raise RuntimeError(f"Samples not on the deck: {samples.return_parameters.not_found}")
    sample_sources = samples.to_positions(barcodes=SAMPLE_BARCODES)

    target_positions = normalize_positions(
        f"{PLATE_ID}@all",
        well_order=WellOrder.COL_ASC,
        total_wells=SAMPLE_COUNT,
        get_spec=star.get_labware_spec,
    )

    # 3. Diluent first.
    star.add_reagent(
        reagent_source=TROUGH_ID,
        dest_plate=target_positions,
        volume=DILUENT_VOLUME_UL,
        tip_pool=TIP_POOL,
        liquid_class=LIQUID_CLASS,
        reuse_tips=True,
        aspirate_settings=aspirate_settings,
    )
    print(f"Dispensed {DILUENT_VOLUME_UL:.0f} uL diluent into {SAMPLE_COUNT} wells")

    # 4. Then the samples, from the positions tracking reported, one fresh tip per tube.
    transfer = star.replicate_samples(
        source_plate=sample_sources,
        dest_plate=target_positions,
        volume_per_replicate=SAMPLE_TRANSFER_VOLUME_UL,
        liquid_class=LIQUID_CLASS,
        tip_pool=TIP_POOL,
        replicates_per_source=1,
        aspirate_settings=aspirate_settings,
        dispense_settings=sample_dispense_settings,
    )
    print(f"Transferred {SAMPLE_TRANSFER_VOLUME_UL:.0f} uL from {transfer.sources_processed} tubes")

    # 5. Sample tracking follows volumes, not sample identity, through a transfer, so
    #    record it: each target well gets the barcode of the sample it received.
    star.set_barcodes(target_positions, [barcode + DILUTION_SUFFIX for barcode in SAMPLE_BARCODES])

    # 6. Trace, read back from tracking alone: the tube each sample is in, the well
    #    its dilution is in, and the tracked volume on both sides.
    dilutions = star.get_barcode_locations(
        [barcode + DILUTION_SUFFIX for barcode in SAMPLE_BARCODES]
    )
    tube_of = {entry.barcode: entry for entry in samples.return_parameters.barcodes}
    well_of = {
        entry.barcode.removesuffix(DILUTION_SUFFIX): entry
        for entry in dilutions.return_parameters.barcodes
    }
    details = tracked_wells(star, sample_sources + dilutions.to_positions())

    print("\nSample trace:")
    print(f"  {'sample':<12}{'tube':<18}{'left in tube':<14}{'well':<18}{'in well'}")
    for barcode in SAMPLE_BARCODES:
        tube, well = tube_of[barcode], well_of[barcode]
        print(
            f"  {barcode:<12}{tube.selector:<18}"
            f"{volume_text(details.get((tube.labware_id, tube.well))):<14}"
            f"{well.selector:<18}{volume_text(details.get((well.labware_id, well.well)))}"
        )

    # 7. Plate map, from the barcodes tracking holds for every well of the plate.
    plate_barcodes = {
        well_id: well.barcode.removesuffix(DILUTION_SUFFIX)
        for (_, well_id), well in tracked_wells(star, PLATE_ID).items()
        if well.barcode
    }
    spec = star.get_labware_spec(PLATE_ID)
    width = len(SAMPLE_BARCODES[0]) + 2
    print(f"\nPlate map ({PLATE_ID}):")
    print("    " + "".join(f"{col:<{width}}" for col in spec.col_labels))
    for row in spec.row_labels:
        cells = (plate_barcodes.get(f"{row}{col}", ".") for col in spec.col_labels)
        print(f"  {row} " + "".join(f"{cell:<{width}}" for cell in cells))
