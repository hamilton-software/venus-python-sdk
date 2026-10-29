import logging

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError

try:
    with StarClient(simulate=True, logging_level=logging.INFO) as star:
        print("Connected — method is running")
        print(f"Instrument is connected: {star.instrument_is_connected()}")
        print(f"Instrument is idle: {star.instrument_is_idle()}")

        star.instrument_init()
        print("Initialization complete")

        print(f"Instrument configuration: {star.instrument_get_configuration().model_dump(by_alias=True)}")
        print(f"Serial number: {star.instrument_get_serial_number().model_dump(by_alias=True)}")
        print(f"Deck tracks: {star.instrument_get_deck_tracks().model_dump(by_alias=True)}")
        print(f"Deck dimensions: {star.instrument_get_deck_dimensions().model_dump(by_alias=True)}")
        print(f"Waste locations: {star.instrument_get_waste_locations().model_dump(by_alias=True)}")
        print("\nInstrument Smoke Test Complete - Disconnecting")
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
