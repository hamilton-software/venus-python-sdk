from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

LABWARE_NAME = LABWARE.PLATE.NUN_96_FL_HB

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        print("\n--- Labware Types ---")
        types_response = star.labware_get_types()
        print(f"Available labware types: {types_response.return_parameters.labware_types}")

        print("\n--- Labware Definitions (unfiltered) ---")
        definitions_response = star.labware_get_definitions()
        definitions_data = definitions_response.model_dump(by_alias=True)
        print(f"Labware definitions response: {definitions_data}")

        print(f"\n--- Labware Definition: {LABWARE_NAME} ---")
        definition_response = star.labware_get_definition(LABWARE_NAME)
        definition_data = definition_response.model_dump(by_alias=True)
        print(f"Definition: {definition_response.model_dump(by_alias=True)}")

        print("\nLabware Smoke Test Complete - Disconnecting")
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
