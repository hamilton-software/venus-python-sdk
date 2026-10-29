"""Elute off an Alpaqua magnet and transfer the cleared eluent to a BioRad plate.

Deck (single DWP plate carrier, ``PLT_CAR_L5_DWP``):

* site 2 -- Abgene elution plate ("ElutionPlate"), where the bead binding /
  elution chemistry has already happened. This is the plate we move.
* site 3 -- BioRad hard-shell 96 plate ("FinalPlate"), the clean destination.
* site 5 -- Alpaqua MagEx magnet, added onto the carrier site. Once it is on the
  site you address it as the carrier site itself (DWP carrier / site 5) -- both
  for transport and for pipetting -- not as its own carrier.

Flow:

1. CO-RE gripper picks the Abgene plate up from the plain carrier site and sets
   it down on the magnet (DWP carrier / site 5).
2. Hold while the paramagnetic beads pellet against the well walls.
3. The 96-channel head (MPH96) picks up a full rack of 300 uL tips and moves
   100 uL of cleared eluent from the Abgene plate to the BioRad plate in one
   aspirate / dispense, then ejects the tips to waste.

Runs against the simulator (``simulate=True``). Point it at a real instrument by
dropping that argument once the deck teach points are in place. Step 3 needs a
STAR fitted with the CO-RE 96 head.
"""

from __future__ import annotations

import time

from hamilton_venus import StarClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import MPH96AspirateSettings, MPH96DispenseSettings
from hamilton_venus.models.enums import DispenseMode, EjectMode, LightColor

# --- Labware -----------------------------------------------------------------
TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
DWP_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_DWP
TIP_RACK_300 = LABWARE.TIP_RACK.TIP_RACK_300UL
MAGNET_ADAPTER = LABWARE.ADAPTER.ALPAQUA_MAGEX
BIORAD_PLATE = LABWARE.PLATE.BIORAD_HSP_96FULLSKIRT

# The SDK catalog / stock VENUS library has no Abgene entry, so this uses a
# Nunc 1 mL round-bottom plate as the stand-in; swap in your installed Abgene
# definition (VENUS Labware editor name) when running for real.
ABGENE_PLATE = LABWARE.PLATE.NUNC_1ML_ROUNDBOTTOM

# --- Deck identifiers -------------------------------------------------------
TIP_CARRIER_ID = "TipCarrier"
DWP_CARRIER_ID = "DWPCarrier"
MAGNET_ID = "AlpaquaMagnet"
ELUTION_PLATE_ID = "ElutionPlate"
FINAL_PLATE_ID = "FinalPlate"
TIP_POOL_300 = "300uLTips"

# Sites on the DWP carrier.
ELUTION_START_SITE = "2"   # where the Abgene plate is loaded at method start
FINAL_PLATE_SITE = "3"
MAGNET_SITE = "5"          # Alpaqua magnet sits here; address it as this site

# --- Transfer parameters --------------------------------------------------
ELUATE_VOLUME = 100.0
BEAD_SETTLE_SECONDS = 60.0

# Grip height above the plate bottom for the CO-RE gripper -- tune to the
# Abgene MIDI skirt on your bench.
GRIP_HEIGHT = 3.0

LIQUID_CLASS_300 = (
    LIQUID_CLASSES.STAR.SYSTEM.HEAD_96.TIP_300UL.WATER
    .SURFACE_EMPTY.STANDARDVOLUME_96COREHEAD_WATER_DISPENSESURFACE_EMPTY
)

# Aspirate gently just above the well bottom so the tips stay clear of the
# magnetic pellet held against the well wall; follow the meniscus down.
aspirate_settings = MPH96AspirateSettings(
    fixed_height=1.0,
    liquid_following=False,
    air_transport_retract_dist=10.0,
)

dispense_settings = MPH96DispenseSettings(
    dispense_mode=DispenseMode.FROM_LIQUID_CLASS,
    fixed_height=3.0,
    liquid_following=False,
)


