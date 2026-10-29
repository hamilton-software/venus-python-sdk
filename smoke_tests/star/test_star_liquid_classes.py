from logging import DEBUG

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError

try:
    with StarClient(simulate=True, logging_level=DEBUG, venus_trace_logging=True) as star:
        print("Connected — method is running")

        print("\n--- Liquid Devices ---")
        devices_response = star.get_liquid_devices()
        print(f"Liquid devices: {devices_response.model_dump(by_alias=True)}")

        print("\n--- Liquid Names ---")
        names_response = star.get_liquid_names()
        print(f"Liquid names: {names_response.model_dump(by_alias=True)}")

        print("\n--- Tip Types ---")
        tip_types_response = star.get_tip_types()
        print(f"Tip types: {tip_types_response.model_dump(by_alias=True)}")

        print("\n--- Liquid Classes (unfiltered) ---")
        lc_response = star.get_liquid_classes()
        print(f"Total liquid classes: {lc_response.model_dump(by_alias=True)}")

        print("\n--- Liquid Classes (filtered by dispense_mode=0, is_original=1) ---")
        lc_filtered = star.get_liquid_classes(dispense_mode=0, is_original=1)
        print(f"Filtered liquid classes: {lc_filtered.model_dump(by_alias=True)}")

        if lc_response.return_parameters.liquid_class_names:
            first_name = lc_response.return_parameters.liquid_class_names[0]

            print(f"\n--- Get Liquid Class: {first_name} ---")
            lc_definition_response = star.get_liquid_class(name=first_name)
            print(f"Liquid class definition: {lc_definition_response.model_dump(by_alias=True)}")

            print(f"\n--- Update Liquid Class: {first_name} ---")
            definition = lc_definition_response.return_parameters.definition
            update_response = star.update_liquid_class(definition=definition)
            print(f"Update response: {update_response.model_dump(by_alias=True)}")

        print("\nLiquid Classes Smoke Test Complete - Disconnecting")
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
