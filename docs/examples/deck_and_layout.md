# Deck and Layout

Examples for building deck layouts at runtime and managing carriers.

The deck is divided into numbered *tracks* (1-based, counted from the left). A *carrier* is a rack placed on the deck starting at its `left_track`; it holds plates, tip racks, or tubes in numbered *sites*. Every item you add gets an ID (`labware_id`, `plate_id`, ...) that later calls use to refer to it, for example `carrier_id="PlateCarrier1"` or `positions="SourcePlate@col:1"`. Labware definition names such as `LABWARE.CARRIER.PLT_CAR_L5MD` come from the [static catalogs](../static_catalogs.md).

## Building a Deck Layout at Runtime

Define carriers, tip racks, and plates after initializing. `StarClient()` with defaults connects to the instrument automatically (without initializing it), so call `instrument_init()` first and then add the layout:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

with StarClient() as star:
    star.instrument_init()
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
        left_track=1,
        labware_id="TipCarrier1",
    )
    star.add_tip_rack(
        labware_definition=LABWARE.TIP_RACK.TIP_RACK_1000UL,
        carrier_id="TipCarrier1",
        site="1",
        tip_pool="TransferTips",
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=7,  # TIP_CAR_480BC is 6 tracks wide (tracks 1-6), so the next free track is 7
        labware_id="PlateCarrier1",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="SourcePlate",
    )

    channels = [1, 2, 3, 4, 5, 6, 7, 8]
    star.tip_pickup(channels=channels, tip_pool="TransferTips")
    star.aspirate(
        channels=channels,
        positions="SourcePlate@col:1",
        volumes=50.0,
        liquid_class=LIQUID_CLASSES.STAR.HIGHVOLUME_WATER_DISPENSEJET_EMPTY,
    )
    star.dispense(channels=channels, positions="SourcePlate@col:1", volumes=50.0)
    star.tip_eject(channels=channels)
```

### Carrier Widths

Carriers come in different widths, so check each one before placing the next. The width is in the definition, under `customAttributes["hamilton:star"]["widthAsTracks"]` (`customAttributes["hamilton:rck_properties"]["MlStarCarWidthAsT"]` for a sample / tube carrier). A carrier with neither takes its `dimensions["x"]` / 22.5 mm, the width of a track, rounded up:

```python
definition = star.labware_get_definition(LABWARE.CARRIER.TIP_CAR_480BC)       # before adding it
added = star.labware_get_params_from_id("TipCarrier1")                          # after adding it
```

Most plate and tip carriers are 6 or 7 tracks wide, reagent and sample/tube carriers 1 or 2, and `TIP_CAR_288` 4. A carrier at `left_track=t` that is `w` tracks wide takes tracks `t` to `t + w - 1`. The next carrier goes at `t + w` or later, and the last one must still fit the deck (`instrument_get_configuration()` reports `tracks`).

## Autoload Carrier Management

Load and unload carriers via the autoload mechanism (see [Autoload](./autoload.md) for details):

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    star.instrument_init()
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=5,
        labware_id="MyCarrier",
    )
    star.autoload_load_carrier_by_id("MyCarrier")

    occupied = star.autoload_is_track_occupied(track_id=5)
    print(f"Track 5 occupied: {occupied.return_parameters.is_occupied}")

    star.autoload_unload_carrier_by_id("MyCarrier")
```

## Lidded Plate Management

Add lidded plates to the deck and automatically manage both the plate and its associated lid.

### `add_lidded_plate()` — Add Lidded Plate with Automated Lid

Add a lidded plate to the deck layout and automatically track both the plate and its associated lid.

**Signature:**
```python
def add_lidded_plate(
    self,
    labware_definition: str,
    carrier_id: str,
    site: str,
    plate_id: str | None = None,
    lid_definition: str = LABWARE.LID.NUNC_LID,
) -> AddLiddedPlateResponse:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_definition` | `str` | ✓ | Labware definition identifier (e.g., `LABWARE.PLATE.NUN_96_FL_HB`) |
| `carrier_id` | `str` | ✓ | Carrier identifier to place the plate on |
| `site` | `str` | ✓ | Site position on the carrier |
| `plate_id` | `str \| None` | — | Custom plate ID (optional; auto-generated if not provided) |
| `lid_definition` | `str` | — | Lid definition identifier used by `labware.addLiddedPlate` (defaults to `LABWARE.LID.NUNC_LID`) |

