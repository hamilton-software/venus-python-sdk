from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import LightColor

TIP_POOL = "SmokeTipPool"
TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_300UL

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id="TipCarrier1",
        )
        star.add_tip_rack(
            labware_definition=TIP_RACK_DEFINITION,
            carrier_id="TipCarrier1",
            site="1",
            tip_pool=TIP_POOL,
        )
        print("Layout built")

        star.instrument_init()
        print("Initialization complete")

        print("\n--- Status Light Commands ---")
        star.status_light_set_front_light(color=LightColor.GREEN)
        print("Status light set to GREEN")

        star.status_light_set_front_light(color=LightColor.RED, blink=True)
        print("Status light set to RED blinking")

        star.status_light_set_front_light(color=LightColor.RED, blink=True, progress=3)
        print("Status light progress set to level 3 (60%)")

        star.status_light_set_front_light(color=LightColor.WHITE)
        print("Status light turned off")

        print("\n--- Pipetting Arm Commands ---")
        x_pos_response = star.pip_arm_get_x_position()
        print(f"Pipetting arm X position: {x_pos_response.model_dump(by_alias=True)}")

        star.pip_arm_park_left()
        print("Pipetting arm parked left")

        star.pip_arm_park_right()
        print("Pipetting arm parked right")

        print("\n--- Tip Counter Commands ---")
        all_counters = star.tip_pool_get_tip_counters()
        print(f"All tip counters: {all_counters.model_dump(by_alias=True)}")

        counter = star.tip_pool_get_tip_counter(TIP_POOL)
        print(f"Tip counter for '{TIP_POOL}': {counter.model_dump(by_alias=True)}")

        available_tips = star.tip_pool_get_available_tips(TIP_POOL)
        print(f"Available tips for '{TIP_POOL}': {available_tips.model_dump(by_alias=True)}")

        missing_racks = star.tip_pool_get_missing_racks(TIP_POOL)
        print(f"Missing racks for '{TIP_POOL}': {missing_racks.model_dump(by_alias=True)}")

        star.tip_pool_initialize_tip_counter(TIP_POOL)
        print(f"Tip counter for '{TIP_POOL}' initialized")

        print("\nSystem Smoke Test Complete - Disconnecting")
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
