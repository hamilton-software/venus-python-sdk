"""Smoke tests for the replicate_samples compound command."""

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
        # 1. multi_dispense=True (default): 4 sources x 3 replicates -> one
        #    aspirate per source feeds three destination wells.
        # ------------------------------------------------------------------
        print("\n--- 1. multi-dispense (4 sources x 3 replicates) ---")
        result = star.replicate_samples(
            source_plate="source_plate@col:1",
            dest_plate="dest_plate",
            replicates_per_source=3,
            volume_per_replicate=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  sources_processed: {result.sources_processed}")
        print(f"  replicates_filled: {result.replicates_filled}")
        print(f"  iterations:        {result.iterations}")
        print(f"  multi_dispense:    {result.multi_dispense}")
        print(f"  source_plates:     {result.source_plate_ids}")
        print(f"  dest_plates:       {result.dest_plate_ids}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 2. multi_dispense=False: each src->dest pair is its own aspirate +
        #    dispense; a fresh tip is used per channel-row chunk.
        # ------------------------------------------------------------------
        print("\n--- 2. single-dispense ---")
        result = star.replicate_samples(
            source_plate="source_plate@col:1",
            dest_plate="dest_plate",
            replicates_per_source=3,
            volume_per_replicate=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            multi_dispense=False,
        )
        print(f"  sources_processed: {result.sources_processed}")
        print(f"  replicates_filled: {result.replicates_filled}")
        print(f"  iterations:        {result.iterations}")
        print(f"  multi_dispense:    {result.multi_dispense}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 3. Pre/post aliquot with disposal back to source.
        # ------------------------------------------------------------------
        print("\n--- 3. Multi-dispense with pre/post aliquot (disposal=SOURCE) ---")
        result = star.replicate_samples(
            source_plate="source_plate@col:1",
            dest_plate="dest_plate",
            replicates_per_source=3,
            volume_per_replicate=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            pre_aliquot_volume=10.0,
            pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
            post_aliquot_volume=5.0,
        )
        print(f"  sources_processed: {result.sources_processed}")
        for idx, it in enumerate(result.iteration_results):
            pre = "yes" if it.pre_aliquot_dispense is not None else "no"
            post = "yes" if it.post_aliquot_dispense is not None else "no"
            print(f"    src[{idx}] pre_aliquot={pre} post_aliquot={post}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 4. Pre/post aliquot with disposal to waste. Requires `liquid_waste`
        #    labware in the deck.
        # ------------------------------------------------------------------
        print("\n--- 4. Multi-dispense with pre/post aliquot (disposal=WASTE) ---")
        result = star.replicate_samples(
            source_plate="source_plate@col:1",
            dest_plate="dest_plate",
            replicates_per_source=3,
            volume_per_replicate=25.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            pre_aliquot_volume=10.0,
            pre_aliquot_disposal=PreAliquotDisposal.WASTE,
            post_aliquot_volume=5.0,
        )
        print(f"  sources_processed: {result.sources_processed}")
        print(f"  replicates_filled: {result.replicates_filled}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 5. Auto-split: high replicate count exceeds tip capacity so
        #    multi-dispense mode aspirates several times per source.
        # ------------------------------------------------------------------
        print("\n--- 5. Multi-dispense auto-split (high replicate count) ---")
        result = star.replicate_samples(
            source_plate="source_plate@col:1",
            dest_plate="dest_plate",
            replicates_per_source=12,
            volume_per_replicate=50.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  sources_processed: {result.sources_processed}")
        print(f"  replicates_filled: {result.replicates_filled}")
        for idx, it in enumerate(result.iteration_results):
            print(
                f"    src[{idx}] aspirates={len(it.aspirates)} "
                f"dispenses={len(it.replicate_dispenses)}"
            )

        # ------------------------------------------------------------------
        # 6. multi-dispense mode across two source plates and two dest plates.
        #    8 sources (4 per plate) * 3 replicates = 24 dest wells (12 per plate).
        # ------------------------------------------------------------------
        print("\n--- 6. multi-dispense mode multi-plate ---")
        result = star.replicate_samples(
            source_plate=["source_plate@A1,B1,C1,D1", "source_plate2@A1,B1,C1,D1"],
            dest_plate=["dest_plate@col:1,2", "dest_plate2@col:1,2"],
            replicates_per_source=3,
            volume_per_replicate=20.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print(f"  iterations:        {result.iterations}")
        print(f"  sources_processed: {result.sources_processed}")
        print(f"  replicates_filled: {result.replicates_filled}")
        print(f"  source_plates:     {result.source_plate_ids}")
        print(f"  dest_plates:       {result.dest_plate_ids}")

        star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 7. single-dispense mode (fresh tip per replicate) across two plates.
        # ------------------------------------------------------------------
        print("\n--- 7. single-dispense mode multi-plate ---")
        result = star.replicate_samples(
            source_plate=["source_plate@A1,B1", "source_plate2@A1,B1"],
            dest_plate=["dest_plate@col:1", "dest_plate2@col:1"],
            replicates_per_source=2,
            volume_per_replicate=20.0,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            multi_dispense=False,
        )
        print(f"  iterations:        {result.iterations}")
        print(f"  replicates_filled: {result.replicates_filled}")

        print("\nReplicate Samples Smoke Test Complete")

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
