"""T3 live test: cause a safe, recoverable error -- tip positions VENUS believes are full but are empty.

Deck (matches the instrument): tip carrier 480 on track 1 -- site 1 = 1000 uL tips (first positions already
used by earlier tests), sites 2-3 = 300 uL, sites 4-5 = 50 uL. The tip counter is initialized and reset so VENUS
thinks the 1000 uL rack is full; the 8-channel pickup then finds empty positions and VENUS raises a tip error.
No liquid, no plates.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier"
TIP_POOL = "Tips1000"
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id=CARRIER_ID)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id=CARRIER_ID, site="1", tip_pool=TIP_POOL, labware_id="Rack_Tips1000")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="2", tip_pool="Tips300A", labware_id="Rack_Tips300A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="3", tip_pool="Tips300B", labware_id="Rack_Tips300B")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="4", tip_pool="Tips50A", labware_id="Rack_Tips50A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="5", tip_pool="Tips50B", labware_id="Rack_Tips50B")

    # Make VENUS believe the rack is full again (the first positions are physically empty).
    star.tip_pool_initialize_tip_counter(TIP_POOL)
    star.tip_pool_reset_tip_counter(TIP_POOL)

    star.instrument_init()
    print("Initialized")

    # Confirm at the VENUS PC WITHOUT marking any tips as missing: the counter must keep saying "full".
    print("Confirm the tip counter dialog at the VENUS PC (leave every tip marked present)")
    star.tip_pool_show_tip_counter(TIP_POOL)
    print("Tip counter confirmed")

    print("Picking up 8 tips from positions that are empty -- an error is expected")
    star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    print("Picked up 8 tips")

    star.tip_eject(channels=CHANNELS)
    print("Ejected tips")

print("Done")
