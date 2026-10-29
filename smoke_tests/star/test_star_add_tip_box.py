from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier1"
TIP_POOL = "SmokeTipPool"
TIP_CARRIER_DEFINITION = LABWARE.CARRIER.HAM_MLTIPBOX_CAR_BASE_50UL_300UL
TIP_BOX_DEFINITION = "Tip_Box_300uL_Filter"
TIP_BOX_SITE = "1"

try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        carrier_response = star.add_carrier(
            labware_definition=TIP_CARRIER_DEFINITION,
            left_track=1,
            labware_id=CARRIER_ID,
        )
        print(f"Add carrier response: {carrier_response.model_dump(by_alias=True)}")

        tip_box_response = star.add_tip_box(
            labware_definition=TIP_BOX_DEFINITION,
            carrier_id=CARRIER_ID,
            site=TIP_BOX_SITE,
            tip_pool=TIP_POOL,
        )
        print(f"Add tip box response: {tip_box_response.model_dump(by_alias=True)}")

        rp = tip_box_response.return_parameters
        print(f"  labwareName: {rp.labware_name}")
        print(f"  tipPoolName: {rp.tip_pool_name}")
        print(f"  totalTips:   {rp.total_tips}")
        print(f"  tipType:     {rp.tip_type}")

        assert rp.labware_name, "Expected a non-empty labwareName in response"
        assert rp.tip_pool_name == TIP_POOL.lower(), (
            f"Expected tipPoolName={TIP_POOL.lower()!r}, got {rp.tip_pool_name!r}"
        )

        print("\nAdd Tip Box Smoke Test Complete - Disconnecting")
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
