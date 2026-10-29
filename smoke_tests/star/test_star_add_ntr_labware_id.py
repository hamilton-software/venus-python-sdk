"""Smoke test for add_ntr with a labware_id and a stack of more than one rack.

Every rack in an NTR stack needs its own name. With a labware_id, VENUS names
them from it with a counter suffix (``namedntr_0001``, ``namedntr_0002``, ...),
continuing across stacks that share the labware_id. Before that, every rack
got the labware_id itself and the second one failed with "Tip Rack ... is
already loaded on the deck!".

Builds two named stacks of three, checks the names and that the tip pool holds
exactly those racks, then picks up tips from the pool and ejects them to waste.
"""
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import EjectMode

NTR_CARRIER_ID = "NtrNamed"
TIP_POOL = "probe_named"
LABWARE_ID = "NamedNTR"
STACK = 3


def rack_names(response) -> list[str]:
    names = response.return_parameters.labware_name
    return [names] if isinstance(names, str) else list(names)


try:
    with StarClient(simulate=True) as star:
        print("Connected - method is running")

        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_NTR,
            left_track=1,
            labware_id=NTR_CARRIER_ID,
        )
        print("Carrier added")

        print(f"\n1. Add a stack of {STACK} with labware_id={LABWARE_ID!r} (site 1)")
        first = star.add_ntr(
            labware_definition=LABWARE.TIP_RACK.TIP_NESTED_300UL,
            carrier_id=NTR_CARRIER_ID,
            site="1",
            stack=STACK,
            tip_pool=TIP_POOL,
            labware_id=LABWARE_ID,
        )
        print(f"   Response: {first.model_dump(by_alias=True)}")
        first_names = rack_names(first)
        expected_first = [f"{LABWARE_ID.lower()}_{n:04d}" for n in range(1, STACK + 1)]
        assert first_names == expected_first, f"Expected {expected_first}, got {first_names}"
        assert first.return_parameters.tip_pool_name.lower() == TIP_POOL.lower()

        print("\n2. Add a second stack with the same labware_id (site 2)")
        second = star.add_ntr(
            labware_definition=LABWARE.TIP_RACK.TIP_NESTED_300UL,
            carrier_id=NTR_CARRIER_ID,
            site="2",
            stack=STACK,
            tip_pool=TIP_POOL,
            labware_id=LABWARE_ID,
        )
        print(f"   Response: {second.model_dump(by_alias=True)}")
        second_names = rack_names(second)
        expected_second = [f"{LABWARE_ID.lower()}_{n:04d}" for n in range(STACK + 1, 2 * STACK + 1)]
        assert second_names == expected_second, f"Expected {expected_second}, got {second_names}"

        print("\n3. The tip pool holds exactly the named racks, all full")
        # The pool's state carries over from earlier sessions; start from full racks.
        star.tip_pool_reset_tip_counter(TIP_POOL)
        available = star.tip_pool_get_available_tips(TIP_POOL).return_parameters
        pool_racks = sorted(name.lower() for entry in available.available_tips for name in entry)
        print(f"   {available.total_available_tips} tips in {pool_racks}")
        assert pool_racks == sorted(first_names + second_names), f"Pool racks: {pool_racks}"
        assert available.total_available_tips == 2 * STACK * 96

        star.instrument_init()
        print("\nInitialization complete")

        print(f"\n4. Pick up + eject to waste from {TIP_POOL!r}")
        pickup = star.tip_pickup(tip_pool=TIP_POOL, channels=[1, 2])
        print(f"   Tip pickup response: {pickup.model_dump(by_alias=True)}")
        eject = star.tip_eject(eject_mode=EjectMode.WASTE)
        print(f"   Tip eject response: {eject.model_dump(by_alias=True)}")

        print("\nadd_ntr labware_id Smoke Test Complete - Disconnecting")
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
