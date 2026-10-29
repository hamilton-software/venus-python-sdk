"""Vantage MagPip channel pipetting smoke test.

The MagPip channels sit on their own pipetting arm, which on a multi-arm system
has a narrower X reach than the 1 mL arm (a second arm to its left blocks the
low-X tracks). Rather than hard-code a deck layout, this script reads the arm's
reach limits from ``instrument_get_configuration()`` and its free tracks from
``instrument_get_deck_tracks()`` / ``get_available_tracks()``, then places the
tip and plate carriers on 6-track sites that fall inside the MagPip arm's window.
The channel waste is likewise discovered from ``instrument_get_waste_locations()``.
"""

import logging

from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings, TadmMode, TadmSettings

TIP_POOL = "transfer_tips_1ml"
CHANNELS = [1]
TRANSFER_STEP_1_VOLUME_UL = 100.0
TRANSFER_STEP_2_VOLUME_UL = 60.0
LIQUID_CLASS = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.JET_EMPTY.HIGHVOLUME_WATER_DISPENSEJET_EMPTY
ASPIRATE_SETTINGS = AspirateSettings()
DISPENSE_SETTINGS_STEP_2 = DispenseSettings(use_side_touch=True)
# Record TADM curves for the second transfer.
TADM_RECORDING = TadmSettings(enabled=TadmMode.RECORDING)

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_1000UL
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5_MTP
PLATE = LABWARE.PLATE.NUN_96_FL

# A 6-track carrier footprint.
CARRIER_TRACK_SPAN = 6
# The default Vantage deck exposes 6-track carrier sites on a 6-track stride
# starting at track 7 (the same anchors the 1 mL smoke tests use: 7, 13, ...).
CARRIER_SITE_STRIDE = 6
FIRST_CARRIER_SITE = 7


def _pick_carrier_sites(vantage: VantageClient, count: int) -> list[int]:
    """Choose ``count`` non-overlapping 6-track carrier anchors that (a) are on
    the deck's carrier-site stride, (b) have all their tracks free, and (c) put
    the whole carrier inside the MagPip arm's X reach.
    """
    config = vantage.instrument_get_configuration().return_parameters
    arms = [arm for arm in (config.left_arm, config.right_arm) if arm is not None]
    magpip_arm = next((arm for arm in arms if arm.channels_mag_pip is not None), None)
    if magpip_arm is None or magpip_arm.channels_mag_pip is None:
        raise SystemExit("This instrument has no MagPip channels; nothing to smoke-test.")
    x_min = magpip_arm.x_min or 0.0
    x_max = magpip_arm.x_max or float("inf")
    print(f"MagPip channels on arm {magpip_arm.arm_id}: X reach {x_min}-{x_max} mm")

    deck = vantage.instrument_get_deck_tracks().return_parameters
    dimensions = vantage.instrument_get_deck_dimensions().return_parameters
    pitch = dimensions.x / (deck.total_tracks + 1)  # ~22.5 mm/track
    free = set(vantage.get_available_tracks().return_parameters.tracks_available)

    # A carrier anchored at track L reaches wells roughly over
    # [L*pitch + edge, L*pitch + edge + span], where ``edge`` is the offset from
    # the carrier's left rail to its first column and ``span`` covers up to 12
    # plate columns at the 9 mm channel raster. Keep a margin off both reach ends.
    raster = magpip_arm.channels_mag_pip.raster or 9
    edge, span, margin = 20.0, 12 * raster, 12.0

    def fits(anchor: int) -> bool:
        if any(anchor + k not in free for k in range(CARRIER_TRACK_SPAN)):
            return False
        left_x = anchor * pitch + edge
        right_x = left_x + span
        return left_x >= x_min + margin and right_x <= x_max - margin

    chosen: list[int] = []
    for anchor in range(FIRST_CARRIER_SITE, deck.total_tracks - CARRIER_TRACK_SPAN, CARRIER_SITE_STRIDE):
        if fits(anchor) and (not chosen or anchor >= chosen[-1] + CARRIER_TRACK_SPAN):
            chosen.append(anchor)
        if len(chosen) == count:
            return chosen
    raise SystemExit(f"Could not find {count} MagPip-reachable carrier sites (found {chosen}).")