**Returns:** `AddLiddedPlateResponse` with fields:
- `labware_name: str` — The created plate name (e.g., "test plate")
- `lid_name: str` — The automatically created lid name (e.g., "test plate_lid")

**Example:**

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    star.instrument_init()
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=10,
        labware_id="PlateCarrier1",
    )

    # Add a lidded plate to the deck
    result = star.add_lidded_plate(
        labware_definition=LABWARE.PLATE.NUN_96_FL_HB,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="MyLiddedPlate",
        lid_definition=LABWARE.LID.NUNC_LID,
    )

    print(f"Plate: {result.return_parameters.labware_name}")
    print(f"Lid: {result.return_parameters.lid_name}")

    # Both plate and lid are now in the layout and can be used in operations
```

## Channel Liquid Waste Management

- Add a channel liquid waste container to the active deck layout for collecting waste liquid from channel operations.

### `add_channel_liquid_waste()` — Add Channel Liquid Waste Container

Add a channel liquid waste container to the deck layout. This is typically used as a waste destination for tip ejections and liquid disposal operations.

**Signature:**
```python
def add_channel_liquid_waste(self) -> CommandResponse:
```

**Returns:** `CommandResponse` with fields:
- `return_status: str` — Status of the operation (e.g., "Success")
- `return_code: int` — Status code (0 for success)
- `return_parameters: dict` — Contains `labwareName: str` (typically "liquid_waste")

**Example:**

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    
    # Add channel liquid waste container to the deck
    result = star.add_channel_liquid_waste()
    
    print(f"Waste container: {result.return_parameters.get('labwareName')}")
    
    # Now you can eject tips and dispense waste to this container
    channels = [1, 2, 3, 4, 5, 6, 7, 8]
    star.tip_eject(channels=channels)  # Ejects to waste container
```

## Shift Labware

Apply relative X/Y/Z/angle offsets to a labware item's position in the deck layout without physically moving it via a gripper.

### `shift_labware()` — Shift Labware Position

**Signature:**
```python
def shift_labware(
    self,
    labware_name: str,
    relative_x: float = 0.0,
    relative_y: float = 0.0,
    relative_z: float = 0.0,
    relative_angle: float = 0.0,
) -> LayoutShiftLabwareResponse:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_name` | `str` | ✓ | Name of the labware to shift |
| `relative_x` | `float` | — | Offset in the X direction (mm). Defaults to `0.0`. |
| `relative_y` | `float` | — | Offset in the Y direction (mm). Defaults to `0.0`. |
| `relative_z` | `float` | — | Offset in the Z direction (mm). Defaults to `0.0`. |
| `relative_angle` | `float` | — | Rotational offset (degrees). Defaults to `0.0`. |

**Returns:** `LayoutShiftLabwareResponse` with fields:
- `return_parameters.x: float` — Resulting absolute X coordinate (mm)
- `return_parameters.y: float` — Resulting absolute Y coordinate (mm)
- `return_parameters.z: float` — Resulting absolute Z coordinate (mm)
- `return_parameters.angle: float` — Resulting absolute angle (degrees)

**Example:**

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    star.instrument_init()
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5_MTP,
        left_track=7,
        labware_id="PlateCarrier1",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.NUN_96_FL,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="Plate1",
    )

    result = star.shift_labware(
        labware_name="Plate1",
        relative_x=2.5,
        relative_y=-1.0,
    )

    rp = result.return_parameters
    print(f"New position: x={rp.x}, y={rp.y}, z={rp.z}, angle={rp.angle}")
