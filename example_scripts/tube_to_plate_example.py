import math
import tkinter as tk
from tkinter import messagebox, simpledialog

from hamilton_venus import StarClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode,  LightColor
from hamilton_venus.models import normalize_positions, WellOrder

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_DWP
SAMPLE_CARRIER = LABWARE.TUBE_RACK.SMP_CAR_32_12X100
REAGENT_CARRIER = LABWARE.CARRIER.RGT_CAR_5R60
TIP_RACK_HIGH = LABWARE.TIP_RACK.TIP_RACK_1000UL
TIP_RACK_STANDARD = LABWARE.TIP_RACK.TIP_RACK_300UL
RESERVOIR = LABWARE.RESERVOIR.RGT_CONT_60ML
PLATE = LABWARE.PLATE.COS_96_DW_1ML
TIP_POOL_HIGH = "1000uLTips"
TIP_POOL_STANDARD = "300uLTips"

SAMPLE_CARRIER_POSITIONS = 32
MAX_SAMPLE_CARRIERS = 3
SAMPLE_CARRIER_FIRST_TRACK = 8
# Number of deck tracks SAMPLE_CARRIER occupies, so multiple carriers can be
# placed side by side without overlapping. Every carrier definition under
# sdk_method_structure/Labware/**/*.json carries this as "MlStarCarWidthAsT" --
# open the JSON for the carrier in question to look it up. Most sample tube
# racks are 1 track wide; the 16-position rack is the only 2-track exception.
SAMPLE_CARRIER_TRACK_WIDTH = 1
MAX_SAMPLES = SAMPLE_CARRIER_POSITIONS * MAX_SAMPLE_CARRIERS

root = tk.Tk()
root.withdraw()

TOTAL_SAMPLES = simpledialog.askinteger(
    title="Tube to Plate Setup",
    prompt=f"How many samples (1-{MAX_SAMPLES})?",
    minvalue=1,
    maxvalue=MAX_SAMPLES,
)
if TOTAL_SAMPLES is None:
    messagebox.showwarning("Cancelled", "Setup was cancelled. Exiting.")
    raise SystemExit(0)

root.destroy()

NUM_SAMPLE_CARRIERS = math.ceil(TOTAL_SAMPLES / SAMPLE_CARRIER_POSITIONS)

aspirate_settings = AspirateSettings(
    capacitive_lld=CapacitiveLLD.MAX,
    submerge_depth=2.0,
    liquid_following=True,
    )

dispense_settings_buffer = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    fixed_height=15.0,
    liquid_following=False,
    )

dispense_settings_enzyme = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    fixed_height=2.0,
    liquid_following=False,
    air_transport_retract_dist=10.0
    )

dispense_settings_sample = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    capacitive_lld=CapacitiveLLD.MAX,
    submerge_depth=2.0,
    liquid_following=True,
    mix_cycles=3,
    mix_volume=300.0
    )

volumeEnzyme = 100.0
volumeBuffer = 400.0
volumeSample = 200.0

liquidClassEnzyme = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY
liquidClassBuffer = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.SURFACE_EMPTY.HIGHVOLUME_WATER_DISPENSESURFACE_EMPTY
liquidClassSample = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.SURFACE_EMPTY.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY

def parseLabwareReturn(returnValue):
    rp = returnValue.return_parameters
    print("Labware ID: ",rp["labwareName"])
    return rp["labwareName"]

