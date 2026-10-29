from logging import INFO

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE

DECK_NAME = "VantageSmokeDeck"

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_MTP
PLATE = LABWARE.PLATE.NUN_96_FL

try:
    with VantageClient(simulate=True, logging_level=INFO, venus_trace_logging=False) as vantage:
        print("Connected - method is running")

        # Tracks 1-6 are outside Pipetting Arm 1's physical reach on this Vantage; 7 is the minimum.
        vantage.add_carrier(
            labware_definition=TIP_CARRIER,
            left_track=7,
            labware_id="tip_carrier",
        )
        vantage.add_tip_rack(
            tip_pool="transfer_tips",
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

        print("\n--- Layout Queries ---")
        print(f"Added carriers: {vantage.get_added_carriers().model_dump(by_alias=True)}")
        print(f"Available tracks: {vantage.get_available_tracks().model_dump(by_alias=True)}")
        print(f"Occupied tracks: {vantage.get_occupied_tracks().model_dump(by_alias=True)}")
        print(f"Added plates: {vantage.get_added_plates().model_dump(by_alias=True)}")
        print(f"Added tip racks: {vantage.get_added_tip_racks().model_dump(by_alias=True)}")

        print("\n--- Deck Save/Load/Delete ---")
        print(f"Saved decks before save: {vantage.deck_get_saved().model_dump(by_alias=True)}")

        vantage.deck_save(DECK_NAME, overwrite=True)
        print(f"Deck saved as '{DECK_NAME}'")

        print(f"Saved decks after save: {vantage.deck_get_saved().model_dump(by_alias=True)}")

    print("\nVantage Deck Smoke Test Phase 1 Complete - Disconnecting")
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

try:
    with VantageClient(simulate=True, auto_connect=False, deck_name=DECK_NAME) as vantage:
        print(f"Deck '{DECK_NAME}' loaded")

        print(f"Previous deck available: {vantage.deck_get_previous().model_dump(by_alias=True)}")

        vantage.deck_delete_saved(DECK_NAME)
        print(f"Deck '{DECK_NAME}' deleted")

        print(f"Saved decks after delete: {vantage.deck_get_saved().model_dump(by_alias=True)}")

        print("\nVantage Deck Smoke Test Phase 2 Complete - Disconnecting")
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