```

## Tilt Labware

VENUS treats every plate as flat, so a plate on a tilt module needs each well's X and Z adjusted before it can be pipetted. `tilt_labware()` computes those offsets in Python from the plate's labware definition and sends them to VENUS (`labware.tiltLabware`), which applies them to the existing labware item:

- **Calls do not add up.** Every call is computed from the flat plate, so tilting 7° twice is the same as tilting once, and `tilt_degrees=0` returns every well to its nominal position.
- **Sample tracking is kept.** The labware item is not removed and re-added, so barcodes, volumes and well state survive the tilt and the return to flat.
- **Transport is blocked while tilted.** The CO-RE / QCG and iSWAP / IPG transport commands raise `LabwareTiltedError` for a tilted plate without sending anything to VENUS. Tilt it back to 0 first.
- **Plates only.** Reservoirs, tip racks, tubes and tube racks, and plates without a single rectangular well grid, raise `ValueError` before anything is sent.
- **Deck layout only.** It does not move the tilt hardware. Tilt the module to the same angle before calling it, and back to 0 before moving the plate. On an MFX Tilt Module, `TiltModuleClient.tilt_module_move_to_position()` does that; see [Tilt Module](./tilt_module.md#tilting-the-plate-in-the-deck-layout).
- **Split wells follow the tilt.** Wells split with [`split_wells()`](#split-wells) are rebuilt for the new angle, aim and margins (and the slot count can change).
- **Aims that keep the tip off the wall.** `DEEPEST_POINT` / `HIGHEST_POINT` put one tip as close to the low / high wall as it fits (see [Where a Tip Fits](#where-a-tip-fits-in-a-tilted-well)). If no tip fits, `tilt_labware` raises `ValueError` before anything is sent, naming the largest angle that would fit.

### `tilt_labware()` — Tilt a Plate

**Signature:**
```python
def tilt_labware(
    self,
    labware_name: str,
    tilt_degrees: float,
    pivot_point: TiltPivotPoint = TiltPivotPoint.LEFT_EDGE,
    *,
    pivot_x_offset_mm: float = 0.0,
    pivot_z_offset_mm: float = 0.0,
    well_position: TiltWellPosition = TiltWellPosition.CENTER,
    measured_tilt_degrees: float | None = None,
    tip_end_height_mm: float = 0.0,
    wall_margin_mm: float = 1.0,
    high_wall_margin_mm: float = 2.0,
    tip_profile: TipProfile | None = None,
) -> LayoutTiltLabwareResponse:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_name` | `str` | ✓ | Name of the plate on the deck. |
| `tilt_degrees` | `float` | ✓ | The angle the tilt module is commanded to, 0 (flat) to 10; fractions are accepted. Positive raises the right side. This is what VENUS gets. |
| `pivot_point` | `TiltPivotPoint` | — | Hinge line on the plate base: `LEFT_EDGE` (default; the right side rises) or `CENTER` (middle of the footprint; the right half rises and the left half drops). |
| `pivot_x_offset_mm` | `float` | — | Measured hinge X offset from the pivot point; positive toward -X. Defaults to `0.0`. See [Calibrating a Tilt Module](#calibrating-a-tilt-module). |
| `pivot_z_offset_mm` | `float` | — | Measured hinge Z offset below the labware base; positive toward -Z. Defaults to `0.0`. |
| `well_position` | `TiltWellPosition` | — | Where in each well to aim one tip: `CENTER` (default), `DEEPEST_POINT` (as close to the low wall as the tip fits) or `HIGHEST_POINT` (as close to the high wall as it fits). Ignored at 0 degrees, which always uses the center. |
| `measured_tilt_degrees` | `float \| None` | — | The angle the plate really sits at, if it differs from `tilt_degrees` (e.g. 10.8 on a module commanded to 10; up to 15). The offsets are computed for it. |
| `tip_end_height_mm` | `float` | — | How far above the well floor the tip end will be: the fixed height you aspirate / dispense at. `0.0` (default) is the most conservative. Tilt again if it changes. |
| `wall_margin_mm` | `float` | — | Gap kept between the tip and the low wall. Defaults to `1.0`. |
| `high_wall_margin_mm` | `float` | — | Gap kept between the tip and the high wall. Defaults to `2.0`: the high wall leans in over the tip, so errors in the angle, hinge or teaching reach it first. |
| `tip_profile` | `TipProfile \| None` | — | The tip's shape. Defaults to a 1000 uL CO-RE tip. Pass the real tip's profile for smaller tips (e.g. 300 uL) or narrow wells (see [Tip Profiles](#tip-profiles)). `split_wells` reuses it. |

**Returns:** `LayoutTiltLabwareResponse` with fields:
- `return_parameters.labware_name: str`
- `return_parameters.tilt_degrees: float`
- `return_parameters.wells: list[LabwareWellCoordinates]` — each well's deck coordinates (`well`, `x`, `y`, `z`) after the tilt

Related: `is_labware_tilted(labware_name)` and `get_tilted_labware()` report the SDK's tilt state, and `get_tilt_settings(labware_name)` returns the angle, aim, tip and margins of the last tilt. `hamilton_venus.tilt_geometry.compute_tilt_well_deltas()` and `well_aim_x_shift()` preview the offsets and the aim for a definition without VENUS.

**Example** — wash cells: remove media from the deep side, add buffer down the high side (full script: `example_scripts/tilt_labware_example.py`):

```python
from hamilton_venus import VantageClient
from hamilton_venus.models import TiltWellPosition

