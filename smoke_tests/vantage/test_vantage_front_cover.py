import logging

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError

try:
    with VantageClient(simulate=True, logging_level=logging.INFO) as vantage:
        print("Connected - method is running")

        is_closed = vantage.front_cover_is_closed()
        print(f"Front cover is closed: {is_closed.return_parameters.is_closed}")

        is_locked = vantage.front_cover_is_locked()
        print(f"Front cover is locked: {is_locked.return_parameters.is_locked}")

        print("\nVantage Front Cover Smoke Test Complete - Disconnecting")
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
