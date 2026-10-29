"""Vantage MagPip: aspirate with TADM, then dispense-on-the-fly at 2 uL/well.

Deck (three 6-track carriers on a Vantage):

* Tip carrier -- one rack of 300 uL tips.
* Reagent carrier -- a single-well trough ("Trough") all 8 MagPip channels
  draw from at once.
* Plate carrier -- the destination 96-well plate ("DestPlate").

Flow:

1. The MagPip channels pick up a full row of 300 uL tips.
2. Aspirate from the trough using a WhiPip-mode liquid class (VENUS dispense
   mode 6 -- the mode built for on-the-fly dispensing) with TADM recording
   on, so the aspirate pressure curve is available afterward.
3. Dispense on the fly: a single continuous X-axis sweep lays down 2 uL in
   every well of the destination plate, with TADM/ADC on for that pass too.
4. Tips eject to waste.

WhiPip-mode liquid classes are shop-specific (each install tunes/names its own),
so rather than hardcode a ``LIQUID_CLASSES`` constant that may not exist on
whichever instrument this runs against, this looks one up at runtime via
``get_liquid_classes(device=5, dispense_mode=6)`` -- point it at an
instrument/simulator that has at least one WhiPip liquid class defined for
300 uL MagPip tips.

Runs against the simulator (``simulate=True``). Point it at a real Vantage
fitted with MagPip channels by dropping that argument once the deck teach
points are in place.
"""

from __future__ import annotations

from hamilton_venus import VantageClient, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE,LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, TadmMode, TadmSettings

# --- Labware -----------------------------------------------------------------
TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
REAGENT_CARRIER = LABWARE.CARRIER.RGT_CAR_5R60
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_MTP
TIP_RACK_300 = LABWARE.TIP_RACK.TIP_RACK_300UL
TROUGH = LABWARE.RESERVOIR.RGT_CONT_60ML
DEST_PLATE = LABWARE.PLATE.NUN_96_FL

# --- Deck identifiers -------------------------------------------------------
TIP_POOL_300 = "300uLTips"
TROUGH_ID = "Trough"
DEST_PLATE_ID = "DestPlate"

# All 8 MagPip channels, aligned one-per-row, so a single X sweep covers
# every well of a standard 96-well plate (8 rows x 12 columns) in one pass.
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

# --- Transfer parameters -----------------------------------------------------
# 12 columns x 2 uL/well = 24 uL minimum per channel; aspirate with margin
# for dead volume/priming, comfortably inside a 300 uL tip's capacity.
ASPIRATE_VOLUME = 40.0
DISPENSE_VOLUME_PER_WELL = 2.0

# Z clearance above the plate surface during the on-the-fly sweep -- tune to
# the destination labware's well depth on your bench.
LABWARE_SURFACE_DISTANCE = 3.0

TADM_RECORDING = TadmSettings(enabled=TadmMode.RECORDING)
aspirate_settings = AspirateSettings()

def _find_whipip_liquid_class(vantage: VantageClient, *, tip_hint: str = "300") -> str:
    """Look up a WhiPip-mode (dispense mode 6) liquid class for the MagPip
    channels (device 5). Prefers a name that mentions the tip size in use
    (``tip_hint``) when more than one is available, since liquid class names
    aren't filterable by tip size directly through this call.
    """
    names = vantage.get_liquid_classes(device=5, dispense_mode=6).return_parameters.liquid_class_names
    if not names:
        raise SystemExit(
            "No WhiPip-mode liquid class (device=5 MagPip, dispense_mode=6) is defined on this "
            "instrument. Create or import one for 300 uL MagPip tips before running this script."
        )
    return next((n for n in names if tip_hint in n), names[0])


try:
    with VantageClient(simulate=True) as vantage:
        print("Connected - building deck layout")

        vantage.add_carrier(labware_definition=TIP_CARRIER, left_track=30, labware_id="TipCarrier")
        vantage.add_carrier(labware_definition=REAGENT_CARRIER, left_track=37, labware_id="ReagentCarrier")
        vantage.add_carrier(labware_definition=PLATE_CARRIER, left_track=39, labware_id="PlateCarrier")

        vantage.add_tip_rack(
            labware_definition=TIP_RACK_300,
            carrier_id="TipCarrier",
            site="1",
            tip_pool=TIP_POOL_300,
        )
        vantage.add_reservoir(
            labware_definition=TROUGH,
            carrier_id="ReagentCarrier",
            site="1",
            labware_id=TROUGH_ID,
        )
        vantage.add_plate(
            labware_definition=DEST_PLATE,
            carrier_id="PlateCarrier",
            site="1",
            plate_id=DEST_PLATE_ID,
        )

        print("Deck layout built successfully")

        vantage.instrument_init()

        liquid_class = _find_whipip_liquid_class(vantage)
        print(f"Using WhiPip liquid class: {liquid_class!r}")

        print(f"Picking up tips on channels {CHANNELS}")
        vantage.tip_pickup_magpip(channels=CHANNELS, tip_pool=TIP_POOL_300)

        print(f"Aspirating {ASPIRATE_VOLUME:.0f} uL/channel from {TROUGH_ID} (TADM recording on)")
        aspirate_response = vantage.aspirate_magpip(
            channels=CHANNELS,
            positions=f"{TROUGH_ID}@all",
            volumes=ASPIRATE_VOLUME,
            liquid_class=liquid_class,
            settings=aspirate_settings,
            tadm=TADM_RECORDING,
        )

        tadm = aspirate_response.return_parameters.tadm
        if tadm is None:
            print("  No TADM data in the aspirate response")
        else:
            for curve in tadm.tadm_curves:
                print(
                    f"  TADM channel {curve.channel_number}: {curve.step_type_name}, "
                    f"{len(curve.curve_points)} points, error={curve.error}"
                )

        print(
            f"Dispensing {DISPENSE_VOLUME_PER_WELL:.1f} uL/well across {DEST_PLATE_ID} "
            "in one on-the-fly sweep (ADC + TADM on)"
        )
        vantage.dispense_on_the_fly_magpip(
            channels=CHANNELS,
            labware_name=DEST_PLATE_ID,
            volumes=DISPENSE_VOLUME_PER_WELL,
            labware_surface_distance=LABWARE_SURFACE_DISTANCE,
            adc=True,
            tadm=TADM_RECORDING,
        )
        # dispenseOnTheFly's own response carries no inline TADM curve data
        # (VENUS returns an empty returnParameters for this action) -- the
        # ADC/TADM settings above still apply during the sweep and land in
        # the run's own trace/log, just not in this call's return value.

        print("Ejecting tips to waste")
        vantage.tip_eject_magpip(channels=CHANNELS)

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
