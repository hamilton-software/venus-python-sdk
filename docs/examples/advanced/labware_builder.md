# Labware Builder

Guide for building a labware definition from scratch in Python — plates, reservoirs and tubes — and registering it with VENUS, without starting from an existing definition or a VENUS labware file.

---

## Overview

`hamilton_venus.labware_builder` produces the JSON object that `labware_add_definition()` sends to VENUS. It covers:

- **Plates and reservoirs** — one rectangular grid of identical wells
- **Tubes** — a single sample tube, placed on a tube carrier

Tube racks, tip racks, carriers and lids are not covered.

Building a definition is always two steps:

1. Describe **one well** with `round_well()` or `rectangular_well()`.
2. Wrap it with `build_labware_definition()` (plate or reservoir) or `build_tube_definition()` (tube).

The result is a plain `dict`. Anything the helpers do not set can be changed on it directly before it is sent.

All lengths are in **millimetres**.

---

## Quick Start

```python
from hamilton_venus import StarClient
from hamilton_venus.labware_builder import build_labware_definition, round_well

definition = build_labware_definition(
	"My_96_DW",
	height=42.0,
	rows=8,
	columns=12,
	first_well_center=(14.0, 11.5),
	well=round_well(diameter=6.5, depth=40.0, bottom="round"),
)

with StarClient() as star:
	star.labware_add_definition("My_96_DW", definition)

	# The new definition is used by name, exactly like a catalog one.
	star.add_plate(labware_definition="My_96_DW", carrier_id="PlateCarrier", site="1", plate_id="Plate1")
```

The name passed to `build_labware_definition()` and to `labware_add_definition()` should be the same. It must be unique: adding fails if a definition with that name already exists.

---

## Step 1: Describe the Well

### Round wells

```python
from hamilton_venus.labware_builder import round_well

flat = round_well(diameter=6.9, depth=11.3)
deep = round_well(diameter=6.5, depth=40.0, bottom="round", bottom_height=2.5)
pcr = round_well(diameter=6.0, depth=20.5, bottom="cone", bottom_height=12.0)
```

| `bottom` | Shape | `bottom_height` |
|----------|-------|-----------------|
| `"flat"` (default) | Plain cylinder | Must not be given |
| `"round"` | Cylinder ending in a spherical cap | Optional; defaults to the well radius (a full hemisphere) and cannot exceed it |
| `"cone"` | Cylinder ending in a cone that tapers to a point | Required |

`depth` is always the full depth of the well, including the shaped bottom. The volume-versus-height curve VENUS uses is derived from this shape.

### Rectangular wells and troughs

```python
from hamilton_venus.labware_builder import rectangular_well

trough = rectangular_well(width=108.0, length=72.0, depth=38.0, clld_mode=4)
```

`width` is the opening's X size (left to right) and `length` its Y size (front to back). Rectangular wells are flat-bottomed.

### Well parameters

`round_well()` and `rectangular_well()` share these keyword arguments:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bottom_wall_thickness` | `1.0` | Plastic under the well, from the inside floor to the outside bottom |
| `max_pipetting_depth` | `0.0` | Maximum safe pipetting depth. Most shipped plates use `0.0`; most shipped tubes use `1.0` |
| `supports_lld` | `True` | Whether liquid level detection can be used. When `False`, no liquid seeking start height is written |
| `clearance` | 5 mm above the top of the labware | Height above the labware base the tip must reach to move clear of the well |
| `liquid_seeking_start_height` | same as `clearance` | Height above the labware base at which the channel starts searching for liquid |
| `clld_mode` | not written | VENUS capacitive LLD setting for the container. Shipped plates use `1`–`3`, shipped reservoirs use `4` |
| `touch_off` | disabled | Touch-off settings from `touch_off()` |

`clearance` and `liquid_seeking_start_height` are filled in when the well is passed to a `build_*` function, because their defaults depend on the labware height:

| You set | Clearance | Liquid seeking start height |
|---------|-----------|-----------------------------|
| neither | top of labware + 5 | same as clearance |
| `clearance=50.0` | 50.0 | 50.0 |
| `liquid_seeking_start_height=41.0` | top of labware + 5 | 41.0 |
| both | as given | as given |

### Touch off

```python
from hamilton_venus.labware_builder import round_well, touch_off

well = round_well(diameter=6.5, depth=40.0, touch_off=touch_off(2.9, 32.0))
```

`touch_off(distance, height, base=0.0)` enables touch off. `distance` is the distance from the well centre toward the wall, used for all four sides; `height` is measured from the well floor.

---

## Step 2: Build the Definition

### Plates

```python
from hamilton_venus.labware_builder import build_labware_definition, round_well