with VantageClient() as vantage:
    # ... deck with "CellPlate" moved onto the tilt module's site, tips picked up ...
    # Aim as close to the low wall as a tip 1 mm above the floor fits (the fixed height used below).
    vantage.tilt_labware("CellPlate", 7, well_position=TiltWellPosition.DEEPEST_POINT, tip_end_height_mm=1.0)
    vantage.aspirate("CellPlate@col:1", channels=channels, volumes=140.0,
                     liquid_class=liquid_class, settings=fixed_height_settings)

    # Same angle, re-aimed at the high wall -- calls do not add up.
    vantage.tilt_labware("CellPlate", 7, well_position=TiltWellPosition.HIGHEST_POINT, tip_end_height_mm=1.0)
    vantage.dispense("CellPlate@col:1", channels=channels, volumes=150.0, settings=dispense_settings)

    vantage.tilt_labware("CellPlate", 0)  # flat again; transport is allowed
```

Liquid level detection and liquid following assume vertical wells: on a tilted plate use fixed heights with both off.

### Where a Tip Fits in a Tilted Well

The channels stay vertical while the well tilts, so a tip's position across the well changes with height: it moves away from the low wall going up, and toward the high wall, which leans in over it. The SDK (`hamilton_venus.tilt_clearance`) checks the tip's surface against the wall at the tip end, at each change in the well's shape and at the rim, with:

- the tip's shape (`tip_profile`, a cone from the tip end);
- where the tip end sits (`tip_end_height_mm` above the floor);
- a margin to each wall: `wall_margin_mm` (low wall, default 1.0 mm) and `high_wall_margin_mm` (high wall, default 2.0 mm).

`DEEPEST_POINT` / `HIGHEST_POINT` are the closest aims that keep those margins. On a 6-well plate measured on a real tilt module (36 mm straight wells, 15.8 mm deep) at 10 degrees, with the tip end 2 mm above the floor, a 1000 uL tip ends up this far from the well center (lab X); [`split_wells`](#split-wells) gives the 2- to 4-tip rows:

| Tips per well | Low wall (`DEEPEST_POINT`) | High wall (`HIGHEST_POINT`) |
|---|---|---|
| 1 | 16.5 mm | 11.0 mm |
| 2 | 15.9 mm | 10.2 mm |
| 3 | 13.8 mm | 7.7 mm |
| 4 | 9.0 mm | 0.6 mm |

Narrow or deep wells may have no room for a tip at all once tilted: with the default 1000 uL profile, 96-well plates do not fit at 10 degrees. `tilt_labware` then raises `ValueError` for `DEEPEST_POINT` / `HIGHEST_POINT` (with the largest angle that would fit) and logs a warning for `CENTER`. Use a smaller angle, the real (narrower) tip's profile, the real tip end height, or smaller margins.

The margins are a starting point, checked on one module: not every tilt module or teaching is the same, so check them on your instrument (for example, step the tip toward each wall with VENUS "Move Probe - Key Control").

### Calibrating a Tilt Module

A module commanded to 10 degrees may hold the plate at a slightly different angle, and its hinge is a pin under the plate rather than the plate's lower-left corner that `tilt_labware` assumes by default. On the module tested, the plate sat at about 10.8 degrees, and the hinge was about 6 mm below the plate base: left uncorrected, that moves every well about 2 mm in X at 10 degrees.

`hamilton_venus.tilt_calibration.fit_tilt_hinge()` works both out from four probe readings: two points far apart along X (e.g. where the left wall of a well meets the floor, in the first and last column of one row), read with the module flat and tilted. Example script: `example_scripts/tilt_module_fit_hinge.py`.

```python
from hamilton_venus.models import TiltWellPosition
from hamilton_venus.tilt_calibration import fit_tilt_hinge

