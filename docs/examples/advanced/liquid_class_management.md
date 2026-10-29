# Liquid Class Management

Comprehensive guide for querying, filtering, and syncing liquid class definitions.

## Overview

This guide covers:
- filtering liquid class names with `get_liquid_classes()`
- querying available devices, liquid names, and tip types
- pulling and pushing named liquid class definitions
- validating that required liquid classes exist before a run
- syncing a named set of liquid classes between runs

---

## Filter Liquid Classes

Use `get_liquid_classes()` to narrow the available class names by tip type, device, dispense mode, or metadata flags. All filter parameters default to `-1` (no filter):

```python
from hamilton_venus import StarClient

with StarClient() as star:
    result = star.get_liquid_classes(
        tip_type=0,
        device=1,
        dispense_mode=3,
        is_original=1,
        has_tadm_enabled=0,
    )

    print(f"Matched classes: {result.return_parameters.count}")
    for name in result.return_parameters.liquid_class_names:
        print(f"  - {name}")
```

---

## Query Available Liquid Metadata

```python
from hamilton_venus import StarClient

with StarClient() as star:
    devices = star.get_liquid_devices()
    print([device.device_name for device in devices.return_parameters.devices])

    liquid_names = star.get_liquid_names()
    print(liquid_names.return_parameters.liquid_names)

    tip_types = star.get_tip_types()
    print(tip_types.return_parameters.tip_types)
```

---

## Automatic Push Before Pipetting

You don't need to push a liquid class before using it. Before any command that names a liquid class (aspirate, dispense, MPH96, MagPip, ...), the SDK checks the JSON library in the SDK `Liquid Class` folder (`<STAR|VANTAGE>\System|User\...\<name>.json`):

- **Original liquid classes** (the `System` folder) are never pushed. VENUS already has them.
- **Custom liquid classes** (the `User` folder) are pushed the first time a session uses them, and again whenever their JSON file changes. While you develop a liquid class, each saved edit is picked up by the next command.
- **Compound commands** (`add_reagent`, `serial_dilution_by_volume`, ...) push their liquid class(es) once at the start, then use them for the whole command without re-checking.
- A name that isn't in the JSON library isn't pushed: it is assumed to exist only in VENUS's database.

If VENUS rejects a pushed liquid class, the command is not sent and `LiquidClassPushError` is raised with VENUS's reason.

---

## Pull and Push Named Liquid Classes

`pull_liquid_classes()` and `push_liquid_classes()` operate on a list of liquid class names. Pushing explicitly is optional. It can load several custom liquid classes up front in one call.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

names = [
    LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,

]

with StarClient() as star:
    star.pull_liquid_classes(names=names)
    print("Pulled liquid class definitions from the instrument")

    star.push_liquid_classes(names=names)
    print("Pushed liquid class definitions back to the instrument")
```

---

## Query Available Liquid Metadata

```python
from hamilton_venus import StarClient

with StarClient() as star:
    devices = star.get_liquid_devices()
    print([device.device_name for device in devices.return_parameters.devices])

    liquid_names = star.get_liquid_names()
    print(liquid_names.return_parameters.liquid_names)

    tip_types = star.get_tip_types()
    print(tip_types.return_parameters.tip_types)
```

---

## Filter Liquid Classes

Use `get_liquid_classes()` when a workflow needs to narrow the available classes by tip type, device, dispense mode, or metadata flags.

```python
from hamilton_venus import StarClient

with StarClient() as star:
    result = star.get_liquid_classes(
        tip_type=0,
        device=1,
        dispense_mode=3,
        is_original=1,
        has_tadm_enabled=0,
    )

    print(f"Matched classes: {result.return_parameters.count}")
    for name in result.return_parameters.liquid_class_names:
        print(f"  - {name}")
```

---

## Production Check: Verify Required Liquid Classes

```python
import logging
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUIRED_CLASSES = {
    LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY,
}


def verify_required_liquid_classes(star: StarClient) -> bool:
    result = star.get_liquid_classes()
    available = set(result.return_parameters.liquid_class_names)
    missing = sorted(REQUIRED_CLASSES - available)

    if missing:
        logger.error("Missing liquid classes: %s", ", ".join(missing))
        return False

    logger.info("All required liquid classes are available")
    return True


with StarClient() as star:
    if not verify_required_liquid_classes(star):
        raise SystemExit("Required liquid classes are missing")
```

---

## Sync a Named Liquid Class Set

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

SYNC_SET = [
    LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSESURFACE_EMPTY,
    LIQUID_CLASSES.STAR.STANDARDVOLUME_SERUM_DISPENSEJET_EMPTY,
]

with StarClient() as star:
    star.pull_liquid_classes(names=SYNC_SET)
    # External editing or version-controlled file updates would happen here.
    star.push_liquid_classes(names=SYNC_SET)
    print("Liquid class sync complete")
```

---

## API Reference

| Method | Returns | Key response field | Description |
|--------|---------|-------------------|-------------|
| `get_liquid_classes(tip_type=-1, device=-1, dispense_mode=-1, is_original=-1, has_tadm_enabled=-1)` | `LiquidClassesResponse` | `.return_parameters.liquid_class_names`, `.return_parameters.count` | Filter liquid class names |
| `get_liquid_devices()` | `LiquidDevicesResponse` | `.return_parameters.devices` | List available liquid handling devices |
| `get_liquid_names()` | `LiquidNamesResponse` | `.return_parameters.liquid_names` | List available liquid names |
| `get_tip_types()` | `TipTypesResponse` | `.return_parameters.tip_types` | List available tip types |
| `pull_liquid_classes(names)` | `CommandResponse` | — | Pull named definitions from the instrument database |
| `push_liquid_classes(names)` | `CommandResponse` | — | Push named definitions back to the instrument database |

---

## See Also

- [`../liquid-classes.md`](../liquid-classes.md) — Quick-reference examples (redirects here)
- [`../static-catalogs.md`](../../static-catalogs.md) — `LIQUID_CLASSES` catalog reference
- [`../../star-commands.md`](../../star-commands.md) — Full API reference
