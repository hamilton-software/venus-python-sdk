"""Diagnostic: tip counter state around instrument_init and the first pickup. Simulation only."""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier"
TIP_POOL = "Tips1000"


def show(label, star):
    p = star.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    racks = {list(d.keys())[0]: (list(d.values())[0].count if hasattr(list(d.values())[0], "count") else list(d.values())[0]) for d in p.available_tips}
    print(f"{label}: available={p.total_available_tips} empty={p.total_empty_tips} consumed={p.total_consumed_tips} missing_racks={p.missing_racks} racks={racks}")


with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id=CARRIER_ID)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id=CARRIER_ID, site="1", tip_pool=TIP_POOL, labware_id="Rack_Tips1000")
    show("after add rack", star)
    star.tip_pool_initialize_tip_counter(TIP_POOL)
    show("after initialize", star)
    star.instrument_init()
    show("after instrument_init", star)
    print("Showing the tip counter dialog -- acknowledge it at the VENUS PC")
    star.tip_pool_show_tip_counter(TIP_POOL)
    print("Dialog acknowledged")
    show("after show tip counter", star)
    try:
        star.tip_pickup(channels=[1, 2, 3, 4, 5, 6, 7, 8], tip_pool=TIP_POOL)
        print("pickup OK")
        star.tip_eject(channels=[1, 2, 3, 4, 5, 6, 7, 8])
    except Exception as exc:
        print("pickup FAILED:", str(exc)[:300])
        show("after failure", star)

print("Done")
