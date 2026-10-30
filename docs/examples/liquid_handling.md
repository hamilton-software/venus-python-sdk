# Liquid Handling

Examples for aspirate, dispense, and transfer operations using individual channels.

The examples assume a deck that already contains a tip pool `"TransferTips"` and plates with labware IDs `"SourcePlate"` and `"DestPlate"` — load it with `StarClient(deck_name=...)` or build it in code (see [Common Patterns](common_patterns.md#pattern-1-setup--execute--cleanup-standard)). `liquid_class="Water"` (and similar short names) are placeholders: use a liquid class name from your VENUS installation, such as `LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY` from `hamilton_venus.catalog`.

## Simple Liquid Transfer

Transfer 50 uL from a source plate to a destination plate using the default 8 channels:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="LiquidTransferDeck") as star:
    star.instrument_init()

    star.tip_pickup(tip_pool="TransferTips")
    star.aspirate(positions="SourcePlate@col:1", volumes=50.0, liquid_class="Water")
    star.dispense(positions="DestPlate@col:1", volumes=50.0)
    star.tip_eject()
```

## Simple Liquid Transfer (Explicit Channels)

Explicitly specify which channels to use:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="LiquidTransferDeck") as star:
    star.instrument_init()
    channels = [1, 2, 3, 4, 5, 6, 7, 8]

    star.tip_pickup(channels=channels, tip_pool="TransferTips")
    star.aspirate(channels=channels, positions="SourcePlate@col:1", volumes=50.0, liquid_class="Water")
    star.dispense(channels=channels, positions="DestPlate@col:1", volumes=50.0)
    star.tip_eject(channels=channels)
```

## Reusable Liquid-Handling Settings

Define aspirate and dispense settings once, then reuse them across repeated calls.
Import `AspirateSettings` and `DispenseSettings` from `hamilton_venus.models`.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings
from hamilton_venus.models.enums import DispenseMode

aspirate_settings = AspirateSettings()
dispense_settings = DispenseSettings(dispense_mode=DispenseMode.FROM_LIQUID_CLASS)

with StarClient() as star:
    star.instrument_init()

    for col in range(1, 4):
        star.tip_pickup(tip_pool="TransferTips")
        star.aspirate(
            positions=f"SourcePlate@col:{col}",
            volumes=50.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
            settings=aspirate_settings,
        )
        star.dispense(
            positions=f"DestPlate@col:{col}",
            volumes=50.0,
            settings=dispense_settings,
        )
        star.tip_eject()
```

## Multi-Column Transfer

Iterate across multiple columns, changing tips between each:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    for col in range(1, 13):
        star.tip_pickup(tip_pool="TransferTips")
        star.aspirate(
            positions=f"SourcePlate@col:{col}",
            volumes=100.0,
            liquid_class="Water",
        )
        star.dispense(
            positions=f"DestPlate@col:{col}",
            volumes=100.0,
        )
        star.tip_eject()
```

## Variable Volumes Per Channel

Pass a list of volumes to aspirate/dispense different amounts per channel:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    channels = [1, 2, 3, 4]
    volumes = [10.0, 25.0, 50.0, 100.0]

    star.tip_pickup(channels=channels, tip_pool="TransferTips")
    star.aspirate(channels=channels, positions="SourcePlate@col:1", volumes=volumes, liquid_class="Water")
    star.dispense(channels=channels, positions="DestPlate@col:1", volumes=volumes)
    star.tip_eject(channels=channels)
```

## Aspirate with Mixing

Mix 3 times at 80 uL before aspirating:

```python
from hamilton_venus import StarClient
from hamilton_venus.models import AspirateSettings

mixing_settings = AspirateSettings(mix_cycles=3, mix_volume=80.0)

with StarClient() as star:
    star.instrument_init()

    star.tip_pickup(tip_pool="TransferTips")
    star.aspirate(
        positions="SourcePlate@col:1",
        volumes=100.0,
        liquid_class="Water",
        settings=mixing_settings,
    )
    star.dispense(positions="DestPlate@col:1", volumes=100.0)
    star.tip_eject()
```

---

## Aspirate Settings Reference

When using `aspirate()`, you can pass an `AspirateSettings` object to fine-tune aspiration behavior. All fields accept either a scalar value (applied uniformly to all channels) or a list with one entry per channel.

**`aspirate()` Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channels` | `list[int] \| None` | `[1, 2, 3, 4, 5, 6, 7, 8]` | Channel numbers to use |
| `positions` | `PositionInput` | *required* | Target positions (selector DSL or explicit) |
| `volumes` | `float \| list[float]` | *required* | Aspirate volume(s) in µL |
| `liquid_class` | `str \| list[str]` | *required* | Liquid class name (scalar or one per channel) |
| `settings` | `AspirateSettings \| None` | `None` | Reusable aspirate settings object |
| `well_order` | `WellOrder` | `COL_ASC` | Well expansion order for selector inputs |
| `mad_enabled` | `bool \| None` | `None` | Enable Monitored Air Displacement. Single value for all channels (not per-channel); `None` omits it from the wire call, so VENUS uses its own default (disabled) |
| `mad_threshold` | `int \| None` | `None` | MAD pressure threshold. Range 1-1023. Single value for all channels; `None` omits it, so VENUS uses its own default (`30`) |
| `adc` | `bool \| None` | `None` | Enable Aspiration/Dispense Control (TADM-based). Single value for all channels; `None` omits it, so VENUS uses its own default (disabled) |

**`AspirateSettings` Fields** (all accept scalar or per-channel list, except `tip_tracking_factor` which is scalar only):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `aspirate_mode` | `AspirateMode \| list[AspirateMode]` | `NORMAL` | Aspiration mode |
| `capacitive_lld` | `CapacitiveLLD \| list[CapacitiveLLD]` | `OFF` | Capacitive LLD sensitivity |
| `pressure_lld` | `PressureLLD \| list[PressureLLD]` | `OFF` | Pressure LLD sensitivity |
| `liquid_following` | `bool \| list[bool]` | `False` | Enable liquid surface following |
| `tip_tracking_factor` | `float` | `1.0` | Liquid-following movement factor. `0.5` tracks half the distance in the same time, `2.0` twice the distance; `1.0` is normal tracking. VENUS accepts `0.1`–`5.0`. Scalar only |
| `submerge_depth` | `float \| list[float]` | `2.0` | Submerge depth (mm) |
| `fixed_height` | `float \| list[float]` | `5.0` | Fixed height above bottom (mm) |
| `max_lld_difference` | `float \| list[float]` | `3.0` | Maximum LLD difference (mm) |
| `mix_cycles` | `int \| list[int]` | `0` | Number of mix cycles |
| `mix_position` | `float \| list[float]` | `0.0` | Mix position height (mm) |
| `mix_volume` | `float \| list[float]` | `0.0` | Mix volume (µL) |
| `air_transport_retract_dist` | `float \| list[float]` | `5.0` | Air-transport retract distance (mm) |
| `touch_off` | `int \| list[int]` | `0` | Enable touch-off (0=off, 1=on) |
| `touch_off_height` | `float \| list[float]` | `1.0` | Touch-off height (mm) |

---

## Dispense Settings Reference

When using `dispense()`, you can pass a `DispenseSettings` object to control dispensing behavior. Most fields accept scalar or per-channel lists, except `use_side_touch` and `tip_tracking_factor` which are scalar only. Dispense has no `liquid_class` parameter of its own — the liquid class used is whichever one the tip aspirated with.

**`dispense()` Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channels` | `list[int] \| None` | `[1, 2, 3, 4, 5, 6, 7, 8]` | Channel numbers to use |
| `positions` | `PositionInput` | *required* | Target positions (selector DSL or explicit) |
| `volumes` | `float \| list[float]` | *required* | Dispense volume(s) in µL |
| `settings` | `DispenseSettings \| None` | `None` | Reusable dispense settings object |
| `well_order` | `WellOrder` | `COL_ASC` | Well expansion order for selector inputs |
| `adc` | `bool \| None` | `None` | Enable Aspiration/Dispense Control (TADM-based). Single value for all channels; `None` omits it, so VENUS uses its own default (disabled) |

**`DispenseSettings` Fields:**

| Field | Type | Default | Per-channel? | Description |
|-------|------|---------|:------------:|-------------|
| `dispense_mode` | `DispenseMode \| list[DispenseMode]` | `FROM_LIQUID_CLASS` | ✓ | Dispense mode |
| `capacitive_lld` | `CapacitiveLLD \| list[CapacitiveLLD]` | `OFF` | ✓ | Capacitive LLD sensitivity |
| `liquid_following` | `bool \| list[bool]` | `False` | ✓ | Enable liquid surface following |
| `tip_tracking_factor` | `float` | `1.0` | ✗ | Liquid-following movement factor. `0.5` = half distance, `2.0` = twice; `1.0` is normal. VENUS accepts `0.1`–`5.0` (scalar only) |
| `submerge_depth` | `float \| list[float]` | `2.0` | ✓ | Submerge depth (mm) |
| `fixed_height` | `float \| list[float]` | `5.0` | ✓ | Fixed height above bottom (mm) |
| `mix_cycles` | `int \| list[int]` | `0` | ✓ | Number of mix cycles |
| `mix_position` | `float \| list[float]` | `0.0` | ✓ | Mix position height (mm) |
| `mix_volume` | `float \| list[float]` | `0.0` | ✓ | Mix volume (µL) |
| `air_transport_retract_dist` | `float \| list[float]` | `5.0` | ✓ | Air-transport retract distance (mm) |
| `touch_off` | `int \| list[int]` | `0` | ✓ | Enable touch-off (0=off, 1=on) |
| `touch_off_height` | `float \| list[float]` | `1.0` | ✓ | Touch-off height (mm) |
| `use_side_touch` | `bool` | `False` | ✗ | Enable side-touch (scalar only) |

---

## Position Selector DSL

All channel commands accept a selector DSL (domain-specific language) string for the `positions` parameter. Each call uses one well per channel: the first `len(channels)` wells of the expanded selection (a single well is repeated across all channels). Common patterns:

```python
# Single well
star.aspirate(channels=[1], positions="Plate1@A1", volumes=50.0, liquid_class="Water")

# Explicit well list
star.aspirate(channels=[1, 2, 3], positions="Plate1@A1,B1,C1", volumes=50.0, liquid_class="Water")

# Entire column
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Plate1@col:1", volumes=50.0, liquid_class="Water")

# Column range (8 channels use the first 8 wells: column 1)
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Plate1@col:1:3", volumes=50.0, liquid_class="Water")

# Row selection (rows A-D, column-ascending order: A1, B1, C1, D1)
star.aspirate(channels=[1, 2, 3, 4], positions="Plate1@row:A:D", volumes=50.0, liquid_class="Water")

# Well range (rectangular)
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8], positions="Plate1@A1:H1", volumes=50.0, liquid_class="Water")
```

For the full DSL syntax reference, see [Position and Well Selection](position_and_well_selection.md).

---

## Accessing Aspirate and Dispense Response Data

Both `aspirate()` and `dispense()` return typed response objects that provide access to per-channel data and TADM (Total Aspiration and Dispense Monitoring) curves.

### Per-Channel Response Data

Each aspirate operation returns a `ChannelAspirationResponse` with per-channel metrics:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="LiquidTransferDeck") as star:
    star.instrument_init()
    
    star.tip_pickup(channels=[1, 2], tip_pool="TransferTips")
    response = star.aspirate(
        channels=[1, 2],
        positions=["SourcePlate@A1", "SourcePlate@B1"],
        volumes=50.0,
        liquid_class="Water",
    )
    
    # Access per-channel aspirate data
    for channel_data in response.return_parameters.channels:
        print(f"Channel {channel_data.channel}:")
        print(f"  Aspirated volume: {channel_data.aspirated_volume} µL")
        print(f"  Liquid level: {channel_data.liquid_level_mm} mm")
        print(f"  Liquid volume: {channel_data.liquid_volume_ul} µL")
```

