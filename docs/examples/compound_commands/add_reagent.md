# Add Reagent (Compound Command)

Add Reagent is a high-level compound command that dispenses a reagent from one or more source locations into destination wells, handling tip management and multi-dispense batching automatically.

## Basic Usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
	star.instrument_init()

	result = star.add_reagent(
		reagent_source="ReagentTrough",
		dest_plate="DestPlate",
		volume=50.0,
		tip_pool="TipPool300uL",
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)
	print(f"Filled {result.wells_filled} wells in {result.iterations} iterations")
```

`"MyDeck"`, `"ReagentTrough"`, `"DestPlate"`, and `"TipPool300uL"` are placeholders for the deck, labware IDs, and tip pool on your system; see [Before You Start](./README.md#before-you-start).
`reagent_source` and `dest_plate` accept the same [position selector syntax](../position_and_well_selection.md) used by other SDK commands:

| Syntax | Meaning |
|--------|---------|
| `"Trough"` | All wells of the named labware |
| `"Trough@col:1"` | Column 1 only |
| `"Trough@col:1,2"` | Columns 1 and 2 |
| `"Trough@row:A"` | Row A only |
| `"Trough@wells:A1,B1"` | Specific wells |

Both also accept a pre-resolved `Position` or `list[Position]` (e.g. from
[`normalize_positions()`](../position_and_well_selection.md#feeding-normalize_positions-into-compound_commands))
instead of a selector string -- useful when the target wells don't correspond to a
single selector expression, such as capping a plate to an exact sample count with
`total_wells`:

```python
from hamilton_venus.models import normalize_positions, WellOrder

target_positions = normalize_positions("DestPlate@all", well_order=WellOrder.COL_ASC, total_wells=17)
result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate=target_positions,  # list[Position], not a selector string
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)
```

## Multi-Plate Selectors

Both `reagent_source` and `dest_plate` accept either a single selector string or a `list[str]` of selectors to span multiple plates in one call:

```python
# Broadcast: one reagent source -> two destination plates
result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate=["PlateA@col:1,2", "PlateB@col:1,2"],
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)

# Index-wise: N sources paired with N destinations
result = star.add_reagent(
	reagent_source=["TroughA", "TroughB"],
	dest_plate=["PlateA@col:1", "PlateB@col:1"],
	volume=40.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)
```

Pairing rules when `reagent_source` is a list:

| Sources | Destinations | Behaviour |
|---------|--------------|-----------|
| 1 selector | N selectors | The source is broadcast to every destination selector |
| N selectors | N selectors | Each source selector is paired with the destination at the same index |
| Otherwise | Otherwise | `ValueError` |

A "1 selector" source can be either a bare string (`reagent_source="Trough"`) or a single-element list (`reagent_source=["Trough"]`) — both trigger broadcast behaviour when `dest_plate` is a multi-entry list.

Channel-row chunks never cross a plate boundary, so each aspirate/dispense pair targets a single plate.

With `transfer_csv`, `dest_plate` must be a single string (the default for rows without a `dest_labware`); `reagent_source` can be anything above, and is the drain order for every row (see [Worklist-Driven Volumes](#worklist-driven-volumes)).

## Reagent Sources: Tubes, Wells and Reservoirs

`reagent_source` says which containers hold the reagent, and **every channel is used** on them. The channels are spread across the selected positions, in passes when there are more channels than positions -- two channels can never share a tube:

| `reagent_source` | 8 channels aspirate from |
|------------------|--------------------------|
| `"Tubes@1"` | tube 1, each channel in turn (8 passes) |
| `"Tubes@1:4"` | tubes 1-4 with channels 1-4, then tubes 1-4 with channels 5-8 (2 passes) |
| `"Tubes@1:8"` | tubes 1-8, one per channel (1 pass) |
| `"Trough"` or `"Trough@1"` (8-section reservoir) | sections 1-8, one per channel -- see [Connected-Container Sources](#connected-container-sources-multi-channel-aspiration) |

Pre/post-aliquots returned to the source use the same passes, so each channel returns to the container it drew from.

### Draining several sources in order (Consumable Liquid Management)

With a worklist (`transfer_csv`), `reagent_source` can be a **list** of such selectors. Each entry is one source, and the entries are used one after another as each runs out. (Without a worklist, a list is paired with `dest_plate` instead -- see [Multi-Plate Selectors](#multi-plate-selectors).)

| `reagent_source` | What each stroke draws from |
|------------------|-----------------------------|
| `["Tubes@1", "Tubes@2", "Tubes@3", "Tubes@4"]` | one tube: every channel in turn at tube 1 until it runs low, then tube 2, then 3, then 4 |
| `["Tubes@1:4", "Tubes@5:8"]` | four tubes: tubes 1-4 (channels 1-4, then 5-8) until they run low, then tubes 5-8 |
| `"Tubes@1:4"` | all four tubes every stroke, never switching -- one source, not a drain order |

The list of single tubes empties one tube at a time, at the cost of one aspirate per channel on every stroke; `"Tubes@1:4"` draws the four tubes down together in two aspirates per 8-channel stroke.

Moving on to the next source needs a **measured** level (LLD on -- see below): without it the first source is used for the whole run.

The SDK tracks the reagent reactively: it reads the measured per-channel liquid volume after each aspirate (the minimum across channels) and moves to the next source only **between** aspirations. When every source is exhausted the `on_liquid_reload_prompt` callback is invoked so an operator can refill or replace the container. With no callback configured the run carries on: the shortage is logged as a warning and recorded as a `liquid_shortage` entry in the run log, and the estimate starts over from the next measured aspirate.

Only aspirates with liquid level detection on (capacitive or pressure LLD in `aspirate_settings`) count as measurements. Without LLD, VENUS reports the fixed aspirate height instead of a level, so those readings are ignored and the sources are never considered used up.

```python
from hamilton_venus.models import AspirateSettings
from hamilton_venus.models.enums import CapacitiveLLD

