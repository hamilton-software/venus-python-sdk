# Getting Started

Practical usage examples for connecting, configuring, and starting the Hamilton STAR SDK.

## Quick Start Decision Tree

| Scenario | Use This | Code |
|----------|----------|------|
| Standard workflow with auto-init | `StarClient()` | `with StarClient() as star:` |
| Load a saved deck automatically | `StarClient(deck_name=...)` | `with StarClient(deck_name="MyDeck") as star:` |
| Manual control over every step | `StarClient(auto_connect=False)` | See "Manual Connect" section below |
| Testing/simulation mode | `StarClient(simulate=True)` | `with StarClient(simulate=True) as star:` |

---

## Basic Connection

```python
from hamilton_venus import StarClient

with StarClient() as star:
    print(f"Connected: {star.instrument_is_connected()}")
    print(f"Connection state: {star.connection_state}")
```

> `with StarClient(...) as star:` already calls `star.start()` on entry (and `star.stop()` on exit). During `start()`, the SDK polls the `ready` channel until the server reports readiness. `StarClient` defaults `auto_connect` to `True`, but most instrument, channel, deck, layout, transport, and liquid-class commands still require `instrument_init()` first (unless you connected with initialization enabled).

## Connection with a Saved Deck

Pass `deck_name` to load a previously saved deck layout automatically during startup — it fires before auto-connect, so everything is ready in one line:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="MyDeckLayout") as star:
    carriers = star.get_added_carriers()
    print(f"Loaded carriers: {carriers}")
```

## Startup Flow (7-Step Lifecycle)

The Venus backend follows a 7-step lifecycle. The SDK maps each step to a method:

| Step | Description | SDK Method |
|------|-------------|------------|
| 1 | Start client infrastructure (SignalR, error handler, method start) | `star.start()` |
| 2 | (Optional) Load a saved deck or query labware/liquid classes | `star.deck_load(...)`, `star.get_liquid_classes(...)` |
| 3 | Connect to the instrument (optionally include initialization) | `star.instrument_connect(initialize=True/False)` |
| 4 | Add carriers, tips, plates (must be after instrument connect) | `star.add_carrier(...)`, `star.add_tip_rack(...)` |
| 5 | Initialize the instrument (if not done in step 3) | `star.instrument_init()` |
| 6 | Run instrument commands | Any command method |
| 7 | Stop the client (terminate method, shut down SignalR) | `star.stop()` |

The `StarClient` context manager handles steps 1 and 7 automatically. The `auto_connect` parameter adds step 3, and `deck_name` adds step 2:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="MyDeck") as star:
    star.add_carrier(...)
    star.instrument_init()
    # ... run commands ...
```

For full manual control over every step:

```python
from hamilton_venus import StarClient

star = StarClient()
star.start()
try:
    star.deck_load(name="MyDeck")
    star.instrument_connect(initialize=False)
    star.add_carrier(...)
    star.add_tip_rack(...)
    star.instrument_init()
    # ... run commands ...
finally:
    star.stop()
```

## Manual Connect and Initialization Control

```python
from hamilton_venus import StarClient
from hamilton_venus.config import SdkConfig

config = SdkConfig(base_url="http://localhost:42400")
star = StarClient(config, auto_connect=False)
star.start()
try:
    connect_result = star.instrument_connect(initialize=False)
    print(connect_result.return_parameters.instrument_name)

    if star.instrument_is_connected() and star.instrument_is_idle():
        star.instrument_init()
finally:
    star.stop()
```

## Manual or Forced Initialization

Use manual initialization when you need to delay startup actions or override the default init behavior:

```python
from hamilton_venus import StarClient

star = StarClient(auto_connect=False)
star.start()

try:
    # Query labware or liquid classes
    star.instrument_connect()
    # Make any changes to the deck
    star.instrument_init(force_init=True)

    config = star.instrument_get_configuration()
    serial = star.instrument_get_serial_number()
    print(f"Serial: {serial.return_parameters.serial_number}")
finally:
    star.stop()
```

## Programmatic Configuration

Construct configuration entirely in code:

```python
from hamilton_venus import MethodConfig, SdkConfig, StarClient

config = SdkConfig(
    method=MethodConfig(method_display_name="MyScript"),
)

with StarClient(config, auto_connect=False) as star:
    star.instrument_init()
    print(star.instrument_is_connected())
```

## Run Log

Every `StarClient` and `VantageClient` session writes a structured JSON run log by default. It captures every HTTP request/response, SignalR event, console interaction and VENUS's firmware COM trace in a single file:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient(run_log=True) as star:
    star.instrument_init()
    star.aspirate(
        channels=[1, 2],
        positions="Plate@col:1",
        volumes=50.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    )
```

After the `with` block exits, the SDK writes a finalized `.json` file (e.g. `<methodName>_<runGuid>_SdkRunLog.json`, or `<scriptName>_<session_id>_SdkRunLog.json` when no VENUS run GUID is linked) to VENUS's LogFiles directory (`C:\Program Files (x86)\Hamilton\Logfiles` on a standard install). `run_log=True` in the example above only makes that explicit; pass `run_log=False` to turn it off.

For full configuration options — output directory, disabling console capture, filtering SignalR events, embedding VENUS's firmware COM trace (`.trc`), and crash recovery — see the [Run Log guide](advanced/run_log.md).
