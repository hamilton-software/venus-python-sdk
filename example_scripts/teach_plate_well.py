"""Teach a plate's true position with the teaching needle and save it as a taught location.

The teaching needle feels the plate with the channel's Z-stall sensor. ``teach_well``
finds the four walls of one well and its bottom, and compares them with the labware
definition. With ``register=True`` the corrected plate position is saved to
``TaughtLocations.json``, and VENUS applies it the next time the plate is placed on
that carrier site.

Deck layout:
  - Tracks 8-13: PLT_CAR_L5_MTP, Nunc 96 flat-bottom plate in site 1
  - The teaching needles come from the instrument's built-in teaching needle block (STAR system deck).

Teach a well near the middle of the plate (D6), so a small rotation of the plate averages out.
"""

from __future__ import annotations

from hamilton_venus import StarClient, TeachingError
from hamilton_venus.catalog import LABWARE

SIMULATE = False  # teach_well needs the instrument: its searches rely on Z-stall feedback the simulator lacks

CARRIER_ID = "PlateCarrier"
SITE = 1
PLATE_ID = "NuncPlate"
WELL = "D6"

with StarClient(simulate=SIMULATE) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=8, labware_id=CARRIER_ID)
    star.add_plate(labware_definition=LABWARE.PLATE.NUN_96_FL, carrier_id=CARRIER_ID, site=str(SITE), plate_id=PLATE_ID)

    dimensions = star.teaching_get_labware_dimensions(PLATE_ID, WELL).return_parameters
    print(f"Teaching channel: {star.teaching_get_channel().return_parameters.channel}")
    print(f"Definition: {WELL} center {dimensions.well.center}, bottom {dimensions.well.bottom_z} mm")

    star.teaching_pickup_needle()
    try:
        result = star.teach_well(PLATE_ID, WELL, register=True, carrier=CARRIER_ID, site=SITE)
    except TeachingError as error:
        print(f"Teach failed: {error}")
    else:
        for wall in result.walls:
            print(f"  wall {wall.wall}: {wall.coordinate:.1f} mm (wall top at Z {wall.entrance_z:.1f})")
        print(f"Taught center X {result.center.x:.1f}, Y {result.center.y:.1f}, bottom Z {result.bottom_z:.1f}")
        print(
            f"Offset from the definition: X {result.offset.x:+.1f}, Y {result.offset.y:+.1f}, Z {result.offset.z:+.1f}"
        )
        if result.taught_position is not None:
            position = result.taught_position
            print(f"Saved taught position for {position.labware} at {position.carrier}/{position.site}")
    finally:
        star.teaching_eject_needle()