plate = build_labware_definition(
	"My_384_Flat",
	height=14.4,
	rows=16,
	columns=24,
	row_pitch=4.5,
	column_pitch=4.5,
	first_well_center=(11.75, 9.25),
	well=round_well(diameter=3.6, depth=11.5),
)
```

### Footprint and body shape

`width` and `depth` are the **footprint** VENUS uses to place the labware on a carrier site. They default to `127.0` x `86.0`, which is what a standard (SBS) carrier site requires. If the footprint does not match the site, placing the labware fails with *"Invalid placement of labware. Either the labware has no defined boundary for boundary placement or the boundary will not fit the deck site selected."* Leave them at the default for anything that sits on a standard plate site, even though the real plate measures slightly differently (typically 127.76 x 85.48).

The **measured** outer shape goes into `body_segments` instead: a list of slices from the top of the labware down, each with a height and its outer X/Y size. VENUS uses this shape for its default grip parameters.

```python
from hamilton_venus.labware_builder import body_segment, build_labware_definition, round_well

plate = build_labware_definition(
	"My_96_Flat",
	height=14.4,
	rows=8,
	columns=12,
	first_well_center=(14.0, 11.5),
	well=round_well(diameter=6.9, depth=11.3),
	body_segments=[
		body_segment(height=11.9, width=124.0, depth=82.0),                      # upper body
		body_segment(height=2.5, width=127.76, depth=85.48, top_width=126.76),   # skirt, sloped in X
	],
)
```

| `body_segment()` argument | Description |
|---------------------------|-------------|
| `height` | Height of the slice |
| `width` | Outer X size at the bottom of the slice |
| `depth` | Outer Y size at the bottom of the slice |
| `top_width` | Outer X size at the top of the slice, for sloped sides. Defaults to `width` |
| `top_depth` | Outer Y size at the top of the slice. Defaults to `depth` |

The slice heights may add up to at most the labware `height`. When `body_segments` is omitted, no body shape is written.

Because well positions are given inside the footprint, `first_well_center` for a 96-well plate on the default footprint is `(14.0, 11.5)`, and `(11.75, 9.25)` for a 384-well plate.

### Reservoirs

```python
from hamilton_venus.labware_builder import build_labware_definition, rectangular_well

reservoir = build_labware_definition(
	"My_Trough",
	labware_class="reservoir",
	height=40.0,
	rows=1,
	columns=1,
	first_well_center=(63.5, 43.0),
	well=rectangular_well(width=108.0, length=72.0, depth=38.0, clld_mode=4),
)
```

### `build_labware_definition()` parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `name` | required | Labware name. Letters, digits, `_` and `-` only |
| `height` | required | Outer height, from base to top |
| `rows` | required | Number of well rows (along Y) |
| `columns` | required | Number of well columns (along X) |
| `first_well_center` | required | `(x, y)` centre of the first well (A1) inside the footprint. X from the left edge, Y from the back edge |
| `well` | required | The well shared by every position, from `round_well()` or `rectangular_well()` |
| `width` | `127.0` | Footprint along X. Keep the default for a standard carrier site |
| `depth` | `86.0` | Footprint along Y. Keep the default for a standard carrier site |
| `body_segments` | none | Measured outer shape, as a list of `body_segment()` from the top down |
| `labware_class` | `"plate"` | `"plate"` or `"reservoir"` |
| `row_pitch` | `9.0` | Centre-to-centre spacing between rows |
| `column_pitch` | `9.0` | Centre-to-centre spacing between columns |
| `well_floor_height` | `height` − well depth | Height of the inside well floor above the labware base. The default puts the well opening flush with the top of the labware |
| `iteration_order` | `"row_major"` for plates, `"column_major"` otherwise | How wells are numbered 1..N. The defaults follow the shipped definitions |
| `stack_height` | `0.0` | Height added per plate when stacked on itself |
| `description` | none | Free-text description |
| `publisher` | `"user"` | Prefix of the definition `id` (`"user:My_384_Flat"`) |

> Most real plates have a skirt, so the well floor is closer to the base than the default assumes. Measure it and pass `well_floor_height` when accuracy at the bottom of the well matters.

### Tubes

```python
from hamilton_venus.labware_builder import build_tube_definition, round_well

