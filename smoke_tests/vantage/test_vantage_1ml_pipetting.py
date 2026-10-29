import logging

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings

TIP_POOL = "transfer_tips_1ml"
CHANNELS = [1]
TRANSFER_STEP_1_VOLUME_UL = 100.0
TRANSFER_STEP_2_VOLUME_UL = 60.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.JET_EMPTY.HIGHVOLUME_WATER_DISPENSEJET_EMPTY
ASPIRATE_SETTINGS = AspirateSettings()
ASPIRATE_SETTINGS_STEP_2 = AspirateSettings(mix_cycles=1, mix_volume=25.0, touch_off=1)
DISPENSE_SETTINGS_STEP_2 = DispenseSettings(use_side_touch=True)

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_1000UL
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_MTP
PLATE = LABWARE.PLATE.NUN_96_FL

try:
    with VantageClient(simulate=True, logging_level=logging.INFO) as vantage:
        print("Connected - method is running")

        vantage.instrument_init()
        print("Initialization complete")

        # Tracks 1-6 are outside Pipetting Arm 1's physical reach on this Vantage; 7 is the minimum.
        vantage.add_carrier(
            labware_definition=TIP_CARRIER,
            left_track=7,
            labware_id="tip_carrier",
        )
        vantage.add_tip_rack(
            tip_pool=TIP_POOL,
            labware_definition=TIP_RACK,
            carrier_id="tip_carrier",
            site="1",
        )
        vantage.add_carrier(
            labware_definition=PLATE_CARRIER,
            left_track=13,
            labware_id="plate_carrier",
        )
        vantage.add_plate(
            labware_definition=PLATE,
            carrier_id="plate_carrier",
            site="1",
            plate_id="source_plate",
        )
        vantage.add_plate(
            labware_definition=PLATE,
            carrier_id="plate_carrier",
            site="2",
            plate_id="dest_plate",
        )
        vantage.add_liquid_waste(track=35)
        print("Layout built")

        init_tips_response = vantage.tip_pool_initialize_tip_counter(TIP_POOL)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = vantage.tip_pool_reset_tip_counter(TIP_POOL)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

        print("\n1. Tip Pickup - Single 1mL tip")
        tip_pickup_response = vantage.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
        print(f"   Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        print("\n2. Aspirate - From source plate")
        aspirate_response = vantage.aspirate(
            channels=CHANNELS,
            positions="source_plate@col:1",
            volumes=TRANSFER_STEP_1_VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            settings=ASPIRATE_SETTINGS,
        )
        print(f"   Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        print("\n3. Dispense - To destination plate")
        dispense_response = vantage.dispense(
            channels=CHANNELS,
            positions="dest_plate@col:1",
            volumes=TRANSFER_STEP_1_VOLUME_UL,
        )
        print(f"   Dispense response: {dispense_response.model_dump(by_alias=True)}")

        print("\n4. Aspirate - Different transfer from single well")
        aspirate_step_2_response = vantage.aspirate(
            channels=CHANNELS,
            positions="source_plate@B2",
            volumes=TRANSFER_STEP_2_VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            settings=ASPIRATE_SETTINGS_STEP_2,
        )
        print(f"   Aspirate response: {aspirate_step_2_response.model_dump(by_alias=True)}")

        print("\n5. Dispense - Different transfer to single well with side touch")
        dispense_step_2_response = vantage.dispense(
            channels=CHANNELS,
            positions="dest_plate@H12",
            volumes=TRANSFER_STEP_2_VOLUME_UL,
            settings=DISPENSE_SETTINGS_STEP_2,
        )
        print(f"   Dispense response: {dispense_step_2_response.model_dump(by_alias=True)}")

        print("\n6. Tip Eject - To waste")
        tip_eject_response = vantage.tip_eject(channels=CHANNELS)
        print(f"   Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nVantage 1mL Pipetting Smoke Test Complete - Disconnecting")
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
