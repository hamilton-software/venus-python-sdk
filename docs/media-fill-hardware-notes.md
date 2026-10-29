# Hamilton Media Fill Module — Hardware Notes

What to expect from a real Hamilton Media Fill Module when you drive it with `MediaFillClient`. For setup
and the API, see the [Media Fill Module guide](examples/media-fill.md).

## Connection

- **USB:** the module appears in Device Manager as **USB Serial Device (COM*n*)** on Windows' built-in USB
  serial driver; Windows 10/11 needs no driver. Its USB id is **VID 2341 / PID 0043**. The vendor's
  `Ruggeduino.inf` lists 16D0 / 0613, which the driver also accepts.
- **Firmware:** a module reports `Media Fill Module V1.00 94821-01 A` (or a later version).
- **Vendor COM object:** the driver uses whichever Hamilton Media Fill library is installed: 2.0
  (`HxMediaFill.HxMediaFillCOM`, `HxMediaFillCOM.dll`, from the HxMediaFill 2.0.8767 MSI) or 1.1
  (`Hamilton.HxMediaFillModule`, `HxMediaFill.dll`), preferring 2.0. `hamilton-media-fill --diagnose` shows
  which one is in use. The hardware behaviour below was confirmed with the 1.1 library.
- **One program per port:** close any VENUS method that uses the module before connecting from Python, and
  the reverse.

## Identifying the Module

VID 2341 / PID 0043 is also the id of a stock Arduino Uno, so the USB id alone does not prove a port is a
Media Fill Module. The driver therefore:

1. Never opens a port whose USB device lacks a Media Fill USB id.
2. Before connecting, sends only the read-only firmware query and refuses the port unless the reply contains
   `Media Fill Module`.

Several modules can be connected at once: each has its own COM port and USB serial number
(`hamilton-media-fill --list-ports` shows both).

## Pumping

- **Fill (`media_fill_fill_trough`)** starts the pump and returns at once. The pump stops when the trough's
  liquid level sensor reads liquid, or when the timeout elapses. A fill on a trough that already reads full
  returns without pumping (the last error then reads `SENSOR ON`).
- **Pump out (`media_fill_waste_pump_no_sensor`)** turns the pump in the **reverse** of the direction set with
  `media_fill_set_pump_direction`, ignores the sensor, and runs for the full timeout. Leave the pump on its
  fill direction (counter-clockwise as delivered) and pump out pulls liquid from the trough back toward the
  bottle. With the other direction set it pumps *into* the trough, and only the timeout stops it. The 2.0
  library allows at most 20 s per pump out; with 1.1, keep the timeout within Hamilton's 720 s limit for any
  pumping operation.
- **Direction:** every pump starts each run counter-clockwise (0). Which rotation fills depends on how the
  tubing sits in the pump head: if a fill moves nothing, check the tubing first.
- **Waiting:** the vendor API cannot report whether a pump is running. `media_fill_wait_for_pump` blocks until
  it stops; with the 2.0 library it returns an error after 1 minute, with 1.1 it has no timeout of its own.
- **Stopping:** `media_fill_stop_pump` stops one pump (2.0 library only); `media_fill_disconnect` stops every
  pump on that module at once.
- **Speed:** 30–100 %. At 30 % a pump is nearly inaudible for the first few seconds, so a short run can look
  like nothing happened. A long or dry source tube needs about 60 % and well over 60 s to prime: use a longer
  timeout rather than assuming the fill failed.

## Liquid Level Sensors

`media_fill_get_liquid_level_sensor_state` returns 0 when no liquid is detected, and 1 when liquid is
detected, **or** the sensor is unplugged, **or** the controller is powered down. A pump without a sensor
fitted therefore reads 1.

## Serial Protocol (Read-Only Queries)

`hamilton-media-fill --probe COMn` reads the module directly over its serial port (9600 baud, 8N1, no
handshake) without connecting the vendor object, so nothing moves and the pump directions are not rewritten.
It only sends these queries:

| Query | Reports |
|---|---|
| `:11;` | Firmware version |
| `:7;` | Liquid level sensors |
| `:10;` | Each pump's status: stopped, or the time until it stops |
| `:13;` | Each pump's direction |

The probe is the only way to see whether a pump is running, and works only while no program holds the port.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `--list-ports` finds nothing | The USB cable, the 24 V power and Device Manager > Ports. |
| `Initialize failed ... Failed to connect to Media Fill Module` | Wrong COM port, or the port is open in another program (VENUS or a terminal). |
| `... already being controlled by HSL ...` after a failed connect | Disconnect the other modules (or call `media_fill_terminate()`), then connect again. |
| `device_id N (COMn) is no longer connected` | The module was lost (for example the USB cable was pulled). Connect that COM port again; it gets the same `device_id` back. |
| A fill times out without the sensor tripping | Tubing direction in the pump head, a dry long source tube (raise the speed or timeout), the pump clamp, or pump and sensor cables not paired. |
| A failed connect takes minutes | The vendor driver waits up to 5 minutes on a port that exists but does not answer. Check the port with `--probe` first. |
| `registered without a CodeBase` (1.1 library) | Run `hamilton-media-fill --register-codebase` once as Administrator. |
| `.NET 2.0/3.5 component ...` (1.1 library) | Run `hamilton-media-fill --configure` (as Administrator if the SDK is under Program Files), or turn on .NET Framework 3.5 in Windows Features. |
| `EmptyLineToSource` rejected with a long timeout (2.0 library) | The 2.0 library allows at most 20 s per pump out; run it again if more is needed. |

When contacting support, include the output of `hamilton-media-fill --diagnose`, `--list-ports` and
`--probe COMn`, the firmware version, and the log and report written by
`example_scripts/media_fill_hardware_test.py` (in `Documents\MFM Hardware Test\logs`).
