"""Smoke test for the Teaching category: every teaching.1mL.* command, then teach_well.

Runs in simulation by default. In simulation the wall searches return straight away, so
this checks routing and response shapes, not the measurements; set SIMULATE = False on an
instrument with the teaching needle block on the deck to check the real searches.
"""

from hamilton_venus import (
    StarClient,
    TeachingDirection,
    TeachingError,
    VenusCommandFailedError,
    VenusError,
    VenusTimeoutError,
)
from hamilton_venus.catalog import LABWARE

SIMULATE = True

PLATE_CARRIER_ID = "PlateCarrier1"
PLATE_ID = "Plate1"
WELL = "D6"

try:
    with StarClient(simulate=SIMULATE) as star:
        print("Connected — method is running")

        star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=7, labware_id=PLATE_CARRIER_ID)
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL, carrier_id=PLATE_CARRIER_ID, site="1", plate_id=PLATE_ID
        )

        print("\n--- Teaching channel ---")
        channel = star.teaching_get_channel().return_parameters.channel
        print(f"  teaching channel: {channel}")
        print(f"  set back to {star.teaching_set_channel(channel).return_parameters.channel}")

        print("\n--- Labware dimensions ---")
        dimensions = star.teaching_get_labware_dimensions(PLATE_ID, WELL).return_parameters
        print(f"  labware: {dimensions.labware}")
        print(f"  well:    {dimensions.well}")
        well = dimensions.well

        print("\n--- Needle ---")
        print(f"  picked up before: {star.teaching_is_needle_picked_up().return_parameters.is_needle_picked_up}")
        star.teaching_pickup_needle()
        print(f"  picked up after:  {star.teaching_is_needle_picked_up().return_parameters.is_needle_picked_up}")
        try:
            print("\n--- Single moves and searches ---")
            entrance = round(well.entrance_z, 1)
            position = star.teaching_move_channel(x=well.center.x, y=well.center.y, z=entrance, z_traverse=245.0)
            print(f"  moved to: {position.return_parameters}")
            wall = star.teaching_measure_wall(
                TeachingDirection.PLUS_X, safe_height=entrance + 5.0, min_search_z=entrance - 3.0, well_width=6.9
            ).return_parameters
            print(f"  +X wall: {wall.wall} {wall.status} {wall.measured}")
            star.teaching_move_channel(x=well.center.x, y=well.center.y, z=entrance, z_traverse=245.0)
            bottom = star.teaching_measure_z(entrance, max(well.bottom_z - 5.0, 100.0)).return_parameters
            print(f"  bottom: {bottom.measured_z} {bottom.status}")

            print("\n--- teach_well ---")
            try:
                result = star.teach_well(PLATE_ID, WELL)
                print(f"  center {result.center}, bottom {result.bottom_z}, offset {result.offset}")
            except (TeachingError, ValueError) as e:
                # The simulator does not track positions (moves read back a fixed X/Z) and its searches
                # report entrance Z 0 / bottom not found, so teach_well cannot complete in simulation.
                if not SIMULATE:
                    raise
                print(f"  teach_well stopped (expected in simulation): {type(e).__name__}: {e}")
        finally:
            star.teaching_eject_needle()
            needle = star.teaching_is_needle_picked_up().return_parameters.is_needle_picked_up
            print(f"\n  picked up after eject: {needle}")
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
