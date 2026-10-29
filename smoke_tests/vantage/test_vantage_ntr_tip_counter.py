"""Smoke test: restoring an NTR tip pool with tip_pool_set_tip_counter (Vantage).

Two nested tip racks are stacked on one site of an NTR carrier, and the tip
counter is set with the bottom rack full and:

- the top rack listed with ``positions: []`` -- on the deck but empty. The next
  pickup from the pool moves the empty top rack to the NTR waste with the
  CO-RE gripper and picks up from the rack below.
- the top rack left out -- missing, already taken away. The next pickup comes
  straight from the rack below.

The tip counter tracks which racks are present. The deck layout keeps every
rack the stack was built with, since tip management needs the full stack to
reload and rearrange NTRs, so neither case changes the labware on the carrier.

The empty-rack flow runs in two sessions with the same tip pool and rack names,
because the pool's state carries over between sessions: the reset at the start
of the second session must replace what the first one left behind.

The NTR carrier sits on track 10 so the channels reach the NTR waste.
"""
from hamilton_venus import VantageClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import EjectMode

NTR_CARRIER_ID = "NtrCarrier"
TIP_POOL = "ntr_empty_top"
LABWARE_ID = "EmptyTopNTR"
ALL_POSITIONS = [str(i) for i in range(1, 97)]


def rack_counts(entries) -> dict[str, int]:
    return {name.lower(): len(state.positions) for entry in entries for name, state in entry.items()}


def build_stack(vantage: VantageClient) -> tuple[str, str]:
    """Two racks on site 1, the pool reset to full; returns (bottom, top)."""
    vantage.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_NTR,
        left_track=10,
        labware_id=NTR_CARRIER_ID,
    )
    ntr = vantage.add_ntr(
        labware_definition=LABWARE.TIP_RACK.TIP_NESTED_300UL,
        carrier_id=NTR_CARRIER_ID,
        site="1",
        stack=2,
        tip_pool=TIP_POOL,
        labware_id=LABWARE_ID,
    )
    bottom, top = ntr.return_parameters.labware_name
    print(f"1. Stack added, bottom to top: {bottom}, {top}")

    vantage.tip_pool_reset_tip_counter(TIP_POOL)
    counter = vantage.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    print(f"2. After reset: {rack_counts(counter.available_tips)}, missing={counter.missing_racks}")
    assert rack_counts(counter.available_tips) == {bottom: 96, top: 96}
    assert counter.missing_racks == []
    return bottom, top


def pick_up_from_bottom_rack(vantage: VantageClient, bottom: str, top: str) -> None:
    vantage.instrument_init()
    pickup = vantage.tip_pickup(tip_pool=TIP_POOL, channels=[1, 2])
    print(f"4. Tip pickup: {pickup.model_dump(by_alias=True)['returnParameters']}")

    counter = vantage.tip_pool_get_tip_counter(TIP_POOL).return_parameters
    print(f"5. After pickup: available={rack_counts(counter.available_tips)}, missing={counter.missing_racks}")
    assert rack_counts(counter.available_tips) == {bottom: 94}, "Tips should come from the bottom rack"
    assert counter.missing_racks == [top], "The top rack should be gone"

    vantage.tip_eject(eject_mode=EjectMode.WASTE)
    print("6. Tips ejected to waste")


def run_empty_top_rack(session: int) -> None:
    with VantageClient(simulate=True) as vantage:
        print(f"\n=== Empty top rack, session {session} ===")
        bottom, top = build_stack(vantage)

        vantage.tip_pool_set_tip_counter(TIP_POOL, available_tips=[
            {bottom: {"count": 96, "positions": ALL_POSITIONS}},
            {top: {"count": 0, "positions": []}},
        ])
        counter = vantage.tip_pool_get_tip_counter(TIP_POOL).return_parameters
        print(f"3. Top rack set empty: available={rack_counts(counter.available_tips)}, "
              f"empty={rack_counts(counter.empty_tips)}, missing={counter.missing_racks}")
        assert rack_counts(counter.available_tips) == {bottom: 96}
        assert rack_counts(counter.empty_tips) == {top: 96}, "Top rack should be on the deck and empty"
        assert counter.missing_racks == [], "Top rack should not be missing"

        # The pickup first tosses the empty top rack to the NTR waste.
        pick_up_from_bottom_rack(vantage, bottom, top)


def run_top_rack_left_out() -> None:
    with VantageClient(simulate=True) as vantage:
        print("\n=== Top rack left out ===")
        bottom, top = build_stack(vantage)

        vantage.tip_pool_set_tip_counter(TIP_POOL, available_tips=[
            {bottom: {"count": 96, "positions": ALL_POSITIONS}},
        ])
        counter = vantage.tip_pool_get_tip_counter(TIP_POOL).return_parameters
        print(f"3. Top rack left out: available={rack_counts(counter.available_tips)}, missing={counter.missing_racks}")
        assert rack_counts(counter.available_tips) == {bottom: 96}
        assert counter.missing_racks == [top], "Top rack should be missing"

        pick_up_from_bottom_rack(vantage, bottom, top)


try:
    run_empty_top_rack(1)
    run_empty_top_rack(2)
    run_top_rack_left_out()
    print("\nNTR Tip Counter Smoke Test Complete")
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
