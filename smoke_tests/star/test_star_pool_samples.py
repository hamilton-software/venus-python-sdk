"""Smoke tests for the pool_samples compound command."""

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.enums import WellOrder

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
        # 1. pool_size=4, 16 sources -> 4 pools. Default mix-after, default
        #    fresh tip per source well.
        # ------------------------------------------------------------------
        print("\n--- 1. Default pool (pool_size=4, 16 sources, mix_after_pool=True) ---")
        result = star.pool_samples(
            source_plate="source_plate@col:1,2",
            dest_plate="dest_plate@col:1",
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  wells_pooled:  {result.wells_pooled}")
        print(f"  source_plates: {result.source_plate_ids}")
        print(f"  dest_plates:   {result.dest_plate_ids}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 2. reuse_tips_within_pool=True: one tip per destination well, reused
        #    for all sources in that pool.
        # ------------------------------------------------------------------
        print("\n--- 2. Reuse tips within pool ---")
        result = star.pool_samples(
            source_plate="source_plate@col:1,2",
            dest_plate="dest_plate@col:1",
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            reuse_tips_within_pool=True,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  reuse_tips_within_pool: {result.reuse_tips_within_pool}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 3. mix_after_pool=False: no final mix at the destination.
        # ------------------------------------------------------------------
        print("\n--- 3. No final mix (mix_after_pool=False) ---")
        result = star.pool_samples(
            source_plate="source_plate@col:1,2",
            dest_plate="dest_plate@col:1",
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            mix_after_pool=False,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  mix_after_pool: {result.mix_after_pool}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 4. Incomplete final pool: 18 sources / pool_size=4 -> 4 full pools
        #    plus a final pool of size 2. col:1,2 = 16 wells; add 2 more from
        #    column 3 to make 18.
        # ------------------------------------------------------------------
        print("\n--- 4. Incomplete final pool (18 sources, pool_size=4) ---")
        result = star.pool_samples(
            source_plate="source_plate@wells:A1,B1,C1,D1,E1,F1,G1,H1,A2,B2,C2,D2,E2,F2,G2,H2,A3,B3",
            dest_plate="dest_plate@col:1",
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  wells_pooled:  {result.wells_pooled}")
        for idx, it in enumerate(result.iteration_results):
            print(f"    pool[{idx}] sources: {len(it.source_wells)} -> {it.dest_well}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 5. source_order=ROW_ASC: traverse sources row-by-row instead of
        #    the default column-major order.
        # ------------------------------------------------------------------
        print("\n--- 5. source_order=ROW_ASC ---")
        result = star.pool_samples(
            source_plate="source_plate@col:1,2",
            dest_plate="dest_plate@col:1",
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            source_order=WellOrder.ROW_ASC,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  pools_completed: {result.pools_completed}")

        # ------------------------------------------------------------------
        # 6. Sources span two plates (col:1 on each); dest spans two plates.
        #    16 sources, pool_size=4 -> 4 pools (2 per dest plate).
        # ------------------------------------------------------------------
        print("\n--- 6. Multi-plate sources and dests ---")
        result = star.pool_samples(
            source_plate=["source_plate@col:1", "source_plate2@col:1"],
            dest_plate=["dest_plate@A1,B1", "dest_plate2@A1,B1"],
            pool_size=4,
            volume_per_source=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  pools:         {len(result.iteration_results)}")
        print(f"  wells_pooled:  {result.wells_pooled}")
        print(f"  source_plates: {result.source_plate_ids}")
        print(f"  dest_plates:   {result.dest_plate_ids}")
        for idx, it in enumerate(result.iteration_results):
            print(
                f"    pool[{idx}] src={it.source_plate_id}/{len(it.source_wells)} -> {it.dest_plate_id}/{it.dest_well}"
            )

        print("\nPool Samples Multi-Plate Smoke Test Complete")

        print("\nPool Samples Smoke Test Complete")

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
