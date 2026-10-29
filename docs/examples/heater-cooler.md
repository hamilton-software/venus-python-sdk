# Heater Cooler (HHC)

Guide for controlling Hamilton Heater Cooler (HHC) blocks — connecting, setting and
holding a temperature, and reading status.

---

## Overview

The HHC is a Peltier heat/cool block (**0 °C … 110 °C**). The HHC driver is **pure
Python and does not go through the VENUS runtime** — it talks to the device directly,
and has its own standalone client, `HeaterCoolerClient`. There is no
`StarClient`/`VantageClient` involved at all; it works with no instrument connection
and regardless of `auto_connect` / `instrument_init()`.

This guide covers:

- Connecting to an HHC daisy chain and registering its units
- Starting, holding, waiting on, and stopping temperature control
- Reading device status, firmware and verification date
- Display, identify and self-diagnostic helpers

### Hardware vs. simulation

The real device is reached through the vendor COM object
(`HamiltonHeaterCoolerCOM`), a **32-bit** .NET server. The SDK's Python is usually
64-bit, so:

- on **32-bit Python** the object is created in-process;
- on **64-bit Python** the SDK runs `hamilton_venus._com32_worker` under a 32-bit
  Python and proxies each call over a JSON pipe. The SDK **bundles a private
  32-bit Python** at `hamilton_venus/_com32_py32/python.exe` (shared with every
  other 32-bit-COM driver, e.g. the [Inheco ODTC](./odtc.md)), or uses the
  runtime installed by `setup-venus-sdk --install-py32` under
  `%PROGRAMDATA%\Hamilton\VenusSDK\py32`;
  `HAMILTON_HHC_PYTHON32` or a `py -3-32` install override it.

`HamiltonHeaterCoolerCOM.dll` is also built against an older
`Hamilton.Components.TransportLayer.*` than the build in the vendor `Bin` folder,
so the worker needs a binding-redirect `python.exe.config`. `setup-venus-sdk`
writes it at install time (versions read from the on-disk DLLs); the worker also
writes it itself on first run as a fallback.

If no COM path is reachable — the vendor driver isn't installed, there's no 32-bit
Python, or you pass `simulate=True` — the SDK logs a one-line diagnosis and uses a
built-in **simulation transport** (in-memory, enforces the 0–110 °C limit, ramps
toward the target) instead of failing at `hhc_connect`. Every snippet below runs
unchanged in simulation.

### Making a real connection work

After installing with `setup-venus-sdk` (the installer runs it), check:

```console
$ hamilton-hhc --diagnose
64-bit Python:   True
driver:          installed
available:       True
diagnosis:       HamiltonHeaterCoolerCOM is 32-bit; bridging through 32-bit Python (bundled).
...
$ hamilton-hhc --selftest
selftest OK: created HamiltonHeaterCoolerCOM.HamiltonHeaterCoolerHSLCOM via _Bridge32Backend
```

It works **without elevation**. If `--selftest` fails:

- `driver: NOT installed` → install the Hamilton HeaterCooler driver.
- `32-bit Python: (none found)` → run `setup-venus-sdk --install-py32` (installs
  Python 3.12 32-bit + pywin32 under `%PROGRAMDATA%\Hamilton\VenusSDK\py32`;
  `--py32-from <folder>` for offline PCs with the two pinned files
  `python-3.12.10-embed-win32.zip` and `pywin32-312-cp312-cp312-win32.whl`),
  otherwise install a 32-bit Python (3.11+, `pip install pywin32`) or set
  `HAMILTON_HHC_PYTHON32`.
- a binding / `0x80070002` error from the worker → run `hamilton-hhc --configure`
  from an elevated shell to (re)write the 32-bit-Python `.config` and the
  ProgramData log ACL. `hamilton-hhc --fix-permissions` re-does just the ACL.

`hamilton_venus.heater_cooler.heater_cooler_com_diagnosis()` returns the diagnosis
line from Python.

---

## Fundamental Concepts

Create a `HeaterCoolerClient` (optionally as a `with` block — `close()` releases the
connection and, on 64-bit Python, the 32-bit worker subprocess) and call
`hhc_connect(address)` first. It opens the chain and assigns an integer `device_id`
(`1..N`) to each unit, in the order the chain reports serial numbers — the same
convention as the Heater Shaker. Every other command takes an optional `device_id`;
when omitted it applies to **all** registered units.

`hhc_connect` also bundles a per-unit read of firmware version, current temperature
and verification date, so a single call gives you everything you need to confirm the
connection.

---

## Basic Operations

### Connect and inspect

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    connected = hhc.hhc_connect("COM4")          # address = COM port / USB id
    for unit in connected.return_parameters.units:
        print(
            f"device {unit.device_id}: sn={unit.serial_number} "
            f"fw={unit.firmware_version} temp={unit.temperature} °C "
            f"verified={unit.verification_date}"
        )
```

### Set a temperature and wait for it

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    hhc.hhc_connect("COM4")

    # Drive every unit to 8 °C (±0.5 °C) and block until in band.
    hhc.hhc_start_temp_control(target=8.0, wait=True, timeout=1800)

    row = hhc.hhc_get_status().return_parameters.device_ids[0]
    print(f"unit {row.device_id}: {row.temperature} °C, controlling={row.controlling}")

    hhc.hhc_stop_temp_control()
```

