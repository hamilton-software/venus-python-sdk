from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_300UL
NESTED_TIP_RACK_DEFINITION = "Tip_Nested_300uL"

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id="TipCarrier1",
        )
        print(f"Add carrier response: {carrier_response.model_dump(by_alias=True)}")

        tip_rack_response = star.add_tip_rack(
            labware_definition=TIP_RACK_DEFINITION,
            carrier_id="TipCarrier1",
            site="1",
            tip_pool="TipPool1",
        )
        print(f"Add tip rack response: {tip_rack_response.model_dump(by_alias=True)}")

        ntr_response = star.add_ntr(
            labware_definition=NESTED_TIP_RACK_DEFINITION,
            carrier_id="TipCarrier1",
            site="1",
            stack=4,
            tip_pool="TipPool2",
        )
        print(f"Add ntr response: {ntr_response.model_dump(by_alias=True)}")

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
            plate_id="Plate1",
        )
        print(f"Add plate response: {plate_response.model_dump(by_alias=True)}")

        lidded_plate_response = star.add_lidded_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id="PlateCarrier1",
            site="2",
            plate_id="LiddedPlate1",
            lid_definition=LABWARE.LID.NUNC_LID,
        )
        print(f"Add lidded plate response: {lidded_plate_response.model_dump(by_alias=True)}")

        print("\nLayout Smoke Test Complete - Disconnecting")
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
