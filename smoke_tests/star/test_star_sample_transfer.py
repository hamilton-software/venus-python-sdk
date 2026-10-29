from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import DispenseMode

rows = "ABCDEFGH"
transfer_columns = [1, 2]
transfer_volume_ul = 50.0
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_PART.STANDARDVOLUME_WATER_DISPENSEJET_PART
tip_pool = "Transfer_Tips"
aspirate_settings = AspirateSettings()
dispense_settings = DispenseSettings()

try:
    with StarClient(simulate=True, deck_name="example_deck", venus_trace_logging=True) as star:

        print("Connected — method is running")

        print(f"Instrument is connected: {star.instrument_is_connected()}")


        star.instrument_init()

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")


        print("Initialization complete")

        for column in transfer_columns:
            print(f"\nTransfer cycle for column {column}")

            source_positions = f"Source_Plate@col:{column}"
            destination_positions = f"Dest_Plate@col:{column}"

            tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
            print(f"Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

            aspirate_response = star.aspirate(
                positions=source_positions,
                volumes=transfer_volume_ul,
                liquid_class=liquid_class,
                settings=aspirate_settings,
            )
            print(f"Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

            dispense_response = star.dispense(
                positions=destination_positions,
                volumes=transfer_volume_ul,
                settings=dispense_settings,
            )
            print(f"Dispense response: {dispense_response.model_dump(by_alias=True)}")

            tip_eject_response = star.tip_eject()
            print(f"Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nSample Transfer Smoke Test Complete - Disconnecting")
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

