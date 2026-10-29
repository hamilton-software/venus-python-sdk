"""Smoke test for the optional tip_pool/labware_id support on
add_tip_rack, add_tip_box, and add_ntr.

Adds one of each tip labware type without specifying tip_pool or
labware_id, letting VENUS auto-assign both, then verifies the
auto-assigned pool actually works by picking up tips and ejecting
them to waste.
"""
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import EjectMode

TIP_RACK_CARRIER_ID = "TipRackCarrier1"
TIP_BOX_CARRIER_ID = "TipBoxCarrier1"
NTR_CARRIER_ID = "NtrCarrier1"

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

        print("\n1. Add Tip Rack (tip_pool and labware_id omitted)")
        tip_rack_response = star.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
            carrier_id=TIP_RACK_CARRIER_ID,
            site="1",
        )
        print(f"   Response: {tip_rack_response.model_dump(by_alias=True)}")
        tip_rack_pool = tip_rack_response.return_parameters.tip_pool_name
        assert tip_rack_pool, "Expected VENUS to auto-assign a tip pool name"
        print(f"   Auto-assigned tip pool: {tip_rack_pool!r}, labware: {tip_rack_response.return_parameters.labware_name!r}")

        print("\n2. Add Tip Box (tip_pool and labware_id omitted)")
        tip_box_response = star.add_tip_box(
            labware_definition=LABWARE.TIP_RACK.TIP_BOX_1000UL,
            carrier_id=TIP_BOX_CARRIER_ID,
            site="1",
        )
        print(f"   Response: {tip_box_response.model_dump(by_alias=True)}")
        tip_box_pool = tip_box_response.return_parameters.tip_pool_name
        assert tip_box_pool, "Expected VENUS to auto-assign a tip pool name"
        print(f"   Auto-assigned tip pool: {tip_box_pool!r}, labware: {tip_box_response.return_parameters.labware_name!r}")

        print("\n3. Add NTR (tip_pool and labware_id omitted)")
        ntr_response = star.add_ntr(
            labware_definition=LABWARE.TIP_RACK.TIP_NESTED_300UL,
            carrier_id=NTR_CARRIER_ID,
            site="1",
            stack=4,
        )
        print(f"   Response: {ntr_response.model_dump(by_alias=True)}")
        ntr_pool = ntr_response.return_parameters.tip_pool_name
        assert ntr_pool, "Expected VENUS to auto-assign a tip pool name"
        print(f"   Auto-assigned tip pool: {ntr_pool!r}, labware: {ntr_response.return_parameters.labware_name!r}")

        star.instrument_init()
        print("\nInitialization complete")

        for label, pool in (
            ("tip rack", tip_rack_pool),
            ("tip box", tip_box_pool),
            ("NTR", ntr_pool),
        ):
            print(f"\nPick up + eject to waste - {label} ({pool!r})")
            pickup_response = star.tip_pickup(tip_pool=pool)
            print(f"   Tip pickup response: {pickup_response.model_dump(by_alias=True)}")
            eject_response = star.tip_eject(eject_mode=EjectMode.WASTE)
            print(f"   Tip eject response: {eject_response.model_dump(by_alias=True)}")

        print("\nTip Pickup Auto-Naming Smoke Test Complete - Disconnecting")
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
