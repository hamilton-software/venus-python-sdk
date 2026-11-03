"""Diagnostic: read, initialize, re-read and set the tip counter for the 1000 uL pool. No motion."""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier"
TIP_POOL = "Tips1000"

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id=CARRIER_ID)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id=CARRIER_ID, site="1", tip_pool=TIP_POOL, labware_id="Rack_Tips1000")

    print("COUNTERS:", star.tip_pool_get_tip_counters().return_parameters.model_dump())
    before = star.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    print("BEFORE:", before.model_dump())

    star.tip_pool_initialize_tip_counter(TIP_POOL)
    after_init = star.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    print("AFTER INIT:", after_init.model_dump())

    star.tip_pool_set_tip_counter(TIP_POOL, after_init.available_tips)
    after_set = star.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    print("AFTER SET:", after_set.model_dump())

print("Done")
