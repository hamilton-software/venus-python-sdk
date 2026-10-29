"""Smoke tests for the add_reagent compound command."""

import pathlib
import tempfile
import textwrap

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.enums import PreAliquotDisposal

tip_pool = "transfer_tips"
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


def _init(star: StarClient) -> None:

    star.instrument_init()
    print("Initialization complete")
    star.tip_pool_initialize_tip_counter(tip_pool)
    star.tip_pool_reset_tip_counter(tip_pool)
    print(f"Tip counter reset for pool '{tip_pool}'")


try:
    with StarClient(simulate=True, deck_name="example_deck") as star:
        _init(star)

        # ------------------------------------------------------------------
        # 1. Single Dispense
        # ------------------------------------------------------------------
        print("\n--- Single Dispense ---")
        result = star.add_reagent(
            reagent_source="reagent_trough",
            dest_plate="dest_plate@col:1,2,3,4",
            volume=50.0,
            tip_pool=tip_pool,
            liquid_class=liquid_class,
        )
        print(f"  wells_filled:  {result.wells_filled}")
        print(f"  iterations:    {result.iterations}")
        print(f"  source_plates: {result.source_plate_ids}")
        print(f"  dest_plates:   {result.dest_plate_ids}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 2. Multi-dispense with 50μL dispense and 10μL pre-aliquot to source
        # and 5μL post-aliquot
        # ------------------------------------------------------------------
        print("\n--- Multi-dispense with 50 dispense and 10 pre-aliquot to source and 5 post-aliquot ---")
        result = star.add_reagent(
            reagent_source="reagent_trough",
            dest_plate="dest_plate@col:1,2,3,4",
            volume=50.0,
            tip_pool=tip_pool,
            liquid_class=liquid_class,
            multi_dispense=True,
            pre_aliquot_volume=10.0,
            pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
            post_aliquot_volume=5.0,
        )
        print(f"  wells_filled:  {result.wells_filled}")
        print(f"  iterations:    {result.iterations}")
        print(f"  multi_dispense: {result.multi_dispense}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 3. Multi-dispense with 100μL dispense and 25μL pre-aliquot to waste
        # and 25μL post-aliquot
        # ------------------------------------------------------------------
        print("\n--- Multi-dispense with 100 dispense and 25 pre-aliquot to waste and 25 post-aliquot ---")
        result = star.add_reagent(
            reagent_source="reagent_trough",
            dest_plate="dest_plate@col:1,2,3,4",
            volume=100.0,
            tip_pool=tip_pool,
            liquid_class=liquid_class,
            multi_dispense=True,
            pre_aliquot_volume=25.0,
            pre_aliquot_disposal=PreAliquotDisposal.WASTE,
            post_aliquot_volume=25.0,
        )
        print(f"  wells_filled:  {result.wells_filled}")
        print(f"  iterations:    {result.iterations}")
        print(f"  multi_dispense: {result.multi_dispense}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 4. Broadcast: single reagent source -> two destination plates.
        # ------------------------------------------------------------------
        print("\n--- Broadcast: 1 source selector -> 2 dest plates ---")
        result = star.add_reagent(
            reagent_source="reagent_trough",
            dest_plate=["dest_plate@col:1,2", "dest_plate2@col:1,2"],
            volume=50.0,
            tip_pool=tip_pool,
            liquid_class=liquid_class,
        )
        print(f"  wells_filled:  {result.wells_filled}")
        print(f"  source_plates: {result.source_plate_ids}")
        print(f"  dest_plates:   {result.dest_plate_ids}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 5. CSV-driven transfer
        # ------------------------------------------------------------------
        print("\n--- CSV transfer ---")
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = pathlib.Path(tmp) / "transfers.csv"
            csv_path.write_text(
                textwrap.dedent(
                    """\
                    dest_labware,dest_well,volume
                    dest_plate,A1,50.0
                    dest_plate,B1,50.0
                    dest_plate,C1,75.0
                    dest_plate,D1,100.0
                    """
                ),
                encoding="utf-8",
            )
            result = star.add_reagent(
                reagent_source="source_plate@A1",
                dest_plate="dest_plate",
                volume=50.0,
                tip_pool=tip_pool,
                liquid_class=liquid_class,
                transfer_csv=str(csv_path),
                multi_dispense=True,
            )
        print(f"  wells_filled:  {result.wells_filled}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 6. Multiple reagent sources: one selector addressing several wells is
        #    drained in order (consumable liquid management).  Once a well runs
        #    low the run advances to the next; sources_used reports the order.
        # ------------------------------------------------------------------
        print("\n--- Multiple sources: source_plate@A1,B1,C1 drained in order ---")
        result = star.add_reagent(
            reagent_source="source_plate@A1,B1,C1",
            dest_plate="dest_plate@col:1,2,3,4",
            volume=50.0,
            tip_pool=tip_pool,
            liquid_class=liquid_class,
        )
        print(f"  wells_filled:  {result.wells_filled}")
        print(f"  source_plates: {result.source_plate_ids}")
        print(f"  sources_used:  {result.sources_used}")
        print("\nAdd Reagent Smoke Test Complete")

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
