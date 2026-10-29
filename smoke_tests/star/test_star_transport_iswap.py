"""Smoke test for iSWAP transport commands.

Demonstrates iSWAP operations including:
- Basic labware transport with PlaceRotation and GripInverse enums
- Checking held-labware status
- Barcode scanning with present-and-scan
- Get and put labware (split grip/place)
- Transport to waste
- Tracking clear
- Park
"""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import GripInverse, PlaceRotation

try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        # Set up deck layout
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

        # Initialize instrument before transport operations
        star.instrument_init()
        print("Initialization complete")

        print("\n--- iSWAP Check Held Labware (before transport) ---")
        holding_response = star.iswap_is_holding_labware()
        print(f"Is holding labware: {holding_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Basic Transport (DEGREES_0 rotation, grip from right) ---")
        transport_response = star.iswap_transport(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="2",
            grip_height_above_bottom=8.0,
            place_rotation=PlaceRotation.DEGREES_0,
            grip_inverse=GripInverse.GRIP_FROM_RIGHT,
        )
        print(f"iSWAP transport response: {transport_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Transport with 90-degree rotation (grip from left) ---")
        transport_90_response = star.iswap_transport(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="3",
            grip_height_above_bottom=8.0,
            place_rotation=PlaceRotation.DEGREES_90,
            grip_inverse=GripInverse.GRIP_FROM_LEFT,
        )
        print(f"iSWAP transport 90° response: {transport_90_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Transport with 180-degree rotation ---")
        transport_180_response = star.iswap_transport(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="4",
            grip_height_above_bottom=8.0,
            place_rotation=PlaceRotation.DEGREES_180,
        )
        print(f"iSWAP transport 180° response: {transport_180_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Transport with 270-degree rotation ---")
        transport_270_response = star.iswap_transport(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="5",
            grip_height_above_bottom=8.0,
            place_rotation=PlaceRotation.DEGREES_270,
        )
        print(f"iSWAP transport 270° response: {transport_270_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Present and Scan ---")
        scan_response = star.iswap_present_and_scan(
            labware_name="SourcePlate1",
            carrier="PlateCarrier1",
            site="2",
            track=7,
            grip_height_above_bottom=8.0,
            z_minimal_position=150.0,
            place_rotation=PlaceRotation.DEGREES_0,
            grip_inverse=GripInverse.GRIP_FROM_RIGHT,
        )
        print(f"iSWAP present and scan response: {scan_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Get Labware (pick up only) ---")
        get_response = star.iswap_get_labware(
            labware_name="SourcePlate1",
            grip_height_above_bottom=8.0,
            grip_inverse=GripInverse.GRIP_FROM_LEFT,
        )
        print(f"iSWAP get labware response: {get_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Check Held Labware (after get) ---")
        holding_after_get = star.iswap_is_holding_labware()
        print(f"Is holding labware: {holding_after_get.model_dump(by_alias=True)}")

        print("\n--- iSWAP Put Labware (place only) ---")
        put_response = star.iswap_put_labware(
            carrier="PlateCarrier1",
            site="1",
            place_rotation=PlaceRotation.DEGREES_0,
        )
        print(f"iSWAP put labware response: {put_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Transport to Waste ---")
        waste_response = star.iswap_transport_to_waste(
            labware_name="SourcePlate1",
            grip_height_above_bottom=8.0,
            grip_inverse=GripInverse.GRIP_FROM_RIGHT,
        )
        print(f"iSWAP waste transport response: {waste_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Tracking Clear ---")
        clear_response = star.iswap_tracking_clear()
        print(f"iSWAP tracking clear response: {clear_response.model_dump(by_alias=True)}")

        print("\n--- iSWAP Park ---")
        park_response = star.iswap_park()
        print(f"iSWAP park response: {park_response.model_dump(by_alias=True)}")

        print("\niSWAP Transport Smoke Test Complete - Disconnecting")
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
