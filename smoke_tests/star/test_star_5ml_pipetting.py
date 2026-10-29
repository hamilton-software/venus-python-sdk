import logging

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings

tip_pool = "transfer_tips"
aspirate_volume_ul = 100.0
dispense_volume_ul = 100.0
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

        print("\n=== Testing 5mL Pipetting Patterns ===")

        print("\n1. Tip Pickup - Using tip pool with 4 channels (5mL pattern)")
        channels_4 = [1, 2, 3, 4]
        tip_pickup_response = star.tip_pickup(
            channels=channels_4,
            tip_pool=tip_pool,
            optimized_pickup=True,
        )
        print(f"   Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        print("\n2. Aspirate - From source plate")
        aspirate_response = star.aspirate(
            channels=channels_4,
            positions="source_plate@col:1",
            volumes=aspirate_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"   Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        print("\n3. Dispense - To destination plate")
        dispense_response = star.dispense(
            channels=channels_4,
            positions="dest_plate@col:1",
            volumes=dispense_volume_ul,
        )
        print(f"   Dispense response: {dispense_response.model_dump(by_alias=True)}")

        print("\n4. Tip Eject - Return to tip pool")
        tip_eject_response = star.tip_eject(
            channels=channels_4,
        )
        print(f"   Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\n5. Tip Pickup - Second batch using all 8 channels")
        channels_8 = [1, 2, 3, 4, 5, 6, 7, 8]
        tip_pickup_response2 = star.tip_pickup(
            channels=channels_8,
            tip_pool=tip_pool,
            optimized_pickup=True,
        )
        print(f"   Tip pickup response: {tip_pickup_response2.model_dump(by_alias=True)}")

        print("\n6. Aspirate - From source plate with all 8 channels")
        aspirate_response2 = star.aspirate(
            channels=channels_8,
            positions="source_plate@col:2",
            volumes=dispense_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"   Aspirate response: {aspirate_response2.model_dump(by_alias=True)}")

        print("\n7. Dispense - To destination plate with all 8 channels")
        dispense_response2 = star.dispense(
            channels=channels_8,
            positions="dest_plate@col:2",
            volumes=dispense_volume_ul,
        )
        print(f"   Dispense response: {dispense_response2.model_dump(by_alias=True)}")

        print("\n8. Tip Eject - All channels to waste")
        tip_eject_response2 = star.tip_eject(
            channels=channels_8,
        )
        print(f"   Tip eject response: {tip_eject_response2.model_dump(by_alias=True)}")

        print("\n=== 5mL Pipetting Patterns Smoke Test Complete - Disconnecting ===")

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
