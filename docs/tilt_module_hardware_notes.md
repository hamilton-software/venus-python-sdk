# MFX Tilt Module — Hardware Notes

What to expect from a real MFX Tilt Module (ambient, control box / RS-232, part no. 188061) when you drive it
with `TiltModuleClient`. For setup and the API, see the [Tilt Module guide](examples/tilt_module.md).

## Connection

- **Serial settings:** 1200 baud, 8 data bits, even parity, 1 stop bit, no flow control, CR/LF line ends.
  These are the driver's defaults. They match the VENUS library `HSLMultiDaisyChainedTiltModuleAmbient`.
- **Module name:** each module has a two-character name, which you pass as `module_name`. Do not assume a
  default: read it with `hamilton-tilt-module --probe COMn` while the module is alone on the port.
- **One program per port:** close any VENUS method that uses the module before connecting from Python, and
  the reverse.

## Commands and Replies

The driver sends the same commands as the VENUS library:

| Step | Commands |
|---|---|
| `tilt_module_initialize` | `EI` (reset error), `SI` (home to horizontal), `RF` (read firmware version) |
| `tilt_module_move_to_position` | `GP<0..10>` |
| `tilt_module_terminate_module` | `GP0` (back to horizontal), then `PO` (motor off) |

Each reply carries a firmware code, `er00` when the command was accepted. A non-zero code raises
`TiltModuleError` with that `error_code`, and `tilt_module_error_message(code)` gives its text.

Typical timings: homing about 1.5 s, and each move under 1 s from command to reply.

## Position and Status

- **No position read-back.** The module cannot report its angle. `tilt_module_get_status` returns the last
  angle *commanded*. After a failed move it is `None` until the next successful move.
- **A move is confirmed by its reply only.** The `GP` reply means the module accepted the move; there is no
  "move finished" signal. Some firmware versions have no busy query: they answer `RS` with error 7 ("Unknown
  command"). The driver then stops asking, as the VENUS library does, and `busy` in the status is `None`.
- **Let the plate settle.** The plate is not fixed to the module. Before pipetting, wait for the plate to come
  to rest, especially when lowering. Near horizontal, a plate can also catch on the module's frame instead of
  settling flat: check that it sits flat after returning to 0°.

## Orientation

The module hinges on its left short side (landscape), so a positive angle lifts the **right** side of the
plate. This matches `tilt_labware()`'s default `TiltPivotPoint.LEFT_EDGE`. Tilting the module does not change
the deck layout: call `tilt_labware()` at the same angle as well (see
[Tilting the Plate in the Deck Layout](examples/tilt_module.md#tilting-the-plate-in-the-deck-layout)).

The hinge is a pin under the plate, not the plate's lower-left corner, and the plate's real angle can differ
from the commanded one: on one module commanded to 10°, the plate sat at about 10.8° with the hinge about
6 mm below the plate base. Calibrate each module once from probe readings (see
[Calibrating a Tilt Module](examples/deck_and_layout.md#calibrating-a-tilt-module)). If the module tilts
noticeably more than commanded, or is not flat at 0°, check its home sensor setting on the control box first.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Error −8, "Reading from COM port failed" | No module answered. Check the cable, INTERFACE BOX power, the COM port number and the module name (a wrong name gets no reply). Read the name with `--probe`; `hamilton-tilt-module --scan COMn` (read-only) tries common serial settings. |
| Error −11, "Unknown device name" | A different module answered than the one addressed. Check the module names on the chain. |
| Error 1, "Init position not found!" | The module could not find its home position. Check that nothing blocks the plate or hinge, then initialize again. |
| Plate not flat at 0° | Check that the plate is seated and not caught on the frame. If it persists, the module's home position needs service. |
| Module stopped responding after a power cycle | The driver cannot detect a power cycle: initialize the module again. |

When contacting support, include the output of `hamilton-tilt-module --diagnose` and `--probe COMn`, the
firmware version, and the log written by `example_scripts/tilt_module_hardware_test.py`.
