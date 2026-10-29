from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

PLATE_CARRIER_ID = "PlateCarrier1"
PLATE_ID = "Plate1"

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
            left_track=7,
            labware_id=PLATE_CARRIER_ID,
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL,
            carrier_id=PLATE_CARRIER_ID,
            site="1",
            plate_id=PLATE_ID,
        )

        print("\n--- Initial labware coordinates ---")
        initial = star.get_labware_coordinates(PLATE_ID)
        rp0 = initial.return_parameters.origin  # no well given: the labware origin
        print(f"  {PLATE_ID} initial: x={rp0.x}, y={rp0.y}, z={rp0.z}, angle={rp0.angle}")

        SHIFT_X, SHIFT_Y = 2.5, -1.0

        print("\n--- Shift labware by relative offsets ---")
        result = star.shift_labware(
            labware_name=PLATE_ID,
            relative_x=SHIFT_X,
            relative_y=SHIFT_Y,
            relative_z=0.0,
            relative_angle=0.0,
        )
        rp = result.return_parameters
        print(f"  {PLATE_ID} after shift (+{SHIFT_X}, {SHIFT_Y}): x={rp.x}, y={rp.y}, z={rp.z}, angle={rp.angle}")
        assert rp.x == rp0.x + SHIFT_X, f"Expected x={rp0.x + SHIFT_X}, got {rp.x}"
        assert rp.y == rp0.y + SHIFT_Y, f"Expected y={rp0.y + SHIFT_Y}, got {rp.y}"

        print("\nShift Labware Smoke Test Complete - Disconnecting")
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
