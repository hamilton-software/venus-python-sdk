# Inheco Single/Multi TEC Controller (STC/MTC)

Guide for controlling an Inheco Single/Multi TEC Controller — connecting, reading
identification, setting and reading temperature, and driving the shaker.

---

## Overview

The InhecoTEC controller manages up to 6 attached devices (a Thermoshake, CPAC,
Heated Lid, ...) per box, and up to 8 boxes can share one bus. The InhecoTEC
driver is **pure Python and does not go through the VENUS runtime** — it talks
to the device directly, and has its own standalone client, `InhecoTECClient`.
There is no `StarClient`/`VantageClient` involved at all; it works with no
instrument connection and regardless of `auto_connect` / `instrument_init()`.

This guide covers:

- Connecting to a controller and scanning its 6 device slots
- Reading identification, firmware and sensor values
- Setting and reading temperature control
- Driving the shaker
- Addressing: `controller_id` + `device_id`

### Hardware vs. simulation

The real device is reached through the vendor COM object (`InhecoMTCdll.GlobCom`),
a **32-bit** .NET server. The SDK's Python is usually 64-bit, so:

- on **32-bit Python** the object is created in-process;
- on **64-bit Python** the SDK runs `hamilton_venus._com32_worker` under a 32-bit
  Python and proxies each call over a JSON pipe. It uses a **private 32-bit
  Python** — `hamilton_venus/_com32_py32/python.exe` when your SDK build bundles
  one, otherwise the runtime installed by `setup-venus-sdk --install-py32` under
  `%PROGRAMDATA%\Hamilton\VenusSDK\py32` (shared with every other 32-bit-COM
  driver, e.g. the [Heater Cooler](./heater_cooler.md) and the
  [Media Fill Module](./media_fill.md)); `HAMILTON_INHECO_TEC_PYTHON32`
  overrides both, and a `py -3-32` install is the last fallback.

Unlike the Heater Cooler, `InhecoMTCdll.dll` ships with no external `.dll.config`
at all, so there is no binding-redirect or ProgramData-ACL step to run — 
`hamilton-inheco-tec --configure` is a presence check only.

If no COM path is reachable — the vendor driver isn't installed, there's no 32-bit
Python, or you pass `simulate=True` — the SDK logs a one-line diagnosis and uses a
built-in **simulation transport** instead of failing at `inheco_tec_connect`. Every
snippet below runs unchanged in simulation.

### Making a real connection work

The real controller also needs the `HSLInhecoTEC` library installed (under
`C:\Program Files (x86)\Hamilton\Library\HSLInhecoTEC`; it provides the COM
object). After running `setup-venus-sdk`, check:

```console
$ hamilton-inheco-tec --diagnose
64-bit Python:   True
driver:          installed
available:       True
diagnosis:       InhecoMTCdll.GlobCom is 32-bit; bridging through 32-bit Python (bundled).
...
$ hamilton-inheco-tec --selftest
selftest OK: created InhecoMTCdll.GlobCom via Bridge32Backend
```

It works **without elevation**. If `--selftest` fails:

- `driver: NOT installed` → install the `HSLInhecoTEC` library.
- `32-bit Python: (none found)` → run `setup-venus-sdk --install-py32` (installs
  Python 3.12 32-bit + pywin32 under `%PROGRAMDATA%\Hamilton\VenusSDK\py32`;
  `--py32-from <folder>` for offline PCs with the two pinned files
  `python-3.12.10-embed-win32.zip` and `pywin32-312-cp312-cp312-win32.whl`),
  otherwise install a 32-bit Python (3.11+, `pip install pywin32`) or set
  `HAMILTON_INHECO_TEC_PYTHON32`.

`hamilton_venus.inheco_tec.inheco_tec_com_diagnosis()` returns the diagnosis line
from Python.

---

## Fundamental Concepts

Addressing is **two-level**, matching the vendor's own `HSLInhecoTECLib.hsl`:

- `controller_id` (`0`-`7`) selects which physical controller box a command
  targets on the shared bus.
- `device_id` (`1`-`6`, or `0` for the controller unit itself) selects a slot on
  that box.

