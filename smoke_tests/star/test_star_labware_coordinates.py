from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

PLATE_CARRIER_ID = "PlateCarrier1"
TIP_CARRIER_ID = "TipCarrier1"
PLATE_ID = "Plate1"
TIP_RACK_POOL = "TipRack1"
TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_300UL

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
            left_track=7,
            labware_id=PLATE_CARRIER_ID,
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL,
            carrier_id=PLATE_CARRIER_ID,
            site="1",
            plate_id=PLATE_ID,
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id=TIP_CARRIER_ID,
        )
        tip_rack_resp = star.add_tip_rack(
            labware_definition=TIP_RACK_DEFINITION,
            carrier_id=TIP_CARRIER_ID,
            site="1",
            tip_pool=TIP_RACK_POOL,
        )
        tip_rack_labware_name = tip_rack_resp.return_parameters["labwareName"]

        print("\n--- Carrier origin coordinates ---")
        # No well given: origin only for a carrier (it has no wells).
        carrier_coords = star.get_labware_coordinates(PLATE_CARRIER_ID)
        rp = carrier_coords.return_parameters
        origin = rp.origin
        print(f"  {PLATE_CARRIER_ID}: x={origin.x}, y={origin.y}, z={origin.z}, angle={origin.angle}")
        print(f"  wells returned: {rp.wells!r} (a carrier has none)")

        print("\n--- Plate origin and well coordinates ---")
        # No well given: origin plus every well, ordered by column.
        coords = star.get_labware_coordinates(PLATE_ID)
        rp = coords.return_parameters
        origin = rp.origin
        print(f"  {PLATE_ID}: x={origin.x}, y={origin.y}, z={origin.z}, angle={origin.angle}")
        wells = rp.wells or []
        print(f"  wells returned: {len(wells)}")
        for entry in wells[:3] + wells[-1:]:
            print(f"    {entry.well}: x={entry.x}, y={entry.y}, z={entry.z}, angle={entry.angle}")

        print(
            f"\n--- Tip rack well coordinates ({TIP_RACK_DEFINITION} row-major, "
            f"labwareName={tip_rack_labware_name!r}) ---"
        )
        tip_wells = {"A1": "1", "A12": "12", "H1": "85", "H12": "96"}
        for well_name, position in tip_wells.items():
            coords = star.get_labware_coordinates(tip_rack_labware_name, well=position)
            rp = coords.return_parameters
            print(f"  {well_name} (pos {position}, returned well {rp.well!r}): x={rp.x}, y={rp.y}, z={rp.z}, angle={rp.angle}")

        print("\nLabware Coordinates Smoke Test Complete - Disconnecting")
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
