import logging

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

LABWARE_NAME = LABWARE.PLATE.NUN_96_FL

try:
    with VantageClient(simulate=True, logging_level=logging.INFO) as vantage:
        print("Connected - method is running")

        print("\n--- Labware Types ---")
        types_response = vantage.labware_get_types()
        print(f"Available labware types: {types_response.return_parameters.labware_types}")

        print("\n--- Labware Definitions ---")
        definitions_response = vantage.labware_get_definitions()
        count = len(definitions_response.return_parameters.labware)
        print(f"Total labware definitions available: {count}")

        print(f"\n--- Labware Definition: {LABWARE_NAME} ---")
        definition_response = vantage.labware_get_definition(LABWARE_NAME)
        print(f"Definition: {definition_response.model_dump(by_alias=True)}")

        print("\nVantage Labware Smoke Test Complete - Disconnecting")
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
