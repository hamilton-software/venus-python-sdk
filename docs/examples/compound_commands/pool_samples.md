# Pool Samples (Compound Command)

Pool Samples is a high-level compound command that combines `pool_size` source
wells into a single destination well, one pool at a time. It is the inverse of
[Replicate Samples](./replicate_samples.md) (one source → many destinations) and
distinct from [Copy Plate](./copy_plate.md) (positional same-shape copy) and
[Hit Picking](./hit_picking.md) (CSV-driven many-to-many).

## When to Use

| Command | Shape | Typical use |
|---------|-------|-------------|
| `copy_plate` | Plate → plate, same wells | Replicate a plate |
| `add_reagent` | One source → many wells | Dispense reagent across a plate |
| `pool_samples` | `N` sources → 1 destination (per pool) | Pool replicates or fractions |
| `replicate_samples` | 1 source → `N` destinations (per source) | Aliquot a sample |
| `hit_picking` | Many wells → many wells | Consolidate selected hits |

## Basic Usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
	star.instrument_init()

	result = star.pool_samples(
		source_plate="SourcePlate",
		dest_plate="DestPlate",
		pool_size=4,
		volume_per_source=25.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
	print(f"Executed {result.pools_completed} pools, pooled {result.wells_pooled} wells")
```

`"MyDeck"`, `"SourcePlate"`, `"DestPlate"`, and `"TipPool300uL"` are placeholders for the deck, labware IDs, and tip pool on your system; see [Before You Start](./README.md#before-you-start).

`source_plate` and `dest_plate` accept the same [position selector syntax](../position_and_well_selection.md) used by
other SDK commands. Sources are partitioned in order: the first `pool_size`
selected source wells feed the first selected destination well, the next
`pool_size` feed the second, and so on.

Both also accept a pre-resolved `Position` or `list[Position]` instead of a selector
string (e.g. from [`normalize_positions()`](../position_and_well_selection.md#feeding-normalize_positions-into-compound_commands)):

```python
from hamilton_venus.models import normalize_positions

source_positions = normalize_positions("SourcePlate@all", total_wells=16)
result = star.pool_samples(
	source_plate=source_positions,  # list[Position], not a selector string
	dest_plate="DestPlate@col:1",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)
```

Both arguments also accept a `list[str]` of selectors to span multiple plates:

```python
result = star.pool_samples(
	source_plate=["PlateA@col:1", "PlateB@col:1"],
	dest_plate=["DestA@A1,B1", "DestB@A1,B1"],
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)
```

Channel-row chunks never cross a plate boundary; a pool that spans two source
plates simply emits one aspirate per plate before its single dispense.

## Source / Destination Ordering

By default sources and destinations are traversed in **column-major** order
(`WellOrder.COL_ASC`). Override with the `source_order` or `dest_order` flags
when you need row-major traversal or a custom layout:

```python
from hamilton_venus.models.enums import WellOrder

result = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	source_order=WellOrder.ROW_ASC,
)
```

## Incomplete Final Pool

When the number of selected sources is not a multiple of `pool_size`, the final
pool is partial. For example, 18 sources with `pool_size=4` yields 4 full pools
(of 4) plus one final pool of 2. The destination selector must supply at least
`ceil(num_sources / pool_size)` wells; extra destination wells are ignored.

## Tip Management

### Default — fresh tip per source well (`reuse_tips_within_pool=False`)

Each source well gets its own fresh tip from `tip_pool`. A pool's sources are
processed in channel-row chunks: tips are picked up, the chunk's source wells
are aspirated and dispensed into the destination well, and the tips are ejected
before the next chunk. This is the safest mode (no source-to-source carryover)
and the default.

**Tip budget:** `num_sources` tips (plus one extra per pool when the final mix
runs; see below).

### Reuse tips within pool (`reuse_tips_within_pool=True`)

One tip set (one tip per channel used, up to `pool_size`) is picked up per
destination well and reused for every chunk of source wells feeding that pool,
then ejected after the pool is complete. Use
this when sources within a pool are non-contaminating (e.g. replicate wells of
the same sample).

```python
result = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	reuse_tips_within_pool=True,
)
```

**Tip budget:** `pools * min(len(channels), pool_size)` tips, where `pools` is
`ceil(num_sources / pool_size)`.

| `reuse_tips_within_pool` | Final mix runs | Tip budget |
|--------------------------|----------------|------------|
| `False` | No | `num_sources` |
| `False` | Yes | `num_sources + pools` |
| `True` | No | `pools * min(len(channels), pool_size)` |
| `True` | Yes | `pools * min(len(channels), pool_size)` (the existing tip is reused for the mix) |

## Mix After Pool

When `mix_after_pool=True` (the default), the command performs a single trailing
mix at the destination well after all `pool_size` aspirates have been dispensed.
The mix is driven by the `DispenseSettings.mix_cycles`, `mix_volume`, and
`mix_position` fields. When `mix_cycles` is `0` (default), the
mix step is skipped even with `mix_after_pool=True`, so the final mix runs only
when you pass `dispense_settings` with `mix_cycles > 0`.

```python
from hamilton_venus.models import DispenseSettings

result = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	dispense_settings=DispenseSettings(mix_cycles=3, mix_volume=50.0),
)
```

In `reuse_tips_within_pool=False` mode the command picks up one additional fresh
tip per pool to perform the final mix.

## Operator-Prompted Tip Reload

If the tip pool runs out mid-run, the SDK can pause and ask an operator to
reload. Supply an `on_tip_reload_prompt` callback when constructing `StarClient`:

```python
def on_reload(ctx) -> bool:
	print(f"Please refill tip pool '{ctx.tip_pool}' (need {ctx.required} tips).")
	input("Press Enter when done...")
	return True   # True = continue; False = abort

with StarClient(deck_name="MyDeck", on_tip_reload_prompt=on_reload) as star:
	star.instrument_init()
	result = star.pool_samples(
		source_plate="SourcePlate",
		dest_plate="DestPlate",
		pool_size=4,
		volume_per_source=25.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
```

The callback receives a context object with `tip_pool`, `required`, `available`,
`command` (e.g. `"pool_samples"`), and `attempt`. Return `True` to continue
after the operator reloads; return `False` to abort the run (raising
`OperatorCancelledError`).

## Error Profile

Pass an `ErrorProfile` to use a different profile for this command:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction

profile = ErrorProfile(
	name="PoolSamples_Profile",
	default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
)

result = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	error_profile=profile,
)
```

When `error_profile=None` (default), the client's currently active profile is
used. See [Error Handling](../../error_handling.md) for the full
profile/entry/action reference.

## Custom Channels

Restrict the operation to a subset of channels:

```python
result = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	channels=[1, 2, 3, 4],
)
```

`pool_size` may exceed `len(channels)`: a pool's source wells are aspirated in
channel-row chunks of up to `len(channels)` wells, each dispensed into the same
destination well.

## Inspecting Results

```python
from hamilton_venus import PoolSamplesResult

result: PoolSamplesResult = star.pool_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	pool_size=4,
	volume_per_source=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)

print(f"Pools:             {result.pools_completed}")
print(f"Wells pooled:      {result.wells_pooled}")
print(f"Iterations:        {result.iterations}")
print(f"Source plates:     {result.source_plate_ids}")
print(f"Dest plates:       {result.dest_plate_ids}")
print(f"mix_after_pool:    {result.mix_after_pool}")
print(f"reuse_tips:        {result.reuse_tips_within_pool}")

for i, pool in enumerate(result.iteration_results):
	print(f"  Pool {i}: {pool.source_plate_ids} {pool.source_wells} -> "
	      f"{pool.dest_plate_id}@{pool.dest_well}")
```

Each entry in `iteration_results` is a `PoolSamplesIterationResult` carrying the
source wells, destination well, raw `aspirates` / `dispenses` responses, the
optional `mix_after` dispense response, and `tip_pickups` / `tip_ejects`
covering the pool.

### TADM Curves

Access all pressure-monitoring curves from a run in one call:

```python
for curve in result.tadm_curves:
	print(curve)
```
