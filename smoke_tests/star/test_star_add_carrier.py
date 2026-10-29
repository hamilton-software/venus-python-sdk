import logging

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

try:
    with StarClient(simulate=True, logging_level=logging.DEBUG, venus_trace_logging=True) as star:
        print("Connected - method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id="tip_carrier",
        )
        print("Carrier added")

        print("\nAdd Carrier Smoke Test Complete - Disconnecting")
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
