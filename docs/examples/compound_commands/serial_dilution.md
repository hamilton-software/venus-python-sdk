# Serial Dilution (Compound Commands)

Serial Dilution is a pair of high-level compound commands that dilute a sample
**across the columns** of a plate, one independent series **per row**, running
the active rows in parallel on the multi-channel head. The samples to be diluted
are assumed to be pre-loaded at `start_column`; the command pre-charges the
downstream wells with diluent and then walks the transfer chain
column-by-column.

Two peer commands differ only in how the per-well **diluent volume** is
determined:

| Command | Diluent volume | Typical use |
|---------|----------------|-------------|
| `serial_dilution_by_volume` | Explicit `diluent_volume` | You know the exact buffer volume per well |
| `serial_dilution_by_dilution_factor` | `transfer_volume * (dilution_factor - 1)` | You know the target fold dilution (e.g. 1:2, 1:10) |

## The Two-Phase Model

A run has two globally ordered phases:

1. **Diluent pre-charge** — every dilution well on every plate/pass is filled
   with `diluent_volume` of buffer, using one clean tip set drawn from
   `diluent_tip_pool`.
2. **Transfer chains** — the sample is carried `start_column -> next -> ...`,
   one `transfer_volume` step at a time, mixing after each dispense (optional),
   using tips from `transfer_tip_pool`.

**Phase 1 completes entirely before Phase 2 begins**, across every plate and
every pass. The two phases always use **separate tip sets** — `reuse_tips` never
bridges them.

## Basic Usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
	star.instrument_init()

	# 1:2 serial dilution, six steps, across a 96-well plate (rows A-H run in
	# parallel). Each well is pre-charged with transfer_volume * (2 - 1) = 20 uL
	# of diluent, then 20 uL is carried between wells.
	result = star.serial_dilution_by_dilution_factor(
		plate_id="AssayPlate",
		start_column=1,
		num_dilutions=6,
		transfer_volume=20.0,
		dilution_factor=2.0,
		diluent_source="ReagentTrough",
		diluent_liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		diluent_tip_pool="TipPool300uL",
		transfer_liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
		transfer_tip_pool="TipPool300uL",
	)
	print(f"{result.num_series} series x {result.num_dilutions} dilutions")
```

`"MyDeck"`, `"AssayPlate"`, `"ReagentTrough"`, and `"TipPool300uL"` are placeholders for the deck, labware IDs, and tip pool on your system; see [Before You Start](./README.md#before-you-start).
When omitted, `diluent_liquid_class` and `transfer_liquid_class` default to
`"HighVolume_Water_DispenseJet_Empty"`, a liquid class for 1000 µL tips. Pass
liquid classes that match the tips in your tip pools, as above. The remaining
examples omit them for brevity.

The equivalent by-volume call supplies the diluent volume directly:

```python
result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	diluent_volume=180.0,  # a 1:10 dilution: 180 uL buffer + 20 uL sample
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
)
```

## Plate Layout: Columns, Rows, and Exclusions

Traversal moves **left to right across columns**. `start_column` is **1-based**
(column `1` is the first physical column). With `start_column=1` and
`num_dilutions=6`, a series spans columns `1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7`
(the sample column plus six dilution columns).

- **`exclude_columns`** — 1-based columns skipped during traversal. Excluded
  columns **do not** consume a dilution step; the chain simply hops over them.
- **`exclude_rows`** — rows to leave untouched, accepted as **1-based integers
  and/or letters** in the same list (e.g. `[1, "C", 8]`). Excluded rows reduce
  the number of active series (and therefore the channels used per pass).

```python
result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=3,
	transfer_volume=20.0,
	diluent_volume=100.0,
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
	exclude_columns=[3],          # hop over column 3
	exclude_rows=[1, "C"],        # skip rows A (1) and C
)
```

## Separate Diluent and Transfer Configuration

The two phases are configured independently, so the buffer and the sample can
use different tips, liquid classes, settings, and error profiles:

```python
# buffer_profile and sample_profile are ErrorProfile objects, built as shown in
# the Error Profile section of add_reagent.md.
result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	diluent_volume=180.0,
	diluent_source="ReagentTrough",
	diluent_liquid_class="HighVolume_Water_DispenseJet_Empty",
	diluent_tip_pool="BufferTips",
	diluent_error_profile=buffer_profile,
	transfer_liquid_class="StandardVolume_Serum_DispenseSurface_Empty",
	transfer_tip_pool="SampleTips",
	transfer_error_profile=sample_profile,
)
```

Each phase enters its own scoped error profile (`diluent_error_profile` /
`transfer_error_profile`) for the duration of that phase only; both default to
the client's active profile when omitted.

## Mixing

When `mix_after_dispense=True` (the default) **and** the transfer dispense
settings request at least one mix cycle, a dedicated mix stroke follows each
transfer dispense (the same mechanism used by `pool_samples`). The diluent
pre-charge never mixes.

```python
from hamilton_venus.models.liquid_handling_settings import DispenseSettings

