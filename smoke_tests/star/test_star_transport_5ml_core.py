"""Smoke test for 5 mL CO-RE transport and gripper commands.

Demonstrates 5 mL CO-RE gripper operations including:
- Basic labware transport
- Transport with barcode scanning
- Return operations
- Waste transport
"""


from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        # Set up deck layout with carriers and plates for transport
        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
            left_track=7,
            labware_id="PlateCarrier1",
        )
        print(f"Add carrier response: {carrier_response.model_dump(by_alias=True)}")

        plate_response = star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id="PlateCarrier1",
            site="1",
            plate_id="SourcePlate1",
        )
        print(f"Add plate response: {plate_response.model_dump(by_alias=True)}")

        gripper_response = star.add_5ml_core_grip()
        print(f"Add 5mL core gripper response: {gripper_response.model_dump(by_alias=True)}")

        # Initialize instrument before transport operations
        star.instrument_init()
        print("Initialization complete")

        print("\n--- Basic Plate Transport ---")
        transport_response = star.core_5ml_transport(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="2",
            grip_height_above_bottom=8.0,
            grip_width=100.0,
            grip_open=90.0,
        )
        print(f"Transport response: {transport_response.model_dump(by_alias=True)}")

        print("\n--- Check if Gripper is Holding Labware ---")
        holding_response = star.core_5ml_transport_is_holding_labware()
        print(f"Is holding labware: {holding_response.model_dump(by_alias=True)}")

        print("\n--- Scan Barcode with Transport ---")
        barcode_response = star.core_5ml_present_and_scan(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="2",
            track=7,
            z_minimal_position=150,
            grip_height_above_bottom=8.0,
        )
        print(f"Barcode scan response: {barcode_response.model_dump(by_alias=True)}")

        print("\n--- Transport to Waste ---")
        waste_response = star.core_5ml_transport_to_waste(
            labware_name="SourcePlate1",
            grip_height_above_bottom=8.0,
        )
        print(f"Waste transport response: {waste_response.model_dump(by_alias=True)}")

        print("\n--- Eject Grips ---")
        eject_response = star.core_5ml_eject_grips()
        print(f"Eject grips response: {eject_response.model_dump(by_alias=True)}")

        print("\n5mL Transport Smoke Test Complete - Disconnecting")
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
