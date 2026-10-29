# Copy Plate (Compound Command)

Copy Plate is a high-level compound command that transfers the contents of one plate to another, handling tip management and multi-iteration batching automatically.

## Basic Usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
    # Deck setup: add carriers, tip racks, plates, then init
    # ...
    star.instrument_init()

    result = star.copy_plate(
        source_plate_id="SourcePlate",
        dest_plate_id="DestPlate",
        volume=100.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        tip_pool="TipPool300uL",
    )
    print(f"Copied {result.wells_copied} wells in {result.iterations} iterations")
```

## Copying to Multiple Destinations

`dest_plate_id` accepts either a single labware id or a `list[str]` of ids.
When a list is supplied the source plate is copied to every destination in
order:

```python
result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id=["DestPlateA", "DestPlateB", "DestPlateC"],
    volume=100.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
)
print(f"Copied to plates: {result.dest_plate_ids}")
```

`result.dest_plate_ids` is a tuple of every destination plate processed.

## Automatic Geometry Caching

Labware geometry (rows/cols/well spacing) is resolved automatically the first
time a labware id is referenced and cached for the lifetime of the client, so
high-density plates like 384-well work out of the box without any extra
arguments:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
    star.instrument_init()

    result = star.copy_plate(
        source_plate_id="Source384Plate",
        dest_plate_id="Dest384Plate",
        volume=10.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        tip_pool="TipPool300uL",
    )
    print(f"Copied {result.wells_copied} wells efficiently")
```

**Benefits:**
- **No redundant deck queries:** Geometry is computed once per labware and reused
- **Automatic interleaving:** For 384-well plates (4.5 mm spacing), wells are automatically sequenced correctly for 8-channel operations
- **No extra arguments:** Works transparently from the labware id alone

## Reusing Tips

For workflows where cross-contamination is not a concern, reuse the same tip set across all iterations:

```python
result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=50.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
    reuse_tips=True,
)
```

## Custom Channels

Use fewer channels (e.g. 4 instead of 8) for partial-plate operations:

```python
result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=100.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    channels=[1, 2, 3, 4],
    tip_pool="TipPool300uL",
)
```

## 384-Well Plate Support (Automatic Interleaving)

When copying high-density plates (384-well with 4.5 mm spacing), `copy_plate` automatically applies spacing-aware interleaving so that 8-channel operations can physically reach the wells correctly. No special configuration needed:

```python
result = star.copy_plate(
    source_plate_id="Source384Plate",
    dest_plate_id="Dest384Plate",
    volume=5.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
)
# Internally: 384-well wells are reordered so 8-channel commands work correctly
# Pass 1: A1, C1, E1, G1, I1, K1, M1, O1 (even rows)
# Pass 2: B1, D1, F1, H1, J1, L1, N1, P1 (odd rows)
```

384-well plates benefit from this automatically -- no extra configuration is needed:

```python
result = star.copy_plate(
    source_plate_id="Source384Plate",
    dest_plate_id="Dest384Plate",
    volume=5.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
)
```

## Operator-Prompted Tip Reload

`copy_plate` supports the same `on_tip_reload_prompt` callback used by other compound commands. When the configured tip pool runs out mid-run, the SDK pauses and asks the operator to reload:

```python
def on_reload(ctx) -> bool:
    print(f"Please refill tip pool '{ctx.tip_pool}' (need {ctx.required} tips).")
    input("Press Enter when done...")
    return True   # True = continue; False = abort

with StarClient(deck_name="MyDeck", on_tip_reload_prompt=on_reload) as star:
    star.instrument_init()
    result = star.copy_plate(
        source_plate_id="SourcePlate",
        dest_plate_id="DestPlate",
        volume=100.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        tip_pool="TipPool300uL",
    )
```

The callback receives a context with `tip_pool`, `required`, `available`, `command` (here `"copy_plate"`), and `attempt`. Return `True` to continue, `False` to abort. If no callback is configured and the pool is short, `copy_plate` raises `ValueError` before touching hardware.

## Error Profile

Pass an `ErrorProfile` to to use a different error profile for this command:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction

profile = ErrorProfile(
    name="CopyPlate_Profile",
    default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
)

result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=100.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
    error_profile=profile,
)
```

When `error_profile=None` (default), the client's currently active profile is used. See [Error Handling](../../error_handling.md) for the full reference.

## Inspecting Results

```python
from hamilton_venus import CopyPlateResult

result: CopyPlateResult = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=100.0,
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TipPool300uL",
)

print(f"Wells copied:    {result.wells_copied}")
print(f"Wells skipped:   {result.wells_skipped}")
print(f"Iterations:      {result.iterations}")
print(f"Total processed: {result.total_wells_processed}")
print(f"Source plate:    {result.source_plate_id}")
print(f"Dest plate:      {result.dest_plate_id}")

for i, it in enumerate(result.iteration_results):
    tadm_count = len(it.aspirate.return_parameters.tadm.tadm_curves) if it.aspirate.return_parameters.tadm else 0
    print(f"  Iteration {i}: aspirated {len(it.aspirate.return_parameters.channels)} channels, {tadm_count} TADM curves")
```
