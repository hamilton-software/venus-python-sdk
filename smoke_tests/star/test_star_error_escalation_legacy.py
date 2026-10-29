from logging import DEBUG

from hamilton_venus import StarClient
from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


with StarClient(
    deck_name="example_deck",
    logging_level=DEBUG,
    venus_trace_logging=True,
) as star:
    star.instrument_init()

    init_tips_response = star.tip_pool_initialize_tip_counter("transfer_tips")
    print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
    reset_tips_response = star.tip_pool_reset_tip_counter("transfer_tips")
    print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

    star.tip_pickup(tip_pool="transfer_tips")
    star.aspirate(positions="source_plate@col:1", volumes=50.0, liquid_class=liquid_class)
    star.dispense(positions="dest_plate@col:1", volumes=50.0)
    star.tip_eject()