Create an `InhecoTECClient` (optionally as a `with` block — `close()` releases
the connection and, on 64-bit Python, the 32-bit worker subprocess) and call
`inheco_tec_connect(controller_id)` for **every** `controller_id` you intend to
use before any other command targeting it. It verifies the box answers on the
bus and bundles a scan of its own type (STC/MTC) plus every device slot's type,
so a single call tells you what's actually plugged in. A Single TEC (STC)
controller has exactly 1 physical slot, so only slot 1 is scanned; a Multi TEC
(MTC) has up to 6, all of which are scanned.

### Not every slot can do everything

A CPAC, CPLC, Heat_PAC, Heated_Lid, ... is a **temperature-only** block with no
shaker motor; only a Thermoshake/Teleshake (and their AC variants) actually
shake. `inheco_tec_connect`'s per-slot `device_type_name` tells you which is
which. The vendor library itself never checks this before sending a shaker
command — it lets the physical device reject an inapplicable one — so neither
does this driver; `hamilton_venus.inheco_tec.SHAKER_CAPABLE_DEVICE_TYPES` is a
convenience set your own script can check before calling a shaker method:

```python
from hamilton_venus.inheco_tec import SHAKER_CAPABLE_DEVICE_TYPES

# tec is an InhecoTECClient (see "Connect and inspect" below)
devices = tec.inheco_tec_connect(0).return_parameters.devices
shaker_slot = next((d.device_id for d in devices if d.device_type in SHAKER_CAPABLE_DEVICE_TYPES), None)
```

---

## Basic Operations

### Connect and inspect

```python
from hamilton_venus import InhecoTECClient

with InhecoTECClient(simulate=True) as tec:
    connected = tec.inheco_tec_connect(0)
    params = connected.return_parameters
    print(f"controller_id={params.controller_id}: {params.controller_type_name}")
    for slot in params.devices:
        print(f"  slot {slot.device_id}: {slot.device_type_name}")
```

### Identification, firmware, sensors

```python
from hamilton_venus import InhecoTECClient

with InhecoTECClient(simulate=True) as tec:
    tec.inheco_tec_connect(0)

    ident = tec.inheco_tec_get_identification(0, device_id=1).return_parameters
    print(f"{ident.device_type_name} sn={ident.serial_number} runtime={ident.runtime_minutes} min")

    fw = tec.inheco_tec_get_firmware_version(0).return_parameters  # selector=1 (Application_Version)
    print(f"firmware: {fw.value}")
```

### Set a temperature and read it back

```python
from hamilton_venus import InhecoTECClient

with InhecoTECClient(simulate=True) as tec:
    tec.inheco_tec_connect(0)

    tec.inheco_tec_set_target_temperature(0, device_id=1, target_c=8.0)
    tec.inheco_tec_start_temperature_control(0, device_id=1)

    status = tec.inheco_tec_get_temperature_status(0, device_id=1).return_parameters
    print(f"actual={status.actual_temperature} C target={status.target_temperature} C "
          f"heater={status.heater_status_name}")

    tec.inheco_tec_stop_temperature_control(0, device_id=1)
```

