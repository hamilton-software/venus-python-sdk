# Position and Well Selection

Guide to the position selector syntax and well selection features used by channel commands.

---

## Position Input Forms

All channel commands (`aspirate`, `dispense`, `tip_pickup`, `tip_eject`, `detect_liquid_level`) accept positions as any of the following:

| Form | Example | Description |
|------|---------|-------------|
| Selector string | `"Plate1@A1"` | expression expanded into wells |
| List of strings | `["Plate1@A1", "Plate1@B1"]` | Multiple selectors, flattened in order |
| Wire-format dict | `{"labwareId": "Plate1", "wellId": "A1"}` | Explicit labware/well pair |
| List of dicts | `[{"labwareId": "Plate1", "wellId": "A1"}, ...]` | Multiple explicit pairs |
| `Position` object | `Position(labware="Plate1", well="A1")` | Typed position model |
| List of `Position` | `[Position(labware="Plate1", well="A1"), ...]` | Multiple typed positions |

The [compound commands](compound-commands/README.md) (`add_reagent`, `pool_samples`, `replicate_samples`, `serial_dilution_by_volume`/`serial_dilution_by_dilution_factor`) accept the same selector-string, `list[str]`, `Position`, and `list[Position]` forms for their plate parameters (`dest_plate`, `source_plate`, `reagent_source`, `plate_id`) -- see [Feeding `normalize_positions` Into Compound Commands](#feeding-normalize_positions-into-compound-commands) below. The wire-format dict forms are specific to `normalize_positions()` and the channel commands.

---

## Selector Syntax

The selector syntax uses `Labware@expression` where `Labware` is the labware ID on the deck.

### Single Well

```python
star.aspirate(channels=[1], positions="Plate1@A1", volumes=50.0, liquid_class="Water")
```

### Explicit Well List

```python
star.aspirate(channels=[3], positions="Plate1@A1,B1,C1", volumes=50.0, liquid_class="Water")
```

### Well Range (Rectangular)

Select all wells in the rectangle from A1 to C3:

```python
star.aspirate(channels=[8], positions="Plate1@A1:C3", volumes=50.0, liquid_class="Water")
```

### Row Selection

Select entire rows by letter. Supports single rows and ranges. Row addressing
follows the VENUS convention: ``A``-``Z`` for the first 26 rows and Excel-style
two-letter labels ``AA``-``ZZ`` thereafter (e.g., row 27 is ``AA``, row 29 is
``AC``).  This allows 1536-well plates (32 rows: ``A``-``AF``) to be addressed
naturally.

```python
# Row A only
star.aspirate(positions="Plate1@row:A", volumes=50.0, liquid_class="Water")

# Rows A through D
star.aspirate(positions="Plate1@row:A:D", volumes=50.0, liquid_class="Water")

# Rows A and E through H
star.aspirate(positions="Plate1@row:A,E:H", volumes=50.0, liquid_class="Water")

# 1536-well plate: rows that cross the single/two-letter boundary
star.aspirate(positions="Plate1536@row:Y:AB", volumes=2.0, liquid_class="Water")
```

### Column Selection

Select entire columns by number. Supports single columns and ranges:

```python
# Column 1 only
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Plate1@col:1", volumes=50.0, liquid_class="Water")

# Columns 1 through 3
star.aspirate(channels=[8], positions="Plate1@col:1:3", volumes=50.0, liquid_class="Water")
```

### All Wells

Select every well on the labware:

```python
from hamilton_venus.models import normalize_positions

positions = normalize_positions("Plate1@all", channel_count=8)
```

### Bare Labware (No Expression)

A bare labware name with no `@` expression is equivalent to `@all` — it
expands to every well on the labware:

```python
# Equivalent to positions="Plate1@all"
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Plate1", volumes=50.0, liquid_class="Water")
```

### Single Well Across Multiple Channels

A selector that resolves to exactly one well is repeated across every
requested channel instead of raising a channel-count mismatch — this is how
"every channel draws from the same reservoir well" is expressed:

```python
# All 8 channels draw from Trough1/A1
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Trough1@A1", volumes=50.0, liquid_class="Water")
```

In a well split with [`split_wells()`](deck-and-layout.md#split-wells), the
repeated well is instead spread over the well's slots, one per channel, at the
channel pitch:

```python
star.split_wells("Plate6", "A1")   # 4 slots in a 6-well plate's well
star.aspirate(channels=[1, 2, 3, 4], positions="Plate6@A1", volumes=500.0, liquid_class="Water")
```

---

## Well Ordering

The `well_order` parameter controls how expanded wells are sorted. Import `WellOrder` from `hamilton_venus.models`:

```python
from hamilton_venus.models import WellOrder
```

| Value | Description |
|-------|-------------|
| `WellOrder.COL_ASC` | Column-major ascending (A1, B1, ... A2, B2, ...) -- **default** |
| `WellOrder.COL_DESC` | Column-major descending (H12, G12, ... H11, G11, ...) |
| `WellOrder.ROW_ASC` | Row-major ascending (A1, A2, ... B1, B2, ...) |
| `WellOrder.ROW_DESC` | Row-major descending (H12, H11, ... G12, G11, ...) |
| `WellOrder.CUSTOM` | Preserves the declared order of explicit well lists |

```python
star.aspirate(
    channels=[1, 2, 3, 4, 5, 6, 7, 8],
    positions="Plate1@col:1",
    volumes=50.0,
    liquid_class="Water",
    well_order=WellOrder.COL_ASC,
)
```

---

## Using `normalize_positions` Directly

The `normalize_positions` function can be called independently for debugging or manual position construction:

```python
from hamilton_venus.models import normalize_positions, WellOrder

# Single well
positions = normalize_positions("Plate1@A1")
# -> [Position(labware='Plate1', well='A1')]

# Column with ordering
positions = normalize_positions("Plate1@col:1", well_order=WellOrder.COL_ASC)
# -> [Position(labware='Plate1', well='A1'), ..., Position(labware='Plate1', well='H1')]

# Limit to channel count
positions = normalize_positions("Plate1@col:1", channel_count=4)
# -> first 4 wells only

# Cap to a fixed number of wells (total_wells), independent of channel_count
positions = normalize_positions("Plate1@all", total_wells=17)
# -> the first 17 of Plate1's 96 wells, in well_order
```

`total_wells` and `channel_count` serve different purposes and can be used independently or together:

| Parameter | Purpose | If fewer positions are available than requested |
|-----------|---------|---------------------------------------------------|
| `channel_count` | Hardware-channel-count semantics: a single resolved well is *broadcast* across every channel (e.g. all 8 channels drawing from one reservoir well) | Raises `ValueError` |
| `total_wells` | A plain cap on the result -- "give me at most N of however many this selector expands to" (e.g. distributing 17 samples across a 96-well plate without hand-writing a 17-well selector) | Returns whatever is available, no error |

If both are given, `channel_count`'s broadcast/raise logic runs first and `total_wells` caps the (possibly already-broadcast) result further.

---

## Labware Geometry Resolution

For non-standard labware (anything other than the default 8x12 grid), the SDK
automatically fetches the grid dimensions from the connected deck via
`StarClient.get_labware_spec()` and caches the result for the lifetime of the
client. No extra geometry argument needs to be passed to channel commands --
the selector DSL transparently uses the right geometry:

```python
# 384-well plate -- row/col expansion uses 16x24 grid automatically
star.aspirate(
    channels=[1, 2, 3, 4, 5, 6, 7, 8],
    positions="Plate384@col:1",
    volumes=10.0,
    liquid_class="Water",
)
```

The cache is populated lazily on first access. For unit tests or to override
the deck's reported geometry, pre-populate or override the cache with
`StarClient.register_labware_definition()`:

```python
from hamilton_venus.models import LabwareLayoutSpec

custom_spec = LabwareLayoutSpec(rows=4, cols=6, well_spacing_x_mm=18.0, well_spacing_y_mm=18.0)
star.register_labware_definition("TubeRack", custom_spec)

star.aspirate(
    channels=[1, 2, 3, 4],
    positions="TubeRack@col:1",
    volumes=200.0,
    liquid_class="Water",
)
```

---

## Multiple Selectors in a List

Pass a list of selector strings to combine wells from different expressions:

```python
star.aspirate(
    channels=[1, 2, 3, 4, 5, 6],
    positions=["Plate1@A1,B1,C1", "Plate1@A2,B2,C2"],
    volumes=50.0,
    liquid_class="Water",
)
```

Lists are flattened in order before any `channel_count` truncation is applied.

---

## Calling `normalize_positions` Without a Client

For unit tests or debugging you can call `normalize_positions` directly. When
no `get_spec` callback is supplied, a default 8x12 plate layout is assumed --
sufficient for any selector that does not need per-labware geometry:

```python
from hamilton_venus.models import normalize_positions, WellOrder

positions = normalize_positions("Plate1@col:1", well_order=WellOrder.COL_ASC)
# -> [Position(labware='Plate1', well='A1'), ..., Position(labware='Plate1', well='H1')]
```

To resolve high-density plates or other non-default geometry, pass a
`SpecResolver` callable (typically `client.get_labware_spec`):

```python
from hamilton_venus.models import normalize_positions

positions = normalize_positions(
    "Plate384@col:1",
    channel_count=8,
    get_spec=star.get_labware_spec,
)
```

`SpecResolver` is just a type alias for `Callable[[str], LabwareLayoutSpec]`,
so you can plug in any function that maps a labware id to a layout spec --
useful when stubbing layouts in tests:

```python
from hamilton_venus.models import LabwareLayoutSpec

PLATE_384 = LabwareLayoutSpec(rows=16, cols=24, well_spacing_x_mm=4.5, well_spacing_y_mm=4.5)

def resolver(labware_id: str) -> LabwareLayoutSpec:
    return PLATE_384

positions = normalize_positions("Plate384@col:1", channel_count=8, get_spec=resolver)
```

---

## Spacing-Aware Sequencing (Interleaving)

Hamilton 1 mL channels have a fixed 9.0 mm pitch between adjacent channels.
On labware where the well spacing differs from the channel pitch (e.g.
384-well plates at 4.5 mm), the SDK automatically reorders wells so that
each simultaneous channel group targets physically reachable positions.

This happens transparently whenever the labware's VENUS definition declares
well-spacing values (which the SDK resolves automatically via
`StarClient.get_labware_spec`). No additional configuration is required.

### How It Works

Interleaving is applied automatically when both are known:

- command channel spacing for the active head/channel set
- axis spacing from labware geometry (`well_spacing_x_mm` or `well_spacing_y_mm`)

If spacing metadata is unavailable, the SDK preserves the original selector expansion order.

For a 384-well plate (4.5 mm well spacing) with 9.0 mm channel pitch:

- **Skip factor**: `9.0 / 4.5 = 2` -- channels skip every other well.
- For column traversal (for example `Plate384@col:1`), wells run down column 1 as
  `A1, B1, C1, ..., P1` and are interleaved into two passes:
  `A1, C1, E1, ..., O1` then `B1, D1, F1, ..., P1`.

### Verifying Interleaved Order

Use `normalize_positions` to inspect the computed order:

```python
from hamilton_venus.models import normalize_positions

positions = normalize_positions(
    "Plate384@col:1",
    channel_count=8,
    get_spec=star.get_labware_spec,
)

for p in positions:
    print(f"{p.labware}@{p.well}")
# Prints interleaved well order: A1, C1, E1, G1, I1, K1, M1, O1
```

### Numeric vs. Alphanumeric Addressing

Whether a labware is addressed alphanumerically (`"A1"`) or numerically
(`"1"`) is defined by the labware definition, not by its geometry.  The SDK
reads the definition's `rack_layout.indexing.index` field:

- `index == 1` -> **alphanumeric** addressing (`"A1"`, `"H12"`).  Most plates
  and tip racks.
- `index == 0` -> **numeric** addressing (`"1"`, `"2"`, ...).  Most reservoirs,
  troughs, and tube carriers.

When `indexing.index` is absent the SDK assumes alphanumeric (the standard
plate default).

Numeric well numbers run in the definition's `indexing.pattern` order:
`COLUMN_MAJOR` numbers down each column first, `ROW_MAJOR` across each row
first.  (The `indexing.first`/`start`/`increment` fields are carrier-slot and
orientation bookkeeping and never shift well labels, so they are ignored.)

**Input is forgiving.**  You may supply either form regardless of the
labware's native mode; the SDK translates the input to the labware's canonical
form in the resulting `Position.well` value:

- On a numeric labware, `"A1"` -> `"1"`, `"H1"` -> `"8"`, `"AA1"` -> `"27"`.
- On an alphanumeric labware, `"1"` -> `"A1"`, `"8"` -> `"H1"`.

Ambiguous or out-of-range input raises a clear `ValueError` (for example, a
trailing column on a single-column labware, or a well number beyond the
labware's capacity).

For a single-column numeric carrier:

- Use `@all`, explicit numeric wells, numeric ranges (`@1:8`), or alphabetic
  ranges (`@A1:H1`) as appropriate.
- Do not use `@col:` selectors (the carrier has only one column).

Example:

```python
positions = normalize_positions("TubeRack@all", get_spec=star.get_labware_spec)
# -> TubeRack/1, TubeRack/2, ..., TubeRack/N (numeric labware canonical form)

positions = normalize_positions("Reservoir@A1", get_spec=star.get_labware_spec)
# -> Reservoir/1 (alphabetic input translated to numeric canonical form)

positions = normalize_positions("Plate1@1", get_spec=star.get_labware_spec)
# -> Plate1/A1 (numeric input translated to alphanumeric canonical form)
```

---

## Parsing VENUS Labware Definitions

The SDK provides a typed `LabwareDefinition` Pydantic model for VENUS labware
definition JSON payloads. This replaces manual dictionary navigation.

### From a JSON File

```python
import json
from hamilton_venus.models import LabwareDefinition

with open("Cos_96_Rd.json") as f:
    payload = json.load(f)

defn = LabwareDefinition.model_validate(payload)
print(defn.rack_layout.rows)           # 8
print(defn.rack_layout.columns)        # 12
print(defn.rack_layout.well_spacing_x_mm)  # 9.0
```

### From `labware_get_definition` Response

When the labware definition is returned by `labware_get_definition`, use the
`to_labware_definition()` helper on the response:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models import LabwareDefinition

with StarClient() as star:
    response = star.labware_get_definition(LABWARE.PLATE.COS_96_RD)
    defn = response.return_parameters.to_labware_definition()
```

### Converting to LabwareLayoutSpec

`LabwareLayoutSpec.from_definition()` accepts both `LabwareDefinition` objects and
raw dictionaries:

```python
from hamilton_venus.models import LabwareLayoutSpec

# From typed model
spec = LabwareLayoutSpec.from_definition(defn)

# From raw dict (any of the three supported shapes)
spec = LabwareLayoutSpec.from_definition(payload)
```

### Accessing Container Details

Each labware definition contains one or more container definitions with
well geometry, liquid sensing, and touch-off settings:

```python
defn = LabwareDefinition.model_validate(payload)

for container in defn.containers:
    print(f"Container: {container.file_name}")
    print(f"  Total depth: {container.total_depth_mm} mm")

    if container.well_geometry:
        for segment in container.well_geometry.segments:
            print(f"  Segment {segment.id}: {segment.shape} ({segment.name})")

    if container.liquid_sensing:
        print(f"  LLD: {container.liquid_sensing.mode}")

    if container.touch_off:
        print(f"  Touch-off: enabled={container.touch_off.enabled}")
```

---

## Row-Major vs. Column-Major Indexing

For **numerically addressed** labware (tube racks, reservoirs, tip racks), the
`LabwareLayoutSpec.pattern` field controls both how wells are numbered and how
`@all` is ordered by default:

- **COLUMN_MAJOR** (default): 1, 2, 3, ... down each column first
- **ROW_MAJOR**: 1, 2, 3, ... across each row first

This is automatically read from the labware definition's `rack_layout.indexing.pattern`.

**Alphanumeric plates** ("A1") are different: the pattern doesn't change which
well an ID names, so `@all` ignores it and follows `well_order`
(`COL_ASC` by default: A1, B1, C1, ... A2, B2, ...). This matters because
stock plate definitions report `ROW_MAJOR`, and a row-wise order would put
wells along X, where 9 mm channels can't spread across. Pass
`well_order=WellOrder.ROW_ASC` if you do want row-wise order.

```python
from hamilton_venus.models import LabwareLayoutSpec

# Column-major numeric labware (e.g. a tip rack)
rack_col_spec = LabwareLayoutSpec(rows=8, cols=12, pattern="COLUMN_MAJOR", numeric_addressing=True)

# Row-major numeric labware (common for tube racks and reagent carriers).
rack_spec = LabwareLayoutSpec(rows=8, cols=1, pattern="ROW_MAJOR", numeric_addressing=True)
```

When using `@all` on numerically addressed labware, the spec's pattern is used
as the default traversal direction:

```python
star.register_labware_definition("TubeRack", rack_spec)
positions = normalize_positions("TubeRack@all", get_spec=star.get_labware_spec)
# Uses ROW_MAJOR ordering; numeric-addressed -> TubeRack/1, TubeRack/2, ...
```

---

## Custom LabwareLayoutSpec for Non-Standard Labware

For labware whose geometry needs to be supplied manually (e.g. custom or
not-yet-registered labware), construct a `LabwareLayoutSpec` with the exact
dimensions and register it on the client:

```python
from hamilton_venus.models import LabwareLayoutSpec

deep_well_spec = LabwareLayoutSpec(
    rows=8,
    cols=12,
    well_spacing_x_mm=9.0,
    well_spacing_y_mm=9.0,
    pattern="COLUMN_MAJOR",
    # Set numeric_addressing=True for reservoirs/troughs/tube racks whose
    # wells are labelled "1", "2", ... instead of "A1", "B1", ...
    numeric_addressing=False,
)

star.register_labware_definition("DeepWell", deep_well_spec)

star.aspirate(
    channels=[1, 2, 3, 4, 5, 6, 7, 8],
    positions="DeepWell@col:1",
    volumes=500.0,
    liquid_class="Water",
)
```

---

## Feeding `normalize_positions` Into Compound Commands

`normalize_positions()` output (a `list[Position]`) can be pre-resolved once and passed
directly into any of the [compound commands](compound-commands/README.md)'
plate parameters (`dest_plate`, `source_plate`, `reagent_source`, `plate_id`) -- useful
when the set of wells you need doesn't correspond to a single selector expression, or
when you want to inspect/log the resolved positions before running the transfer.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import normalize_positions, WellOrder

TOTAL_SAMPLES = 17

with StarClient(deck_name="MyDeck") as star:
    star.instrument_init()

    # Resolve once: the first 17 wells of a 96-well plate, column-major order.
    target_positions = normalize_positions(
        "DestPlate@all", well_order=WellOrder.COL_ASC, total_wells=TOTAL_SAMPLES
    )
    print(f"Dispensing into {len(target_positions)} wells: "
          f"{[p.well for p in target_positions]}")

    result = star.add_reagent(
        reagent_source="ReagentTrough",
        dest_plate=target_positions,   # list[Position], not a selector string
        volume=50.0,
        tip_pool="TipPool300uL",
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    )
    print(f"Filled {result.wells_filled} wells in {result.iterations} iterations")
```

A single `Position` is also accepted (broadcast the same way a single-well selector
string would be):

```python
star.add_reagent(
    reagent_source=normalize_positions("ReagentTrough@A1")[0],  # a bare Position
    dest_plate="DestPlate@col:1",
    volume=50.0,
    tip_pool="TipPool300uL",
    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)
```

The same pattern works identically for `pool_samples`'s `source_plate`/`dest_plate`,
`replicate_samples`'s `source_plate`/`dest_plate`, and `serial_dilution_by_volume`/
`serial_dilution_by_dilution_factor`'s `plate_id`.

---

## See Also

- [Liquid Handling](liquid-handling.md) -- aspirate/dispense examples and settings reference
- [Compound Commands](compound-commands/README.md) -- add_reagent, pool_samples, replicate_samples, serial_dilution, copy_plate, hit_picking
