from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus._internal._sdk_paths import get_sdk_labware_path
from hamilton_venus.catalog import LABWARE

TUBE_CARRIER_ID = "TubeCarrier1"

tubes_dir = get_sdk_labware_path() / "System" / "tube"
tube_definitions = sorted(p.stem for p in tubes_dir.glob("*.json")) if tubes_dir.exists() else []
if not tube_definitions:
    print(f"No tube labware definitions found in {tubes_dir}")
    print("Regenerate the catalog on this machine to populate tube definitions, then re-run this smoke test.")
    raise SystemExit(1)

print(f"Found {len(tube_definitions)} tube definition(s): {tube_definitions[:5]}")

try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        star.add_tube_carrier(
            labware_definition=LABWARE.TUBE_RACK.SMP_CAR_24_17X75,
            left_track=10,
            labware_id=TUBE_CARRIER_ID,
        )

        positions = [
            {"position": str(i + 1), "tube": tube_definitions[0]}
            for i in range(min(3, len(tube_definitions)))
        ]

        print("\n--- Add tubes to carrier ---")
        result = star.add_tubes_to_carrier(
            labware_name=TUBE_CARRIER_ID,
            positions=positions,
        )

        rp = result.return_parameters
        assert len(rp.positions) == len(positions), (
            f"Expected {len(positions)} positions, got {len(rp.positions)}"
        )
        for tube in rp.positions:
            print(f"  position={tube.position}: x={tube.x}, y={tube.y}, z={tube.z}")
            assert tube.position, "Empty position string returned"

        print("\nAdd Tubes To Carrier Smoke Test Complete - Disconnecting")
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
