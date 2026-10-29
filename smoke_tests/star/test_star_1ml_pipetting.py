import logging

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings

tip_pool = "transfer_tips"
channels = [1]
transfer_volume_ul = 100.0
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY
aspirate_settings = AspirateSettings()

try:
    with StarClient(simulate=True, deck_name="example_deck", logging_level=logging.INFO) as star:
        print("Connected — method is running")

        star.instrument_init()
        print("Initialization complete")

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

        print("\n1. Tip Pickup - Single 1mL tip")
        tip_pickup_response = star.tip_pickup(channels=channels, tip_pool=tip_pool)
        print(f"   Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        print("\n2. Aspirate - From source plate")
        aspirate_response = star.aspirate(
            channels=channels,
            positions="source_plate@col:1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"   Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        print("\n3. Dispense - To destination plate")
        dispense_response = star.dispense(
            channels=channels,
            positions="dest_plate@col:1",
            volumes=transfer_volume_ul,
        )
        print(f"   Dispense response: {dispense_response.model_dump(by_alias=True)}")

        print("\n4. Tip Eject - Return to tip pool")
        tip_eject_response = star.tip_eject(channels=channels)
        print(f"   Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\n1mL Pipetting Smoke Test Complete - Disconnecting")
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
