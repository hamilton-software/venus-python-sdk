# Error Simulation

Inject simulated firmware errors so error-recovery code can be exercised without
hardware. Backed by the custom `ErrorSimulator` knowledge base shipped with the
SDK (`hamilton_venus.error_simulator`). Works for `StarClient` and
`VantageClient`.

> **Simulation mode only.** The simulated firmware only consults the simulator
> config file in simulation mode; on a live instrument these calls raise
> `SimulationModeRequired`.

---

## Overview

`ErrorSimulatorCommandsMixin` adds these methods to both instrument clients:

| Method | Purpose |
|--------|---------|
| `simulate_error(module, step, error, *, channels=None)` | Make the next `step` on `module` return `error` |
| `simulate_error_by_code(firmware_command, error_code, error_recovery="")` | Write a raw firmware error code, no keyword matching |
| `clear_simulated_errors()` | Reset every firmware command to its "no error" reply |
| `list_simulatable_modules()` / `list_simulatable_steps(module)` / `list_simulatable_errors(module)` | Discovery |

`step` and `error` accept either a plain string (fuzzy keyword match, like the
HSL library) or a generated typed constant (exact match):

```python
from hamilton_venus.error_simulator import Module
from hamilton_venus.error_simulator._generated_steps import StarStep
from hamilton_venus.error_simulator._generated_errors import StarChannels1MlError
```

---

## Basic usage

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.error_simulator import Module
from hamilton_venus.error_simulator._generated_errors import StarChannels1MlError
from hamilton_venus.error_simulator._generated_steps import StarStep
from hamilton_venus.exceptions import VenusError

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="TC")
    star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id="TC", site="1", tip_pool="tips")
    star.instrument_init()

    # exact (typed constant) -- or: star.simulate_error("1mL", "tip pick up", "no tip picked up", channels=[1])
    star.simulate_error(
        Module.CHANNELS_1ML,
        StarStep.TIP_PICK_UP,
        StarChannels1MlError.TIP_HANDLING_NO_TIP_PICKED_UP,
        channels=[1],
    )

    try:
        star.tip_pickup(channels=[1], tip_pool="tips")
    except VenusError as exc:
        print("failed as expected:", exc)

    star.clear_simulated_errors()
    star.tip_pickup(channels=[1], tip_pool="tips")  # succeeds now
```

For per-channel modules (`1mL`, `5mL`, `X1`, `MagPip`), `channels` is optional --
omit it to apply the error to all channels, pass `channels=[...]` for a subset,
or use the `"1.<desc>;2.<desc>"` micro-syntax in `error` for a different error
per channel. Single modules (`IPG`, `MPH96`, `MPH384`, `IDL`) take no channels.

> **One error at a time.** Each `simulate_error` / `simulate_error_by_code` call
> clears every previously injected error before writing the new one -- VENUS's
> firmware simulator misbehaves with more than one registered at once. Call it
> immediately before the step it targets; don't stack several up front.

See `example_scripts/simulate_firmware_error.py` (`--instrument star|vantage`).

---

## Regenerating the knowledge base

The data is generated from a custom `ErrorSimulator.mdb` and committed under
`src/hamilton_venus/error_simulator/`. After editing the `.mdb`, regenerate it
(Windows, needs the ACE OLE DB provider):

```
python -m hamilton_venus.tools.generate_error_simulator_data --mdb path/to/ErrorSimulator.mdb
```