try:
    with StarClient(simulate=True) as star:
        print("Connected - building deck layout")

        star.add_carrier(
            labware_definition=TIP_CARRIER,
            left_track=1,
            labware_id=TIP_CARRIER_ID,
        )
        star.add_carrier(
            labware_definition=DWP_CARRIER,
            left_track=8,
            labware_id=DWP_CARRIER_ID,
        )

        star.register_taught_offset(
            carrier=DWP_CARRIER_ID,
            site=FINAL_PLATE_SITE,
            dx=-2.0,
            dy=0.0,
            dz=0.0,
            note="Adjust for spring offset"
        )

        star.register_taught_position(
            labware=ELUTION_PLATE_ID,
            carrier=DWP_CARRIER_ID,
            site=MAGNET_SITE,
            x=275.0,
            y=146.0,
            z=207.0,
            note="Taught on magnet site for elution transfer"
        )

        # MPH96 tip support on site 1; 300 uL tip racks on the rest, one pool.
        star.add_tip_support(
            carrier_id=TIP_CARRIER_ID,
            site="1",
        )
        for site in range(2, 6):
            star.add_tip_rack(
                labware_definition=TIP_RACK_300,
                carrier_id=TIP_CARRIER_ID,
                site=str(site),
                tip_pool=TIP_POOL_300,
            )

        # Alpaqua magnet onto DWP site 5 (addressed as that carrier/site later).
        star.add_carrier_to_site(
            labware_definition=MAGNET_ADAPTER,
            carrier_id=DWP_CARRIER_ID,
            site=MAGNET_SITE,
            labware_id=MAGNET_ID,
        )

        # Abgene elution plate starts on a plain carrier site; BioRad plate is
        # the destination.
        star.add_plate(
            labware_definition=ABGENE_PLATE,
            carrier_id=DWP_CARRIER_ID,
            site=ELUTION_START_SITE,
            plate_id=ELUTION_PLATE_ID,
        )
        star.add_plate(
            labware_definition=BIORAD_PLATE,
            carrier_id=DWP_CARRIER_ID,
            site=FINAL_PLATE_SITE,
            plate_id=FINAL_PLATE_ID,
        )

        star.add_1ml_core_grip()

        print("Deck layout built successfully")

        star.instrument_init()
        star.tip_pool_show_tip_counter(TIP_POOL_300)
        star.status_light_set_front_light(color=LightColor.BLUE, progress=0)

        # 1. Move the Abgene plate from the carrier onto the magnet. The magnet
        #    lives on DWP carrier site 5, so that carrier/site is the target --
        #    the magnet is not addressed as its own carrier.
        print(f"Transporting {ELUTION_PLATE_ID} onto the magnet")
        star.core_transport(
            labware_name=ELUTION_PLATE_ID,
            carrier=DWP_CARRIER_ID,
            site=MAGNET_SITE,
            grip_height_above_bottom=GRIP_HEIGHT,
            eject_grip=True,
        )

        # 2. Let the beads pellet against the well walls before drawing eluate.
        print(f"Settling beads for {BEAD_SETTLE_SECONDS:.0f} s")
        time.sleep(BEAD_SETTLE_SECONDS)

        # 3. Transfer cleared eluate to the BioRad plate with the 96-channel
        #    head (MPH96): one full-plate pickup / aspirate / dispense / eject.
        #    Needs a STAR fitted with the CO-RE 96 head.
        print(f"Transferring {ELUATE_VOLUME:.0f} uL eluate to {FINAL_PLATE_ID}")
        star.tip_pick_up_mph96(tip_pool=TIP_POOL_300)
        star.aspirate_mph96(
            labware_id=ELUTION_PLATE_ID,
            volume=ELUATE_VOLUME,
            liquid_class=LIQUID_CLASS_300,
            settings=aspirate_settings,
        )
        star.dispense_mph96(
            labware_id=FINAL_PLATE_ID,
            volume=ELUATE_VOLUME,
            settings=dispense_settings,
        )
        star.tip_eject_mph96(eject_mode=EjectMode.WASTE)
        star.mph96_clear_tip_support(TIP_POOL_300)

        star.status_light_set_front_light(color=LightColor.GREEN, progress=5)

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