# star: a connected StarClient with "Plate" on the tilt module's site
fit = fit_tilt_hinge(
    flat={"B1": (424.7, 203.0), "B3": (504.9, 203.0)},      # deck (X, Z), module flat
    tilted={"B1": (423.0, 203.4), "B3": (502.1, 218.5)},    # the same points at 10 degrees
    commanded_degrees=10,
    plate_left_edge_x=418.9,                                # the plate when flat, from the deck layout
    plate_base_z=199.65,
)
print(fit.best)            # angle 10.81, pivot_x_offset_mm -2.76, pivot_z_offset_mm +4.57, rms 0.12 mm
print(fit.flat_span_mm)    # 80.2 over two columns: a 40.1 mm pitch -- compare with the labware definition
print(fit.span_change_mm)  # +0.33: a rigid plate keeps its span; much more than ~0.5 mm means a bad reading
star.tilt_labware("Plate", 10, well_position=TiltWellPosition.DEEPEST_POINT, **fit.tilt_labware_kwargs())
```

`fit.at_commanded` is the hinge for exactly the commanded angle (here `+0.7` / `+5.5` mm), for when you would rather not pass a measured angle. Keep the numbers with the module: they belong to that unit.

### Check the Plate's Labware Definition

The tilt offsets are only as good as the plate's definition. The converted culture-plate definitions are best-effort: `Greiner_Culture_Plate_6` has a 38.9 mm column pitch, while the plate measured on the tilt module had 40.1 mm, straight 36 mm wells 15.8 mm deep, and a floor 1.1 mm higher. Measure the plates you tilt (`fit_tilt_hinge`'s `flat_span_mm` gives the real pitch between the probed columns) and register a corrected definition with `labware_add_definition` when they differ.

### `add_tubes_to_carrier()` — Add Tubes to a Sample Tube Carrier

Place individual tubes into a previously loaded sample tube carrier and return the resulting absolute coordinates for each tube. Optional X/Y/Z offsets allow fine-tuning each tube's position relative to its nominal carrier site.

**Signature:**
```python
def add_tubes_to_carrier(
    self,
    labware_name: str,
    positions: list[dict | TubePositionInput],
) -> LayoutAddTubesToCarrierResponse:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_name` | `str` | ✓ | Name of the sample tube carrier already on the deck. |
| `positions` | `list[dict \| TubePositionInput]` | ✓ | One entry per tube. Each entry has `position` (carrier slot, e.g. `"1"`), `tube` (tube labware definition filename from the SDK's `Labware/Tubes/` directory, e.g. `"Tub_17x75_FlipTop_A00"`), and optional `xOffset`/`yOffset`/`zOffset` in mm. |

**Returns:** `LayoutAddTubesToCarrierResponse` with `return_parameters.positions: list[TubePositionResult]`, each containing:
- `position: str` — Carrier slot identifier
- `x: float` — Resulting absolute X coordinate (mm)
- `y: float` — Resulting absolute Y coordinate (mm)
- `z: float` — Resulting absolute Z coordinate (mm)

**Example:**

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    star.instrument_init()
    star.add_tube_carrier(
        labware_definition=LABWARE.TUBE_RACK.SMP_CAR_24_17X75,
        left_track=10,
        labware_id="TubeCarrier1",
    )

    result = star.add_tubes_to_carrier(
        labware_name="TubeCarrier1",
        positions=[
            {"position": "1", "tube": "Tub_17x75_FlipTop_A00", "zOffset": 10.0},
            {"position": "2", "tube": "Tub_17x75_FlipTop_A00", "zOffset": 10.0},
            {"position": "3", "tube": "Tub_17x75_FlipTop_A00", "zOffset": 10.0},
        ],
    )

    for tube in result.return_parameters.positions:
        print(f"  position={tube.position}: x={tube.x}, y={tube.y}, z={tube.z}")
```

---

## Split Wells

A large well (6-, 12- or 24-well plate, 50 mL tube) has room for more than one channel. VENUS can only send every channel to the well's center, though. `split_wells()` gets around that by placing a temporary rack of **slots** inside each chosen well, one slot per channel. The slots are spaced at the channel pitch along Y: 9 mm for 1 mL channels, 18 mm for 5 mL.

