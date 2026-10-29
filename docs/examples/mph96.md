# 96-Channel Head (MPH96)

Examples for full-plate and partial operations using the 96-channel multi-probe head.

MPH96 commands are rejected with `VenusCommandUnsupportedError` when the instrument configuration does not report an MPH96 head. See [Connect-Time Validation](advanced/instrument_configuration.md#connect-time-validation-from-the-instrument-configuration).

## Full-Plate Transfer

Full-plate aspirate and dispense with the 96-channel head:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient() as star:
    star.instrument_init()
    star.tip_pick_up_mph96(tip_pool="Tips96")
    star.aspirate_mph96(
        labware_id="SourcePlate",
        volume=50.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_96COREHEAD_WATER_DISPENSEJET_EMPTY,
    )
    star.dispense_mph96(labware_id="DestPlate", volume=50.0)
    star.tip_eject_mph96()
```

## Partial 96-Channel Pickup

Pick up only 4 columns of tips:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.enums import MphPickupMode, MphPickupSide

with StarClient() as star:
    star.instrument_init()
    star.tip_pick_up_mph96_partial(
        mode=MphPickupMode.COLUMNS,
        count=4,
        tip_pool="Tips96",
        mph_pickup_side=MphPickupSide.RIGHT,
    )
    star.aspirate_mph96(
        labware_id="SourcePlate",
        volume=25.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_96COREHEAD_WATER_DISPENSEJET_EMPTY,
    )
    star.dispense_mph96(labware_id="DestPlate", volume=25.0)
    star.tip_eject_mph96()
```

## MPH96 Reusable Settings

Define MPH96 aspirate and dispense settings once, then reuse them:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import MPH96AspirateSettings, MPH96DispenseSettings

aspirate_settings = MPH96AspirateSettings(mix_cycles=3, mix_volume=50.0)
dispense_settings = MPH96DispenseSettings(
    liquid_following=True,
    use_side_touch=True,
    minimize_z_move=False,
)

with StarClient() as star:
    star.instrument_init()
    star.tip_pick_up_mph96(tip_pool="Tips96")
    star.aspirate_mph96(
        labware_id="SourcePlate",
        volume=50.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_96COREHEAD_WATER_DISPENSEJET_EMPTY,
        settings=aspirate_settings,
    )
    star.dispense_mph96(
        labware_id="DestPlate",
        volume=50.0,
        settings=dispense_settings,
    )
    star.tip_eject_mph96()
```

---

---

## `aspirate_mph96()` Reference

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `labware_id` | `str` | *required* | Target labware identifier |
| `liquid_class` | `str` | *required* | Liquid class name |
| `mph_pattern` | `list[str] \| list[int] \| None` | `None` | Pattern selection for partial operations |
| `volume` | `float` | *required* | Aspirate volume in µL |
| `settings` | `MPH96AspirateSettings \| None` | `None` | Reusable aspirate settings object |

### `MPH96AspirateSettings` Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `aspirate_mode` | `AspirateMode` | `NORMAL` | Aspiration mode |
| `capacitive_lld` | `CapacitiveLLD` | `OFF` | Capacitive LLD sensitivity |
| `liquid_following` | `bool` | `False` | Enable liquid surface following |
| `tip_tracking_factor` | `float` | `1.0` | Liquid-following movement factor. `0.5` tracks half the distance in the same time, `2.0` twice the distance; `1.0` is normal tracking. VENUS accepts `0.1`–`5.0` |
| `submerge_depth` | `float` | `2.0` | Submerge depth (mm) |
| `fixed_height` | `float` | `5.0` | Fixed height above bottom (mm) |
| `mix_cycles` | `int` | `0` | Number of mix cycles |
| `mix_position` | `float` | `0.0` | Mix position height (mm) |
| `mix_volume` | `float` | `0.0` | Mix volume (µL) |
| `air_transport_retract_dist` | `float` | `5.0` | Air-transport retract distance (mm) |

---

## `dispense_mph96()` Reference

Dispense has no `liquid_class` parameter of its own — the liquid class used is whichever one the head aspirated with.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `labware_id` | `str` | *required* | Target labware identifier |
| `mph_pattern` | `list[str] \| list[int] \| None` | `None` | Pattern selection for partial operations |
| `volume` | `float` | *required* | Dispense volume in µL |
| `settings` | `MPH96DispenseSettings \| None` | `None` | Reusable dispense settings object |

### `MPH96DispenseSettings` Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dispense_mode` | `DispenseMode` | `FROM_LIQUID_CLASS` | Dispense mode |
| `capacitive_lld` | `CapacitiveLLD` | `OFF` | Capacitive LLD sensitivity |
| `liquid_following` | `bool` | `False` | Enable liquid surface following |
| `tip_tracking_factor` | `float` | `1.0` | Liquid-following movement factor. `0.5` tracks half the distance in the same time, `2.0` twice the distance; `1.0` is normal tracking. VENUS accepts `0.1`–`5.0` |
| `submerge_depth` | `float` | `2.0` | Submerge depth (mm) |
| `fixed_height` | `float` | `5.0` | Fixed height above bottom (mm) |
| `mix_cycles` | `int` | `0` | Number of mix cycles |
| `mix_position` | `float` | `0.0` | Mix position height (mm) |
| `mix_volume` | `float` | `0.0` | Mix volume (µL) |
| `air_transport_retract_dist` | `float` | `5.0` | Air-transport retract distance (mm) |
| `use_side_touch` | `bool` | `False` | Enable side touch detection during dispense |
| `minimize_z_move` | `bool` | `False` | Minimize Z-axis movement during dispense |
