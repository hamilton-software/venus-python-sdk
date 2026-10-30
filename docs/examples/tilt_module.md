# Tilt Module (MFX)

Guide for controlling the Hamilton **MFX Tilt Module** (ambient, control-box / RS‑232 version, part no.
188061) — connecting, tilting a plate to an angle, and reading status.

> For what the real module does (serial settings, replies, settling, troubleshooting), see the
> [Tilt Module hardware notes](../tilt_module_hardware_notes.md).

---

## Overview

The module tilts SBS-format labware from **0° (horizontal) to 10°**, in whole-degree steps. It hinges on its
**left short side** (landscape view), so a positive angle lifts the **right** side of the plate while the left
stays at the hinge. It is driven over RS‑232 through its INTERFACE BOX. Up to eight modules share one COM
port on a Y‑cable daisy chain, each with its own two-character module name.

The driver is converted from the VENUS library **`HSLMultiDaisyChainedTiltModuleAmbient`** and follows it
one-to-one. It is **pure Python and does not go through the VENUS runtime** — it speaks the firmware's line
protocol straight to the COM port and has its own standalone client, `TiltModuleClient`. There is no
`StarClient`/`VantageClient` involved. There is no vendor COM object and therefore no 32-bit bridge — it uses
`pywin32` (already an SDK dependency). VENUS and the HSL library do **not** need to be installed for the
driver to work.

| HSL function | Python method |
|---|---|
| `InitializeCommunication(systemId, comPort, …)` | `tilt_module_connect(system_id, com_port)` |
| `InitializeTiltModuleAmbient(systemId, module)` | `tilt_module_initialize(system_id, module_name)` |
| `MoveToPosition(systemId, module, angle)` | `tilt_module_move_to_position(system_id, module_name, angle)` |
| `TerminateTiltModuleAmbient(systemId, module)` | `tilt_module_terminate_module(system_id, module_name)` |
| `TerminateCommunication(systemId)` | `tilt_module_terminate_communication(system_id)` |
| `EvaluateErrorMessage(code)` | `tilt_module_error_message(error_code)` |
| *(not in the HSL)* | `tilt_module_get_status(system_id, module_name)` |

A **system** (`system_id` 1–4) is one COM port. Different systems may reuse module names.

This guide covers:

- Connecting a system, initializing and tilting modules, and shutting down
- Reading status and decoding errors
- Telling VENUS the plate is tilted (`tilt_labware`), and splitting its wells for several channels

### Hardware vs. simulation

With `simulate=True` — or when the SDK finds no serial support — the client uses a built-in **firmware
simulator** that speaks the same line protocol, so everything below runs unchanged without hardware. In
simulation any two-character module name is accepted. The simulator's behaviour is *inferred* from the vendor
libraries; treat it as a way to exercise your code, not as proof of how the real unit behaves.

### Making a real connection work

1. Power the INTERFACE BOX and connect its RS‑232 cable to the instrument PC.
2. Find the port and confirm the SDK can see it:

   ```console
   $ hamilton-tilt-module --diagnose
   available:   True
   diagnosis:   pywin32 present; the Tilt Module is reached over a COM port (1200 baud, 8E1).
   COM ports:   COM3, COM10, COM11
   ```

3. Read-only hardware check — asks the unit for its firmware version (`RF`); nothing moves:

   ```console
   $ hamilton-tilt-module --probe COM1
   probe OK: module 'T1' firmware 'A.0.0.1.0 2014-05-14 (SSW)' (raw reply 'T1RFer00 A.0.0.1.0 2014-05-14 (SSW)')
   ```

   `--probe` uses the `99` broadcast address, which only works when **exactly one** module is on the bus. Note
   the module name in the reply: that is the `module_name` you pass to `tilt_module_initialize`. Do not assume a
   default name: the unit tested was named `T1`. Renaming (firmware `MN` command, done once with each module
   alone on the port, before chaining) is recommended when several share a chain. The SDK does not expose `MN`.

