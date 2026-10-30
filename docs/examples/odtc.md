# Inheco ODTC (Thermal Cycler)

Guide for controlling the Inheco ODTC (On-Deck Thermal Cycler) — connecting, running a
PCR protocol, and reading status.

---

## Overview

The ODTC is an on-deck PCR block. The SDK talks to it **directly over its SiLA (lab-device
standard) SOAP interface** (`http://<device_ip>/odtc.wsdl`, service on port 8080) — it does **not** use
the vendor's `Inheco.ODTCInterface` COM object, the 32-bit COM bridge, or the VENUS
runtime. Like the [Heater Cooler](./heater_cooler.md) it has its own standalone client,
`ODTCClient`; there is no `StarClient`/`VantageClient` involved, and it works regardless
of `auto_connect` / `instrument_init()`. Every snippet below also runs unchanged with
`ODTCClient(simulate=True)`, which uses a built-in simulation transport (the snippets
that read Hamilton's `PLR001_ODTCProtocols.xml` need the Inheco ODTC library installed).

This guide covers:

- Connecting to one or more ODTC units
- Building a PCR cycling protocol in Python, or running a method already stored on the unit
- Running a protocol and waiting for it to complete
- Reading status, temperature and run data
- Door control, device settings and lifecycle

### Why SOAP and not the COM object

On real hardware the vendor COM object cannot connect: it tries to open its own
event-receiver listener on a dynamic HTTP port (`http://<local ip>:0/...`), which
Windows' HTTP.SYS refuses even when elevated. The device's SOAP interface has no such
requirement, so the SDK speaks it directly. The old COM transport is still in
`hamilton_venus.odtc` (`_ComODTCTransport`, fixed against the vendor `.hsl`) but is not
used unless you inject it. `hamilton-odtc --diagnose` / `--selftest` still report on
that COM path; they are irrelevant to the SOAP transport.

Requirements for a real connection:

- the unit reachable at its IP (the SDK fetches `http://<ip>/odtc.wsdl`);
- one free TCP port in **18001–18008** on this PC. The unit *calls back* to this PC to
  report command completion, and Hamilton's installer pre-reserves exactly that range
  (firewall rule + URL ACL for everyone), so no admin rights are needed. If that range is
  not reserved on your PC, Windows Firewall must allow those ports inbound. The SDK picks
  the local address automatically by asking the OS which interface routes to the unit.

### `odtc_connect` always Resets the unit

The unit learns where to send its async events only from the callback address given in a
`Reset`, so `odtc_connect` always issues one (then `Initialize`). Connecting therefore
**aborts anything already running on the unit**. Skipping it is worse: events go to a
stale listener and the unit drops into `inError`.

### Don't disconnect while a method is running

Disconnecting (`odtc_terminate_device`, `odtc_terminate`, or leaving the `with` block)
does **not** stop a run, and the unit reports a finished run to *this PC*. If nobody is
listening when it does, the unit logs `ResponseEvent: ConnectFailure` and drops into
`inError` — the run itself still completed normally, and the next `odtc_connect` clears
the state with a `Reset` — but it is untidy, and a `busy` unit you didn't intend to leave
behind. Either wait for the run (`odtc_run_protocol(..., wait=True)` or
`odtc_wait_for_protocol`) or call `odtc_stop_method` before disconnecting.

### Addressing: one unit per `odtc_connect` call

Call `odtc_connect(device_ip)` once per unit (up to 8); each call returns its own
`device_id` (`1..8`, lowest free slot). Status/temperature reads accept
`device_id=None` to poll every connected unit; every other command needs a specific
`device_id`.

### No locking

The SDK never calls `LockDevice`/`UnlockDevice`: `lockId` is optional on every other
command, and a lock that outlives its process (a crash, Ctrl-C) leaves the unit locked
with a token nobody has — recoverable only by power-cycling it. No `lock_id` appears in
the `odtc_*` methods.

### Unit states

`state` is one of `startup` (fresh boot), `standby` (after `Reset`), `idle` (ready),
`busy`, `paused`, `errorHandling`, `inError`. Commands are only valid in certain states:
a stepped method needs a `PreMethod` (a block + lid temperature hold) to have finished first; `SetParameters`
(protocol upload, CSV separator) needs `idle`; configuration changes need `standby`
(the SDK does the Reset → configure → Initialize round trip for you).

---

## Basic Operations

### Connect and inspect

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    connected = odtc.odtc_connect("192.168.1.50")   # device_ip
    unit = connected.return_parameters.unit
    print(f"device {unit.device_id}: sn={unit.serial_number} fw={unit.firmware_version} state={unit.state}")
```

### Run a protocol built in Python

```python
from hamilton_venus import ODTCClient
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder, ODTCStep

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    builder = ODTCProtocolBuilder("MyPCR", description="Quick demo cycle")
    builder.add_hold(95, 900, slope=2)                         # initial denature
    builder.add_cycle(                                          # then 30 more times (Inheco "Cycles" = 30)
        [
            ODTCStep(temperature=95, hold_seconds=30),          # denature
            ODTCStep(temperature=60, hold_seconds=30),          # anneal
            ODTCStep(temperature=72, hold_seconds=60),          # extend
        ],
        repeats=30,
    )
    protocol = builder.build()

    result = odtc.odtc_run_protocol(protocol, device_id=1, wait=True, timeout=3600)
    print(f"ran {result.return_parameters.method_name!r}, request_id={result.return_parameters.request_id}")

    row = odtc.odtc_get_status(device_id=1).return_parameters.device_ids[0]
    print(f"device 1: {row.state}")
```

`add_cycle(steps, repeats)` appends `steps` once and then repeats them `repeats` more times — the
same `GotoNumber`/`LoopNumber` convention Inheco's own protocol editor uses, where `repeats` is
its **"Cycles"** field. So `repeats=3` runs the steps four times in all: Inheco's Script Editor
plots four passes for `Cycles = 3`, and a real unit's trace shows four anneal plateaus. If the
first step of the block is at the same temperature as the step before it (an initial
denaturation, then a 95 °C denature), the first pass merges with it into one wider plateau, so
count the *anneal* dips, not the peaks.

### Run an existing vendor-authored protocol file

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")
    odtc.odtc_run_protocol(
        "C:/Program Files (x86)/Hamilton/Library/Inheco ODTC/PLR001_ODTCProtocols.xml",
        method_name="PLR001_GSPCR",   # required when the file has more than one method
        device_id=1,
        wait=True,
    )
```

### List and run the methods stored on the unit

A unit ships with (and keeps) many methods; you can run any by name without uploading.
A `PreMethod` is a plain block + lid temperature hold, a `Method` is a stepped program.

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    for m in odtc.odtc_list_methods(device_id=1).return_parameters.methods:
        print(m.kind, m.name, m.target_block_temperature, m.target_lid_temperature, m.step_count)

    odtc.odtc_run_stored_method("PRE25", device_id=1)   # block 25 C, lid 110 C
    odtc.odtc_stop_method(device_id=1)
```

Methods you upload with `odtc_run_protocol` stay on the unit too, so they appear here.
A stepped `Method` only starts after a `PreMethod` has *finished* bringing the block and
lid to its start temperatures; run that first (`odtc_run_protocol(pre, ..., wait=True)`).

### Protocol builder parameters

`ODTCProtocolBuilder(method_name, ...)` — the values below are the ones Inheco's own methods use.

| Parameter | Meaning | Values |
|---|---|---|
| `method_name` | Name the method is stored and run under; re-uploading a name replaces it | letters, digits, `_`, `-` |
| `creator`, `description` | Free text shown in `odtc_list_methods` | any; default `"hamilton_venus"` / none |
| `variant` | Instrument model the method is for | `960000` = 96-well ODTC (default), `3840000` = 384-well ODTC |
| `plate_type` | Plate-type code | always `0` in every known method; leave at `0` |
| `fluid_quantity` | Liquid per well (the editor's "Fluid" drop-down); `add_pcr` uses it to pick slopes/overshoot | `0` = 10–29 µl (default), `1` = 30–74 µl, `2` = 75–100 µl; `-1` = unspecified (Inheco's 384-well test methods) |
| `post_heating` | Keep block/lid heated after the run; the unit refuses a stepped `Method` without a finished `PreMethod` or this | `True` (default) / `False` |
| `start_block_temperature` | Block temperature the method starts from (a `PreMethod`'s block target) | °C, typically 4–99, default 25 |
| `start_lid_temperature` | Lid temperature | °C, typically 30–115, default 110 |

Per step (`add_hold`, or an `ODTCStep`): `temperature` (°C, 4–99), `hold_seconds` (0–43000; 0 passes straight
through), `slope` (°C/s ramp rate, above 0 — typically 0.18–5.0, the editor uses ≤ 4.4 heating and ≤ 2.2 cooling),
`lid_temperature` (°C, 30–115), and optional overshoot: the block is driven `overshoot_temperature` °C
(0–12.6) past the target at `overshoot_slope1`, held `overshoot_time` s (0–13.3), and brought back at
`overshoot_slope2` (slopes must stay above 0). `add_cycle`'s `repeats` and `add_pcr`'s `cycles` are the
editor's "Cycles": extra passes after the first. Every docstring lists the same details, e.g.
`help(ODTCProtocolBuilder.add_pcr)`.

### Build a PCR the way Inheco's Script Editor does

`ODTCProtocolBuilder.add_pcr` writes a 3-step PCR with the step layout, ramp slopes and overshoot
that Inheco's Script Editor generates, chosen by the liquid volume — so the liquid reaches
temperature quickly instead of every step ramping at one fixed rate. Each argument is one
editor field; `None` switches an optional part off (like unticking its box); `fluid_quantity` is
optional and defaults to `0` (10–29 µl).

```python
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder

builder = ODTCProtocolBuilder("MyPCR", fluid_quantity=1)   # 0 = 10-29 ul (default), 1 = 30-74 ul, 2 = 75-100 ul
builder.add_pcr(
    initial_denaturation=(95, 15),   # (temperature C, seconds)
    denaturation=(95, 10), annealing=(60, 10), extension=(72, 15),
    cycles=3,                        # the editor's "Cycles" (see add_cycle): four passes in all
    final_extension=(72, 15), cooling=(25, 10),
)
odtc.odtc_run_protocol(builder.build(), device_id=1)   # odtc: a connected ODTCClient, as above
```

What changes with the volume (all read from the editor's own output for the same steps at the three
volume settings, and checked against it field for field): heating always uses the maximum slope (4.4)
with an overshoot that grows with the volume (e.g. extension 4.2 / 9.0 / 11.3 °C); cooling is done in
segments at 60, 40 and 20 °C with slower slopes towards ambient (2.2 / 1.4 / 0.8 / 0.25 °C/s for
10–29 µl, 2.0 / 1.3 / 0.75 / 0.23 for 30–74 µl, 1.8 / 1.2 / 0.65 / 0.20 for 75–100 µl); the overshoot
peak never goes above 102 °C (the rest becomes a hold time). These numbers are **exact for the editor's
default temperatures (95 / 60 / 72 °C)**; for other temperatures the same per-step values are reused
(peak capped at 102 °C), which is approximate — the editor recomputes them. Author such a method in the
editor and import it (`odtc_import_methods`) if you need it exact. The 2-step PCR layout is not covered.

On a real unit (10–29 µl setting, empty block) the tuned method tracked its target with a mean error of 0.34 °C
(max 2.5 °C) against 2.10 °C (max 23.6 °C) for the same steps at a fixed 4.4 °C/s slope, and the unit's own
estimate of the run, 6m07s, matched Inheco's Script Editor's estimate for the same steps to the second.
The 0.20 °C/s last cooling band for 75–100 µl is an estimate (no editor file has that band at that volume).

### Import methods from an XML file, then run them

A vendor `<MethodSet>` file (such as Hamilton's
`Library/Inheco ODTC/PLR001_ODTCProtocols.xml`, with 3 PreMethods and 2 PCR methods) can
be uploaded without running anything; the unit stores every method in it, and they run by
name afterwards -- or run one straight from the file with `odtc_run_protocol`, which
uploads the file first. The BOM these files start with is handled.

```python
from hamilton_venus import ODTCClient

FILE = "C:/Program Files (x86)/Hamilton/Library/Inheco ODTC/PLR001_ODTCProtocols.xml"

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    for m in odtc.odtc_import_methods(FILE, device_id=1).return_parameters.methods:
        print("imported", m.kind, m.name)                    # nothing is started

    odtc.odtc_run_stored_method("PLR001_Init", device_id=1)   # run one by name ...
    odtc.odtc_run_protocol(FILE, method_name="PLR001_Cool8C", device_id=1)   # ... or from the file
```

`method_name` is required when the file holds more than one method, and is checked
against the file before anything is uploaded. A file containing
`<DeleteAllMethods>true</DeleteAllMethods>` is refused (it would wipe the unit's own
methods). `example_scripts/odtc_import_protocol_file.py` runs this end to end on hardware.

### Track a run and plot it

`odtc_download_run_trace` fetches the unit's own trace of a run — about five samples a second of
block target, block actual and lid — matched by method name so you get the run you just did.
`example_scripts/odtc_pcr_temperature_trace.py` builds a pre-method and a 3-cycle PCR, polls the
temperature while they run, downloads both traces and plots the result (needs matplotlib).

```python
trace = odtc.odtc_download_run_trace(1, "traces", method_name="MyPCR").return_parameters   # after the run, on a connected client
for s in trace.rows[:3]:
    print(s.elapsed_ms, s.target_temperature, s.current_temperature, s.lid_temperature)
```

### Download the unit's logs

The logs are not available through SiLA; the unit serves them over anonymous FTP and
`odtc_download_logs` copies them, keeping the folder layout:

```python
result = odtc.odtc_download_logs(1, "odtc_logs")            # add include_traces=True for Traces/
for f in result.return_parameters.files:
    print(f.size, f.remote, "->", f.path)
# SiLA/Logs/InhecoSiLA.log is the SiLA stack's own log -- the first place to look
# when the unit reports an error state.
```

This is not `odtc_get_run_data`, which is the temperature trace of the last run.

### Non-blocking run, then wait later

```python
from hamilton_venus import ODTCClient
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    builder = ODTCProtocolBuilder("Hold25")
    builder.add_hold(25, 60)
    odtc.odtc_run_protocol(builder.build(), device_id=1)   # returns immediately
    # ... do other work ...
    odtc.odtc_wait_for_protocol(device_id=1, timeout=1800)  # block until done
```

---

## Querying State

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    for row in odtc.odtc_get_status().return_parameters.device_ids:
        print(f"device {row.device_id}: {row.state} (locked={row.locked}, door_open={row.door_open})")

    for row in odtc.odtc_get_temperature().return_parameters.device_ids:
        print(f"device {row.device_id}: block={row.block_temperature} °C lid={row.lid_temperature} °C")

    for entry in odtc.odtc_get_run_data(device_id=1).return_parameters.rows:
        print(entry)
```

---

## Door and Run Control

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")

    odtc.odtc_open_door(device_id=1)
    odtc.odtc_close_door(device_id=1)

    # While a protocol is running:
    odtc.odtc_pause(device_id=1)
    odtc.odtc_resume(device_id=1)
    odtc.odtc_abort(device_id=1)
    odtc.odtc_stop_method(device_id=1)
```

---

## Lifecycle

```python
from hamilton_venus import ODTCClient

with ODTCClient(simulate=True) as odtc:
    odtc.odtc_connect("192.168.1.50")
    odtc.odtc_connect("192.168.1.51")
    # ...
    odtc.odtc_stop_method(device_id=1)        # or odtc_wait_for_protocol(device_id=1) to let a run finish -- see "Don't disconnect while a method is running"
    odtc.odtc_terminate_device(device_id=1)   # disconnect one unit (does not stop a run)
    odtc.odtc_terminate()                     # disconnect every unit
# close() (also called on `with` exit) does the same as odtc_terminate()
```

---

## ODTC API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `odtc_connect(device_ip, device_port="8080", *, local_ip="", initialize=True)` | `ODTCConnectResponse` | Register one unit (Reset + Initialize); bundle identification + status. `device_port` is ignored by the SOAP transport |
| `odtc_get_device_ids()` | `ODTCDeviceIdsResponse` | List registered `device_id`s |
| `odtc_get_status(device_id=None)` | `ODTCStatusResponse` | State, locked, door-open per unit |
| `odtc_get_temperature(device_id=None)` | `ODTCTemperatureResponse` | Block + lid temperature per unit |
| `odtc_get_device_identification(device_id)` | `ODTCDeviceIdentificationResponse` | Firmware/serial/manufacturer |
| `odtc_open_door(device_id)` / `odtc_close_door(device_id)` | `MessageResponse` | Plate door control |
| `odtc_run_protocol(protocol, *, method_name=None, priority=1, device_id, wait=False, timeout=3600)` | `ODTCProtocolRunResponse` | Upload + run a protocol (file path or `ODTCProtocol`). `priority` must be 1 or more |
| `odtc_run_stored_method(method_name, *, device_id, priority=1, wait=False, timeout=3600)` | `ODTCProtocolRunResponse` | Run a method already stored on the unit, by name |
| `odtc_import_methods(protocol_file, *, device_id)` | `ODTCMethodListResponse` | Upload every method in a vendor `<MethodSet>` XML file without running any; returns what the file held |
| `odtc_download_logs(device_id, dest_dir="odtc_logs", *, include_traces=False)` | `ODTCLogDownloadResponse` | Copy the unit's log files (over FTP) to `dest_dir`; `Traces/` only with `include_traces=True` |
| `odtc_list_methods(device_id)` | `ODTCMethodListResponse` | Names, kinds and targets of every method stored on the unit |
| `odtc_wait_for_protocol(device_id, *, request_id=None, timeout=3600)` | `MessageResponse` | Block until the run completes |
| `odtc_stop_method(device_id)` / `odtc_pause(device_id)` / `odtc_resume(device_id)` / `odtc_abort(device_id)` | `MessageResponse` | Run control |
| `odtc_reset(device_id, *, timeout=60, simulate_on_device_base=False, initialize=True)` | `MessageResponse` | Firmware-level reset |
| `odtc_get_run_data(device_id)` | `ODTCRunDataResponse` | The unit's `GetLastData` trace as rows (elapsed / target / current / lid, degrees C). **Not reliable as "the last run"** — it returned an older run's trace after two normal runs; use `odtc_download_run_trace` |
| `odtc_download_run_trace(device_id, dest_dir="odtc_traces", *, method_name=None)` | `ODTCRunTraceResponse` | Download + parse the newest per-run trace (or the newest for `method_name`) from the unit's FTP server |
| `odtc_get_parameters(device_id)` | `ODTCConfigurationResponse` | Raw device parameters XML (contains every stored method) |
| `odtc_set_parameter(name, type_, value, device_id)` | `MessageResponse` | Set one device parameter |
| `odtc_set_log_level(level, device_id)` | `MessageResponse` | The unit's own log level: `"DEBUG"`, `"INFO"`, `"WARN"`, `"ERROR"`, `"FATAL"`. Hamilton asks that it only be changed on request. Needs `standby` (Reset → configure → Initialize, ~1 min); refused while a method runs |
| `odtc_set_csv_separator(character, device_id)` | `MessageResponse` | Separator in the `odtc_get_run_data` output; one character such as `;` or `,` (not `.` or `:`) |
| `odtc_set_date_time(date_time, device_id)` | `MessageResponse` | Set the unit's clock: a `datetime` (naive = UTC) or `YYYY-MM-DDTHH:MM:SSZ`. Same standby round trip as `odtc_set_log_level` |
| `odtc_add_allowed_return_code(code, device_id)` | `MessageResponse` | Whitelist a vendor return code as non-fatal |
| `odtc_terminate_device(device_id)` / `odtc_terminate()` | `MessageResponse` | Disconnect one unit, or every unit. Does **not** stop a running method, and a run that ends after you disconnect sends the unit into `inError` (see above) — wait for it or call `odtc_stop_method` first |

**Deliberately not provided:** network configuration (a wrong value can take the unit off
the network) and `GetConfiguration` (not needed).

See [`hamilton_venus.odtc_protocol`](../../src/hamilton_venus/odtc_protocol.py) for
`ODTCStep` / `ODTCPid` / `ODTCProtocol` / `ODTCProtocolBuilder`.

---

## See Also

- [`../star_commands.md`](../star_commands.md) — Full API reference
- [`heater_cooler.md`](./heater_cooler.md) — Hamilton Heater Cooler (HHC), the same pure-Python, no-VENUS approach
- [`common_patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client`](./common_patterns.md#pattern-10-combining-starclientvantageclient-with-a-standalone-device-client) — using `ODTCClient` alongside `StarClient`/`VantageClient` in one script