Similarly, `dispense()` returns a `ChannelDispenseResponse` with per-channel dispensed volumes:

```python
response = star.dispense(
    channels=[1, 2],
    positions=["DestPlate@A1", "DestPlate@B1"],
    volumes=50.0,
)

for channel_data in response.return_parameters.channels:
    print(f"Channel {channel_data.channel}: dispensed {channel_data.dispensed_volume} µL")
```

### Accessing TADM Curve Data

Both aspirate and dispense responses include TADM (Total Aspiration and Dispense Monitoring) curve data, which provides pressure curves for pipetting diagnostics and troubleshooting:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="LiquidTransferDeck") as star:
    star.instrument_init()
    
    star.tip_pickup(channels=[1], tip_pool="TransferTips")
    response = star.aspirate(
        channels=[1],
        positions="SourcePlate@A1",
        volumes=50.0,
        liquid_class="Water",
    )
    
    # Access TADM curves (only present when the instrument provides them)
    tadm_data = response.return_parameters.tadm
    if tadm_data is None:
        print("No TADM data in response")
    else:
        for curve in tadm_data.tadm_curves:
            print(f"TADM Curve (Channel {curve.channel_number}):")
            print(f"  Liquid class: {curve.liquid_class_name}")
            print(f"  Step type: {curve.step_type_name}")
            print(f"  Volume: {curve.volume} µL")
            print(f"  Timestamp: {curve.time_stamp}")
            print(f"  Curve points: {len(curve.curve_points)}")

            # Access individual pressure data points
            for i, point in enumerate(curve.curve_points):
                if point.time_ms is not None and point.pressure is not None:
                    print(f"    Point {i}: {point.time_ms}ms, {point.pressure}mbar")

            if curve.error != 0:
                print(f"  WARNING: Error flag set ({curve.error})")