result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	diluent_volume=180.0,
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
	mix_after_dispense=True,
	transfer_disp_settings=DispenseSettings(mix_cycles=3, mix_volume=100.0),
)
```

Set `mix_after_dispense=False` to suppress mixing even when the settings request
cycles.

## Diluent Multi-Dispense and Multi-Source Reload

By default (`diluent_multi_dispense=True`) the diluent phase aspirates a
capacity- and budget-bounded batch that feeds several columns per aspirate; set
it to `False` to aspirate once per column.

`diluent_source` accepts a `list[str]` of selectors that are **drained in
order** with reactive volume tracking: the SDK reads the measured per-channel
liquid volume after each aspirate (the minimum across channels) and switches to
the next source only **between** aspirations. When every source is exhausted the
`on_liquid_reload_prompt` callback is invoked so an operator can refill or
replace the trough:

```python
def on_reload(ctx) -> bool:
	print(f"Refill {ctx.active_source}: need {ctx.required} uL, {ctx.available} uL left")
	input("Press Enter when refilled...")
	return True  # return False to cancel (raises OperatorCancelledError)

star.on_liquid_reload_prompt = on_reload

result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	diluent_volume=180.0,
	diluent_source=["TroughA", "TroughB"],
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
	diluent_multi_dispense=False,
)
print(f"Diluent sources drained: {result.diluent_sources_used}")
```

If no callback is configured and every source runs short, the run continues:
the shortage is logged as a warning and recorded as a `liquid_shortage` entry
in the run log. As with [add_reagent](add_reagent.md#draining-several-sources-in-order-consumable-liquid-management),
moving to the next source requires liquid level detection (capacitive or
pressure LLD in `diluent_asp_settings`); without it the first source is used
for the whole run.

When the diluent source is a **connected container** — a single physical
reservoir whose several access positions share the same liquid
(`rack_layout.connected_container: true` in the labware definition) — the diluent
aspirate spreads across multiple channels at once, each drawing from a distinct
position, whenever the channels fit the container (otherwise the single active
position is broadcast). This is handled automatically from the labware
definition via the shared consumable-liquid logic, so no extra arguments are
needed (the same behaviour powers [add_reagent](add_reagent.md) sources).

## Multi-Plate and Multi-Pass

`plate_id` accepts a single [selector string](../position_and_well_selection.md) **or**
a `list[str]` -- or a pre-resolved `Position`/`list[Position]` (e.g. from
[`normalize_positions()`](../position_and_well_selection.md#feeding-normalize_positions-into-compound_commands)).
Multiple plates are processed sequentially and share the diluent source, the waste
location, and (when `reuse_tips=True`) the transfer tip set. The two-phase global
ordering holds across plates: every plate's diluent pre-charge runs before any plate's
transfer chain.

When more rows are active than there are channels (for example a 384-well plate,
or a 96-well plate driven by a 4-channel subset), the extra rows are processed in
additional **passes**. Each pass is a `(plate, pass)` unit of work.

```python
result = star.serial_dilution_by_volume(
	plate_id=["PlateA", "PlateB"],
	start_column=1,
	num_dilutions=3,
	transfer_volume=20.0,
	diluent_volume=100.0,
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
	channels=[1, 2, 3, 4],  # 8 rows / 4 channels -> 2 passes per plate
)
for plate in result.plate_results:
	print(f"{plate.plate_id}: {plate.num_passes} pass(es), {len(plate.series_results)} series")
