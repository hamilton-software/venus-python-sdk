"""Show the tip counter dialog for one, several, or every tip pool.

Builds a deck with two tip pools (300 uL and 50 uL tips), then demonstrates
``tip_pool_show_tip_counters``:

1. With no ``tip_pools`` argument -- shows every tip pool.
2. With an explicit ``tip_pools`` list -- shows only the named pools.

Both calls pop VENUS's own tip counter dialog and **block until an operator
closes it** (the command timeout is disabled for this call specifically,
since the wait can otherwise take arbitrarily long depending on the user) --
so this script will hang waiting for a click if run against a live VENUS
instance rather than just inspected/read. The response itself is available
as soon as the dialog closes; see ``ShowTipCountersResponse`` /
``TipCounterSummary`` in ``hamilton_venus.models``.
"""

from __future__ import annotations

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK_300UL = LABWARE.TIP_RACK.TIP_RACK_300UL
TIP_RACK_50UL = LABWARE.TIP_RACK.TIP_RACK_50UL

TIP_POOL_300 = "300 uL Tips"
TIP_POOL_50 = "50 uL Tips"


def print_tip_counters(result) -> None:
    for counter in result.return_parameters.tip_counters:
        print(f"  {counter.tip_counter}: {counter.total_available_tips} available tip(s)")
        for rack_id, rack in counter.available_tips.items():
            print(f"    {rack_id}: {rack.count} tip(s) at {rack.positions}")
        if counter.missing_racks:
            print(f"    missing racks: {counter.missing_racks}")


with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
    star.add_tip_rack(
        labware_definition=TIP_RACK_300UL,
        carrier_id="TipCarrier",
        site="1",
        tip_pool=TIP_POOL_300,
    )
    star.add_tip_rack(
        labware_definition=TIP_RACK_50UL,
        carrier_id="TipCarrier",
        site="2",
        tip_pool=TIP_POOL_50,
    )

    star.instrument_init()

    print("Showing every tip counter (close the VENUS dialog to continue)...")
    all_counters = star.tip_pool_show_tip_counters()
    print_tip_counters(all_counters)

    print(f"\nShowing only {TIP_POOL_300!r} (close the VENUS dialog to continue)...")
    one_counter = star.tip_pool_show_tip_counters(tip_pools=[TIP_POOL_300])
    print_tip_counters(one_counter)

print("Done")