def on_reload(ctx) -> bool:
	print(f"Refill {ctx.active_source}: need {ctx.required} uL, {ctx.available} uL left")
	input("Press Enter when refilled...")
	return True  # return False to cancel (raises OperatorCancelledError)

star.on_liquid_reload_prompt = on_reload

result = star.add_reagent(
	reagent_source=["Tubes@1", "Tubes@2", "Tubes@3", "Tubes@4"],  # tube 1 until low, then 2, 3, 4
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	aspirate_settings=AspirateSettings(capacitive_lld=CapacitiveLLD.MID),
	transfer_csv="path/to/worklist.csv",
)
print(f"Sources used: {result.sources_used}")  # e.g. ('Tubes@1', 'Tubes@2')
```

## single-dispense vs multi-dispense Dispense

By default (`multi_dispense=False`) the command operates in **single-dispense** mode: a fresh tip set is picked up for each channel-row chunk, and each destination well receives its own aspirate + dispense cycle.

Enable **multi-dispense** mode to aspirate enough for several destination wells in one stroke and dispense sequentially; tips are picked up once per source/destination pairing, reducing total tip pickups:

```python
result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	multi_dispense=True,
)
```

### Pre-aliquot and Post-aliquot

A pre-aliquot dispense primes the tip after each aspiration, before the first destination well, and a post-aliquot is returned to the source after the last destination well. Both work in single-dispense and multi-dispense mode; their volumes are added to every aspiration:

```python
from hamilton_venus.models.enums import PreAliquotDisposal

result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	multi_dispense=True,
	pre_aliquot_volume=10.0,
	pre_aliquot_disposal=PreAliquotDisposal.SOURCE,  # dispense back to source
	post_aliquot_volume=5.0,
	post_aliquot_height=5.0,  # fixed height (mm) for the post-aliquot dispense back into the source
)
```

`PreAliquotDisposal` values:

| Value | Behaviour |
|-------|-----------|
| `SOURCE` | Dispense pre-aliquot back to the source well |
| `WASTE` | Dispense pre-aliquot to the `liquid_waste` labware, which must be on the deck |

## Reusing Tips

By default (`reuse_tips=False`) a fresh tip set is picked up and ejected for **each channel-row chunk** (single-dispense) or **each source/destination pairing** (multi-dispense). For workflows where cross-contamination between chunks is not a concern (a single reagent dispensed into many wells), set `reuse_tips=True` to pick up **one** tip set before the run and eject it once after all chunks — across every source, destination, and plate in the call:

```python
result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	reuse_tips=True,
)
```

`reuse_tips` works in both single-dispense and multi-dispense mode. It only affects tip pickups/ejects; the aspirate/dispense sequence and well coverage are unchanged.

## Connected-Container Sources (Multi-Channel Aspiration)

When the reagent source is a **connected container** — a single physical reservoir whose several access positions share the same liquid (`rack_layout.connected_container: true` in the labware definition, e.g. an 8-position reagent container) — the command aspirates with multiple channels at once, each drawing from a distinct position of the container:

```python
result = star.add_reagent(
	reagent_source="RgtContainer",   # connected_container labware
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)
```

A reservoir has no walls between its sections, so it is one liquid however it is addressed: `"RgtContainer@1"` means the whole container, and every channel is used. When there are more channels than sections the aspirate goes in passes that start again at the first section -- with an 8-section container on a 16-channel head, channels 1-8 aspirate from sections 1-8, then channels 9-16 from sections 1-8. Pre/post-aliquots returned to the container use the same passes. This is handled automatically from the labware definition — no extra arguments are required.

The diluent phase of [serial dilution](serial_dilution.md) also spreads channels across a connected container, but caps them at the number of sections rather than using passes.

## Worklist-Driven Volumes

Pass a `transfer_csv` worklist to give each destination well its own volume, across one or more destination plates. The worklist only says **where the reagent goes and how much**; the reagent itself always comes from `reagent_source`:

```csv
dest_labware,dest_well,volume
Plate1,A1,50.0
Plate1,B1,62.5
Plate2,A1,100.0
```

```python
result = star.add_reagent(
	reagent_source="Tubes@1:4",  # the reagent for every row, channels spread over tubes 1-4
	dest_plate="Plate1",          # default for rows without a dest_labware
	volume=50.0,                  # default for rows without a volume
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	transfer_csv="path/to/worklist.csv",
	multi_dispense=True,
)
print(f"Destination plates: {result.dest_plate_ids}")
```

Each channel aspirates exactly its own row's volume (plus any pre/post-aliquot) -- in multi-dispense mode, the sum of the volumes it will dispense. `volume` is only a fallback, so it is not checked against the tip; every row's volume is.

`source_labware` / `source_well` columns are ignored (a warning is logged if they are filled in), so a worklist written for `hit_picking` can be reused as-is. To take each row's liquid from its own tube or well, use [hit picking](hit_picking.md) instead.

Rows are grouped by destination plate. Setting `follow_csv_order=True` keeps the rows in the order written instead, splitting them into consecutive same-plate runs:

```python
result = star.add_reagent(
	...,  # reagent_source, dest_plate, volume, tip_pool as in the previous example
	transfer_csv="path/to/worklist.csv",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	follow_csv_order=True,  # do not re-group by plate
)
```

## Operator-Prompted Tip Reload

If the tip pool runs out mid-run, the SDK can pause and ask an operator to reload. Supply an `on_tip_reload_prompt` callback when constructing `StarClient`:

```python
def on_reload(ctx) -> bool:
	print(f"Please refill tip pool '{ctx.tip_pool}' (need {ctx.required} tips).")
	input("Press Enter when done...")
	return True   # True = continue; False = abort

