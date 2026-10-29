"""Smoke tests for the serial_dilution compound commands.

Runs against ``StarClient(simulate=True, deck_name="example_deck")``.  The
example deck provides ``source_plate`` / ``source_plate2`` (used as the dilution
plates), ``reagent_trough`` (used as the diluent source), the fixed
``liquid_waste`` labware, and the ``transfer_tips`` tip pool.  Because the deck
exposes a single tip pool and a single trough, both the diluent and transfer
phases draw tips from ``transfer_tips`` and the multi-source scenario lists the
same trough twice to exercise the multi-source happy path (the VENUS simulator
does not decrement trough levels, so the exhaustion/reload branch is covered by
the unit tests instead — see the plan §7.2 note).

Each scenario prints a short summary; any :class:`VenusError` exits non-zero.
"""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.enums import LastDilutionWaste

tip_pool = "transfer_tips"
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


def _init(star: StarClient) -> None:
    star.instrument_init()
    print("Initialization complete")
    star.tip_pool_initialize_tip_counter(tip_pool)
    star.tip_pool_reset_tip_counter(tip_pool)
    print(f"Tip counter reset for pool '{tip_pool}'")


def _print_result(result) -> None:
    print(f"  plates:        {result.plate_ids}")
    print(f"  num_series:    {result.num_series}")
    print(f"  num_dilutions: {result.num_dilutions}")
    print(f"  diluent_vol:   {result.diluent_volume}")
    print(f"  transfer_vol:  {result.transfer_volume}")
    print(f"  factor:        {result.dilution_factor}")
    print(f"  sources_used:  {result.diluent_sources_used}")
    for plate in result.plate_results:
        print(f"    plate {plate.plate_id}: {plate.num_passes} pass(es), {len(plate.series_results)} series")
        if plate.series_results:
            first = plate.series_results[0]
            print(f"      series[0] row={first.row} chain={first.well_chain} steps={len(first.steps)}")


try:
    with StarClient(simulate=True, deck_name="example_deck") as star:
        _init(star)

        # ------------------------------------------------------------------
        # 1. serial_dilution_by_dilution_factor: 1:2, num_dilutions=6, mix on.
        # ------------------------------------------------------------------
        print("\n--- 1. By dilution factor (1:2, num_dilutions=6, mix on) ---")
        result = star.serial_dilution_by_dilution_factor(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=6,
            transfer_volume=10.0,
            dilution_factor=2.0,
            diluent_source="reagent_trough@1",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            mix_after_dispense=True,
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 2. serial_dilution_by_volume: explicit diluent/transfer volumes.
        # ------------------------------------------------------------------
        print("\n--- 2. By volume (diluent=180, transfer=25 ---")
        result = star.serial_dilution_by_volume(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=4,
            transfer_volume=25.0,
            diluent_volume=180.0,
            diluent_source="reagent_trough@1,2,3,4",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 3. exclude_columns + exclude_rows (ints and letters).
        # ------------------------------------------------------------------
        print("\n--- 3. exclude_columns=[3] + exclude_rows=[1, 'C'] ---")
        result = star.serial_dilution_by_volume(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=3,
            transfer_volume=20.0,
            diluent_volume=50.0,
            diluent_source="reagent_trough",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            exclude_columns=[3],
            exclude_rows=[1, "C"],
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 4a. discard_last_excess=TO_WASTE with an explicit waste_location.
        # ------------------------------------------------------------------
        print("\n--- 4a. discard_last_excess=TO_WASTE (waste_location='liquid_waste') ---")
        result = star.serial_dilution_by_volume(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=3,
            transfer_volume=20.0,
            diluent_volume=100.0,
            diluent_source="reagent_trough@4",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            discard_last_excess=LastDilutionWaste.TO_WASTE,
            waste_location="liquid_waste",
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 4b. discard_last_excess=WITH_TIP_EJECT (excess leaves with the tips).
        # ------------------------------------------------------------------
        print("\n--- 4b. discard_last_excess=WITH_TIP_EJECT ---")
        result = star.serial_dilution_by_volume(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=3,
            transfer_volume=20.0,
            diluent_volume=100.0,
            diluent_source="reagent_trough@5",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            discard_last_excess=LastDilutionWaste.WITH_TIP_EJECT,
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 5. reuse_tips=True (transfer tips carried across passes) with
        #    diluent_multi_dispense=False.  4 channels over 8 rows -> 2 passes.
        # ------------------------------------------------------------------
        print("\n--- 5. reuse_tips=True + diluent_multi_dispense=False (4 channels, 2 passes) ---")
        result = star.serial_dilution_by_volume(
            plate_id="source_plate",
            start_column=1,
            num_dilutions=4,
            transfer_volume=20.0,
            diluent_volume=100.0,
            diluent_source="reagent_trough@6",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            channels=[1, 2, 3, 4],
            reuse_tips=True,
            diluent_multi_dispense=False,
        )
        _print_result(result)
        star.tip_pool_reset_tip_counter(tip_pool)


        # ------------------------------------------------------------------
        # 7. Multi-plate plate_id=[...]; and a multi-pass case (4 channels on
        #    each plate produces two passes per plate).
        # ------------------------------------------------------------------
        print("\n--- 7. Multi-plate (source_plate + source_plate2), 4 channels -> multi-pass ---")
        result = star.serial_dilution_by_volume(
            plate_id=["source_plate", "source_plate2"],
            start_column=1,
            num_dilutions=3,
            transfer_volume=20.0,
            diluent_volume=100.0,
            diluent_source="reagent_trough",
            diluent_liquid_class=liquid_class,
            diluent_tip_pool=tip_pool,
            transfer_liquid_class=liquid_class,
            transfer_tip_pool=tip_pool,
            channels=[1, 2, 3, 4],
        )
        _print_result(result)

        print("\nSerial Dilution Smoke Test Complete")

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
