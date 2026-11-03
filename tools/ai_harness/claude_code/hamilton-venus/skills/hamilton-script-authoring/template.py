"""Add buffer from a trough to every well of a 96-well plate, one column at a time.

Deck (STAR):
* Tracks 1-6:  TIP_CAR_480BC, 300 uL tips in sites 1-2 (tip pool "Tips300")
* Track 7:     RGT_CAR_5R60, 60 mL trough "Buffer" in site 5
* Tracks 8-13: PLT_CAR_L5_MTP, Nunc 96 flat-bottom plate "DestPlate" in site 1

Runs headless (no dialogs), so the MCP spoke's run_script can start it. run_script forces its
own simulate setting into StarClient, whatever SIMULATE says here.
"""

from hamilton_venus import StarClient, VenusCommandAbortedError, VenusError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode

SIMULATE = True
VOLUME_UL = 100.0
LIQUID = "Water"
TIP_POOL = "Tips300"
DISPENSE_HEIGHT_MM = 5.0

aspirate_settings = AspirateSettings(capacitive_lld=CapacitiveLLD.MAX, submerge_depth=2.0, liquid_following=True)
dispense_settings = DispenseSettings(dispense_mode=DispenseMode.FROM_LIQUID_CLASS, fixed_height=DISPENSE_HEIGHT_MM)

try:
    with StarClient(simulate=SIMULATE) as star:
        # 1. Deck: carriers first, then the labware on them.
        star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="TipCarrier")
        star.add_carrier(labware_definition=LABWARE.CARRIER.RGT_CAR_5R60, left_track=7, labware_id="ReagentCarrier")
        star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=8, labware_id="PlateCarrier")
        for site in ("1", "2"):
            star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id="TipCarrier",
                              site=site, tip_pool=TIP_POOL)
        star.add_reservoir(labware_definition=LABWARE.RESERVOIR.RGT_CONT_60ML, carrier_id="ReagentCarrier",
                           site="5", labware_id="Buffer")
        star.add_plate(labware_definition=LABWARE.PLATE.NUN_96_FL, carrier_id="PlateCarrier", site="1",
                       plate_id="DestPlate")

        # 2. Tip counters: reset in simulation; on the instrument let the operator mark the tips present.
        if star.simulate:
            star.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)
        else:
            star.tip_pool_show_tip_counters(tip_pools=[TIP_POOL])

        # 3. Liquid class for this device, tip and volume (best candidate first).
        found = star.find_liquid_classes(LIQUID, dispense_mode="jet_empty", volume=VOLUME_UL, tip_pool=TIP_POOL)
        liquid_class = found.candidates[0].name
        print(f"Liquid class: {liquid_class} ({found.candidates[0].liquid_match} match)")

        # 4. Tip long enough for the plate at the dispense height?
        reach = star.check_tip_reach("DestPlate", tip_pool=TIP_POOL, height_from_bottom=DISPENSE_HEIGHT_MM)
        if not reach.ok:
            print(f"WARNING: {reach.message}")

        # 5. Transfer, one column per tip pickup. Eject even if a step fails so no tips are left on.
        for column in range(1, 13):
            star.tip_pickup(tip_pool=TIP_POOL)
            aborted = False
            try:
                star.aspirate(positions="Buffer", volumes=VOLUME_UL, liquid_class=liquid_class,
                              settings=aspirate_settings)
                star.dispense(positions=f"DestPlate@col:{column}", volumes=VOLUME_UL, settings=dispense_settings)
            except VenusCommandAbortedError:
                aborted = True  # the operator aborted in VENUS: the client is already stopped, nothing can run now
                print("Aborted in VENUS: tips are still on the channels")
                raise
            finally:
                if not aborted:
                    star.tip_eject()
            print(f"Column {column} done")
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