`target` must be within `[0, 110]` °C — a value outside that range raises
`ValueError`. `tolerance` (default `0.5`) sets the acceptance band
`[target − tolerance, target + tolerance]`, clamped to the device limits.

### Non-blocking set, then wait later

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    hhc.hhc_connect("COM4")

    hhc.hhc_start_temp_control(target=40.0)       # returns immediately
    # ... do other work ...
    hhc.hhc_wait_for_temp_control(timeout=1800)   # block until in band
```

### Hold a temperature for a fixed time

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    hhc.hhc_connect("COM4")
    hhc.hhc_hold_temp_for_time(target=65.0, minutes=15.0)
```

---

## Querying State

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    hhc.hhc_connect("COM4")

    for unit in hhc.hhc_get_device_ids().return_parameters.device_ids:
        print(f"device {unit.device_id}: sn={unit.serial_number} fw={unit.firmware_version}")

    for row in hhc.hhc_get_status().return_parameters.device_ids:
        print(f"device {row.device_id}: {row.temperature} °C, "
              f"remaining={row.time_remaining}, controlling={row.controlling}")
```

---

## Display, Identify, Diagnostics

```python
from hamilton_venus import HeaterCoolerClient

with HeaterCoolerClient(simulate=True) as hhc:
    hhc.hhc_connect("COM4")

    hhc.hhc_identify(device_id=1)                       # blink the display
    hhc.hhc_set_display(on=True, brightness=60)          # send whichever you pass
    hhc.hhc_set_verification_date("2027-03-01", device_id=1)

    diag = hhc.hhc_self_diagnostic(enable=True)          # set, then read back
    print(diag.return_parameters.device_ids[0].enabled)
```

---

## Production Pattern: Chill, Incubate, Release

```python
import logging
from hamilton_venus import HeaterCoolerClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def temper(hhc: HeaterCoolerClient, device_id: int, celsius: float, hold_minutes: float) -> None:
    """Ramp to *celsius*, confirm in band, hold, then stop."""
    hhc.hhc_start_temp_control(target=celsius, wait=True, device_id=device_id)
    logger.info("device %d reached %.1f °C", device_id, celsius)
    hhc.hhc_hold_temp_for_time(target=celsius, minutes=hold_minutes, device_id=device_id)
    hhc.hhc_wait_for_temp_control(device_id=device_id)
    hhc.hhc_stop_temp_control(device_id=device_id)
    logger.info("device %d tempering complete", device_id)


with HeaterCoolerClient(simulate=True) as hhc:
    connected = hhc.hhc_connect("COM4")
    device_id = connected.return_parameters.units[0].device_id
    temper(hhc, device_id=device_id, celsius=8.0, hold_minutes=10.0)
    hhc.hhc_terminate()
```

---

## Heater Cooler API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `hhc_connect(address, keep_alive=5)` | `HHCConnectResponse` | Open the chain at `address`; register units; bundle firmware/temp/verification per unit |
| `hhc_get_device_ids()` | `HHCDeviceIdsResponse` | List registered units + firmware |
| `hhc_get_status(device_id=None)` | `HHCStatusResponse` | Temperature, time-remaining, control state per unit |
| `hhc_start_temp_control(target, *, tolerance=0.5, wait=False, timeout=1800, device_id=None)` | `HHCTempControlResponse` | Drive to `target` °C (0–110); optionally block until in band |
| `hhc_hold_temp_for_time(target, minutes, *, tolerance=0.5, device_id=None)` | `HHCTempControlResponse` | Hold at `target` °C for `minutes` |
| `hhc_wait_for_temp_control(*, timeout=1800, device_id=None)` | `HHCTempControlResponse` | Block until in band |
| `hhc_stop_temp_control(device_id=None)` | `HHCTempControlResponse` | Stop temperature control |
| `hhc_set_verification_date(date, device_id=None)` | `MessageResponse` | Record verification/calibration date (`YYYY-MM-DD`) |
| `hhc_identify(device_id=None)` | `MessageResponse` | Blink the display |
| `hhc_set_display(*, on=None, brightness=None, device_id=None)` | `MessageResponse` | Display on/off and/or brightness (0–100%) |
| `hhc_self_diagnostic(*, enable=None, device_id=None)` | `HHCSelfDiagnosticResponse` | Read, or set-then-read, the self-diagnostic toggle |
| `hhc_terminate()` | `MessageResponse` | Disconnect every unit |

`device_id` is optional on every command after `hhc_connect`; when omitted the
command applies to every registered unit. `close()` (or exiting the `with` block)
also disconnects every unit, same as `hhc_terminate()`.

---

## See Also

- [`../star-commands.md`](../star-commands.md) — Full API reference
- [`heater-shaker.md`](./heater-shaker.md) — Hamilton Heater Shaker (HHS)
- [`odtc.md`](./odtc.md) — Inheco ODTC thermal cycler (same pure-Python, no-VENUS approach)
- [`common-patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client`](./common-patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client) — using `HeaterCoolerClient` alongside `StarClient`/`VantageClient` in one script
