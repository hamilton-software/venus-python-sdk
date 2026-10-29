"""Smoke test for position-based (manual mode) tip pickup and eject across
add_tip_rack, add_tip_box, and add_ntr labware.

Unlike tip_pool mode, manual/positions mode addresses tips directly by
labware name and well/column ("LabwareName@col:N"), so each tip labware is
given an explicit labware_id here (tip_pool is left unset -- not needed for
this workflow) rather than relying on a VENUS auto-assigned name.
"""
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import EjectMode

TIP_RACK_CARRIER_ID = "TipRackCarrier1"
TIP_BOX_CARRIER_ID = "TipBoxCarrier1"
NTR_CARRIER_ID = "NtrCarrier1"

TIP_RACK_ID = "TipRack1"
TIP_BOX_ID = "TipBox1"
NTR_ID = "NTR1"

COLUMN = 3

try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id=TIP_RACK_CARRIER_ID,
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.HAM_MLTIPBOX_CAR_BASE_1ML,
            left_track=7,
            labware_id=TIP_BOX_CARRIER_ID,
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_NTR,
            left_track=15,
            labware_id=NTR_CARRIER_ID,
        )
        print("Carriers added")

        star.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
            carrier_id=TIP_RACK_CARRIER_ID,
            site="1",
            labware_id=TIP_RACK_ID,
        )
        star.add_tip_box(
            labware_definition=LABWARE.TIP_RACK.TIP_BOX_1000UL,
            carrier_id=TIP_BOX_CARRIER_ID,
            site="1",
            labware_id=TIP_BOX_ID,
        )
        star.add_ntr(
            labware_definition=LABWARE.TIP_RACK.TIP_NESTED_300UL,
            carrier_id=NTR_CARRIER_ID,
            site="1",
            stack=1,
            labware_id=NTR_ID,
        )
        print("Tip labware added")

        star.instrument_init()
        print("\nInitialization complete")

        for label, labware_id in (
            ("tip rack", TIP_RACK_ID),
            ("tip box", TIP_BOX_ID),
            ("NTR", NTR_ID),
        ):
            position = f"{labware_id}@col:{COLUMN}"
            print(f"\nPick up + eject (column {COLUMN}, positions mode) - {label} ({position})")
            pickup_response = star.tip_pickup(positions=position)
            print(f"   Tip pickup response: {pickup_response.model_dump(by_alias=True)}")
            eject_response = star.tip_eject(eject_mode=EjectMode.POSITIONS, positions=position)
            print(f"   Tip eject response: {eject_response.model_dump(by_alias=True)}")

        print("\nPosition-Based Tip Pickup Smoke Test Complete - Disconnecting")
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
