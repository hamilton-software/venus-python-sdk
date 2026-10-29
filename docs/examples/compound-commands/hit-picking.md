# Hit Picking (Compound Command)

Hit Picking is a high-level compound command that transfers samples between
arbitrary source and destination wells based on a CSV-driven worklist. It is the
"cherry pick" workflow: pull only the positive hits from one or more screening
plates onto a consolidation plate, handling tip management and batching
automatically.

Unlike [Copy Plate](./copy-plate.md) (positional same-shape copy) or
[Add Reagent](./add-reagent.md) (one source → many destinations), hit picking is
**many-to-many**: every transfer is a distinct `(source_well, dest_well, volume)`
tuple.

## When to Use

| Command | Shape | Typical use |
|---------|-------|-------------|
| `copy_plate` | Plate → plate, same wells | Replicate a plate |
| `add_reagent` | One source → many wells | Dispense reagent across a plate |
| `hit_picking` | Many wells → many wells | Consolidate selected hits |

## Basic Usage

Hit picking is always driven by a `transfer_csv`. Each row specifies one
transfer with columns `source_labware, source_well, dest_labware, dest_well,
volume`:

```csv
source_labware,source_well,dest_labware,dest_well,volume
ScreenPlate1,A1,HitsPlate,A1,20.0
ScreenPlate1,C4,HitsPlate,B1,20.0
ScreenPlate2,H12,HitsPlate,C1,20.0
```

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
	star.instrument_init()

	result = star.hit_picking(
		transfer_csv="path/to/hits.csv",
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
	print(f"Executed {len(result.transfers)} transfers using {result.tips_consumed} tips")
```

Every row must specify all five columns — there are no parameter-level
fallbacks. All referenced source and destination labware must be on the deck,
and every volume must fit within the tip capacity.

## Tip Management Modes

Hit picking supports three tip-management strategies, selected with the
`change_tips` and `minimize_tips` flags.

### Default — fresh tips per transfer (`change_tips=True`, `minimize_tips=False`)

Transfers are processed in channel-sized chunks; each chunk picks up fresh tips,
runs, and ejects. An 8-channel head fills one column of transfers per cycle.
This is the safest mode (no carryover) and the default.

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)
```

**Tip budget:** one tip per transfer (`len(transfers)`).

### Reuse tips (`change_tips=False`, `minimize_tips=False`)

Tips are picked up once and reused for the entire worklist, with a single eject
at the end. Use this when carryover between transfers is acceptable and you want
to conserve tips.

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	change_tips=False,
)
```

**Tip budget:** `min(len(channels), len(transfers))`.

### Minimize tips — one tip per source well (`minimize_tips=True`)

Transfers are grouped by `(source_labware, source_well)`, and one tip serves
every destination fed by that source well (a single channel per group). This is
ideal when many destinations draw from the same source — the same physical
liquid touches one tip, so there is no source-to-source carryover.

Given this worklist:

```csv
source_labware,source_well,dest_labware,dest_well,volume
ScreenPlate,A1,HitsPlate,A1,20.0
ScreenPlate,A1,HitsPlate,B1,20.0
ScreenPlate,A1,HitsPlate,C1,20.0
ScreenPlate,B1,HitsPlate,D1,30.0
ScreenPlate,C1,HitsPlate,E1,40.0
```

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	minimize_tips=True,
)
print(result.tips_consumed)  # 3 — one tip each for A1, B1, C1
```

**Tip budget:** the number of distinct source wells.

When every row is from a distinct source well, `minimize_tips=True` behaves the
same as the default (one tip per transfer).

### Single-tip mode (`minimize_tips=True`, `change_tips=False`)

Combining `minimize_tips=True` with `change_tips=False` keeps **one tip across
every source well** for the whole worklist. The tip budget collapses to `1`. The
operator accepts the cross-contamination risk, and the command logs a warning at
startup.

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	minimize_tips=True,
	change_tips=False,
)
print(result.tips_consumed)  # 1
```

| `change_tips` | `minimize_tips` | Tip budget |
|---------------|-----------------|------------|
| `True` | `False` | `len(transfers)` |
| `False` | `False` | `min(channels, transfers)` |
| `True` | `True` | distinct source wells |
| `False` | `True` | `1` (warns at startup) |

## Transfer Ordering

By default (`follow_csv_order=False`), transfers are reordered for pipetting
efficiency: grouped by plate, then column-major within each plate (source plate →
source column → source row → dest plate → dest column → dest row). Set
`follow_csv_order=True` to run transfers in exact CSV row order instead:

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	follow_csv_order=True,  # preserve worklist order
)
```

Under `minimize_tips=True`, ordering applies within each source-well group while
keeping the group's destinations in their reordered (or CSV) sequence.

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
	result = star.hit_picking(
		transfer_csv="path/to/hits.csv",
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		tip_pool="TipPool300uL",
	)
```

The callback receives a context object with `tip_pool`, `required`, `available`,
`command` (e.g. `"hit_picking"`), and `attempt`. Return `True` to continue after
the operator reloads; return `False` to abort the run (raising
`OperatorCancelledError`).

## Error Profile

Pass an `ErrorProfile` to use a different error profile for this command:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction

profile = ErrorProfile(
	name="HitPicking_Profile",
	default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
)

result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	error_profile=profile,
)
```

When `error_profile=None` (default), the client's currently active profile is
used. See [Error Handling](../../error_handling.md) for the full
profile/entry/action reference.

## Custom Channels

Use a partial channel set for the chunked modes:

```python
result = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
	channels=[1, 2, 3, 4],
)
```

## Inspecting Results

```python
from hamilton_venus import HitPickingResult

result: HitPickingResult = star.hit_picking(
	transfer_csv="path/to/hits.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	tip_pool="TipPool300uL",
)

print(f"Transfers:         {len(result.transfers)}")
print(f"Iterations:        {result.iterations}")
print(f"Total processed:   {result.total_wells_processed}")
print(f"Tips consumed:     {result.tips_consumed}")
print(f"Source plates:     {result.source_plate_ids}")
print(f"Dest plates:       {result.dest_plate_ids}")
print(f"change_tips:       {result.change_tips}")
print(f"minimize_tips:     {result.minimize_tips}")

for t in result.transfers:
	print(f"  {t.source_plate_id}@{t.source_well} -> {t.dest_plate_id}@{t.dest_well} ({t.volume} uL)")
```

Each entry in `transfers` is a `HitPickingTransferResult` with the source/dest
plate and well, the volume, and the raw `aspirate` / `dispense` responses.
Transfers appear in execution order. A worklist that transfers to the same
destination well twice records two transfer events.

### TADM Curves

Access all pressure-monitoring curves from a run in one call:

```python
for curve in result.tadm_curves:
	print(curve)
```