with StarClient(deck_name="MyDeck", on_tip_reload_prompt=on_reload) as star:
	star.instrument_init()
	result = star.add_reagent(
		reagent_source="ReagentTrough",
		dest_plate="DestPlate",
		volume=50.0,
		tip_pool="TipPool300uL",
		liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	)
```

The callback receives a context object with:

| Attribute | Type | Description |
|-----------|------|-------------|
| `tip_pool` | `str` | Name of the exhausted tip pool |
| `required` | `int` | Number of tips needed to continue |
| `available` | `int` | Number of tips currently reported by the pool |
| `command` | `str` | Name of the compound command issuing the prompt (e.g. `"add_reagent"`) |
| `attempt` | `int` | Reload attempt number (starts at 1) |

Return `True` to continue after the operator reloads; return `False` to abort the run (raising `OperatorCancelledError`). If no callback is configured and the pool is short, `add_reagent` raises `ValueError`.

## Error Profile

Pass an `ErrorProfile` to use a different error profile for this command:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction

profile = ErrorProfile(
	name="AddReagent_Profile",
	default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
)

result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	error_profile=profile,
)
```

When `error_profile=None` (default), the client's currently active profile is used. See [Error Handling](../../error_handling.md) for the full profile/entry/action reference.

## Custom Channels

Use fewer channels for partial-row operations:

```python
result = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=100.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
	channels=[1, 2, 3, 4],
)
```

## Inspecting Results

```python
from hamilton_venus import AddReagentResult

result: AddReagentResult = star.add_reagent(
	reagent_source="ReagentTrough",
	dest_plate="DestPlate",
	volume=50.0,
	tip_pool="TipPool300uL",
	liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)

print(f"Wells filled:      {result.wells_filled}")
print(f"Iterations:        {result.iterations}")
print(f"Total processed:   {result.total_wells_processed}")
print(f"Multi-dispense:    {result.multi_dispense}")
print(f"Source plates:     {result.source_plate_ids}")
print(f"Sources used:      {result.sources_used}")  # containers drained, in order
print(f"Dest plates:       {result.dest_plate_ids}")
print(f"By plate:          {result.wells_filled_by_plate}")

for i, it in enumerate(result.iteration_results):
	tadm_count = (
		len(it.aspirate.return_parameters.tadm.tadm_curves)
		if it.aspirate.return_parameters.tadm
		else 0
	)
	print(f"  Iteration {i}: {len(it.well_dispenses)} dispenses, {tadm_count} TADM curves")
```

`wells_filled` counts dispense events. If a CSV run dispenses to the same destination well twice, it is counted twice.

### TADM Curves

Access all pressure-monitoring curves from a run in one call:

```python
for curve in result.tadm_curves:
	print(curve)
```