`target_c` must be within `[0, 199.9]` °C — a value outside that range raises
`ValueError`. There is no built-in "wait for band" helper (the vendor library
doesn't offer one either) — poll `inheco_tec_get_temperature_status` in your own
loop, same as a VENUS method would.

### Drive the shaker

Slot 1 in these examples is a CPAC (temperature-only); slot 2 is a
Thermoshake — the shaker methods below target slot 2, not slot 1:

```python
from hamilton_venus import InhecoTECClient

with InhecoTECClient(simulate=True) as tec:
    tec.inheco_tec_connect(0)

    tec.inheco_tec_set_shaker_shape(0, device_id=2, shape=0)   # 0 = Circular_CCW
    tec.inheco_tec_set_shaker_revolutions(0, device_id=2, rpm=600)
    tec.inheco_tec_start_shaker(0, device_id=2)

    status = tec.inheco_tec_get_shaker_status(0, device_id=2).return_parameters
    print(f"revolutions={status.revolutions} shape={status.shape_name}")

    tec.inheco_tec_stop_shaker(0, device_id=2)
```

---

## Querying State

```python
from hamilton_venus import InhecoTECClient

with InhecoTECClient(simulate=True) as tec:
    tec.inheco_tec_connect(0)

    reservoir = tec.inheco_tec_get_reservoir_status(0, device_id=1).return_parameters
    print(f"reservoir: {reservoir.status_name}")

    sensor = tec.inheco_tec_get_sensor_values(0, selector=2).return_parameters
    print(f"{sensor.selector_name}: {sensor.value}")
```

---

## Escape Hatch: Raw Commands

For anything this device group doesn't otherwise expose, send a raw ASCII
command string directly (mirrors the vendor's own `SendCommandString`), on a
connected client:

```python
result = tec.inheco_tec_send_command(0, "1RAT3")
print(result.return_parameters.response)
```

---

## Lifecycle

```python
tec.inheco_tec_terminate()   # stops shaker + temp control on every connected
                              # controller's slots first, then releases the connection
```

`close()` (or exiting the `with` block) does the same thing.

---

## Inheco TEC API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `inheco_tec_connect(controller_id)` | `InhecoTECConnectResponse` | Verify the controller answers; scan its 6 device slots |
| `inheco_tec_get_identification(controller_id, device_id=0)` | `InhecoTECIdentificationResponse` | Device type, serial number, runtime, calibration date |
| `inheco_tec_get_firmware_version(controller_id, selector=1)` | `InhecoTECFirmwareResponse` | One firmware field (bootstrap/application/serial/hardware/copyright) |
| `inheco_tec_get_sensor_values(controller_id, selector)` | `InhecoTECSensorValueResponse` | One controller housing sensor |
| `inheco_tec_get_reservoir_status(controller_id, device_id)` | `InhecoTECReservoirStatusResponse` | Reservoir/refill status |
| `inheco_tec_get_temperature_status(controller_id, device_id, *, temperature_selector=3)` | `InhecoTECTemperatureStatusResponse` | Actual/target temperature, limits, heater status |
| `inheco_tec_set_target_temperature(controller_id, device_id, target_c)` | `MessageResponse` | Set target temperature (0-199.9 °C) |
| `inheco_tec_start_temperature_control(controller_id, device_id)` | `MessageResponse` | Start heating/cooling toward the target |
| `inheco_tec_stop_temperature_control(controller_id, device_id)` | `MessageResponse` | Stop temperature control |
| `inheco_tec_get_shaker_status(controller_id, device_id)` | `InhecoTECShakerStatusResponse` | Shaker run status, revolutions, shape |
| `inheco_tec_set_shaker_revolutions(controller_id, device_id, rpm)` | `MessageResponse` | Set shaker speed (60-3000, or 0 to clamp only) |
| `inheco_tec_set_shaker_shape(controller_id, device_id, shape)` | `MessageResponse` | Set shaker motion shape (0-5) |
| `inheco_tec_start_shaker(controller_id, device_id)` | `MessageResponse` | Start shaking |
| `inheco_tec_stop_shaker(controller_id, device_id)` | `MessageResponse` | Stop shaking |
| `inheco_tec_set_touchscreen(controller_id, enabled)` | `MessageResponse` | Controller's own touchscreen on/off |
| `inheco_tec_send_command(controller_id, command)` | `InhecoTECRawResponse` | Raw ASCII command escape hatch |
| `inheco_tec_terminate(*, stop_all_devices=True)` | `MessageResponse` | Disconnect every controller |

`close()` (or exiting the `with` block) also disconnects every controller, same
as `inheco_tec_terminate()`.

---

## See Also

- [`../star_commands.md`](../star_commands.md) — Full API reference
- [`heater_cooler.md`](./heater_cooler.md) — Hamilton Heater Cooler (HHC, same pure-Python, no-VENUS approach)
- [`odtc.md`](./odtc.md) — Inheco ODTC thermal cycler (same pure-Python, no-VENUS approach)
- [`common_patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client`](./common_patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client) — using `InhecoTECClient` alongside `StarClient`/`VantageClient` in one script
