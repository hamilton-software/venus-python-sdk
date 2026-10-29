import random

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings

ROWS = "ABCDEFGH"
excluded_positions_a_h = [f"{row}{col}" for row in ("A", "H") for col in range(1, 13)]


def _excluded_channels_from_positions(excluded_positions: list[str]) -> set[int]:
    excluded_channels: set[int] = set()
    for well in excluded_positions:
        if not well:
            continue
        row_letter = well[0].upper()
        row_index = ROWS.find(row_letter)
        if row_index != -1:
            excluded_channels.add(row_index + 1)
    return excluded_channels


def _format_dotf_summary(dotf_response: dict, excluded_positions: list[str]) -> str:
    excluded_channels = _excluded_channels_from_positions(excluded_positions)
    channel_data = dotf_response.get("returnParameters", {}).get("channels", [])
    lines = [
        f"Excluded wells: {', '.join(excluded_positions)}",
        f"Expected excluded channels: {sorted(excluded_channels)}",
        "Channel summary (expected vs reported):",
    ]
    for entry in channel_data:
        channel = entry.get("channel")
        dispensed_volume = entry.get("dispensedVolume")
        expected = "SKIP" if channel in excluded_channels else "DISPENSE"
        lines.append(
            f"  channel {channel}: expected={expected}, reported_dispensed_uL={dispensed_volume}"
        )
    return "\n".join(lines)


def _random_channel_volumes(rng: random.Random, count: int) -> list[float]:
    return [round(rng.uniform(20.0, 80.0), 1) for _ in range(count)]


channels = [1, 2, 3, 4, 5, 6, 7, 8]
tip_pool = "transfer_tips"
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_PART.STANDARDVOLUME_WATER_DISPENSEJET_PART
labware_surface_distance = 2.0
volume_rng = random.Random(20260603)

aspirate_settings = AspirateSettings()

try:
    with StarClient(simulate=True, deck_name="example_deck") as star:

        print("Connected — method is running")

        star.instrument_init()
        print("Initialization complete\n")

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

        # --- Pass 1: dispense on the fly left-to-right (dispense_direction=0) ---
        print("\nPass 1: dispense on the fly (left-to-right)")
        pass_1_volumes = _random_channel_volumes(volume_rng, len(channels))
        print(f"Pass 1 channel volumes (uL): {pass_1_volumes}")

        tip_pickup_response = star.tip_pickup(channels=channels, tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=channels,
            positions="source_plate@col:1",
            volumes=pass_1_volumes,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        dotf_response = star.dispense_on_the_fly(
            channels=channels,
            labware_name="dest_plate",
            volumes=pass_1_volumes,
            labware_surface_distance=labware_surface_distance,
            dispense_direction=0,
        )
        print(f"Dispense on the fly response: {dotf_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject(channels=channels)
        print(f"Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        # --- Pass 2: dispense on the fly right-to-left (dispense_direction=1) ---
        print("\nPass 2: dispense on the fly (right-to-left)")
        pass_2_volumes = _random_channel_volumes(volume_rng, len(channels))
        print(f"Pass 2 channel volumes (uL): {pass_2_volumes}")

        tip_pickup_response = star.tip_pickup(channels=channels, tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=channels,
            positions="source_plate@col:2",
            volumes=pass_2_volumes,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        dotf_response = star.dispense_on_the_fly(
            channels=channels,
            labware_name="dest_plate",
            volumes=pass_2_volumes,
            labware_surface_distance=labware_surface_distance,
            dispense_direction=1,
        )
        print(f"Dispense on the fly response: {dotf_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject(channels=channels)
        print(f"Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        # --- Pass 3: dispense on the fly with excluded positions ---
        print("\nPass 3: dispense on the fly with excluded positions")
        pass_3_volumes = _random_channel_volumes(volume_rng, len(channels))
        print(f"Pass 3 channel volumes (uL): {pass_3_volumes}")

        tip_pickup_response = star.tip_pickup(channels=channels, tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup response: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=channels,
            positions="source_plate@col:3",
            volumes=pass_3_volumes,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate response: {aspirate_response.model_dump(by_alias=True)}")

        dotf_response = star.dispense_on_the_fly(
            channels=channels,
            labware_name="dest_plate",
            volumes=pass_3_volumes,
            labware_surface_distance=labware_surface_distance,
            dispense_direction=0,
                excluded_positions=excluded_positions_a_h,
        )
        print(f"Dispense on the fly response: {dotf_response.model_dump(by_alias=True)}")
        print(
            _format_dotf_summary(
                dotf_response.model_dump(by_alias=True),
                    excluded_positions=excluded_positions_a_h,
            )
        )

        tip_eject_response = star.tip_eject(channels=channels)
        print(f"Tip eject response: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nDispense On The Fly Smoke Test Complete - Disconnecting")
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