tube = build_tube_definition(
	"My_Tube_17x75",
	tube=round_well(
		diameter=14.3,
		depth=73.8,
		bottom="round",
		bottom_wall_thickness=1.1,
		max_pipetting_depth=1.0,
	),
)
```

For a tube, the `round_well()` values mean:

| `round_well()` argument | Meaning for a tube |
|-------------------------|--------------------|
| `diameter` | Diameter at the top of the tube |
| `depth` | Full height of the tube |
| `bottom_wall_thickness` | Height of the inside floor above the outside bottom |

### `build_tube_definition()` parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `name` | required | Tube name. Letters, digits, `_` and `-` only |
| `tube` | required | The tube body, from `round_well()` |
| `material` | `"polypropylene"` | Tube material, as a lowercase identifier |
| `description` | none | Free-text description |
| `publisher` | `"user"` | Prefix of the definition `id` |

A generated tube is placed on a tube carrier by name:

```python
star.labware_add_definition("My_Tube_17x75", tube)
star.add_tube_carrier(labware_definition=LABWARE.TUBE_RACK.SMP_CAR_24_17X75, left_track=14, labware_id="TubeCarrier")
star.add_tubes_to_carrier("TubeCarrier", [{"position": "1", "tube": "My_Tube_17x75"}])
```

---

## Complete Example

Builds a plate and a tube, places both on the deck, removes the definitions again, and pipettes into the plate. The full script is `example_scripts/dynamic_labware_example.py`.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.labware_builder import body_segment, build_labware_definition, build_tube_definition, round_well

plate_definition = build_labware_definition(
	"Example_96_Flat",
	height=14.4,
	rows=8,
	columns=12,
	first_well_center=(14.0, 11.5),
	well=round_well(diameter=6.9, depth=11.3),
	body_segments=[
		body_segment(height=11.9, width=124.0, depth=82.0),
		body_segment(height=2.5, width=127.76, depth=85.48),
	],
)
tube_definition = build_tube_definition(
	"Example_Tube_17x75",
	tube=round_well(diameter=14.3, depth=73.8, bottom="round", bottom_wall_thickness=1.1, max_pipetting_depth=1.0),
)

with StarClient(simulate=True) as star:
	star.labware_add_definition("Example_96_Flat", plate_definition)
	star.labware_add_definition("Example_Tube_17x75", tube_definition)

	star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP, left_track=8, labware_id="PlateCarrier")
	star.add_plate(labware_definition="Example_96_Flat", carrier_id="PlateCarrier", site="5", plate_id="ExamplePlate")

	star.add_tube_carrier(
		labware_definition=LABWARE.TUBE_RACK.SMP_CAR_24_17X75, left_track=14, labware_id="TubeCarrier"
	)
	star.add_tubes_to_carrier("TubeCarrier", [{"position": "1", "tube": "Example_Tube_17x75"}])

	# Optional: remove the definitions again once the labware is on the deck.
	star.labware_delete_definition("Example_96_Flat")
	star.labware_delete_definition("Example_Tube_17x75")
```

---

## Changing a Built Definition

The builder returns a plain dict, so fields it does not cover can be set directly:

```python
definition = build_labware_definition(...)

well = definition["containerGrids"]["default"]["containerDefinition"]
well["customAttributes"]["hamilton:touch_off"]["frontMm"] = 2.5
definition["material"] = "polystyrene"
```

To change a definition that is already registered, send the edited dict with `labware_update_definition()`. Definitions shipped with the SDK are read-only and cannot be updated; add a copy under a new name instead.

---

## What the Builder Writes for VENUS

VENUS generates its own rack and container files from the definition and takes several values from Hamilton `customAttributes`. The builder always writes them, mirroring the definitions shipped with the SDK:

| Attribute | Where | Value |
|-----------|-------|-------|
| `hamilton:clearance` | well | `clearance`, or top of labware + 5 mm |
| `hamilton:touch_off` | well | from `touch_off()`, or disabled |
| `hamilton:clld_mode` | well | `clld_mode`, only when given |
| `hamilton:ix_params` | grid (plates and reservoirs) | first index 1, starting at the back-left corner |
| `hamilton:is_user_defined` | definition | `true` |
| `hamilton:body_segments` | definition | from `body_segments`, only when given (with matching `collisionShapes`) |

VENUS validates every definition against the labware schema when it is added or updated, and rejects it with the list of violations if it does not conform.

---

## API Reference

| Function | Returns | Description |
|----------|---------|-------------|
| `round_well(diameter, depth, *, bottom="flat", bottom_height=None, ...)` | `dict` | Well or tube body with a circular opening |
| `rectangular_well(width, length, depth, ...)` | `dict` | Flat-bottomed rectangular well or trough |
| `touch_off(distance, height, *, base=0.0)` | `dict` | Enabled touch-off settings for a well |
| `body_segment(height, width, depth, *, top_width=None, top_depth=None)` | `dict` | One slice of the outer shell of a plate or reservoir |
| `build_labware_definition(name, *, height, rows, columns, first_well_center, well, width=127.0, depth=86.0, body_segments=None, ...)` | `dict` | Complete plate or reservoir definition |
| `build_tube_definition(name, *, tube, material="polypropylene", ...)` | `dict` | Complete tube definition |

---

## See Also

- [`custom_labware.md`](./custom_labware.md) — Adding, listing, updating and deleting labware definitions
- [`deck-and-layout.md`](../deck-and-layout.md) — `add_plate()`, `add_tube_carrier()`, `add_tubes_to_carrier()`
- [`../../labware_schema/schema-tour.md`](../../labware_schema/schema-tour.md) — Tour of the labware JSON schema
