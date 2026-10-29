import logging

from hamilton_venus import OVERRIDE_SAFETY_CHECKS, StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError

# WARNING: firmware_command sends raw instructions directly to the instrument.
# It is an advanced escape hatch — prefer the typed command helpers whenever one
# exists. Passing safety_bypass_token=OVERRIDE_SAFETY_CHECKS waives safety
# checks and risks hardware collisions; only do so when you fully understand the
# firmware command being issued.

try:
    with StarClient(simulate=True, logging_level=logging.INFO) as star:
        print("Connected — method is running")

        star.instrument_init()
        print("Initialization complete")

        # Send a raw firmware query. "C0RF" requests the instrument firmware
        # version. Safety bypass token is required for all firmware commands.
        response = star.firmware_command(command="C0RF", safety_bypass_token=OVERRIDE_SAFETY_CHECKS)
        print(f"Firmware response return value: {response.return_parameters.return_value!r}")
        print(f"Return code: {response.return_code}, status: {response.return_status}")

        print("\nFirmware Smoke Test Complete - Disconnecting")
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