```

The TADM data includes pressure measurements throughout the pipetting cycle, which can be used for:
- Detecting clogs or blockages
- Verifying consistent tip contact
- Diagnosing liquid delivery issues
- Quality control and process validation

---

## Liquid Level Detection

`detect_liquid_level()` performs capacitive and/or pressure-based liquid level detection without aspirating. Use it to verify that liquid is present before committing to an aspirate step, or to measure fill heights across wells.

### Basic Detection

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.tip_pickup(channels=[1, 2, 3, 4], tip_pool="TransferTips")

    star.detect_liquid_level(
        positions="SourcePlate@col:1",
        channels=[1, 2, 3, 4],
    )
    print("Liquid level detection complete")

    star.tip_eject(channels=[1, 2, 3, 4])
```

### Choose LLD Mode

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CapacitiveLLD, PressureLLD

with StarClient() as star:
    star.instrument_init()
    star.tip_pickup(channels=[1, 2, 3, 4, 5, 6, 7, 8], tip_pool="TransferTips")

    # Capacitive only (default — MAX sensitivity)
    star.detect_liquid_level(
        positions="SourcePlate@col:1",
        capacitive_lld=CapacitiveLLD.MAX,
        pressure_lld=PressureLLD.OFF,
    )

    # Pressure only (useful for non-conductive liquids)
    star.detect_liquid_level(
        positions="SourcePlate@col:2",
        capacitive_lld=CapacitiveLLD.OFF,
        pressure_lld=PressureLLD.MAX,
    )

    star.tip_eject(channels=[1, 2, 3, 4, 5, 6, 7, 8])
