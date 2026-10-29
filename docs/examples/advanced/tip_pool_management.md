# Tip Pool Management

Practical patterns for querying and updating tip pool counters.

## Overview

This guide covers:
- querying tip counter names and per-pool status
- inspecting structured available-tip and missing-rack data
- resetting and initializing counters
- updating counters with the grouped rack structure expected by the backend

---

## Query a Tip Pool

```python
from hamilton_venus import StarClient

with StarClient() as star:
    counter = star.tip_pool_get_tip_counter(tip_pool="TransferTips")

    print(counter.return_parameters.total_available_tips)
    print(counter.return_parameters.available_tips)
    print(counter.return_parameters.missing_racks)
```

## Query All Tip Counter Names

```python
from hamilton_venus import StarClient

with StarClient() as star:
    counters = star.tip_pool_get_tip_counters()
    print(counters.return_parameters.tip_counter_names)
```

## Query Structured Available Tips

```python
from hamilton_venus import StarClient

with StarClient() as star:
    available = star.tip_pool_get_available_tips(tip_pool="TransferTips")

    print(available.return_parameters.total_available_tips)
    print(available.return_parameters.available_tips)
```

## Query Empty Tips and Missing Racks

```python
from hamilton_venus import StarClient

with StarClient() as star:
    empty = star.tip_pool_get_empty_tips(tip_pool="TransferTips")
    missing = star.tip_pool_get_missing_racks(tip_pool="TransferTips")

    print(empty.return_parameters)
    print(missing.return_parameters.missing_racks)
```

---

## Initialize or Reset a Tip Counter

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.tip_pool_initialize_tip_counter("TransferTips")
    star.tip_pool_reset_tip_counter("TransferTips")
```

---

## Set a Tip Counter with Grouped Rack Data

`tip_pool_set_tip_counter()` replaces the whole state of the pool. Each entry names one rack (its
labware id) and lists the positions that hold a tip:

- A **listed rack** is present and holds exactly the listed tips; its other positions are empty.
- A rack listed with **`positions: []`** is on the deck but empty.
- A rack **left out** is marked *missing*: not on the deck, as after it has been transported away.
  `missing_racks` reports it and pickups skip it.
- `count` is not used: the positions are the state.

```python
from hamilton_venus import StarClient

ALL = [str(i) for i in range(1, 97)]
AVAILABLE_TIPS = [
    {"tip_rack_300ul_0001": {"count": 86, "positions": ALL[10:]}},  # positions 1-10 used
    {"tip_rack_300ul_0002": {"count": 96, "positions": ALL}},
]

with StarClient() as star:
    star.tip_pool_set_tip_counter(
        tip_pool="TransferTips",
        available_tips=AVAILABLE_TIPS,
    )
```

Rack names are lowercase labware ids, as `add_tip_rack`/`add_ntr` return them in `labware_name` and
as `tip_pool_get_available_tips` keys them.

### Restore a known state onto an NTR pool

The racks of a nested tip rack (NTR) stack are in the pool from the bottom of the stack to the top.
The tip counter, not the deck layout, tracks which of them are still there: tip management moves
NTRs itself (it tosses an empty top rack to the NTR waste, and consolidates partial racks when, say,
the MPH96 needs a full 96 tips), and it needs every rack the stack was built with to do that. So
build the deck with the full stacks, and refill or restore a pool by changing its tip counter, with
`tip_pool_set_tip_counter` or the `tip_pool_show_tip_counter` dialog. Don't remove racks from the
deck (`remove_labware`) or build smaller stacks to match.

- **A rack with tips**: list its exact positions.
- **An empty rack that is still on the stack**: list it with `positions: []`. When it is the top
  rack, the next pickup from the pool moves it to the NTR waste with the CO-RE gripper, then picks
  up from the rack below.
- **A rack that has been taken away**, such as a stack's top rack: leave it out. Pickups continue
  from the rack below.

```python
ALL = [str(i) for i in range(1, 97)]

# Two racks stacked on one site: tip_nested_300ul_0001 (bottom), tip_nested_300ul_0002 (top).
star.tip_pool_set_tip_counter("NtrTips", [
    {"tip_nested_300ul_0001": {"count": 96, "positions": ALL}},
    {"tip_nested_300ul_0002": {"count": 0, "positions": []}},  # empty, still on the stack
])
star.tip_pickup(tip_pool="NtrTips", channels=[1, 2])  # tosses _0002, picks up from _0001
```

---

## Tip Pool State Persists Between Sessions

VENUS keeps a tip pool's state from one session to the next. Building the deck again with the **same
tip pool name and the same rack names** picks up where the last session left off, even when a rack is
placed on a different site: the state follows the rack name. A different pool name, or different rack
names, starts with full racks.

Rack names come from `labware_id`, or, without one, from the order the racks are added
(`tip_rack_300ul_0001`, ...). A script that relies on the carried-over state should give its racks
fixed `labware_id`s. To start a run with full racks, reset the pool after building the deck; the
reset replaces the carried-over state, so a `tip_pool_set_tip_counter` after it starts from full racks:

```python
with StarClient() as star:
    # ... add carriers and tip racks ...
    star.tip_pool_reset_tip_counter("TransferTips")
```

---

## Production Check: Warn When Tip Supply Is Low

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def warn_if_low(star: StarClient, tip_pool: str, threshold: int = 50) -> bool:
    available = star.tip_pool_get_available_tips(tip_pool)
    total = available.return_parameters.total_available_tips

    if total < threshold:
        logger.warning("Low tips in %s: %s", tip_pool, total)
        return False

    logger.info("Tip pool %s has %s tips available", tip_pool, total)
    return True


with StarClient() as star:
    warn_if_low(star, "TransferTips", threshold=100)


