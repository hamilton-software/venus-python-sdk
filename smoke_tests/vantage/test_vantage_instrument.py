import logging

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError

try:
    with VantageClient(simulate=True, logging_level=logging.INFO) as vantage:
        print("Connected — method is running")
        print(f"Instrument is connected: {vantage.instrument_is_connected()}")
        print(f"Instrument is idle: {vantage.instrument_is_idle()}")

        vantage.instrument_init()
        print("Initialization complete")

        print(f"Instrument configuration: {vantage.instrument_get_configuration().model_dump(by_alias=True)}")
        print(f"Serial number: {vantage.instrument_get_serial_number().model_dump(by_alias=True)}")
        print(f"Deck tracks: {vantage.instrument_get_deck_tracks().model_dump(by_alias=True)}")
        print(f"Deck dimensions: {vantage.instrument_get_deck_dimensions().model_dump(by_alias=True)}")
        print(f"Waste locations: {vantage.instrument_get_waste_locations().model_dump(by_alias=True)}")
        print("\nVantage Instrument Smoke Test Complete - Disconnecting")
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
