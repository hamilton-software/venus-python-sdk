"""T1 live test: pick up 8 x 1000 uL tips and eject them. No liquid, no plates.

Deck (matches the instrument): tip carrier 480 on track 1 -- site 1 = 1000 uL tips,
sites 2-3 = 300 uL tips, sites 4-5 = 50 uL tips. Only the 1000 uL rack is used.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier"
TIP_POOL = "Tips1000"
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id=CARRIER_ID)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL, carrier_id=CARRIER_ID, site="1", tip_pool=TIP_POOL)
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="2", tip_pool="Tips300A", labware_id="Rack_Tips300A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id=CARRIER_ID, site="3", tip_pool="Tips300B", labware_id="Rack_Tips300B")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="4", tip_pool="Tips50A", labware_id="Rack_Tips50A")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id=CARRIER_ID, site="5", tip_pool="Tips50B", labware_id="Rack_Tips50B")

    # VENUS only trusts a pool's tip counter once it has been shown and confirmed: initialize it,
    # then show it. The dialog appears on the VENUS PC and the script waits until it is acknowledged
    # there (it cannot be answered remotely).
    star.tip_pool_initialize_tip_counter(TIP_POOL)

    star.instrument_init()
    print("Initialized")

    print("Confirm the tip counter dialog at the VENUS PC")
    star.tip_pool_show_tip_counter(TIP_POOL)
    print("Tip counter confirmed")

    star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    print("Picked up 8 x 1000 uL tips")

    star.tip_eject(channels=CHANNELS)
    print("Ejected tips")

print("Done")
