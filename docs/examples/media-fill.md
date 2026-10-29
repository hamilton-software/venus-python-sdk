# Hamilton Media Fill Module

Guide for controlling the Hamilton Media Fill Module — connecting, setting pump
direction, filling troughs, pumping out and reading the liquid level sensors.

> **Status:** run on a real module (firmware `Media Fill Module V1.00 94821-01 A`, USB
> 2341/0043 on COM5, one pump) on 2026-10-15: connect, status, direction, fill to the
> sensor, pump out, stop by disconnect — the full hardware test passed with all 12
> `media_fill_*` functions. See [Media Fill hardware notes](../media-fill-hardware-notes.md).

---

## Overview

The Media Fill Module pumps media into reagent troughs. Each module has **four pumps**,
each with a **liquid level sensor** in its trough; a fill runs until that sensor
triggers or a timeout elapses. The driver is **pure Python and does not go through the
VENUS runtime** — it talks to the device directly, and has its own standalone client,
`MediaFillClient`. There is no `StarClient`/`VantageClient` involved at all; it works
with no instrument connection and regardless of `auto_connect` / `instrument_init()`.

The Python methods map one-to-one onto the functions of the vendor HSL library
(`HxMediaFill` 2.0, or the older `HSLHamiltonMediaFillModule` 1.1), so anything written
against the HSL library translates directly.

This guide covers:

- Connecting to one or more modules
- Setting and reading pump direction
- Starting a fill, waiting for it, and reading the liquid level sensors
- Error messages and disconnecting

### Vendor library: 2.0 or 1.1

The driver works with either Hamilton Media Fill library and uses whichever is installed
(2.0 when both are; set `HAMILTON_MEDIA_FILL_PROGID` to choose):

| | 2.0 (`HxMediaFill` 2.0.8767 MSI) | 1.1 (`HSLHamiltonMediaFillModule`) |
|---|---|---|
| COM object | `HxMediaFill.HxMediaFillCOM` | `Hamilton.HxMediaFillModule` |
| DLL | `Bin\Hamilton Media Fill\HxMediaFillCOM.dll` (.NET 4) | `Bin\HxMediaFill.dll` (.NET 2.0) |
| Pump out | `EmptyLineToSource`, **at most 20 s** | `WastePumpNoSensor`, up to Hamilton's 720 s limit |
| Stop one pump | `StopPump` → `media_fill_stop_pump` | not available (use `media_fill_disconnect`) |
| `WaitForPump` | errors after its default 1 minute | waits until the pump stops |
| Firmware version | read with the module's serial query at connect | `GetFirmwareVersion` |
| COM port range | 1–256 | 1–65535 |

`media_fill_connect` and `media_fill_get_status` report the library in use as
`vendor_api` (`"2.0"`, `"1.1"` or `"simulated"`); `hamilton-media-fill --diagnose` shows it
as `vendor object`. Pump out works the same with both: reverse of the set direction,
ignoring the sensor.

### Hardware vs. simulation

The real device is reached through the vendor COM object (see above), a **32-bit** COM
server registered by the Hamilton Media Fill library. The SDK's Python is usually 64-bit, so:

- on **32-bit Python** the object is created in-process;
- on **64-bit Python** the SDK runs `hamilton_venus._com32_worker` under a 32-bit
  Python and proxies each call over a JSON pipe. The SDK **bundles a private 32-bit
  Python** at `hamilton_venus/_com32_py32/python.exe` (shared with every other
  32-bit-COM driver, e.g. the [Heater Cooler](./heater-cooler.md));
  `HAMILTON_MEDIA_FILL_PYTHON32` overrides it, and without it a `py -3-32` install is used.

The 2.0 DLL is a .NET 4 component registered with a `CodeBase`, so it needs no further
setup. For the 1.1 `HxMediaFill.dll` (.NET 2.0), VENUS runs it on .NET 4 (its
`HxRun.exe.config` sets `useLegacyV2RuntimeActivationPolicy`); the driver gives the bundled
32-bit Python the same setting in its `python.exe.config`, so .NET Framework 3.5 isn't
needed. Neither DLL uses Hamilton TransportLayer assemblies, so no binding redirects are
involved.

