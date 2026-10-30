# Liquid Class Management

Comprehensive guide for querying, filtering, and syncing liquid class definitions.

## Overview

This guide covers:
- choosing the right liquid class for a transfer with `find_liquid_classes()`
- filtering liquid class names with `get_liquid_classes()`
- querying available devices, liquid names, and tip types
- pulling and pushing named liquid class definitions
- validating that required liquid classes exist before a run
- syncing a named set of liquid classes between runs

---

## Choose the Right Liquid Class

A liquid class only fits a transfer when everything in its `appliesTo` matches:

- **Pipetting device:** fitted on this instrument. MagPip classes exist only in the Vantage library, and need MagPip channels.
- **Tip type:** registered in VENUS and loaded for the transfer, filter or not.
- **Dispense mode:** fits the transfer (jet or surface, empty or part volume).
- **Volume:** in range.
- **Liquid:** the closest match.

`find_liquid_classes()` checks all of these and returns the candidates best first:

```python
result = star.find_liquid_classes(
    "Ethanol",
    dispense_mode=DispenseMode.JET_EMPTY_TIP,  # or "jet_empty"
    volume=100,
    tip_pool="Tips300",  # the tip type loaded in this pool is used
)
print(result.device_label, result.tip.name, f"max {result.tip.max_liquid_volume} µL")
for c in result.candidates:
    print(c.name, c.liquid, c.liquid_match, "original" if c.original else "custom")
liquid_class = result.candidates[0].name
```

- **Where the inputs come from:**
  - The device is taken from `instrument_get_configuration()`; pass `device="1mL" | "5mL" | "MagPip" | "MPH96" | "MPH384"` to choose one.
  - Instead of `tip_pool`, pass `tip_type=<id>` from `get_registered_tip_types()`.
- **Ranking:** candidates for the closest liquid come first, Hamilton's validated originals before custom classes. When `liquid_match` is not `"exact"`, no class is made for that liquid with this tip and mode; check the choice, or create a custom class.
- **Refusals:** it raises `ValueError` with the reason for:
  - a device that is not fitted
  - a tip type that is not registered, or cannot be used on the device
  - a volume above the tip's maximum liquid volume
- **Without a connected instrument:** the device can't be checked against the hardware, and `result.notes` says so.

`get_registered_tip_types()` works once the session is started, before connecting the instrument. It returns each registered tip type by id with its name, `max_liquid_volume`, `max_tip_volume`, `tip_length`, `stop_disk_immersion_depth`, `length_below_channel`, `filter`, `conductive`, `tip_class` and the devices that can use it. A tip type that is not in this list cannot be used.

`tip_length` is the whole tip. Part of it, the collar, sits on the channel up to its stop disk (`stop_disk_immersion_depth`, e.g. 8 mm for 300 µL tips), so what reaches below the channel is `length_below_channel` = `tip_length` − `stop_disk_immersion_depth`. For a 300 µL tip that is 59.9 − 8 = 51.9 mm. Use `length_below_channel` for heights and clearances.

### Tip long enough for the labware

A tip reaches only its `length_below_channel` below the channel. If it pipettes deeper into a well or tube than that, the channel itself goes inside the container and can touch its wall: a contamination risk. A 50 µL tip in a 100 mm tube (98.9 mm deep) is the classic case.

```python
reach = star.check_tip_reach("TubeRack1", tip_pool="Tips300")
if not reach.ok:
    print(reach.message)      # how far the channel would go inside, and at what height
    print(reach.longer_tips)  # registered tips on this device that are long enough
```

- **Pipetting at a fixed height** (no liquid level detection): pass `height_from_bottom`. Up to 10 mm of channel below the rim counts as safe, because the channel's lower end is narrow enough not to reach a tube wall (`CHANNEL_INSIDE_ALLOWANCE_MM` in `hamilton_venus.tip_reach`). For example, a 1000 µL tip at 5 mm in a 100 mm tube puts it 6.8 mm inside, which is fine. A warning names the lowest safe height for the tip in use.
- **With liquid level detection** (the default, `height_from_bottom=0`), the tip goes to the liquid, so only the last of it takes the tip near the bottom. The check warns when the tip reaches less than half the container's depth. In a 100 mm tube that flags a 50 µL tip (42.4 mm) but not a 300 µL (51.9 mm) or 1000 µL (87.1 mm) tip. The message also says how high above the bottom the tip must stay to keep the channel out.
- Aspirate, dispense and liquid level detection on the channels and the 96 head make the same check on their own, using the tips each channel picked up (from a tip pool or a tip rack). A risk is logged, written to the run log as a `warning` entry, and returned by `pop_command_warnings()`. The MCP server adds these to the command's result as `"warnings"`.
- The command still runs; the warning is for the person to act on.

Pipetting commands also check their liquid class before anything is sent to VENUS. Aspirate, dispense and the compound commands refuse a class made for another pipetting device (for example a MagPip class on the 1 mL channels), or one that only exists in the other instrument's library, with `LiquidClassMismatchError`.

---

## Filter Liquid Classes

Use `get_liquid_classes()` to narrow the available class names by tip type, device, dispense mode, or metadata flags. All filter parameters are keyword-only and default to `-1` (no filter). Look up valid `device` and `tip_type` IDs with `get_liquid_devices()` and `get_tip_types()` (see [Query Available Liquid Metadata](#query-available-liquid-metadata)):

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
| `get_liquid_classes(*, tip_type=-1, device=-1, dispense_mode=-1, is_original=-1, has_tadm_enabled=-1)` | `LiquidClassesResponse` | `.return_parameters.liquid_class_names`, `.return_parameters.count` | Filter liquid class names |
| `get_liquid_devices()` | `LiquidDevicesResponse` | `.return_parameters.devices` | List available liquid handling devices |
| `get_liquid_names()` | `LiquidNamesResponse` | `.return_parameters.liquid_names` | List available liquid names |
| `get_tip_types()` | `TipTypesResponse` | `.return_parameters.tip_types` | List available tip types |
| `pull_liquid_classes(names)` | `CommandResponse` | — | Pull named definitions from the instrument database |
| `push_liquid_classes(names)` | `CommandResponse` | — | Push named definitions back to the instrument database |

---

## See Also

- [`../liquid_classes.md`](../liquid_classes.md) — Quick-reference examples (redirects here)
- [`../../static_catalogs.md`](../../static_catalogs.md) — `LIQUID_CLASSES` catalog reference
- [`../../star_commands.md`](../../star_commands.md) — Full API reference