try:
    with StarClient(simulate=True) as star:
        print("Connected - building deck layout")

        returnValue = star.add_carrier(
            labware_definition=TIP_CARRIER,
            left_track=1,
        )
        tipCarrier = parseLabwareReturn(returnValue)
        
        returnValue = star.add_carrier(
            labware_definition=REAGENT_CARRIER,
            left_track=7,
        )
        reagentCarrier = parseLabwareReturn(returnValue)
        
        sampleCarriers = []
        for i in range(NUM_SAMPLE_CARRIERS):
            returnValue = star.add_tube_carrier(
                labware_definition=SAMPLE_CARRIER,
                left_track=SAMPLE_CARRIER_FIRST_TRACK + i * SAMPLE_CARRIER_TRACK_WIDTH,
            )
            sampleCarriers.append(parseLabwareReturn(returnValue))

        returnValue = star.add_carrier(
            labware_definition=PLATE_CARRIER,
            left_track=12,
        )
        plateCarrier = parseLabwareReturn(returnValue)

        returnValue = star.add_reservoir(
            labware_definition=RESERVOIR,
            carrier_id=reagentCarrier,
            site="5",
            labware_id="BUFFER",
        )
        reservoirBuffer = parseLabwareReturn(returnValue)
        
        returnValue = star.add_reservoir(
            labware_definition=RESERVOIR,
            carrier_id=reagentCarrier,
            site="4",
            labware_id="ENZYME",
        )
        reservoirEnzyme = parseLabwareReturn(returnValue)

        for site in range(1, 3):
            star.add_tip_rack(
                labware_definition=TIP_RACK_HIGH,
                carrier_id=tipCarrier,
                site=str(site),
                tip_pool=TIP_POOL_HIGH,
            )
            
        for site in range(3, 6):
            star.add_tip_rack(
                labware_definition=TIP_RACK_STANDARD,
                carrier_id=tipCarrier,
                site=str(site),
                tip_pool=TIP_POOL_STANDARD,
            )

        returnValue = star.add_plate(
            labware_definition=PLATE,
            carrier_id=plateCarrier,
            site="1"
        )
        plateTarget = parseLabwareReturn(returnValue)
        
        star.add_1ml_core_grip()

        print("Deck layout built successfully")

        star.tip_pool_show_tip_counter(TIP_POOL_HIGH)
        star.tip_pool_show_tip_counter(TIP_POOL_STANDARD)

        star.status_light_set_front_light(color=LightColor.GREEN, progress=0)
        
        samplesRemaining = TOTAL_SAMPLES
        sampleCarrierLoads = []
        for carrierId in sampleCarriers:
            positionCount = min(samplesRemaining, SAMPLE_CARRIER_POSITIONS)
            sampleCarrierLoads.append((carrierId, positionCount))
            samplesRemaining -= positionCount

        for carrierId, positionCount in sampleCarrierLoads:
            star.autoload_load_carrier_by_id(
                carrier_id=carrierId,
                scan_positions=list(range(1, positionCount + 1)),
            )

        targetPositions = normalize_positions(plateTarget+"@all", well_order=WellOrder.COL_ASC, total_wells=TOTAL_SAMPLES)

        star.add_reagent(
            reagent_source=reservoirEnzyme,
            dest_plate=targetPositions,
            volume=volumeEnzyme,
            tip_pool=TIP_POOL_STANDARD,
            liquid_class=liquidClassEnzyme,
            multi_dispense=False,
            aspirate_settings=aspirate_settings,
            dispense_settings=dispense_settings_enzyme,
            optimized_tip_pickup=True,
            reuse_tips=True
        )
        
        star.add_reagent(
            reagent_source=reservoirBuffer,
            dest_plate=targetPositions,
            volume=volumeBuffer,
            tip_pool=TIP_POOL_HIGH,
            liquid_class=liquidClassBuffer,
            multi_dispense=False,
            aspirate_settings=aspirate_settings,
            dispense_settings=dispense_settings_buffer,
            optimized_tip_pickup=True,
            reuse_tips=True,
        )
        
        sourcePositions = [
            f"{carrierId}@1:{positionCount}" for carrierId, positionCount in sampleCarrierLoads
        ]

        star.replicate_samples(
            source_plate=sourcePositions,
            dest_plate=targetPositions,
            volume_per_replicate=volumeSample,
            liquid_class=liquidClassSample,
            tip_pool=TIP_POOL_STANDARD,
            replicates_per_source=1,
            aspirate_settings=aspirate_settings,
            dispense_settings=dispense_settings_sample,
        )
        
        
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
