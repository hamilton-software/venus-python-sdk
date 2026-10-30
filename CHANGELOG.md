# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project structure
- `setup-venus-sdk --install-py32` (and `--py32-from` for offline installs) downloads a pinned, hash-verified 32-bit Python 3.12 + pywin32 runtime for the 32-bit COM drivers; `uninstall-venus-sdk` removes it unless `--keep-py32`.
- `VenusClient` — low-level HTTP client for communication with Hamilton VENUS.
- `StarClient` — synchronous high-level client for controlling a Hamilton STAR.
- Lifecycle: `StarClient.start()` starts SignalR, loads and starts the configured method, waits for readiness, and auto-initializes the instrument by default when a method is configured. `StarClient.stop()` terminates the running method, waits for `ExecutorEvent.TERMINATED`, unloads the method, and tears down connections.
- TOML-based configuration via `SdkConfig` with nested `MethodConfig`, `NetworkConfig`, and `TimeoutConfig`.
- `send_command()` method for posting commands to the queue and receiving responses via SignalR events.
- Command implementations - add currently supported star commands.
- Add Venus Authentication - sends authentication if enabled and configured.
- Add Error Handling profiles - default profiles for common error scenarios, with support for custom profiles and operator escalation.
- Add Copy Plate compound command and infrastructure for future complex commands.
- Add Add Reagent compound command.
- Add Hit Picking compound command.
- Add Pool Samples compound command.
- Add Replicate Samples compound command.
- Add Serial Dilution compound commands.
- Add ODTC protocol models, a fluent PCR protocol builder, and XML rendering.
- Add standalone Hamilton Heater Cooler and Inheco ODTC simulated device clients.
- Add WXS balance commands to `VantageClient`.
- Add taught-location persistence for operator-calibrated labware positions and carrier/site offsets.
- Add simulated firmware-error injection for STAR and Vantage sessions.
- Channel limits (1mL/5mL/MagPip channel counts and numbers, CO-RE/QCG `front_channel`) are now read from the instrument configuration at connect time instead of hardcoded to 8, so instruments with more channels (up to 16) are no longer rejected. Falls back to a 16-channel ceiling if the configuration cannot be read. Commands needing an MPH96 head, autoload, or iSWAP/IPG gripper, or (on STAR) a QCG/CO-RE gripper matching the installed channel type, are now rejected client-side with a new `VenusCommandUnsupportedError` if the instrument configuration reports the hardware is not present.
- `tilt_labware` — tilt a plate on a tilt module or angled carrier; the SDK computes per-well X/Z offsets (`tilt_geometry`), with `TiltPivotPoint` / `TiltWellPosition` (e.g. aspirate from the deepest point). Transport commands refuse tilted labware (`LabwareTiltedError`) until it is tilted back to 0.
- `split_wells` / `remove_split_wells` / `get_split_wells` — several channels pipette side by side in one large well (24-well: 2 × 1 mL, 6-well: 4 × 1 mL, 50 mL tube: 3). The SDK sizes the slots from the well's chord (tilt- and offset-aware, `SplitWellFit.POSITION` / `MAX_CHANNELS` / a channel count), places a temporary rack, and routes aspirate / dispense / liquid-level detection for adjacent channels to the slots automatically. New `labware.addSplitWellSite` VENUS action; `SplitWellCapacityError` when more channels target a well than it has slots.
- `TiltModuleClient` — standalone driver for the Hamilton MFX Tilt Module (RS-232, no VENUS runtime needed) plus `hamilton-tilt-module` CLI; registered as a standalone device. New `TiltModuleError`.
- Examples: `tilt_labware_example.py`, `tilt_module_demo.py`, `tilt_module_hardware_test.py`, `tilt_module_split_wells_example.py`; docs `docs/examples/tilt_module.md`.
- `MediaFillClient` — standalone driver for the Hamilton Media Fill Module through the 32-bit COM bridge (no VENUS runtime). Uses whichever vendor library is installed, preferring 2.0 (`HxMediaFill.HxMediaFillCOM`) over 1.1 (`Hamilton.HxMediaFillModule`); `HAMILTON_MEDIA_FILL_PROGID` picks one. Connect, pump direction, liquid level sensor, fill trough (stops at the sensor), pump out without the sensor (`EmptyLineToSource` on 2.0, at most 20 s; `WastePumpNoSensor` on 1.1), wait for pump, stop pump (2.0 only), status; connect and status report the library as `vendor_api`. `MediaFillError`, `PumpDirection`, `hamilton-media-fill` CLI (`--diagnose`, `--list-ports`, `--probe COMn`, `--configure`, ...), a `setup-venus-sdk` configure step, guide `docs/examples/media_fill.md`, hardware notes, fill example and hardware test.
- `tilt_labware` takes `tip_end_height_mm` (the fixed height; default 0), `wall_margin_mm` (default 1.0) and `high_wall_margin_mm` (default 2.0, the wall that leans over the tip), `tip_profile`, and `measured_tilt_degrees` (the plate's real angle, up to 15: the offsets use it while VENUS still gets the commanded angle); `tilt_degrees` accepts fractions. `split_wells` takes the same `tip_end_height_mm` / `wall_margin_mm` / `high_wall_margin_mm`, defaulting to the plate's `tilt_labware` values. New `get_tilt_settings()` / `TiltSettings`.
- `hamilton_venus.tilt_calibration.fit_tilt_hinge()` — a tilt module's real angle and hinge from four probe readings, returned as `tilt_labware` arguments; example `tilt_module_fit_hinge.py`.
- Liquid class library (`liquid_class_library.find_liquid_classes`), labware models (`labware_models`) and tip reach checks (`tip_reach`); add commands return typed results with the labware name; `installed_instrument_type()` reads the instrument family VENUS is installed for.

### Changed
- `sdk_method_structure` brought up to date with the current GitHub executor method: Layout, Labware, Channel 1 mL / 5 mL, System and iSWAP controllers, LayoutTracking / TaughtLocation / TipCounterTracking / Tools helpers, executors and `Deck Layout.json` (includes `getLabwareCoordinates`, `tiltLabware` and `addSplitWellSite`). The HSL files need to be checked in VENUS.
- `tilt_labware` `DEEPEST_POINT` / `HIGHEST_POINT` aim one tip as close to the low / high wall as it fits (new `hamilton_venus.tilt_clearance`: tip shape, tip end height, per-wall margins, the leaning high wall) instead of 85 % of the well radius, which on a real tilt module left 2.5 mm to the low wall and hit the rim of the high wall at 10 degrees. No room for a tip raises `ValueError` naming the largest angle that fits. `split_wells` uses the same maths; `fit=SplitWellFit.POSITION` aimed at a wall uses as many channels as fit, each count as close to the wall as it fits. `TipProfile` describes only the tip's shape (`radius()`; margins are arguments).
- Split well rack ids include the slot count: `<parent>_<well>_split_<1ml|5ml>_<N>slots`.

### Fixed
- Per-channel lists (`aspirate`, `dispense`, `move_axis` y/z, MagPip versions) are placed at each channel's slot (`array[channel - 1]`) as VENUS reads them; before, `dispense(channels=[7], ...)` with a list ran channel 7 with zeros. Lists whose length doesn't match `channels` are still rejected.
- Start-up could hang when an earlier run left a `ready` message on the run-message queue: the client took it as the new run's `ready` and sent its first command, which the executor then deleted when it reset its queues. The client now deletes the `ready`, `action` and `action-response` queues before `StartMethod` and ignores a `ready` that survives the delete (`_drain_stale_ready` and its 0.5 s grace period are removed).
- The run-message dispatcher keeps only the latest event of the `action` channel (the client's own command posts, which nothing consumes), so sessions of more than 512 commands no longer log a queue overflow warning on every command.