4. **If nothing answers**, look for working serial settings — read-only, it only ever sends `RF`:

   ```console
   $ hamilton-tilt-module --scan COM1
    1200 baud, 8E1: ANSWERED: 'T1RFer00 A.0.0.1.0 2014-05-14 (SSW)'
    1200 baud, 8N1: no valid reply (no reply from module '99' …)
    …
   answered at: 1200 8E1
   ```

   The defaults are Hamilton's documented settings: **1200 baud, 8 data bits, even parity, 1 stop bit, no
   flow control, CR/LF line ends**. Override them only if the scan finds something else:
   `TiltModuleClient(baudrate=9600, parity="N")`.

Only one program can hold the COM port. Close VENUS methods and HSL libraries that use the tilt module before
connecting from Python.

---

## Basic operations

The HSL's own example method, in Python:

```python
from hamilton_venus import TiltModuleClient

with TiltModuleClient(simulate=True) as tilt:           # drop simulate=True for hardware
    tilt.tilt_module_connect(system_id=1, com_port=3)   # open COM3 for system 1
    tilt.tilt_module_initialize(1, "TM")                # EI, SI, RF -> homed to 0 deg; on hardware use the name --probe reported
    tilt.tilt_module_move_to_position(1, "TM", 10)      # waits until the module is idle
    tilt.tilt_module_move_to_position(1, "TM", 0)
    tilt.tilt_module_terminate_module(1, "TM")          # GP0, PO
    tilt.tilt_module_terminate_communication(1)         # close COM3
```

Do not pipette to or from the module while it moves. `tilt_module_move_to_position` returns only after the
module has acknowledged the move (and, when it answers status queries, reports idle).

`close()` / leaving the `with` block shuts down anything still up: each initialised module is returned to
horizontal and powered off, then every port is closed. If a plate with liquid is tilted and you do *not* want it
moved on exit, pass `return_to_flat_on_close=False`.

### Status

With `tilt` connected and `"TM"` initialized as above:

```python
status = tilt.tilt_module_get_status(1, "TM").return_parameters
status.angle      # last angle *commanded* -- the module has no position read-back
status.busy       # from the firmware's RS command   (None if the query failed)
status.error_code # from the firmware's RE command   (None if the query failed)
status.query_error  # why busy/error_code are None, if they are
```

On the unit tested (firmware A.0.0.1.0) the firmware has no `RS` command: it answers `er07` (unknown command),
so `busy` is `None` with `query_error` saying why, and the driver does not ask again. `RE` answers a bare
`er00`, which is read as "no error". Moves are acknowledged by the `GP` reply alone, as in the vendor library.
The `GP` reply only means the command was accepted: allow the plate time to settle before pipetting.

### Several modules / several systems

```python
tilt.tilt_module_connect(1, 3)
tilt.tilt_module_connect(2, 4)                 # a second COM port is a second system
for system_id, names in ((1, ["T1", "T2"]), (2, ["T1"])):   # names may repeat across systems
    for name in names:
        tilt.tilt_module_initialize(system_id, name)
```

### Errors

Every failure raises `TiltModuleError` (a `VenusError`; the HSL returns codes instead). `error_code` carries the
HSL return code and `tilt_module_error_message(code)` gives its text.

| Code | Meaning |
|-----:|---------|
| 1 | Init position not found! |
| 2 | Steps lost (overload)! |
| 3 | Drive not initialized! |
| 4 | Parallel functions not allowed! |
| 5 | Stepper motor power amp defective! |
| 6 | Parameter out of range! (system ID 1–4, COM port 1–255, angle 0–10) |
| 7 | Unknown command! |
| −1 | Assigned system (COM port) already initialized! |
| −2 | Assigned system (COM port) not yet initialized! |
| −3 | Assigned module already initialized! |
| −4 | Assigned module not yet initialized! |
| −6 | Any HSL function failed! (also: closing a system whose modules are still up) |
| −7 | Writing to COM port failed! |
| −8 | Reading from COM port failed (e.g. timeout)! |
| −9 | Unexpected error in transmitting command/receiving response occurred! |
| −11 | Unknown device name (module identifier)! |

