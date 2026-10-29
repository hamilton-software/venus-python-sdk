from logging import INFO

from hamilton_venus import (
    StarClient,
    VenusCommandFailedError,
    VenusError,
    VenusTimeoutError,
)
from hamilton_venus.catalog import LABWARE

DECK_NAME = "SmokeDeck"
TIP_CARRIER_ID = "TipCarrier1"
PLATE_CARRIER_ID = "PlateCarrier1"
REAGENT_CARRIER_ID = "ReagentCarrier1"
TRANSFER_TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL

try:
    with StarClient(simulate=True, logging_level=INFO) as star:
        print("Connected - method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id=TIP_CARRIER_ID,
        )
        star.add_tip_rack(
            tip_pool="transfer_tips",
            labware_definition=TRANSFER_TIP_RACK,
            carrier_id=TIP_CARRIER_ID,
            site="1",
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
            left_track=7,
            labware_id=PLATE_CARRIER_ID,
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id=PLATE_CARRIER_ID,
            site="1",
            plate_id="source_plate",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id=PLATE_CARRIER_ID,
            site="2",
            plate_id="source_plate2",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id=PLATE_CARRIER_ID,
            site="3",
            plate_id="dest_plate",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
            carrier_id=PLATE_CARRIER_ID,
            site="4",
            plate_id="dest_plate2",
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.RGT_CAR_12R,
            left_track=15,
            labware_id=REAGENT_CARRIER_ID,
        )
        star.add_reservoir(
            labware_definition=LABWARE.RESERVOIR.RGT_20ML_CONTAINER_BLACK,
            carrier_id=REAGENT_CARRIER_ID,
            labware_id="reagent_trough",
            site="1",
        )
        star.add_channel_liquid_waste()
        print("Layout built")

        print("\n--- Layout Queries ---")
        added_carriers = star.get_added_carriers()
        print(f"Added carriers: {added_carriers.model_dump(by_alias=True)}")

        available_tracks = star.get_available_tracks()
        print(f"Available tracks: {available_tracks.model_dump(by_alias=True)}")

        occupied_tracks = star.get_occupied_tracks()
        print(f"Occupied tracks: {occupied_tracks.model_dump(by_alias=True)}")

        added_plates = star.get_added_plates()
        print(f"Added plates: {added_plates.model_dump(by_alias=True)}")

        added_tip_racks = star.get_added_tip_racks()
        print(f"Added tip racks: {added_tip_racks.model_dump(by_alias=True)}")

        carrier_sites = star.get_available_carrier_sites(TIP_CARRIER_ID)
        print(f"Available sites on {TIP_CARRIER_ID}: {carrier_sites.model_dump(by_alias=True)}")

        occupied_sites = star.get_occupied_carrier_sites(TIP_CARRIER_ID)
        print(f"Occupied sites on {TIP_CARRIER_ID}: {occupied_sites.model_dump(by_alias=True)}")

        labware_on_carrier = star.get_labware_on_carrier(PLATE_CARRIER_ID)
        print(f"Labware on {PLATE_CARRIER_ID}: {labware_on_carrier.model_dump(by_alias=True)}")

        track_occupied = star.is_track_occupied(1)
        print(f"Track 1 occupied: {track_occupied.model_dump(by_alias=True)}")

        print("\n--- Deck Save/Load/Delete ---")
        saved_before = star.deck_get_saved()
        print(f"Saved decks before save: {saved_before.model_dump(by_alias=True)}")

        star.deck_save(DECK_NAME, overwrite=True)
        print(f"Deck saved as '{DECK_NAME}'")

        saved_after = star.deck_get_saved()
        print(f"Saved decks after save: {saved_after.model_dump(by_alias=True)}")

    print("\nDeck Smoke Test Phase 1 Complete - Disconnecting")
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
    with StarClient(simulate=True, auto_connect=False, deck_name=DECK_NAME) as star:
        print(f"Deck '{DECK_NAME}' loaded")

        previous_available = star.deck_get_previous()
        print(f"Previous deck available: {previous_available.model_dump(by_alias=True)}")

        star.deck_delete_saved(DECK_NAME)
        print(f"Deck '{DECK_NAME}' deleted")

        saved_final = star.deck_get_saved()
        print(f"Saved decks after delete: {saved_final.model_dump(by_alias=True)}")

        print("\nDeck Smoke Test Phase 2 Complete - Disconnecting")
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
