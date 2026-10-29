from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

tip_pool = "transfer_tips"
transfer_volume_ul = 50.0
liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

try:
    with StarClient(simulate=True, deck_name="example_deck") as star:

        print("Connected — method is running") 

        star.instrument_init()
        print("Initialization complete")

        init_tips_response = star.tip_pool_initialize_tip_counter(tip_pool)
        reset_tips_response = star.tip_pool_reset_tip_counter(tip_pool)

        # ------------------------------------------------------------------
        # 1. Copy 1 Source Plate to 1 Destination Plate.
        # ------------------------------------------------------------------
        print("\n--- 1. 1 Source Plate copied to 1 Destination Plate ---")
        result = star.copy_plate(
            source_plate_id="source_plate",
            dest_plate_id="dest_plate",
            volume=transfer_volume_ul,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
        )
        print("\nCopy plate result:")
        print(f"  wells_copied:  {result.wells_copied}")
        print(f"  wells_skipped: {result.wells_skipped}")
        print(f"  iterations:    {result.iterations}")
        print(f"  total_wells:   {result.total_wells_processed}")
        print(f"  responses:     {len(result.iteration_results)} iterations collected")
        
        star.tip_pool_reset_tip_counter(tip_pool)
               
        # ------------------------------------------------------------------
        # 2. Copy 1 Source Plate to 2 Destination Plates and reuse_tips=True
        # ------------------------------------------------------------------
        print("\n--- 2. 1 Source Plate copied to 2 Destination Plates ---")
        result = star.copy_plate(
            source_plate_id="source_plate",
            dest_plate_id=["dest_plate", "dest_plate2"],
            volume=transfer_volume_ul,
            liquid_class=liquid_class,
            tip_pool=tip_pool,
            reuse_tips=True
        )
        print("\nCopy plate result:")
        print(f"  wells_copied:  {result.wells_copied}")
        print(f"  wells_skipped: {result.wells_skipped}")
        print(f"  iterations:    {result.iterations}")
        print(f"  total_wells:   {result.total_wells_processed}")
        print(f"  responses:     {len(result.iteration_results)} iterations collected")

        print("\nCopy Plate Smoke Test Complete - Disconnecting")
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
