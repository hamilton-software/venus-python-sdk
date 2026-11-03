"""T4 live test: reagent percent-full from a 60 mL trough (cLLD on), water only.

Deck (matches the instrument): tip carrier 480 on track 1 (site 1 = 1000 uL tips, sites 2-3 = 300 uL, sites 4-5 =
50 uL); plate carrier (DWP) on track 8 with a Nunc 96 flat-bottom plate on sites 1 and 2; 60 mL reagent carrier on
track 30 with a 60 mL trough on site 1 holding 45 mL of water.

One set of 8 tips draws 250 uL per channel from the trough (2 mL per aspirate) six times and dispenses each draw
into a new column of plate 2 (site 2; surface, empty). 12 mL leaves the trough in total: 45 mL -> 33 mL expected. Each
aspirate prints the measured liquid level and volume per channel so they can be compared with what was drawn.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

CARRIER_ID = "TipCarrier"
TIP_POOL = "Tips1000"
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
TROUGH_ID = "Trough1"
PLATE_ID = "Plate2"  # dispense target (site 2); plate 1 on site 1 already holds liquid from an earlier run
CYCLES = 6
VOLUME_UL = 250.0
START_VOLUME_UL = 45000.0

# After each dispense the tip must leave the well before the air gap is drawn, or the gap pulls back up the liquid
# that was just dispensed. Retract = well depth - dispense height + 2 mm, i.e. 2 mm above the well's opening.
WELL_DEPTH_MM = 11.3  # Nunc 96 flat-bottom well (labware definition: totalDepth)
DISPENSE_HEIGHT_MM = 2.0  # dispense height above the well bottom
ENTRANCE_CLEARANCE_MM = 2.0
RETRACT_DIST_MM = WELL_DEPTH_MM - DISPENSE_HEIGHT_MM + ENTRANCE_CLEARANCE_MM

LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.SURFACE_EMPTY.HIGHVOLUME_WATER_DISPENSESURFACE_EMPTY

aspirate_settings = AspirateSettings(capacitive_lld=CapacitiveLLD.MAX, submerge_depth=2.0, liquid_following=True)
dispense_settings = DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    fixed_height=DISPENSE_HEIGHT_MM,
    liquid_following=False,
    air_transport_retract_dist=RETRACT_DIST_MM,
)

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id=CARRIER_ID)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id=CARRIER_ID, site="1", tip_pool=TIP_POOL, labware_id="Rack_Tips1000")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="2", tip_pool="Tips300A", labware_id="Rack_Tips300A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="3", tip_pool="Tips300B", labware_id="Rack_Tips300B")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="4", tip_pool="Tips50A", labware_id="Rack_Tips50A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="5", tip_pool="Tips50B", labware_id="Rack_Tips50B")

    star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_DWP, left_track=8, labware_id="DwpCarrier")
    star.add_plate(labware_definition=LABWARE.PLATE.NUN_96_FL_HB, carrier_id="DwpCarrier", site="1", plate_id="Plate1")
    star.add_plate(labware_definition=LABWARE.PLATE.NUN_96_FL_HB, carrier_id="DwpCarrier", site="2", plate_id=PLATE_ID)

    star.add_carrier(labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=30, labware_id="RgtCarrier")
    star.add_reservoir(labware_definition=LABWARE.RESERVOIR.RGT_CONT_60ML, carrier_id="RgtCarrier", site="1", labware_id=TROUGH_ID)

    # VENUS only hands out tips once the pool's tip counter has been shown and confirmed at the VENUS PC.
    star.tip_pool_initialize_tip_counter(TIP_POOL)

    star.instrument_init()
    print("Initialized")

    print("Confirm the tip counter dialog at the VENUS PC (mark the tips that are missing from the rack)")
    star.tip_pool_show_tip_counter(TIP_POOL)
    print("Tip counter confirmed")

    star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    print("Picked up 8 tips")

    drawn_ul = 0.0
    for cycle in range(1, CYCLES + 1):
        result = star.aspirate(
            f"{TROUGH_ID}@all",
            channels=CHANNELS,
            volumes=VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            settings=aspirate_settings,
        )
        expected_before_ul = START_VOLUME_UL - drawn_ul
        drawn_ul += VOLUME_UL * len(CHANNELS)
        rows = result.return_parameters.channels
        volumes = [row.liquid_volume_ul for row in rows]
        print(
            f"Cycle {cycle}/{CYCLES}: expected before {expected_before_ul:.0f} uL, "
            f"measured per channel {[round(v, 0) for v in volumes]}, "
            f"levels mm {[round(row.liquid_level_mm, 1) for row in rows]}, drawn so far {drawn_ul:.0f} uL"
        )
        star.dispense(f"{PLATE_ID}@col:{cycle}", channels=CHANNELS, volumes=VOLUME_UL, settings=dispense_settings)
        print(f"Cycle {cycle}/{CYCLES}: dispensed into column {cycle}")

    star.tip_eject(channels=CHANNELS)
    print(f"Ejected tips; drew {drawn_ul:.0f} uL in total (expected left: {START_VOLUME_UL - drawn_ul:.0f} uL)")

print("Done")
