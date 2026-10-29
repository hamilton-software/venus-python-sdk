"""
Smoke test demonstrating position and well selection for smaller plate formats.

This test covers 12-well and 48-well plates, showing how position selection
works with different labware geometries and smaller well counts.
"""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import (
    WellOrder,
    normalize_positions,
)

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY
tip_pool = "TipPool300uL"
transfer_volume_ul = 200.0  # Larger volume for small plates
TIP_RACK_DEFINITION = LABWARE.TIP_RACK.TIP_RACK_300UL

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

        # Set up plate carrier with small plates
        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.REA_CAR_L3AT,
            left_track=7,
            labware_id="PlateCarrierSmallA",
        )
        print(f"Add small-plate carrier A response: {carrier_response.model_dump(by_alias=True)}")

        source_plate_12_response = star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_12_FL,
            carrier_id="PlateCarrierSmallA",
            site="1",
            plate_id="SourcePlate12",
        )
        print(f"Add 12-well source plate response: {source_plate_12_response.model_dump(by_alias=True)}")

        dest_plate_12_response = star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_12_FL,
            carrier_id="PlateCarrierSmallA",
            site="2",
            plate_id="DestPlate12",
        )
        print(f"Add 12-well dest plate response: {dest_plate_12_response.model_dump(by_alias=True)}")

        carrier_response = star.add_carrier(
            labware_definition=LABWARE.CARRIER.REA_CAR_L3AT,
            left_track=13,
            labware_id="PlateCarrierSmallB",
        )
        print(f"Add small-plate carrier B response: {carrier_response.model_dump(by_alias=True)}")

        source_plate_48_response = star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_48_FL,
            carrier_id="PlateCarrierSmallB",
            site="1",
            plate_id="SourcePlate48",
        )
        print(f"Add 48-well source plate response: {source_plate_48_response.model_dump(by_alias=True)}")

        dest_plate_48_response = star.add_plate(
            labware_definition=LABWARE.PLATE.NUN_48_FL,
            carrier_id="PlateCarrierSmallB",
            site="2",
            plate_id="DestPlate48",
        )
        print(f"Add 48-well dest plate response: {dest_plate_48_response.model_dump(by_alias=True)}")

        star.instrument_init()
        print("Initialization complete\n")

        # ====================================================================
        # Section 1: 12-Well Plate Operations
        # ====================================================================
        print("=" * 70)
        print("Section 1: 12-Well Plate (3 rows x 4 columns)")
        print("=" * 70)

        # Technique 1: Understanding 12-well plate layout
        print("\nTechnique 1: 12-Well Plate Layout")

        # Show all wells
        positions = normalize_positions("SourcePlate12@all", get_spec=star.get_labware_spec)
        print(f"All wells in plate: {[f'{p.well}' for p in positions]}")

        # Show row expansion
        positions = normalize_positions(
            "SourcePlate12@row:A", well_order=WellOrder.ROW_ASC, get_spec=star.get_labware_spec
        )
        print(f"Row A wells: {[f'{p.well}' for p in positions]}")

        # Show column expansion
        positions = normalize_positions(
            "SourcePlate12@col:1", well_order=WellOrder.COL_ASC, get_spec=star.get_labware_spec
        )
        print(f"Column 1 wells: {[f'{p.well}' for p in positions]}")

        # Technique 2: Single well transfer on 12-well plate
        print("\nTechnique 2: Single Well Transfer (12-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1],
            positions="SourcePlate12@A1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from A1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1],
            positions="DestPlate12@A1",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to A1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        # Technique 3: Explicit well list on 12-well plate
        print("\nTechnique 3: Explicit Well List (12-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3],
            positions="SourcePlate12@A1,A2,A3",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from A1,A2,A3: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3],
            positions="DestPlate12@A1,A2,A3",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to A1,A2,A3: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        # Technique 4: Column selection on 12-well plate
        print("\nTechnique 4: Column Selection (12-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3],
            positions="SourcePlate12@col:1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from col:1: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3],
            positions="DestPlate12@col:1",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to col:1: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        # ====================================================================
        # Section 2: 48-Well Plate Operations
        # ====================================================================
        print("=" * 70)
        print("Section 2: 48-Well Plate")
        print("=" * 70)

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        # Technique 1: Understanding 48-well plate layout
        print("\nTechnique 1: 48-Well Plate Layout")

        # Show row expansion
        positions = normalize_positions(
            "SourcePlate48@row:A", well_order=WellOrder.ROW_ASC, get_spec=star.get_labware_spec
        )
        print(f"Row A wells: {[f'{p.well}' for p in positions]}")

        # Show column expansion
        positions = normalize_positions(
            "SourcePlate48@col:1", well_order=WellOrder.COL_ASC, get_spec=star.get_labware_spec
        )
        print(f"Column 1 wells: {[f'{p.well}' for p in positions]}")

        # Technique 2: Column selection on 48-well plate
        print("\nTechnique 2: Column Selection (48-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6],
            positions="SourcePlate48@col:1",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from col:1 (6-channel): {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6],
            positions="DestPlate48@col:1",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to col:1 (6-channel): {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        # Technique 3: Multiple column transfers on 48-well plate
        print("\nTechnique 3: Multiple Column Transfers (48-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        for col in range(1, 4):
            tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
            print(f"Tip pickup for column {col}: {tip_pickup_response.model_dump(by_alias=True)}")

            aspirate_response = star.aspirate(
                channels=[1, 2, 3, 4, 5, 6],
                positions=f"SourcePlate48@col:{col}",
                volumes=transfer_volume_ul,
                liquid_class=liquid_class,
            )
            print(f"Aspirate from col:{col}: {aspirate_response.model_dump(by_alias=True)}")

            dispense_response = star.dispense(
                channels=[1, 2, 3, 4, 5, 6],
                positions=f"DestPlate48@col:{col}",
                volumes=transfer_volume_ul,
            )
            print(f"Dispense to col:{col}: {dispense_response.model_dump(by_alias=True)}")

            tip_eject_response = star.tip_eject()
            print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}")

        print()

        # Technique 4: Row selection on 48-well plate
        print("Technique 4: Row Selection (48-well)")

        star.tip_pool_initialize_tip_counter(tip_pool)
        star.tip_pool_reset_tip_counter(tip_pool)

        tip_pickup_response = star.tip_pickup(tip_pool=tip_pool, optimized_pickup=True)
        print(f"Tip pickup: {tip_pickup_response.model_dump(by_alias=True)}")

        aspirate_response = star.aspirate(
            channels=[1, 2, 3, 4, 5, 6],
            positions="SourcePlate48@row:A",
            volumes=transfer_volume_ul,
            liquid_class=liquid_class,
        )
        print(f"Aspirate from row:A: {aspirate_response.model_dump(by_alias=True)}")

        dispense_response = star.dispense(
            channels=[1, 2, 3, 4, 5, 6],
            positions="DestPlate48@row:A",
            volumes=transfer_volume_ul,
        )
        print(f"Dispense to row:A: {dispense_response.model_dump(by_alias=True)}")

        tip_eject_response = star.tip_eject()
        print(f"Tip eject: {tip_eject_response.model_dump(by_alias=True)}\n")

        print("Small Plate Format Position Selection Smoke Test Complete - Disconnecting")

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