The module itself is a USB virtual COM port. On Windows 10/11 it appears automatically
as **USB Serial Device (COM*n*)** under *Ports* in Device Manager; on Windows 7 install
its USB driver first (`DPInst` with the vendor's `Ruggeduino.inf`).

If no COM path is reachable — the vendor library isn't installed, there's no 32-bit
Python, or you pass `simulate=True` — the SDK logs a one-line diagnosis and uses a
built-in **simulation transport** instead of failing at `media_fill_connect`. It models
four pumps per module, starts them counter-clockwise, rejects what the vendor object
rejects (COM port outside 1–65535 or already open, pump outside 1–4, speed outside
30–100 %, direction other than 0/1) with the vendor's own messages, and triggers the
liquid level sensor a few polls after a fill starts. Every snippet below runs unchanged
in simulation.

### Making a real connection work

```console
$ hamilton-media-fill --diagnose
64-bit Python:   True
vendor object:   HxMediaFill.HxMediaFillCOM (2.0 library)
registered:      C:\Program Files (x86)\Hamilton\Bin\Hamilton Media Fill\HxMediaFillCOM.dll
CLSID:           {ADFEA221-F5D4-3635-90BF-8FFC8C20CAC0}
assembly:        HxMediaFillCOM, Version=2.0.8767.17585, Culture=neutral, PublicKeyToken=null
runtime:         v4.0.30319
CodeBase:        C:\Program Files (x86)\Hamilton\Bin\Hamilton Media Fill\HxMediaFillCOM.dll
available:       True
diagnosis:       HxMediaFill.HxMediaFillCOM (2.0) is 32-bit; bridging through 32-bit Python (bundled); ...
32-bit Python:   ...\src\hamilton_venus\_com32_py32\python.exe
.NET 3.5:        installed
$ hamilton-media-fill --selftest
selftest OK: created HxMediaFill.HxMediaFillCOM (2.0) via Bridge32Backend
$ hamilton-media-fill --list-ports
COM5  USB Serial Device (COM5)
$ hamilton-media-fill --probe COM5
probe OK: COM5 firmware 'Media Fill Module V1.00 94821-01 A'; P1 counter_clockwise S1=0 stopped, ...
```

**Finding modules, and only modules.** Every Media Fill Module has the same USB id —
2341/0043 on the module tested (Arduino's own id: the controller is an Uno-type board), or
the 16D0/0613 of the vendor's `.inf` — and each unit has its own USB serial and COM port.

- `--list-ports` lists every port with that id, with its serial, **without opening anything**.
- A port **without** that USB id (a Tilt Module's RS-232 adapter, a Bluetooth link, a
  camera, ...) is refused unopened by `media_fill_connect`, `--probe` and `--find`, even
  when named explicitly.
- Because an Arduino Uno shares the id, `media_fill_connect` on real hardware first sends
  the module's firmware query `:11;` — and nothing else — and **refuses** the port unless
  the reply contains `Media Fill Module`. Only then does the vendor `Initialize` run (which
  has no identity check of its own). The firmware is checked once more after connecting.
- `--find` sends that query to each port from `--list-ports` and lists the confirmed
  modules. `--probe COMn` sends the four read-only queries (firmware, sensors, pump
  status, directions) and reports each pump's direction, sensor and whether it is
  **running** — a status the vendor API doesn't offer. Nothing moves; the vendor object
  isn't involved (so the port must not be connected elsewhere).
- From Python: `hamilton_venus.media_fill.raw_status("COM5")` returns the same as a dict;
  `raw_query` sends only the query commands 7, 10, 11 and 13 and refuses any other.

```console
$ hamilton-media-fill --find
COM5  'Media Fill Module V1.00 94821-01 A'  USB Serial Device (COM5)  serial 754393332353519041C0
```

Then run the hardware test (`example_scripts\media_fill_hardware_test.py`, see below).

Day-to-day use needs **no elevation**. If `--selftest` fails, the `diagnosis` line says
why:

- `registered: (not registered)` → install the Hamilton Media Fill Module library.
- `registered without a CodeBase` (1.1 only) → `HxMediaFill.dll` isn't strong-named, so without a
  `CodeBase` in its COM registration only programs started from VENUS's `Bin` folder can
  load it. Run `hamilton-media-fill --register-codebase` once, as Administrator (it runs
  the 32-bit .NET `RegAsm.exe HxMediaFill.dll /codebase`; VENUS is unaffected). If the DLL
  isn't in `C:\Program Files (x86)\HAMILTON\Bin`, set `HAMILTON_MEDIA_FILL_BIN_DIR` to its folder.
- `.NET Framework 3.5` / `host config: ... no .NET 4 policy` (1.1 only) → run
  `hamilton-media-fill --configure` (adds the `<startup>` setting above to the 32-bit
  Python's `python.exe.config`; as Administrator if the SDK is under Program Files), or
  turn on .NET Framework 3.5 in Windows Features.
- `32-bit Python: (none found)` → the SDK's bundled `_com32_py32` is missing; reinstall the
  SDK, install a 32-bit Python (3.11+, `pip install pywin32`), or set
  `HAMILTON_MEDIA_FILL_PYTHON32`.

`hamilton_venus.media_fill.media_fill_com_diagnosis()` returns the diagnosis line from
Python. Only one process can control a module at a time, so close any VENUS method (or
other script) that has it open before connecting.

---

## Fundamental Concepts

Create a `MediaFillClient` (optionally as a `with` block — `close()` disconnects every
module, which **stops any running pump**, and releases the vendor object and, on 64-bit
Python, the 32-bit worker subprocess) and call `media_fill_connect(com_port)` first. It
opens the module on that COM port (HSL `Initialize`), reads its firmware version, and
assigns an integer `device_id` (`1..N`, lowest free first). Every other command takes
`device_id` (default `1`) in place of the HSL's `InstrumentId`.

Pumps are numbered **1–4**. A fill is **asynchronous**: `media_fill_fill_trough` returns
as soon as the pump starts, and the pump keeps running until its trough's liquid level
sensor triggers or `timeout` **seconds** elapse. `speed` is a relative rate, **30–100 %**.
`media_fill_wait_for_pump` blocks until the pump stops. Every pump starts each run
**counter-clockwise**.

The liquid level sensor reads **0** when no liquid is detected, and **1** when liquid
is detected — but also when the sensor is unplugged or the controller is powered down,
so a `1` before a fill is worth checking.

Values are passed through unchanged, as the HSL does; the vendor COM object checks them
(COM port 1–65535 in 1.1 / 1–256 in 2.0, pump 1–4, speed 30–100, direction 0/1). A failed command raises
`MediaFillError` (a `VenusError`) carrying the vendor's error text. A fill on a trough whose
sensor already reads liquid succeeds without pumping (`media_fill_get_last_error_message`
then reads `SENSOR ON`); before the first error it reads `No error.`.

**Pumping out.** `media_fill_waste_pump_no_sensor` (vendor `EmptyLineToSource` in 2.0,
`WastePumpNoSensor` in 1.1) runs the pump in the **reverse** of the direction set with
`media_fill_set_pump_direction` and **ignores the sensor**. Leave the pump on its fill
direction and it pulls liquid back from the trough toward the source bottle; set the other
direction first and it pumps *into* the trough with no sensor stop (verified on a real
module with the 1.1 library, firmware V1.00 94821-01 A; the 2.0 documentation describes the
same). It runs for the full `timeout`: at most **20 s** with the 2.0 library; with 1.1, keep
it within Hamilton's **720 s** limit per pumping operation (that vendor object doesn't check
it). Stop it early with `media_fill_stop_pump` (2.0) or `media_fill_disconnect`.

```python
with MediaFillClient() as mfm:
    mfm.media_fill_connect("COM5")
    mfm.media_fill_fill_trough(pump_id=1, speed=60, timeout=180)            # in, stops at the sensor
    mfm.media_fill_wait_for_pump(pump_id=1)
    mfm.media_fill_waste_pump_no_sensor(pump_id=1, speed=60, timeout=20)    # out, same direction setting
    mfm.media_fill_wait_for_pump(pump_id=1)
```

`media_fill_get_status` (1.3.0+) reads everything the module reports in one call —
firmware, each pump's direction and sensor, the last error message — and moves nothing.
The vendor API has no "is the pump running" query; `media_fill_wait_for_pump` is the only
way to learn a pump stopped.

| HSL function (2.0 / 1.1) | Python method |
|---|---|
| `Initialize` | `media_fill_connect` |
| `Disconnect` | `media_fill_disconnect` |
| `GetPumpDirection` | `media_fill_get_pump_direction` |
| `SetPumpDirection` | `media_fill_set_pump_direction` |
| `GetLiquidLevelSensorState` | `media_fill_get_liquid_level_sensor_state` |
| `FillTrough` | `media_fill_fill_trough` |
| `EmptyLineToSource` / `WastePumpNoSensor` (1.1: in the `.hs_`, not the header) | `media_fill_waste_pump_no_sensor` |
| `WaitForPump` | `media_fill_wait_for_pump` |
| `StopPump` (2.0 only) | `media_fill_stop_pump` |
| `GetLastErrorMessage` | `media_fill_get_last_error_message` |

---

## Basic Operations

### Connect and inspect

```python
from hamilton_venus import MediaFillClient

with MediaFillClient(simulate=True) as mfm:
    info = mfm.media_fill_connect("COM5").return_parameters   # 5 or "COM5"
    print(f"device {info.device_id}: COM{info.com_port} firmware={info.firmware_version}")
```

### Fill a trough and wait for it

```python
from hamilton_venus import MediaFillClient

with MediaFillClient(simulate=True) as mfm:
    mfm.media_fill_connect("COM5")

    mfm.media_fill_fill_trough(pump_id=1, speed=60, timeout=90)   # returns immediately
    # ... do other work ...
    mfm.media_fill_wait_for_pump(pump_id=1)                        # block until it stops

    state = mfm.media_fill_get_liquid_level_sensor_state(pump_id=1).return_parameters
    print("full" if state.liquid_level_sensor_state == 1 else "timed out before the sensor triggered")
```

### Set the pump direction

```python
from hamilton_venus import MediaFillClient
from hamilton_venus.models import PumpDirection

with MediaFillClient(simulate=True) as mfm:
    mfm.media_fill_connect("COM5")
    mfm.media_fill_set_pump_direction(pump_id=2, direction=PumpDirection.CLOCKWISE)   # or 1 / "cw"
    print(mfm.media_fill_get_pump_direction(pump_id=2).return_parameters.direction_name)
```

### Several modules

```python
from hamilton_venus import MediaFillClient

with MediaFillClient(simulate=True) as mfm:
    left = mfm.media_fill_connect("COM5").return_parameters.device_id    # 1
    right = mfm.media_fill_connect("COM6").return_parameters.device_id   # 2

    for device_id in (left, right):
        mfm.media_fill_fill_trough(pump_id=1, speed=60, timeout=90, device_id=device_id)
    for device_id in (left, right):
        mfm.media_fill_wait_for_pump(pump_id=1, device_id=device_id)
```

---

## Querying State

```python
from hamilton_venus import MediaFillClient

with MediaFillClient(simulate=True) as mfm:
    mfm.media_fill_connect("COM5")

    for unit in mfm.media_fill_get_device_ids().return_parameters.device_ids:
        print(f"device {unit.device_id}: COM{unit.com_port} firmware={unit.firmware_version}")

    for pump_id in range(1, 5):
        direction = mfm.media_fill_get_pump_direction(pump_id).return_parameters.direction_name
        sensor = mfm.media_fill_get_liquid_level_sensor_state(pump_id).return_parameters.liquid_level_sensor_state
        print(f"pump {pump_id}: {direction}, sensor={sensor}")
```

---

## Errors and Disconnecting

```python
from hamilton_venus import MediaFillClient, MediaFillError

with MediaFillClient(simulate=True) as mfm:
    mfm.media_fill_connect("COM5")
    try:
        mfm.media_fill_fill_trough(pump_id=1, speed=10, timeout=60)   # below the 30 % minimum
    except MediaFillError as exc:
        print(exc)                                                     # includes the vendor's message
        print(mfm.media_fill_get_last_error_message().return_parameters.error_message)

    mfm.media_fill_disconnect(device_id=1)   # stops that module's pumps
```

To stop a fill part-way, call `media_fill_stop_pump(pump_id)` (2.0 library), or disconnect
the module (`media_fill_disconnect`) — the vendor driver stops its active pumps. If a
disconnect fails, the module stays registered, and `close()` / `media_fill_terminate()`
retries it and then falls back to the vendor's `Abort` (2.0) / `AbortAll` (1.1) — what the
HSL library's own abort handler calls. Commands on one client run one at a time, so start the
fill without waiting if you may need to stop it.

What the vendor driver does that the SDK handles for you:

- **A failed `media_fill_connect`** (wrong port, port open in VENUS or a terminal, module
  unplugged) leaves that COM port reserved inside the vendor object. The SDK starts a
  fresh vendor object as soon as no module is connected on the client — at once if none
  is — so fix the cause and connect again. While other modules stay connected, retrying
  that port fails ("already being controlled by HSL"): disconnect them, or call
  `media_fill_terminate()`, first. A port that exists but doesn't answer takes up to
  5 minutes to fail (the vendor's serial timeout).
- **A lost module, or a restarted vendor driver.** When the vendor driver reports a module
  lost ("... lost connection ... Initialize must be called"), or the SDK's 32-bit worker
  ended (pulling a USB module can crash it) and a new one was started, those modules are
  no longer connected. Commands on their `device_id` raise `MediaFillError` telling you to
  connect that COM port again — they never reach another module — and reconnecting the
  port gives it its `device_id` back.

`MediaFillError.error_code` is the vendor call's return code when the vendor object
reported the failure, and `None` for errors the SDK raises itself (unknown `device_id`,
missing driver, a COM error). 1.1 returns `1` for any failure; 2.0 returns `1` BadParameter,
`2` DeviceError, `3` ConnectionError or `4` GeneralError (the message names it).

**2.0 vendor messages** seen through the SDK:

| Message | Meaning |
|---|---|
| `The device is not in the collection of connected Media Fill devices.` | Module not connected (or lost); connect its COM port again |
| `The device is already in the collection of connected devices.` | That COM port is already connected |
| `COMPort variable is out of range of accepted values, ... between 1 and 256 inclusive` | COM port outside 1–256 |

**1.1 vendor messages** (verbatim from `HxMediaFill.dll`; the simulator raises the same):

| Message | Meaning |
|---|---|
| `No error.` | Nothing has failed since the vendor object was created |
| `SENSOR ON` | A fill on a trough whose sensor already reads liquid: success, nothing pumped |
| `Error, Speeed variable is out of range of accepted values, ...` (sic) | `FillTrough` speed outside 30–100 % |
| `Error. Speed variable is out of range of accepted values. ...` | `WastePumpNoSensor` speed outside 30–100 % (its own wording) |
| `Error, PumpID variable is out of range of accepted values, ...` | Pump outside 1–4 |
| `Error, Direction variable is out of range of accepted values, ...` | Direction other than 0/1 |
| `Error, COMPort variable is out of range of accepted values, ...` | COM port outside 1–65535 |
| `Error, unable to connect to instrument on COMn; ... already being controlled by HSL.` | Port still reserved after a failed connect, see above |
| `Failed to connect to Media Fill Module ...` | Wrong port, port open elsewhere, or module not on USB |
| `... lost connection with the following error message ...` | Module lost; connect its COM port again |
| `Error, provided DeviceID does not correspond to an existing instrument.` | Instrument id unknown to the vendor object |

---

## Hardware Test

`example_scripts\media_fill_hardware_test.py` checks a real module in stages: preflight, read-only, direction,
optional sensor check, fill, pump out and stop. It asks before anything pumps, watches all four
sensors while a pump runs and stops the module if the wrong one trips, writes a `.log` and a
`.json` per run, and reports which `media_fill_*` functions it used. With the 2.0 library it
also checks `media_fill_stop_pump` and keeps pump-out runs within 20 s.

```console
python example_scripts\media_fill_hardware_test.py --simulate --full                              # dry run
python example_scripts\media_fill_hardware_test.py --real COM5                                    # nothing pumps
python example_scripts\media_fill_hardware_test.py --real COM5 --full --speed 60 --timeout 180    # everything, every driver function
```

Exit code 0 = PASS, 1 = FAIL, 2 = INCOMPLETE (a requested check was skipped).

---

## Production Pattern: Fill Before a Run

```python
import logging
from hamilton_venus import MediaFillClient, MediaFillError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fill(mfm: MediaFillClient, pumps: list[int], speed: int = 60, timeout: int = 120, device_id: int = 1) -> None:
    """Fill every trough in *pumps* in parallel, then confirm each sensor triggered."""
    for pump_id in pumps:
        mfm.media_fill_fill_trough(pump_id, speed, timeout, device_id=device_id)
    for pump_id in pumps:
        mfm.media_fill_wait_for_pump(pump_id, device_id=device_id)
        state = mfm.media_fill_get_liquid_level_sensor_state(pump_id, device_id=device_id)
        if state.return_parameters.liquid_level_sensor_state != 1:
            raise MediaFillError(f"pump {pump_id}: timed out before the trough was full")
        logger.info("pump %d: trough full", pump_id)


with MediaFillClient(simulate=True) as mfm:
    mfm.media_fill_connect("COM5")
    fill(mfm, pumps=[1, 2])
```

---

## Media Fill API Reference

| Method | Returns | HSL function / description |
|--------|---------|-------------|
| `media_fill_connect(com_port)` | `MediaFillConnectResponse` | `Initialize` (+ firmware read): open the module on `com_port`; returns `device_id`, COM port, instrument id, firmware, `simulated`, `vendor_api` |
| `media_fill_get_device_ids()` | `MediaFillDeviceIdsResponse` | List connected modules + firmware |
| `media_fill_get_pump_direction(pump_id, device_id=1)` | `MediaFillPumpDirectionResponse` | `GetPumpDirection`: 0 counter-clockwise, 1 clockwise |
| `media_fill_set_pump_direction(pump_id, direction, device_id=1)` | `MessageResponse` | `SetPumpDirection`: `PumpDirection`, 0/1 or "ccw"/"cw" |
| `media_fill_get_liquid_level_sensor_state(pump_id, device_id=1)` | `MediaFillLiquidLevelSensorStateResponse` | `GetLiquidLevelSensorState`: 0 no liquid; 1 liquid, sensor unplugged or controller off |
| `media_fill_fill_trough(pump_id, speed, timeout, device_id=1)` | `MessageResponse` | `FillTrough`: start a fill (speed 30–100 %, timeout in s); returns immediately |
| `media_fill_waste_pump_no_sensor(pump_id, speed, timeout, device_id=1)` | `MessageResponse` | `EmptyLineToSource` (2.0) / `WastePumpNoSensor` (1.1): pump out — reverse of the set direction, ignores the sensor (speed 30–100 %, runs the full timeout, max 20 s on 2.0 / 720 s on 1.1); returns immediately |
| `media_fill_wait_for_pump(pump_id, device_id=1)` | `MessageResponse` | `WaitForPump`: block until the pump stops (2.0: error after 1 minute) |
| `media_fill_stop_pump(pump_id, device_id=1)` | `MessageResponse` | `StopPump` (2.0 only): stop one pump, module stays connected |
| `media_fill_get_last_error_message()` | `MediaFillLastErrorMessageResponse` | `GetLastErrorMessage` |
| `media_fill_get_status(device_id=1)` | `MediaFillStatusResponse` | firmware, every pump's direction + sensor, last error, `vendor_api` (read-only) |
| `media_fill_disconnect(device_id=1)` | `MessageResponse` | `Disconnect`: close one module; stops its pumps |
| `media_fill_terminate()` | `MessageResponse` | Disconnect every module and release the vendor object |

`close()` (or exiting the `with` block) disconnects every module, same as
`media_fill_terminate()`.

---

## See Also

- [`../media-fill-hardware-notes.md`](../media-fill-hardware-notes.md) — what the real module does (USB id, firmware, pump-out direction, timings)
- [`../star-commands.md`](../star-commands.md) — Full API reference
- [`heater-cooler.md`](./heater-cooler.md) — Hamilton Heater Cooler (same pure-Python, no-VENUS approach)
- [`odtc.md`](./odtc.md) — Inheco ODTC thermal cycler (same approach)
- [`common-patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client`](./common-patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client) — using `MediaFillClient` alongside `StarClient`/`VantageClient` in one script