- **Pipetting is routed automatically.** After a split, an `aspirate` / `dispense` / `detect_liquid_level` call that sends two or more channels of the split's type to the same well goes to its slots. Channel `c` goes to slot `c - first channel + 1`, so channels 1-4 use slots 1-4 and channels `[1, 3]` use slots 1 and 3. A single channel still goes to the well center. Asking for more channels than the well has slots raises `SplitWellCapacityError` before anything is sent.
- **The well's own container.** Every slot gets the parent well's container, so its depth, Z bottom and liquid level detection behave as in the parent well. On a V- or round-bottom well, the outer slots sit on the sloped floor.
- **Sized from the well, the tip and the tilt.** The SDK works out how many tips fit in the well and where, in `hamilton_venus.split_well_geometry`, from three things:
  - the well's shape in its labware definition;
  - the tip's shape (`TipProfile`; the defaults are measured 1000 uL and 5000 uL CO-RE tips);
  - on a tilted plate, the angle, the point in the well being aimed at, the tip end height and the wall margins (the same math as [`tilt_labware`](#where-a-tip-fits-in-a-tilted-well); by default the values passed to `tilt_labware`).
- **The splits follow the plate.**
  - `tilt_labware`, `shift_labware`, `move_carrier` and the CO-RE / QCG / iSWAP transports remove the slots and rebuild them at the plate's new position.
  - A plate picked up by `*_present_and_scan` / `iswap_get_labware` gets its slots back on `*_return_plate` / `iswap_put_labware`.
  - `remove_labware` (of the plate, or of its carrier) and the to-waste transports remove them.
  - `deck_load` forgets them.
- **A deck-layout feature only.** The slot racks are labware that VENUS uses for positioning. They are not tracked as carrier sites.

### `split_wells()` — Pipette Several Channels in One Well

**Signature:**
```python
def split_wells(
    self,
    labware_name: str,
    wells: str | list[str] | None = None,
    *,
    channel_type: SplitChannelType = SplitChannelType.ONE_ML,
    max_channels: int | None = None,
    fit: SplitWellFit | int = SplitWellFit.POSITION,
    well_position: TiltWellPosition | None = None,
    tip_profile: TipProfile | None = None,
    tip_end_height_mm: float | None = None,
    wall_margin_mm: float | None = None,
    high_wall_margin_mm: float | None = None,
) -> list[SplitWellSite]:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_name` | `str` | ✓ | The plate (or other labware) holding the wells. |
| `wells` | `str \| list[str] \| None` | — | Wells to split. Either a selector as used by pipetting steps, without the labware part (`"A1"`, `"A1:B3"`, `"row:A"`), or a list of well names. `None` (the default) splits every well. |
| `channel_type` | `SplitChannelType` | — | `ONE_ML` (default, 9 mm slot pitch) or `FIVE_ML` (18 mm). Only channels of this type are routed to the slots. |
| `max_channels` | `int \| None` | — | Most slots per well. Defaults to the number of channels installed. |
| `fit` | `SplitWellFit \| int` | — | What to give up when a well is narrow where the tips go (see [Narrow Wells](#narrow-wells-the-fit-option)): `POSITION` (default), `MAX_CHANNELS`, or a channel count. |
| `well_position` | `TiltWellPosition \| None` | — | Where to aim the slots across a tilted well. Defaults to where `tilt_labware` aimed the plate. It has no effect on a flat plate. |
| `tip_profile` | `TipProfile \| None` | — | Tip shape used to decide what fits. Defaults to the profile passed to `tilt_labware` (for `ONE_ML` splits), else the measured profile for `channel_type`. |
| `tip_end_height_mm` | `float \| None` | — | How far above the floor the tip ends will be. Defaults to `tilt_labware`'s, else `0.0`. |
| `wall_margin_mm` | `float \| None` | — | Gap kept between the tips and the low wall (and the walls along the hinge). Defaults to `tilt_labware`'s, else `1.0`. |
| `high_wall_margin_mm` | `float \| None` | — | Gap kept between the tips and the high wall. Defaults to `tilt_labware`'s, else `2.0`. On a flat plate both walls use `wall_margin_mm`. |

Plain values (`"1mL"`, `"5mL"`, `"position"`, `"max_channels"`) are also accepted and validated. A misspelled value raises `ValueError` listing the enum members.

**Returns:** a `list[SplitWellSite]`, one per well that was split. Wells that can take only one channel are skipped, with a warning. Each `SplitWellSite` has:
- `parent_labware`, `parent_well`, `channel_type`
- `split_labware`: the slot rack's labware id, `<plate>_<well>_split_<1ml|5ml>_<N>slots`, where N is the slot count (e.g. `plate1_a1_split_1ml_4slots`)
- `slot_wells`: the rack's positions, `"1"`..`"N"` from the back. Slot 1 is where channel 1 goes.
- `slot_count`
- `coordinates`: each slot's deck coordinates as VENUS placed them
- `plan`: the computed `SplitWellPlan`. It holds the slot offsets from the parent well, `requested_x_shift` / `x_shift_applied`, and `limited_by` (`"chord"`: the well was the limit; `"max_channels"`: the channels were).

Splitting a well again replaces its split.

**Related:**

| Method | Description |
|--------|-------------|
| `remove_split_wells(labware_name=None, wells=None, *, channel_type=None, consolidate_volumes=False)` | Remove splits; pipetting goes to the well centers again. `consolidate_volumes=True` adds the volume tracked in the slots back onto the parent well, as STAR Tools' Split Wells does. Returns the removed rack ids. |
| `get_split_wells(labware_name=None)` | The wells currently split. |

**Example** — four channels into each well of a 6-well plate:

```python
from hamilton_venus import VantageClient
from hamilton_venus.models import SplitChannelType

with VantageClient() as vantage:
    # ... deck with "CellPlate" (Greiner_Culture_Plate_6), tips picked up on channels 1-4 ...
    sites = vantage.split_wells("CellPlate", "A1:B3", channel_type=SplitChannelType.ONE_ML)
    print([(s.parent_well, s.slot_count) for s in sites])   # [('A1', 4), ('B1', 4), ...]

    # Four channels on one well -> its four slots, 9 mm apart.
    vantage.dispense("CellPlate@A1", channels=[1, 2, 3, 4], volumes=500.0, settings=dispense_settings)

    vantage.remove_split_wells("CellPlate", consolidate_volumes=True)
```

Slots per well on the Greiner culture plates, flat, with the default tip profiles:

| Plate | 1 mL channels (9 mm) | 5 mL channels (18 mm) |
|---|---|---|
| Greiner_Culture_Plate_6 | 4 | 2 |
| Greiner_Culture_Plate_12 | 2 | 1 (not split) |
| Greiner_Culture_Plate_24 | 2 | 1 (not split) |

### Narrow Wells: the `fit` Option

The channels line up along Y, so the room available is the width of the well along Y at the X where the tips go. On a plate tilted to its deepest point (`tilt_labware(..., well_position=TiltWellPosition.DEEPEST_POINT)`), the tips go near the low wall, where a round well is much narrower than across its center. A tilted well also leans, so a vertical tip's position across the well changes between the floor and the opening. The SDK checks that each tip clears the wall at both.

`fit` chooses the trade-off:

| `fit` | Behavior |
|---|---|
| `SplitWellFit.POSITION` (default) | Keep the aim. At the center, use as many channels as fit there. At a wall (`DEEPEST_POINT` / `HIGHEST_POINT`), use as many channels as the well holds, as close to that wall as they fit (the same as `MAX_CHANNELS`). |
| `SplitWellFit.MAX_CHANNELS` | Use the most channels the well can hold, and stay as close to the aimed point as that allows. The slots are raised to match where they sit on the tilted floor. |
| `int` (e.g. `2`) | Exactly that many channels, as close to the aimed point as they fit. Fewer channels sit closer to the wall. Raises `ValueError` if the well cannot hold them. |

Greiner 6-well tilted 10 degrees, aimed at the deepest point, 1 mL channels, default margins, tip end on the floor:

| Channels | Offset from well center (plate frame) | Height above the 1-tip aim |
|---|---|---|
| 1 (`tilt_labware` alone) | 15.7 mm | 0 mm |
| `fit=2` | 15.0 mm | 0.1 mm |
| `POSITION`, `MAX_CHANNELS` or `fit=3` | 12.9 mm | 0.5 mm |

```python
from hamilton_venus.models import SplitWellFit, TiltWellPosition

vantage.tilt_labware("CellPlate", 10, well_position=TiltWellPosition.DEEPEST_POINT, tip_end_height_mm=1.0)
vantage.split_wells("CellPlate", "A1:B3")          # as many channels as fit, as close to the wall as they fit
vantage.split_wells("CellPlate", "A1:B3", fit=2)   # 2 channels, closer to the wall
```

The tips keep `wall_margin_mm` (default 1.0 mm) from the low wall and the walls along the hinge, and `high_wall_margin_mm` (default 2.0 mm) from the high wall. On an instrument, allow for channel positioning and plate seating accuracy: pass larger margins to `tilt_labware` (or `split_wells`) when you need more room.

### Tip Profiles

`TipProfile` models the tip as a cone from its end. The defaults come from measured CO-RE tips:

| Tip | Outside diameter at the end | 19.8 mm above the end | Body diameter (estimated) |
|---|---|---|---|
| 1000 uL (`SplitChannelType.ONE_ML`) | 1.2 mm | 5.4 mm | 8 mm |
| 5000 uL (`SplitChannelType.FIVE_ML`) | 1.8 mm | 6.0 mm | 10 mm |

Above the measured 19.8 mm, the cone is assumed to continue up to the body diameter. This only matters for wells deeper than about 20 mm, such as tubes.

The 1 mL channels also take smaller tips (300 uL, 50 uL), which are narrower: the 1000 uL default is conservative for them, and narrow wells lose room. For another tip, build a profile from its outside diameter at the end, 19.8 mm above the end, and at its widest part, and pass it to `tilt_labware` (which `split_wells` then reuses) or to `split_wells`:

```python
from hamilton_venus.models import TiltWellPosition
from hamilton_venus.tilt_clearance import TipProfile

tip = TipProfile.from_measurements(1.0, 4.8, 19.8, max_diameter_mm=7.0)
vantage.tilt_labware("CellPlate", 10, well_position=TiltWellPosition.DEEPEST_POINT, tip_profile=tip)
vantage.split_wells("CellPlate", "A1")
```

Margins are passed separately (`wall_margin_mm`, `high_wall_margin_mm`), not on the profile.

`hamilton_venus.split_well_geometry.compute_split_well_plan()` previews the slots for a labware definition without VENUS.

## Recording Taught Locations

Persist operator-taught position corrections to
`C:\Program Files (x86)\Hamilton\SDK\Active Layout\TaughtLocations.json` so a VENUS
method can read them back and enforce them. These calls are local file I/O only —
no instrument connection is required, and nothing is sent to the VENUS runtime.

The Active Layout folder, `TaughtLocations.json` included, is cleared each time a
new session connects. To keep taught locations for a later session, save the deck
with `deck_save(...)` after registering, then start that session from it with
`deck_name=...`; loading the saved deck restores the file.

Two record kinds live in one file:

- **`carrierSiteOffsets`** — a relative `dx/dy/dz` (+ angle) correction, keyed by
  `"<carrier>/<site>"`.
- **`labwarePositions`** — absolute `x/y/z` (+ angle) coordinates, keyed by labware
  name **then** by `"<carrier>/<site>"`, so one plate can carry different
  coordinates on different sites.

Each `register_*` call is *latest-wins* (it replaces the record under that key).
VENUS is expected to look a plate up in `labwarePositions[<plate>]["<carrier>/<site>"]`
first and fall back to `carrierSiteOffsets["<carrier>/<site>"]` —
`resolve_taught_location()` mirrors that order.

`labware`, `carrier` and `site` are stored **lower-cased** (record fields and map
keys alike), so `"Plate1"` and `"plate1"` are the same entry — the VENUS side must
lower-case before it builds a key.

```python
from hamilton_venus import VantageClient

with VantageClient(auto_connect=False) as vantage:
    # A carrier/site offset (e.g. operator jogged the arm and read back a delta)
    vantage.register_taught_offset(
        "CAR_1", 3, dx=0.42, dy=-0.18, dz=0.10, note="teach 2026-09-01"
    )

    # Absolute coordinates taught for one plate on two different sites
    vantage.register_taught_position("Plate_01", "CAR_1", 3, x=123.45, y=210.90, z=95.20)
    vantage.register_taught_position("Plate_01", "CAR_1", 4, x=123.45, y=304.10, z=95.20)

    # Direct keyed lookups
    print(vantage.get_taught_position("Plate_01", "CAR_1", 3))
    print(vantage.get_taught_positions("Plate_01"))   # {"CAR_1/3": ..., "CAR_1/4": ...}
    print(vantage.get_taught_offset("CAR_1", 3))

    # Resolve the way VENUS will: plate-at-site first, then the carrier/site offset
    print(vantage.resolve_taught_location("Plate_99", "CAR_1", 3))  # -> CarrierSiteOffset

    # Inspect / prune
    doc = vantage.get_taught_locations()
    print(list(doc.labware_positions), list(doc.carrier_site_offsets))
    vantage.remove_taught_position("Plate_01", "CAR_1", 4)  # one site
    vantage.remove_taught_position("Plate_01")              # all sites for the plate
    vantage.clear_taught_locations()
```

Without a client, call the same functions from `hamilton_venus.taught_locations`
with an explicit `path=` (they also expose `carrier_site_key(carrier, site)` so
the VENUS side can build the identical map key).
