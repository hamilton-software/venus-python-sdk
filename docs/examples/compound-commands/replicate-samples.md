# Replicate Samples (Compound Command)

Replicate Samples is a high-level compound command that aliquots each selected
source well into `replicates_per_source` destination wells. It is the inverse
of [Pool Samples](./pool-samples.md) (many sources → one destination) and is
optimized for the "split one sample into many replicates" workflow.

## When to Use

| Command | Shape | Typical use |
|---------|-------|-------------|
| `add_reagent` | One source → many wells | Dispense a shared reagent |
| `replicate_samples` | 1 source → `N` destinations (per source) | Aliquot per-source replicates |
| `pool_samples` | `N` sources → 1 destination (per pool) | Pool replicates or fractions |
| `copy_plate` | Plate → plate, same wells | Replicate a plate |
| `hit_picking` | Many wells → many wells | Consolidate selected hits |

Use `replicate_samples` when every source has the **same number of replicates**
going to its **own block** of destination wells. For mixed source/destination
worklists, use [Hit Picking](./hit-picking.md).

## Basic Usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
	star.instrument_init()

	result = star.replicate_samples(
		source_plate="SourcePlate",
		dest_plate="DestPlate",
		replicates_per_source=3,
		volume_per_replicate=25.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
	print(f"Filled {result.replicates_filled} replicates "
	      f"from {result.sources_processed} sources")
```

`source_plate` and `dest_plate` accept the same [position selector syntax](../position-and-well-selection.md) used by
other SDK commands. Destinations are partitioned in order: the first source's
replicates go to the first `replicates_per_source` destination wells, the
second source's replicates go to the next block, and so on.

Both also accept a pre-resolved `Position` or `list[Position]` instead of a selector
string (e.g. from [`normalize_positions()`](../position-and-well-selection.md#feeding-normalize_positions-into-compound-commands)):

```python
from hamilton_venus.models import normalize_positions

dest_positions = normalize_positions("DestPlate@all", total_wells=12)
result = star.replicate_samples(
	source_plate="SourcePlate@col:1",
	dest_plate=dest_positions,  # list[Position], not a selector string
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)
```

Both arguments also accept a `list[str]` of selectors to span multiple plates:

```python
result = star.replicate_samples(
	source_plate=["PlateA@A1,B1,C1,D1", "PlateB@A1,B1,C1,D1"],
	dest_plate=["DestA@col:1,2", "DestB@col:1,2"],
	replicates_per_source=3,
	volume_per_replicate=20.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)
```

Channel-row chunks never cross a plate boundary on the **source** side. In
multi-dispense mode a single source's replicates may still fan out across multiple
destination plates without a re-aspirate; in single-dispense mode chunks split on
either source- or destination-plate boundary.

## Source / Destination Ordering

By default sources and destinations are traversed in **column-major** order
(`WellOrder.COL_ASC`). Use `source_order` / `dest_order` to switch to row-major
or another layout:

```python
from hamilton_venus.models.enums import WellOrder

result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	dest_order=WellOrder.ROW_ASC,
)
```

## single-dispense vs multi-dispense Dispense

| Mode | Behaviour | Tip budget |
|------|-----------|------------|
| `multi_dispense=True` (default) | One aspirate per source feeds every replicate destination in sequence. Auto-splits when per-source volume exceeds tip capacity. | `num_sources` tips |
| `multi_dispense=False` | Each `(source, dest)` transfer is its own aspirate + dispense; fresh tip per channel-row chunk. | `num_sources * replicates_per_source` tips |

### multi-dispense mode

```python
result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	multi_dispense=True,  # default
)
```

In multi-dispense mode the command aspirates
`replicates_per_source * volume_per_replicate` (plus optional pre/post-aliquot
volumes) and dispenses sequentially into each destination. If that total
exceeds the available tip capacity, the source is **auto-split** across
multiple aspirations: each batch fills as many replicates as the tip can hold
(`reps_per_batch = floor(net_capacity / volume_per_replicate)`).

### single-dispense mode

```python
result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	multi_dispense=False,
)
```

single-dispense mode runs every `(source, dest)` transfer as its own aspirate + dispense
cycle. The transfers are processed in channel-sized chunks; each chunk uses
fresh tips.

## Pre-aliquot and Post-aliquot (multi-dispense mode)

A pre-aliquot dispense primes the tip and a post-aliquot dispense flushes it
after the last replicate. Both are multi-dispense mode only.

```python
from hamilton_venus.models.enums import PreAliquotDisposal

result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	pre_aliquot_volume=10.0,
	pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
	post_aliquot_volume=5.0,
	post_aliquot_height=5.0,
)
```

`PreAliquotDisposal` values:

| Value | Behaviour |
|-------|-----------|
| `SOURCE` | Dispense pre-aliquot back to the source well |
| `WASTE` | Dispense pre-aliquot to the deck waste location |

When using `PreAliquotDisposal.WASTE`, the deck must include a labware named
`liquid_waste` (or equivalent — see [Add Reagent](./add-reagent.md#pre-aliquot-and-post-aliquot-multi-mode)
for the deeper aliquot discussion). The post-aliquot dispense always goes back
to the **last** replicate destination at `post_aliquot_height` mm above its
bottom.

When auto-split kicks in, only the **first** batch carries the pre-aliquot and
only the **last** batch carries the post-aliquot.

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
	result = star.replicate_samples(
		source_plate="SourcePlate",
		dest_plate="DestPlate",
		replicates_per_source=3,
		volume_per_replicate=25.0,
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
```

The callback receives a context object with `tip_pool`, `required`, `available`,
`command` (e.g. `"replicate_samples"`), and `attempt`. Return `True` to
continue after the operator reloads; return `False` to abort the run.

## Error Profile

Pass an `ErrorProfile` to use a different profile for this command:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction

profile = ErrorProfile(
	name="ReplicateSamples_Profile",
	default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
)

result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
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
result = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	channels=[1, 2, 3, 4],
)
```

Sources are processed in chunks of up to `len(channels)` per cycle.

## Inspecting Results

```python
from hamilton_venus import ReplicateSamplesResult

result: ReplicateSamplesResult = star.replicate_samples(
	source_plate="SourcePlate",
	dest_plate="DestPlate",
	replicates_per_source=3,
	volume_per_replicate=25.0,
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)

print(f"Sources processed: {result.sources_processed}")
print(f"Replicates filled: {result.replicates_filled}")
print(f"Iterations:        {result.iterations}")
print(f"multi_dispense:    {result.multi_dispense}")
print(f"Source plates:     {result.source_plate_ids}")
print(f"Dest plates:       {result.dest_plate_ids}")

for it in result.iteration_results:
	print(f"  {it.source_plate_id}@{it.source_well} -> "
	      f"{it.dest_plate_id}@{it.dest_wells} "
	      f"(aspirates={len(it.aspirates)}, dispenses={len(it.replicate_dispenses)})")
```

In `multi_dispense=True` mode each entry in `iteration_results` is one source
well; `aspirates` and `replicate_dispenses` may contain multiple elements when
auto-split is in effect, and `pre_aliquot_dispense` / `post_aliquot_dispense`
are populated when the corresponding aliquot is configured. In
`multi_dispense=False` mode each entry is a single `(source, dest)` transfer
with one aspirate, one dispense, and `None` aliquot fields.

### TADM Curves

Access all pressure-monitoring curves from a run in one call (with multi-channel
responses automatically deduplicated by identity):

```python
for curve in result.tadm_curves:
	print(curve)
```