```

### `detect_liquid_level()` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `positions` | `PositionInput` | *required* | Target positions (selector DSL, explicit wells, or dicts) |
| `channels` | `list[int] \| None` | All 8 channels | Channel numbers to use. The count and numbers are validated against the channel total in the instrument configuration, up to 16 (see [Connect-Time Validation](advanced/instrument_configuration.md#connect-time-validation-from-the-instrument-configuration)) |
| `capacitive_lld` | `CapacitiveLLD` | `CapacitiveLLD.MAX` | Capacitive LLD sensitivity |
| `pressure_lld` | `PressureLLD` | `PressureLLD.OFF` | Pressure LLD sensitivity |
| `well_order` | `WellOrder` | `WellOrder.COL_ASC` | Well expansion order for selector inputs |

> **Tip:** `detect_liquid_level()` returns a raw `CommandResponse`. To use LLD results in subsequent aspirate steps, set `capacitive_lld` or `pressure_lld` on the `AspirateSettings` passed to `aspirate()` — the instrument will use the detected level automatically.

For more on TADM and pressure curves from liquid handling steps, see [TADM](./advanced/tadm.md).

---

## Working with Non-Standard Labware

Labware geometry (grid size, well spacing, indexing pattern) is resolved
automatically from the connected deck the first time a given labware id is
referenced. The selector DSL therefore "just works" for any labware that is
defined in your VENUS deck file, including 384-well plates and custom tube
racks:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="MyDeck") as star:
    star.instrument_init()
    star.tip_pickup(tip_pool="TransferTips")
    star.aspirate(
        channels=[1, 2, 3, 4, 5, 6, 7, 8],
        positions="Plate384@col:1",
        volumes=5.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    )
```

For high-density plates (e.g. 384-well at 4.5 mm spacing) the SDK transparently
reorders wells so each simultaneous channel group targets physically reachable
positions -- no extra configuration required.

### Overriding or Pre-Populating Geometry

If you need to override the cached spec (e.g. for unit tests or for labware
whose VENUS definition is incomplete), call
`register_labware_definition()` with an explicit `LabwareLayoutSpec`:

```python
from hamilton_venus.models import LabwareLayoutSpec

custom = LabwareLayoutSpec(
    rows=4,
    cols=6,
    well_spacing_x_mm=18.0,
    well_spacing_y_mm=18.0,
)
star.register_labware_definition("TubeRack", custom)
```