Codes 1–7 are the firmware's own. A **−8** usually means the cable, INTERFACE BOX power, COM port, serial
settings or module name is wrong — use `hamilton-tilt-module --scan`.

---

## Tilting the Plate in the Deck Layout

This driver only moves and reports on the hardware. It does **not** change where VENUS thinks the wells
are: to VENUS the plate is still flat. Tell VENUS with
[`tilt_labware()`](./deck_and_layout.md#tilt-labware) on the instrument client, using the same angle, for
the plate on the module's site. Then the channels go to the tilted wells. On a large-well plate,
[`split_wells()`](./deck_and_layout.md#split-wells) lets several channels pipette into each tilted well.

Keep the two in step: tilt the hardware first, then the layout; flatten the layout, then the hardware. A
tilted plate cannot be transported (`LabwareTiltedError`) until `tilt_labware(..., 0)`.

```python
from hamilton_venus import TiltModuleClient, VantageClient
from hamilton_venus.models import SplitWellFit, TiltWellPosition

ANGLE = 10
# This module's hinge and real angle, from fit_tilt_hinge(...).tilt_labware_kwargs() (see below).
CALIBRATION = {"pivot_x_offset_mm": -2.76, "pivot_z_offset_mm": 4.57, "measured_tilt_degrees": 10.81}

with VantageClient() as vantage, TiltModuleClient() as tilt:
    # ... deck with "CellPlate" (a 6-well plate) on the tilt module's site ...
    tilt.tilt_module_connect(1, 1)
    tilt.tilt_module_initialize(1, "T1")

    tilt.tilt_module_move_to_position(1, "T1", ANGLE)                  # the hardware
    vantage.tilt_labware("CellPlate", ANGLE, well_position=TiltWellPosition.DEEPEST_POINT,
                         tip_end_height_mm=1.0, **CALIBRATION)          # the layout
    vantage.split_wells("CellPlate", "A1:B3", fit=SplitWellFit.MAX_CHANNELS)   # optional: several channels per well
    # ... aspirate from the deepest point with channels 1-4 ...

    vantage.tilt_labware("CellPlate", 0)                               # layout flat (splits rebuilt)
    tilt.tilt_module_move_to_position(1, "T1", 0)                      # hardware flat
    # now the plate can be transported
```

The module tilts about its left short side, matching `tilt_labware`'s default `TiltPivotPoint.LEFT_EDGE`: a
positive angle lifts the right side of the plate in both. Its hinge is a pin under the plate, though, and the
plate's real angle can differ a little from the commanded one (about 10.8 for 10 on the module tested).
Measure both once per module with four probe readings and `fit_tilt_hinge()`, and give the result to
`tilt_labware`; see [Calibrating a Tilt Module](./deck_and_layout.md#calibrating-a-tilt-module) and
`example_scripts/tilt_module_fit_hinge.py`.

---

## API reference

All methods live on `TiltModuleClient` (prefix `tilt_module_`).

| Method | Description |
|--------|-------------|
| `tilt_module_connect(system_id, com_port)` | Open the COM port for a system (1–4); `com_port` is `3` or `"COM3"`. |
| `tilt_module_initialize(system_id, module_name)` | `EI`, `SI`, `RF`: reset error, home to 0°, read firmware. |
| `tilt_module_move_to_position(system_id, module_name, angle)` | `GP<angle>` (0–10, whole degrees), wait until idle. |
| `tilt_module_terminate_module(system_id, module_name)` | `GP0` then `PO`: back to horizontal, motor off. |
| `tilt_module_terminate_communication(system_id)` | Close the port (all its modules must be terminated first). |
| `tilt_module_get_status(system_id, module_name)` | Tracked angle, busy flag, firmware error. |
| `tilt_module_error_message(error_code)` | Text for a return code. |

## See Also

- [Combining `StarClient`/`VantageClient` with a standalone device client](./common_patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client)
- [Heater Cooler (HHC)](./heater_cooler.md) — the same standalone-client pattern
- [Tilt Labware and Split Wells](./deck_and_layout.md#tilt-labware) — tilting the plate in the deck layout
- [Tilt Module hardware notes](../tilt_module_hardware_notes.md)
