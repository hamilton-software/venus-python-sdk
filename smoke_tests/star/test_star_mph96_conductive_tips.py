from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import MPH96AspirateSettings, MPH96DispenseSettings
from hamilton_venus.models.enums import MphPickupMode, MphPickupSide

volume_ul = 50.0
conductive_tip_pool = "conductive_tips"
conductive_liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.JET_PART.HIGHVOLUME_WATER_DISPENSEJET_PART
source_plate = "source_plate"
dest_plate = "dest_plate"

aspirate_settings = MPH96AspirateSettings(mix_cycles=2, mix_volume=25.0)
dispense_settings = MPH96DispenseSettings()
CONDUCTIVE_TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_1000UL


def is_known_tadm_extension_error(error: VenusCommandFailedError) -> bool:
    """Return True for the known simulator TADM extension gap on dispense."""
    details = error.response.return_parameters or {}
    message = str(details.get("message", "")).lower()
    code = details.get("code")
    return code == -1591212011 or (
        "instrument extensions for this command is not installed" in message
        and "channel module" in message
    )


def is_unknown_mph96_command_error(error: VenusCommandFailedError, command_name: str) -> bool:
    """Return True when simulator/runtime reports an MPH96 command is unknown."""
    details = error.response.return_parameters or {}
    description = str(details.get("Description") or details.get("message") or "").lower()
    return "command is unknown" in description and command_name.lower() in description

try:
    with StarClient(simulate=True, deck_name="example_deck") as star:
        print("Connected - method is running")

        star.instrument_init()
        print("Initialization complete")

        star.add_tip_rack(
            tip_pool=conductive_tip_pool,
            labware_definition=CONDUCTIVE_TIP_RACK_DEFINITION,
            carrier_id="tip_carrier",
            site="2",
        )
        print(
            "Added conductive tip rack "
            f"({CONDUCTIVE_TIP_RACK_DEFINITION}) to tip_carrier site 2"
        )

        init_conductive_tips_response = star.tip_pool_initialize_tip_counter(conductive_tip_pool)
        print(f"Init conductive tips response: {init_conductive_tips_response.model_dump(by_alias=True)}")
        reset_conductive_tips_response = star.tip_pool_reset_tip_counter(conductive_tip_pool)
        print(f"Reset conductive tips response: {reset_conductive_tips_response.model_dump(by_alias=True)}")


        print("\n--- Full-plate MPH96 transfer (conductive HT tips) ---")
        pickup = star.tip_pick_up_mph96(tip_pool=conductive_tip_pool)
        print(f"MPH96 tip pickup: {pickup.model_dump(by_alias=True)}")

        aspirate = star.aspirate_mph96(
                labware_id=source_plate,
                volume=volume_ul,
                liquid_class=conductive_liquid_class,
                settings=aspirate_settings,
            )
        print(f"MPH96 aspirate: {aspirate.model_dump(by_alias=True)}")

        try:
            dispense = star.dispense_mph96(
                    labware_id=dest_plate,
                    volume=volume_ul,
                    settings=dispense_settings,
                )
            print(f"MPH96 dispense: {dispense.model_dump(by_alias=True)}")
        except VenusCommandFailedError as e:
            if is_known_tadm_extension_error(e):
                print("SKIP mph96.dispense TADM: simulator is missing required Channel module extension")
                print(f"  Details: {e.response.return_parameters}")
            else:
                raise

        eject = star.tip_eject_mph96()
        print(f"MPH96 tip eject: {eject.model_dump(by_alias=True)}")

        reset_conductive_tips_response = star.tip_pool_reset_tip_counter(conductive_tip_pool)
        print(
            "Reset conductive tips response (before partial): "
            f"{reset_conductive_tips_response.model_dump(by_alias=True)}"
        )

        print("\n--- Partial MPH96 pickup (4 columns, conductive HT tips) ---")
        partial_pickup = star.tip_pick_up_mph96_partial(
                mode=MphPickupMode.COLUMNS,
                count=4,
                tip_pool=conductive_tip_pool,
                mph_pickup_side=MphPickupSide.RIGHT,
            )
        print(f"MPH96 partial pickup: {partial_pickup.model_dump(by_alias=True)}")

        partial_aspirate = star.aspirate_mph96(
                labware_id=source_plate,
                volume=25.0,
                liquid_class=conductive_liquid_class,
            )
        print(f"MPH96 partial aspirate: {partial_aspirate.model_dump(by_alias=True)}")

        try:
            partial_dispense = star.dispense_mph96(
                    labware_id=dest_plate,
                    volume=25.0,
                )
            print(f"MPH96 partial dispense: {partial_dispense.model_dump(by_alias=True)}")
        except VenusCommandFailedError as e:
            if is_known_tadm_extension_error(e):
                print("SKIP mph96.dispense (partial) TADM: simulator is missing required Channel module extension")
                print(f"  Details: {e.response.return_parameters}")
            else:
                raise

        partial_eject = star.tip_eject_mph96()
        print(f"MPH96 partial eject: {partial_eject.model_dump(by_alias=True)}")

        print("\nMPH96 Conductive Tips Smoke Test Complete - Disconnecting")
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
except VenusCommandFailedError as e:
    if is_unknown_mph96_command_error(e, "mph96.tipPickup"):
        print("SKIP mph96.tipPickup: this STAR simulator/runtime does not expose MPH96 commands")
        print(f"  Details: {e.response.return_parameters}")
    else:
        print(f"Command failed: {e}")
        print(f"  Return code: {e.response.return_code}")
        print(f"  Details: {e.response.return_parameters}")
except ValueError as e:
    print(f"Command failed: {e}")
except VenusError as e:
    print(f"Other SDK error: {e}")


print("Done")