For advanced use cases including the full selector DSL and the spacing-aware
interleaving engine, see [Position and Well Selection](position_and_well_selection.md).

---

## 5mL (XL) Channels

STAR instruments may be configured with 5mL ("XL") channels in addition to the
standard 1mL channels. The SDK exposes a parallel set of methods with a
`_5ml` suffix that mirror the 1mL API exactly — same parameters, same return
types, same selector DSL. They are dispatched to the `channels.5mL` action
namespace on the VENUS side and emit dedicated error types (`XLAspirateError`,
`XLDispenseError`, etc.) so error-handling profiles can target the larger
channels independently.

### 5mL Method Reference

| 1mL method | 5mL method | Notes |
|------------|------------|-------|
| `tip_pickup` | `tip_pickup_5ml` | Identical signature |
| `tip_eject` | `tip_eject_5ml` | Identical signature |
| `aspirate` | `aspirate_5ml` | Identical signature |
| `dispense` | `dispense_5ml` | Identical signature |
| `detect_liquid_level` | `detect_liquid_level_5ml` | Identical signature |
| `tip_check` | `tip_check_5ml` | Identical signature |
| `dispense_on_the_fly` | `dispense_on_the_fly_5ml` | Identical signature |

Refer to the matching 1mL sections above for parameter tables and behavior —
they apply unchanged to the 5mL variants.

### Simple 5mL Transfer

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(deck_name="XLDeck") as star:
    star.instrument_init()

    star.tip_pickup_5ml(channels=[1, 2, 3, 4], tip_pool="XLTips")
    star.aspirate_5ml(
        channels=[1, 2, 3, 4],
        positions="ReservoirPlate@col:1",
        volumes=2500.0,
        liquid_class=LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_5ML.TIP_5ML.WATER.JET_EMPTY.N_5MLT_WATER_DISPENSEJET_EMPTY,
    )
    star.dispense_5ml(
        channels=[1, 2, 3, 4],
        positions="DestPlate@col:1",
        volumes=2500.0,
    )
    star.tip_eject_5ml(channels=[1, 2, 3, 4])
```

### Reusing AspirateSettings / DispenseSettings

`AspirateSettings` and `DispenseSettings` are shared between the 1mL and 5mL
APIs — the same settings object can be passed to either family of methods:

```python
from hamilton_venus.models import AspirateSettings, DispenseSettings

aspirate_settings = AspirateSettings()
dispense_settings = DispenseSettings()

# 1mL transfer
star.aspirate(channels=[1, 2], positions="Plate@A1,A2", volumes=100.0,
              liquid_class="Water", settings=aspirate_settings)

# 5mL transfer using the same settings object
star.aspirate_5ml(channels=[1, 2], positions="Reservoir@A1,A2", volumes=2000.0,
                  liquid_class="WaterXL", settings=aspirate_settings)
```

### Mixing 1mL and 5mL Channels

The 1mL and 5mL channels are independent hardware and may operate in the same
method. Channel numbering is per-arm: the 5mL channels are addressed as
`channels=[1, 2, 3, 4]` regardless of how many 1mL channels are present.

```python
# Use 1mL channels to prepare a small dilution
star.tip_pickup(channels=[1, 2, 3, 4, 5, 6, 7, 8], tip_pool="StdTips")
star.aspirate(channels=[1, 2, 3, 4, 5, 6, 7, 8],
              positions="DilutionPlate@col:1",
              volumes=50.0, liquid_class="Water")
star.dispense(channels=[1, 2, 3, 4, 5, 6, 7, 8],
              positions="WorkPlate@col:1", volumes=50.0)
star.tip_eject(channels=[1, 2, 3, 4, 5, 6, 7, 8])

# Then use 5mL channels to add bulk reagent
star.tip_pickup_5ml(channels=[1, 2, 3, 4], tip_pool="XLTips")
star.aspirate_5ml(channels=[1, 2, 3, 4],
                  positions="ReagentReservoir@col:1",
                  volumes=2500.0, liquid_class="ReagentXL")
star.dispense_5ml(channels=[1, 2, 3, 4],
                  positions="WorkPlate@col:1", volumes=2500.0)
star.tip_eject_5ml(channels=[1, 2, 3, 4])
```

### Error Handling

5mL methods report dedicated XL error types, allowing per-channel-type
error-handling policies. See [Error Handling](../error_handling.md) for the
full list (`XLTipPickupError`, `XLTipEjectError`, `XLAspirateError`,
`XLDispenseError`, `XLDispenseFlyError`, `XLMoveToPositionError`).
