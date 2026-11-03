"""Live test: tip pickup from a tip rack that is in the layout but NOT physically on the deck.

The layout puts a tip carrier 480 with a 1000 uL rack on track 20; nothing is loaded there on the instrument, so the
8-channel pickup fails with a real "No tip picked up" instrument error. Unlike the autoload error (which has no
error-profile rule), tip pickup has one, so the SDK first repeats automatically and only then escalates -- with no
operator token it defers to VENUS's own operator dialog, which is what this test is meant to show.

The tip counter is initialized and reset, and then shown (VENUS only hands out tips from a pool once its counter has been
shown and confirmed at the VENUS PC; leave every tip marked present).
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

CARRIER_ID = "TipCarrier20"
TIP_POOL = "Tips1000"
CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=20, labware_id=CARRIER_ID)
    star.add_tip_rack(
        labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
        carrier_id=CARRIER_ID,
        site="1",
        tip_pool=TIP_POOL,
        labware_id="Rack_Tips1000_T20",
    )

    star.tip_pool_initialize_tip_counter(TIP_POOL)
    star.tip_pool_reset_tip_counter(TIP_POOL)

    star.instrument_init()
    print("Initialized")

    print("Confirm the tip counter dialog at the VENUS PC (leave every tip marked present)")
    star.tip_pool_show_tip_counter(TIP_POOL)
    print("Tip counter confirmed")

    print("Picking up 8 tips from a rack that is not on the deck -- an error is expected")
    star.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    print("Picked up 8 tips")

    star.tip_eject(channels=CHANNELS)
    print("Ejected tips")

print("Done")
