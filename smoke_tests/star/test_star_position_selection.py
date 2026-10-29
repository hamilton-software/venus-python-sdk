"""
Smoke test demonstrating position and well selection techniques.

This test shows how to use various position selector syntaxes and well selection
features including selector strings, ranges, row/column selection, and custom
labware layouts.
"""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    AspirateSettings,
    DispenseSettings,
    WellOrder,
    normalize_positions,
)
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.GLYCERIN_80.SURFACE_EMPTY.X1_300TIP_B_GLYCERIN80_S_E
tip_pool = "transfer_tips"
transfer_volume_ul = 50.0
aspirate_settings = AspirateSettings()
dispense_settings = DispenseSettings()

try:
    with StarClient(simulate=True, deck_name="example_deck", venus_trace_logging=True) as star:
        print("Connected — method is running")        

        star.instrument_init()
        print("Initialization complete\n")

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)
        print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

        # ====================================================================
        # Technique 1: Single well selector
        # ====================================================================
        print("=" * 70)
        print("Technique 1: Single Well Selector")
        print("=" * 70)
        print("Transfer from Source_Plate@A1 to Dest_Plate@A1")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1],
            positions="Source_Plate@A1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate from A1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1],
            positions="Dest_Plate@A1",
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense to A1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 2: Explicit well list
        # ====================================================================
        print("=" * 70)
        print("Technique 2: Explicit Well List")
        print("=" * 70)
        print("Transfer from Source_Plate@B1,C1,D1 to Dest_Plate@B1,C1,D1")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3],
            positions="Source_Plate@B1,C1,D1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate from B1,C1,D1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3],
            positions="Dest_Plate@B1,C1,D1",
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense to B1,C1,D1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 3: Column selection with 8-channel head
        # ====================================================================
        print("=" * 70)
        print("Technique 3: Column Selection (8-channel)")
        print("=" * 70)
        print("Transfer entire column 1 from Source_Plate@col:1 to Dest_Plate@col:1")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="Source_Plate@col:1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate from col:1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="Dest_Plate@col:1",
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense to col:1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 4: Column range selection
        # ====================================================================
        print("=" * 70)
        print("Technique 4: Column Range Selection")
        print("=" * 70)
        print("Transfer columns 2-4 from Source_Plate@col:2:4 to Dest_Plate@col:2:4")

        for col in range(2, 5):
            tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
            print(f"Tip pickup for column {col}: {tip_pickup_response.model_dump(by_alias=True)}")

            aspirate_response = star.aspirate(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"Source_Plate@col:{col}",
                volumes=transfer_volume_ul,
                liquid_class=liquid_class,
                settings=aspirate_settings,
            )
            print(f"Aspirate from col:{col}: {aspirate_response.model_dump(by_alias=True)}")

            dispense_response = star.dispense(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"Dest_Plate@col:{col}",
                volumes=transfer_volume_ul,
                settings=dispense_settings,
            )
            print(f"Dispense to col:{col}: {dispense_response.model_dump(by_alias=True)}")

            tip_eject_response = star.tip_eject()
            print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        print()

        # ====================================================================
        # Technique 5: Row selection
        # ====================================================================
        print("=" * 70)
        print("Technique 5: Row Selection")
        print("=" * 70)
        print("Transfer first 8 wells of row A from Source_Plate@row:A to Dest_Plate@row:A")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            positions="Source_Plate@row:A",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate from row:A: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            positions="Dest_Plate@row:A",
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense to row:A: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 6: normalize_positions for debugging
        # ====================================================================
        print("=" * 70)
        print("Technique 6: Using normalize_positions for Debugging")
        print("=" * 70)

        # Inspect column ordering
        positions = normalize_positions("Source_Plate@col:1", channel_count=8)
        print(f"Column 1 wells (8-channel): {[f'{p.well}' for p in positions]}")

        # Inspect row ordering
        positions = normalize_positions("Source_Plate@row:A", well_order=WellOrder.ROW_ASC)
        print(f"Row A wells (ROW_ASC): {[f'{p.well}' for p in positions]}")

        # Inspect rectangular range
        positions = normalize_positions("Source_Plate@A1:C3", well_order=WellOrder.COL_ASC)
        print(f"Rectangle A1:C3 (COL_ASC): {[f'{p.well}' for p in positions]}")

        # Inspect with different ordering
        positions = normalize_positions(
            "Source_Plate@col:1", channel_count=8, well_order=WellOrder.COL_DESC
        )
        print(f"Column 1 wells (COL_DESC): {[f'{p.well}' for p in positions]}\n")

        # ====================================================================
        # Technique 7: Multiple selectors in a list
        # ====================================================================
        print("=" * 70)
        print("Technique 7: Multiple Selectors in a List")
        print("=" * 70)
        print("Transfer from multiple selector expressions")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6],
            positions=["Source_Plate@A1,B1,C1", "Source_Plate@A2,B2,C2"],
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        print(f"Aspirate from multiple selectors: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6],
            positions=["Dest_Plate@A1,B1,C1", "Dest_Plate@A2,B2,C2"],
            volumes=transfer_volume_ul,
            settings=dispense_settings,
        )
        print(f"Dispense to multiple selectors: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 8: Reusing well ordering across commands
        # ====================================================================
        print("=" * 70)
        print("Technique 8: Reusing Well Ordering Across Commands")
        print("=" * 70)
        print("Labware geometry is resolved automatically from the deck.")

        # Demonstrate that the same well_order can be reused across multiple commands
        for col in range(5, 7):
            tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
            print(f"Tip pickup for column {col}: {tip_pickup_response.model_dump(by_alias=True)}")

            aspirate_response = star.aspirate(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"Source_Plate@col:{col}",
                volumes=transfer_volume_ul,
                liquid_class=liquid_class,
                settings=aspirate_settings,
                well_order=WellOrder.COL_ASC,
            )
            print(f"Aspirate from col:{col}: {aspirate_response.model_dump(by_alias=True)}")

            dispense_response = star.dispense(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"Dest_Plate@col:{col}",
                volumes=transfer_volume_ul,
                settings=dispense_settings,
                well_order=WellOrder.COL_ASC,
            )
            print(f"Dispense to col:{col}: {dispense_response.model_dump(by_alias=True)}")

            tip_eject_response = star.tip_eject()
            print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        print("\nPosition and Well Selection Smoke Test Complete - Disconnecting")

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
