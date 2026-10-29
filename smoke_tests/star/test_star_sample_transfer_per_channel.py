from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import AspirateMode, CapacitiveLLD, PressureLLD

channels = [1, 2, 3, 4, 5, 6, 7, 8]
transfer_volume_ul = 50.0
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_PART.STANDARDVOLUME_WATER_DISPENSEJET_PART
tip_pool = "transfer_tips"

aspirate_settings = AspirateSettings(
    aspirate_mode=[AspirateMode.NORMAL, AspirateMode.NORMAL, AspirateMode.CONSECUTIVE, AspirateMode.CONSECUTIVE,
                   AspirateMode.NORMAL, AspirateMode.NORMAL, AspirateMode.CONSECUTIVE, AspirateMode.CONSECUTIVE],
    capacitive_lld=[CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF,
                    CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF],
    pressure_lld=[PressureLLD.OFF, PressureLLD.OFF, PressureLLD.OFF, PressureLLD.OFF,
                  PressureLLD.OFF, PressureLLD.OFF, PressureLLD.OFF, PressureLLD.OFF],
    liquid_following=[False, False, True, True, False, False, True, True],
    submerge_depth=[2.0, 2.0, 3.0, 3.0, 2.0, 2.0, 3.0, 3.0],
    fixed_height=[5.0, 5.0, 4.0, 4.0, 5.0, 5.0, 4.0, 4.0],
    max_lld_difference=[3.0, 3.0, 2.0, 2.0, 3.0, 3.0, 2.0, 2.0],
    mix_cycles=[0, 0, 3, 3, 0, 0, 3, 3],
    mix_position=[3.0, 3.0, 2.0, 2.0, 3.0, 3.0, 2.0, 2.0],
    mix_volume=[0.0, 0.0, 25.0, 25.0, 0.0, 0.0, 25.0, 25.0],
    air_transport_retract_dist=[5.0, 5.0, 7.5, 7.5, 5.0, 5.0, 7.5, 7.5],
    touch_off=[0, 0, 1, 1, 0, 0, 1, 1],
    touch_off_height=[1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.5, 0.5],
)

dispense_settings = DispenseSettings(
    capacitive_lld=[CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF,
                    CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF, CapacitiveLLD.OFF],
    liquid_following=[False, False, True, True, False, False, True, True],
    submerge_depth=[2.0, 2.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0],
    fixed_height=[5.0, 5.0, 3.0, 3.0, 5.0, 5.0, 3.0, 3.0],
    mix_cycles=[0, 0, 2, 2, 0, 0, 2, 2],
    mix_position=[3.0, 3.0, 1.0, 1.0, 3.0, 3.0, 1.0, 1.0],
    mix_volume=[0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 10.0],
    air_transport_retract_dist=[5.0, 5.0, 7.5, 7.5, 5.0, 5.0, 7.5, 7.5],
    touch_off=[0, 0, 1, 1, 0, 0, 1, 1],
    touch_off_height=[1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.5, 0.5],
)

try:
    with StarClient(simulate=True, deck_name="example_deck", venus_trace_logging=True) as star:

        print("Connected — method is running")

        star.instrument_init()
        print("Initialization complete\n")

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

        print("\nTransfer with per-channel aspirate/dispense settings")

        source_positions = "source_plate@col:1"
        destination_positions = "dest_plate@col:1"

        tip_pickup_response = star.tip_pickup(channels=channels, tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=channels,
            positions=source_positions,
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=channels,
            positions=destination_positions,
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense response: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject(channels=channels)
        print(f"Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nPer-Channel Settings Smoke Test Complete - Disconnecting")
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