try:
    with VantageClient(simulate=True, logging_level=logging.INFO) as vantage:
        print("Connected - method is running")

        vantage.instrument_init()
        print("Initialization complete")

        tip_track, plate_track = _pick_carrier_sites(vantage, count=2)
        print(f"Placing tip carrier at track {tip_track}, plate carrier at track {plate_track}")

        vantage.add_carrier(
            labware_definition=TIP_CARRIER,
            left_track=tip_track,
            labware_id="tip_carrier",
        )
        vantage.add_tip_rack(
            tip_pool=TIP_POOL,
            labware_definition=TIP_RACK,
            carrier_id="tip_carrier",
            site="1",
        )
        vantage.add_carrier(
            labware_definition=PLATE_CARRIER,
            left_track=plate_track,
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

        # The MagPip channels have their own configured waste location on the
        # deck; only add a generic liquid waste if the instrument reports none.
        waste_entries = [
            location
            for entry in vantage.instrument_get_waste_locations().return_parameters.waste_locations
            for location in entry.values()
        ]
        magpip_waste = next(
            (w for w in waste_entries if getattr(w, "is_mag_pip_waste", False)),
            next((w for w in waste_entries if w.is_default), None),
        )
        if magpip_waste is not None:
            print(f"Using existing channel waste: {magpip_waste.labware_name} (x={magpip_waste.x})")
        else:
            free_tracks = sorted(vantage.get_available_tracks().return_parameters.tracks_available)
            waste_track = next(t for t in free_tracks if t > plate_track + CARRIER_TRACK_SPAN)
            vantage.add_liquid_waste(track=waste_track)
            print(f"Added liquid waste at track {waste_track}")
        print("Layout built")

        vantage.tip_pool_initialize_tip_counter(TIP_POOL)
        vantage.tip_pool_reset_tip_counter(TIP_POOL)

        print("\n1. Tip Pickup (MagPip) - Single 1mL tip")
        tip_pickup_response = vantage.tip_pickup_magpip(channels=CHANNELS, tip_pool=TIP_POOL)
        print(f"   Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        print("\n2. Aspirate (MagPip) - From source plate")
        aspirate_response = vantage.aspirate_magpip(
            channels=CHANNELS,
            positions="source_plate@col:1",
            volumes=TRANSFER_STEP_1_VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            settings=ASPIRATE_SETTINGS,
        )
        print(f"   Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        print("\n3. Dispense (MagPip) - To destination plate")
        dispense_response = vantage.dispense_magpip(
            channels=CHANNELS,
            positions="dest_plate@col:1",
            volumes=TRANSFER_STEP_1_VOLUME_UL,
        )
        print(f"   Dispense response: {dispense_response.model_dump(by_alias=True)}")

        print("\n4. Aspirate (MagPip) - Second transfer with TADM recording")
        aspirate_step_2_response = vantage.aspirate_magpip(
            channels=CHANNELS,
            positions="source_plate@B2",
            volumes=TRANSFER_STEP_2_VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            tadm=TADM_RECORDING,
        )
        print(f"   Aspirate response: {aspirate_step_2_response.model_dump(by_alias=True)}")

        print("\n5. Dispense (MagPip) - Second transfer with side touch and TADM recording")
        dispense_step_2_response = vantage.dispense_magpip(
            channels=CHANNELS,
            positions="dest_plate@H12",
            volumes=TRANSFER_STEP_2_VOLUME_UL,
            settings=DISPENSE_SETTINGS_STEP_2,
            tadm=TADM_RECORDING,
        )
        print(f"   Dispense response: {dispense_step_2_response.model_dump(by_alias=True)}")

        print("\n6. Get Status (MagPip)")
        status_response = vantage.get_status_magpip()
        print(f"   Status response: {status_response.model_dump(by_alias=True)}")

        print("\n7. Tip Eject (MagPip) - To waste")
        tip_eject_response = vantage.tip_eject_magpip(channels=CHANNELS)
        print(f"   Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nVantage MagPip Pipetting Smoke Test Complete - Disconnecting")
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
