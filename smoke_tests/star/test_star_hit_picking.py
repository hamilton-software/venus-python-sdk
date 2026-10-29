"""Smoke tests for the hit_picking compound command."""

import pathlib
import tempfile
import textwrap

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES

tip_pool = "transfer_tips"
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


def _init(star: StarClient) -> None:

    star.instrument_init()
    print("Initialization complete")
    star.tip_pool_initialize_tip_counter(tip_pool)
    star.tip_pool_reset_tip_counter(tip_pool)
    print(f"Tip counter reset for pool '{tip_pool}'")


def _write_csv(directory: str, name: str, body: str) -> str:
    path = pathlib.Path(directory) / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


try:
    with StarClient(simulate=True, deck_name="example_deck") as star:
        _init(star)

        with tempfile.TemporaryDirectory() as tmp:
            # ----------------------------------------------------------------
            # 1. change_tips=True, minimize_tips=False (default): fresh tip per
            #    transfer, processed in channel-sized chunks.
            # ----------------------------------------------------------------
            print("\n--- 1. Default (change_tips=True) ---")
            csv_default = _write_csv(
                tmp,
                "default.csv",
                """\
                source_labware,source_well,dest_labware,dest_well,volume
                source_plate,A1,dest_plate,A1,50.0
                source_plate,B1,dest_plate,B1,50.0
                source_plate,C1,dest_plate,C1,50.0
                source_plate,D1,dest_plate,D1,50.0
                source_plate,E1,dest_plate,E1,50.0
                source_plate,F1,dest_plate,F1,50.0
                source_plate,G1,dest_plate,G1,50.0
                source_plate,H1,dest_plate,H1,50.0
                source_plate,A2,dest_plate,A2,75.0
                source_plate,B2,dest_plate,B2,100.0
                source_plate,D3,dest_plate,A3,75.0
                source_plate,C3,dest_plate,B3,100.0
                source_plate,C2,dest_plate,C2,75.0
                source_plate,D2,dest_plate,D2,100.0
                source_plate,B3,dest_plate,C3,75.0
                source_plate,A3,dest_plate,D3,100.0
                source_plate,A4,dest_plate,A4,75.0
                source_plate,B4,dest_plate,B4,100.0
                source_plate,A5,dest_plate,A5,75.0
                source_plate,B5,dest_plate,B5,100.0
                """,
            )
            result = star.hit_picking(
                transfer_csv=csv_default,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
            )
            print(f"  transfers:     {len(result.transfers)}")
            print(f"  iterations:    {result.iterations}")
            print(f"  tips_consumed: {result.tips_consumed}")
            print(f"  source_plates: {result.source_plate_ids}")
            print(f"  dest_plates:   {result.dest_plate_ids}")
            executed = [(t.source_well, t.dest_well) for t in result.transfers]
            print(f"  execution order (expected to be optimized to column-major order): {executed}")

            star.tip_pool_reset_tip_counter(tip_pool)

            # ----------------------------------------------------------------
            # 2. change_tips=False, minimize_tips=False: pick up tips once,
            #    reuse for the whole worklist, eject at the end.
            # ----------------------------------------------------------------
            print("\n--- 2. Reuse tips (change_tips=False) ---")
            result = star.hit_picking(
                transfer_csv=csv_default,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                change_tips=False,
            )
            print(f"  transfers:     {len(result.transfers)}")
            print(f"  tips_consumed: {result.tips_consumed}")
            print(f"  change_tips:   {result.change_tips}")

            star.tip_pool_reset_tip_counter(tip_pool)

            # ----------------------------------------------------------------
            # 3. minimize_tips=True: one tip per unique source well, serving
            #    every destination fed by that well.
            # ----------------------------------------------------------------
            print("\n--- 3. Minimize tips (one tip per source well) ---")
            csv_minimize = _write_csv(
                tmp,
                "minimize.csv",
                """\
                source_labware,source_well,dest_labware,dest_well,volume
                source_plate,A1,dest_plate,A1,50.0
                source_plate,A1,dest_plate,B1,50.0
                source_plate,A1,dest_plate,C1,50.0
                source_plate,B1,dest_plate,D1,75.0
                source_plate,C1,dest_plate,E1,100.0
                """,
            )
            result = star.hit_picking(
                transfer_csv=csv_minimize,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                minimize_tips=True,
            )
            print(f"  transfers:     {len(result.transfers)}")
            print(f"  iterations:    {result.iterations}")
            print(f"  tips_consumed: {result.tips_consumed}  (expected 3 unique source wells)")
            print(f"  minimize_tips: {result.minimize_tips}")

            star.tip_pool_reset_tip_counter(tip_pool)

            # ----------------------------------------------------------------
            # 4. minimize_tips=True, change_tips=False (Q4): a single tip is
            #    kept across every source well (operator accepts the
            #    cross-contamination risk; a warning is logged at startup).
            # ----------------------------------------------------------------
            print("\n--- 4. Single-tip mode (minimize_tips=True, change_tips=False) ---")
            result = star.hit_picking(
                transfer_csv=csv_minimize,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                minimize_tips=True,
                change_tips=False,
            )
            print(f"  transfers:     {len(result.transfers)}")
            print(f"  tips_consumed: {result.tips_consumed}  (expected 1)")

            star.tip_pool_reset_tip_counter(tip_pool)

            # ----------------------------------------------------------------
            # 5. follow_csv_order=True: run transfers in exact worklist order
            #    instead of the default plate-grouped column-major reorder.
            # ----------------------------------------------------------------
            print("\n--- 5. Follow CSV order ---")
            result = star.hit_picking(
                transfer_csv=csv_default,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                follow_csv_order=True,
            )
            print(f"  transfers:     {len(result.transfers)}")
            print(f"  iterations:    {result.iterations}")
            executed = [(t.source_well, t.dest_well) for t in result.transfers]
            print(f"  execution order: {executed}")

        print("\nHit Picking Smoke Test Complete")

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