```

## Tip Reuse and Cross-Pass Contamination

`reuse_tips` controls the **transfer** tip set only (the diluent set is always
clean and separate):

- `reuse_tips=False` (default) — a fresh transfer set is picked up for **each
  pass**. Slower, but every pass starts with clean tips.
- `reuse_tips=True` — the transfer set is kept mounted **across passes and
  plates**. Faster, but accepts cross-pass carryover on the shared tips. Reuse
  applies *between passes*; it never bridges the diluent and transfer phases.

## Trailing Excess: `discard_last_excess`

After the final transfer, one `transfer_volume` remains in the last dilution
well. `discard_last_excess` (a `LastDilutionWaste`) controls its disposal:

| Value | Behaviour |
|-------|-----------|
| `NONE` (default) | Leave the excess in the final well; no extra stroke. |
| `TO_WASTE` | Aspirate the excess and dispense it to the waste location. |
| `WITH_TIP_EJECT` | Aspirate the excess into the tips and eject them (forces a fresh transfer set for the next `(plate, pass)`). |

For `TO_WASTE`, `waste_location` selects an explicit waste labware; when omitted
the command falls back to the deck's fixed `liquid_waste` labware.

```python
from hamilton_venus.models.enums import LastDilutionWaste

result = star.serial_dilution_by_volume(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	diluent_volume=180.0,
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
	discard_last_excess=LastDilutionWaste.TO_WASTE,
	waste_location="MyWasteTrough",  # optional; defaults to liquid_waste
)
```

## Operator-Prompted Tip Reload

Both phases request their tips up front through the shared tip manager. When a
pool cannot supply enough tips, the client's `on_tip_reload_prompt` callback is
invoked (returning `True` to retry after the operator reloads, or `False` to
cancel with `OperatorCancelledError`). If no callback is set, a `ValueError` is
raised.

## Inspecting the Result

Both commands return a `SerialDilutionResult`:

```python
result = star.serial_dilution_by_dilution_factor(
	plate_id="AssayPlate",
	start_column=1,
	num_dilutions=6,
	transfer_volume=20.0,
	dilution_factor=2.0,
	diluent_source="ReagentTrough",
	diluent_tip_pool="TipPool300uL",
	transfer_tip_pool="TipPool300uL",
)

print(result.plate_ids)             # ('AssayPlate',)
print(result.num_series)            # active rows summed across plates
print(result.num_dilutions)         # 6
print(result.diluent_volume)        # 20.0 (derived from the factor)
print(result.dilution_factor)       # 2.0
print(result.diluent_sources_used)  # ('ReagentTrough',)

for plate in result.plate_results:
	for series in plate.series_results:
		print(series.row, series.well_chain)   # e.g. A ('A1', 'A2', ... 'A7')
		for step in series.steps:
			print(f"  {step.source_well} -> {step.dest_well}")

curves = result.tadm_curves  # aggregated TADM traces across all strokes
```

Sibling series belonging to the same pass share the underlying aspirate,
dispense, and mix responses (each pass is a single multi-channel stroke), so
`tadm_curves` de-duplicates traces by response identity.

## See Also

- [Add Reagent](./add_reagent.md) — one or more ordered sources to many wells.
- [Replicate Samples](./replicate_samples.md) — one source to `N` destinations.
- [Pool Samples](./pool_samples.md) — `N` sources to one destination.
- [Compound Commands index](./README.md)
