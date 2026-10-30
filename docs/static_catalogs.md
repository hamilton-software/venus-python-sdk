# Static Catalogs

Use generated static constants instead of hardcoded labware and liquid-class strings.

## Why use static catalogs

- IDE autocomplete for available labware and liquid classes
- Fewer string typos in workflow code
- Clear grouping by category/family

## Imports

```python
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
```

## Labware examples

These snippets assume `star` is an open `StarClient` (see [Getting Started](examples/getting_started.md)).

```python
star.add_carrier(
    labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
    left_track=1,
    labware_id="PlateCarrier",
)

star.add_plate(
    labware_definition=LABWARE.PLATE.COS_96_RD,
    carrier_id="PlateCarrier",
    site="1",
    plate_id="SourcePlate",
)

# Assumes a tip carrier named "TipCarrier" was already added with add_carrier().
star.add_tip_rack(
    labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
    carrier_id="TipCarrier",
    site="1",
    tip_pool="TransferTips",
)
```

## Liquid class examples

Liquid classes are collected into a nested folder tree matching the local `Liquid Class`
directory's own layout (`<instrument>/<pipettingDevice>/<tipType>/<liquid>/<dispenseMode>/<name>`),
and accessed purely via dot access — there is
deliberately no bracket/name-only lookup for `LIQUID_CLASSES`, unlike `LABWARE`. A liquid
class's tip type, pipetting device, and dispense mode are load-bearing parts of its identity
(the same class *name* can appear more than once under different tip/dispense-mode folders,
representing genuinely different parameter sets), so spell out the full path rather than
relying on a name-only shortcut that would silently pick an arbitrary match:

```python
star.aspirate(
    positions="SourcePlate@col:1",
    volumes=50.0,
    liquid_class=LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
)

result = star.copy_plate(
    source_plate_id="SourcePlate",
    dest_plate_id="DestPlate",
    volume=100.0,
    liquid_class=LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    tip_pool="TransferTips",
)
```

Intermediate levels can be skipped when they aren't meaningfully ambiguous for your use case
(e.g. `LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY`, or even the leaf name
directly off the root) — `__getattr__` searches child namespaces automatically. Prefer
spelling out the full path anyway; it documents exactly which tip/device/mode variant a
script depends on, right at the call site.

## Regenerating catalogs

Regenerate catalog files after adding custom labware or liquid classes.
The tool automatically calls `get_liquid_classes` with default filters to pull all available liquid class names from VENUS before generating the catalog. This requires VENUS to be running on the local PC (the tool starts a simulated client and never connects to an instrument); use `--skip-liquid-classes` to regenerate only labware without VENUS.

```bash
venus-sdk generate-catalog
```

Module form is also supported:

```bash
python -m hamilton_venus.tools.generate_catalog
```

### Useful options

```bash
venus-sdk generate-catalog --verify
venus-sdk generate-catalog --skip-liquid-classes
venus-sdk generate-catalog --debug
venus-sdk generate-catalog --liquid-class-path "C:\Program Files (x86)\HAMILTON\SDK\Liquid Class"
venus-sdk generate-catalog --instrument vantage   # default: auto-detect STAR or Vantage
```

## CI freshness check

Use `--verify` in CI to fail when generated files are stale:

```bash
venus-sdk generate-catalog --verify
```

If output differs from committed files, the command exits non-zero. Pulling liquid classes needs a local VENUS install, so on CI machines without VENUS add `--skip-liquid-classes` (only labware is then verified).
