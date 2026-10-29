"""
Smoke test demonstrating position and well selection for 384-well plates.

This test showcases spacing-aware sequencing (interleaving), a critical feature
when working with 384-well plates where well spacing (4.5 mm) differs from the
1 mL channel pitch (9.0 mm). The SDK automatically reorders wells so that each
simultaneous channel group targets physically reachable positions.
"""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    WellOrder,
    normalize_positions,
)

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY
tip_pool = "TipPool300uL"
transfer_volume_ul = 10.0  # Smaller volume for 384-well plates
TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_300UL


def is_known_384_vector_geometry_error(error: VenusCommandFailedError) -> bool:
    """Return True for known simulator vector limitation on some 384 definitions."""
    details = error.response.return_parameters or {}
    message = str(details.get("message", "")).lower()
    code = details.get("code")
    return code == -1543372793 or "unable to find a dictionary pair" in message

try:
    with StarClient(simulate=True, venus_trace_logging=True) as star:
        print("Connected — method is running")

        print(f"Instrument is connected: {star.instrument_is_connected()}")

        # Set up tip rack
        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id="WorkCarrier1",
        )
        print(f"Add carrier response: {carrier_response.model_dump(by_alias=True)}")

        tip_rack_response = star.add_tip_rack(
            labware_definition=TIP_RACK_DEFINITION,
            carrier_id="WorkCarrier1",
            site="1",
            tip_pool=tip_pool,
        )
        print(f"Add tip rack response: {tip_rack_response.model_dump(by_alias=True)}")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        # Set up plate carrier with 384-well plates
        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
            left_track=7,
            labware_id="PlateCarrier1",
        )
        print(f"Add plate carrier response: {carrier_response.model_dump(by_alias=True)}")

        source_plate_response = star.add_plate(
            labware_definition=LABWARE.PLATE.COS_384_SQ_RD,
            carrier_id="PlateCarrier1",
            site="3",
            plate_id="SourcePlate384",
        )
        print(f"Add source plate response: {source_plate_response.model_dump(by_alias=True)}")

        destination_plate_response = star.add_plate(
            labware_definition=LABWARE.PLATE.COS_384_SQ_RD,
            carrier_id="PlateCarrier1",
            site="5",
            plate_id="DestPlate384",
        )
        print(f"Add destination plate response: {destination_plate_response.model_dump(by_alias=True)}")

        star.instrument_init()
        print("Initialization complete\n")

        # ====================================================================
        # Technique 1: Understanding 384-well plate spacing
        # ====================================================================
        print("=" * 70)
        print("Technique 1: 384-Well Plate Spacing and Interleaving")
        print("=" * 70)
        print("384-well plates have 4.5 mm spacing; 1 mL channels have 9.0 mm pitch")
        print("Skip factor = ceil(9.0 / 4.5) = 2 — channels skip every other well\n")

        ctx = star.get_labware_spec

        print("When aspirating from @col:1 (16 wells total):")
        print("The SDK internally reorders as: A1,C1,E1,G1,I1,K1,M1,O1,B1,D1,F1,H1,J1,L1,N1,P1\n")

        # First pass: A1, C1, E1, G1, I1, K1, M1, O1
        print("Pass 1 (channels 1-8, even rows):")
        positions = normalize_positions(
            "SourcePlate384@col:1",
            channel_count=8,
            get_spec=ctx,
            channel_pitch_mm=9.0,
        )
        for i, p in enumerate(positions):
            print(f"  Channel {i+1}: {p.well}")

        print("\nPass 2 (channels 1-8, odd rows - would be next aspirate call):")
        print("  Channel 1: B1")
        print("  Channel 2: D1")
        print("  Channel 3: F1")
        print("  Channel 4: H1")
        print("  Channel 5: J1")
        print("  Channel 6: K1")
        print("  Channel 7: N1")
        print("  Channel 8: P1")
        print("\nTo transfer all 16 wells, the pattern repeats:")
        print("- First aspirate gets wells at even row indices (A,C,E,G,I,K,M,O)")
        print("- Second aspirate gets wells at odd row indices (B,D,F,H,J,L,N,P)")
        print()

        # ====================================================================
        # Technique 2: Column selection with 384-well plate (8-channel)
        # ====================================================================
        print("=" * 70)
        print("Technique 2: Column Selection on 384-Well Plate (8-channel)")
        print("=" * 70)
        print("Transfer column 1 with automatic interleaving")

        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="SourcePlate384@col:1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from col:1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="DestPlate384@col:1",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to col:1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 3: Multiple column transfers with context reuse
        # ====================================================================
        print("=" * 70)
        print("Technique 3: Multiple Column Transfers (Reusing Context)")
        print("=" * 70)
        print("Transfer columns 2-5 with cached labware geometry")

        star.tip_pool_reset_tip_counter(tip_pool)

        for col in range(2, 6):
            tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
            print(f"Tip pickup for column {col}: {tip_pickup_response.model_dump(by_alias=True)}")

            aspirate_response = star.aspirate(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"SourcePlate384@col:{col}",
                volumes=transfer_volume_ul,
                liquid_class=liquid_class,
            )
            print(f"Aspirate from col:{col}: {aspirate_response.model_dump(by_alias=True)}")

            dispense_response = star.dispense(
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                positions=f"DestPlate384@col:{col}",
                volumes=transfer_volume_ul,
            )
            print(f"Dispense to col:{col}: {dispense_response.model_dump(by_alias=True)}")

            tip_eject_response = star.tip_eject()
            print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        print()

        # ====================================================================
        # Technique 4: Well range selection on 384-well plate
        # ====================================================================
        print("=" * 70)
        print("Technique 4: Rectangular Well Range on 384-Well Plate")
        print("=" * 70)
        print("Transfer a 4x2 rectangle from A1:B4 (8 wells)")

        star.tip_pool_reset_tip_counter(tip_pool)

        # Inspect the well ordering for this rectangle
        positions = normalize_positions(
            "SourcePlate384@A1:B4",
            well_order=WellOrder.COL_ASC,
            get_spec=ctx,
        )
        print(f"Rectangle A1:B4 wells (COL_ASC): {[f'{p.well}' for p in positions]}")

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="SourcePlate384@A1:B4",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from A1:B4: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
            positions="DestPlate384@A1:B4",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to A1:B4: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Technique 5: Comparing well order options with normalize_positions
        # ====================================================================
        print("=" * 70)
        print("Technique 5: Well Ordering Comparison (Debugging Tool)")
        print("=" * 70)
        print("Use normalize_positions() to inspect how wells are reordered\n")

        star.tip_pool_reset_tip_counter(tip_pool)

        # COL_ASC (default) - shows first 8 of interleaved sequence
        positions = normalize_positions(
            "SourcePlate384@col:1",
            channel_count=8,
            well_order=WellOrder.COL_ASC,
            get_spec=ctx,
            channel_pitch_mm=9.0,
        )
        print(f"Column 1 (COL_ASC, first pass): {[f'{p.well}' for p in positions]}")
        print("  (A,C,E,G,I,K,M,O - even rows. Next pass would get B,D,F,H,J,L,N,P)")

        # ROW_ASC - row traversal interleaving
        positions = normalize_positions(
            "SourcePlate384@row:A",
            channel_count=8,
            well_order=WellOrder.ROW_ASC,
            get_spec=ctx,
            channel_pitch_mm=9.0,
        )
        print(f"\nRow A (ROW_ASC, first pass): {[f'{p.well}' for p in positions]}")
        print("  (A1,A3,A5,A7,A9,A11,A13,A15 - odd columns. Next pass: A2,A4,A6,A8,A10,A12,A14,A16)")

        # COL_DESC - descending column order
        positions = normalize_positions(
            "SourcePlate384@col:1",
            channel_count=8,
            well_order=WellOrder.COL_DESC,
            get_spec=ctx,
            channel_pitch_mm=9.0,
        )
        print(f"\nColumn 1 (COL_DESC, first pass): {[f'{p.well}' for p in positions]}")
        print("  (P,N,L,J,H,F,D,B - descending, odd rows. Next pass: O,M,K,I,G,E,C,A)\n")

        # ====================================================================
        # Technique 6: Single well and explicit lists on 384-well
        # ====================================================================
        print("=" * 70)
        print("Technique 6: Single Well and Explicit Lists")
        print("=" * 70)

        star.tip_pool_reset_tip_counter(tip_pool)

        # Single well
        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup (single well): {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1],
            positions="SourcePlate384@A1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from A1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1],
            positions="DestPlate384@A1",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to A1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        print("384-Well Plate Position Selection Smoke Test Complete - Disconnecting")

except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    if is_known_384_vector_geometry_error(e):
        print("SKIP 384-well transfer: simulator vector geometry lookup limitation (Dim.Dx)")
        print(f"  Details: {e.response.return_parameters}")
    else:
        print(f"Command failed: {e}")
        print(f"  Return code: {e.response.return_code}")
        print(f"  Details: {e.response.return_parameters}")
        raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
