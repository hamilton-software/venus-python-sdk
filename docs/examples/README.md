# Examples

Practical usage examples for the Hamilton VENUS SDK, organized by topic. Examples use `StarClient`; the same patterns apply to `VantageClient` unless a section is marked STAR-only.

New to the SDK? Start with [Getting Started](./getting_started.md). Most pipetting examples refer to labware IDs and tip pools (such as `"SourcePlate"` or `"TransferTips"`) that must already exist on the deck, either from a saved deck (`deck_name=...`) or built in code (see [Deck and Layout](./deck_and_layout.md) and [Common Patterns](./common_patterns.md#pattern-1-setup--execute--cleanup-standard)).

## Quick Navigation

### [Getting Started](./getting_started.md)
Connection, startup lifecycle, configuration, simulation mode, and logging. Includes quick-start decision tree.

### [Liquid Handling](./liquid_handling.md)
Aspirate, dispense, liquid level detection, transfers, reusable settings, variable volumes, and mixing.

### [Position and Well Selection](./position_and_well_selection.md)
Position selector syntax and well selection features.

### [Autoload](./autoload.md)
Loading and unloading carriers by ID or track, occupancy sensing, carrier sensor status, and deck audit patterns.

### [96-Channel Head (MPH96)](./mph96.md)
Full-plate transfers, partial column pickup, and reusable MPH96 settings.

### [Deck and Layout](./deck_and_layout.md)
Building deck layouts at runtime, autoload carrier management, tilted plates, and splitting large wells for several channels.

### [Transport and Gripper Tools](./transport.md)
CO-RE gripper setup, iSWAP transport, plate movement, barcode scanning, and gripper state management.

### [Common Patterns](./common_patterns.md)
Reusable workflow templates and patterns for typical Hamilton operations. Includes exception handling, checkpoints, progress tracking, and more.

### [Error Simulation](./error_simulation.md)
Inject simulated firmware errors in simulation mode to exercise error-recovery code: `simulate_error()`, `simulate_error_by_code()`, `clear_simulated_errors()`.

### [Error Handling Profiles](../error_handling.md)
Configure recovery actions for instrument operation failures. Define how the SDK responds to errors during tip pickup, aspiration, dispensing, and more.

### [Compound Commands](./compound_commands/)
High-level workflow helpers (Copy Plate, Add Reagent, Hit Picking, Pool Samples, Replicate Samples, Serial Dilution) that orchestrate multiple SDK commands into a single call.

### [Liquid Classes](./liquid_classes.md)
→ See [Liquid Class Management](./advanced/liquid_class_management.md) for the full guide.

### [Heater Shaker (HHS)](./heater_shaker.md)
Register HHS devices, lock plates, run the shaker, and control temperature.

### [Heater Cooler (HHC)](./heater_cooler.md)
Drive Hamilton Heater Cooler blocks (0–110 °C) straight from Python — no VENUS runtime. Connect, set/hold temperature, read status.

### [Inheco ODTC (Thermal Cycler)](./odtc.md)
Drive the Inheco ODTC PCR block straight from Python — no VENUS runtime. Connect, build or upload a cycling protocol, run it, read status and run data.

### [Inheco TEC Controller (STC/MTC)](./inheco_tec.md)
Drive an Inheco Single/Multi TEC Controller straight from Python — no VENUS runtime. Connect, identify slots, set/read temperature, drive the shaker.

### [Tilt Module (MFX)](./tilt_module.md)
Drive the MFX Tilt Module straight from Python over RS-232 — no VENUS runtime. Connect, home, tilt 0–10°, power off; pair it with `tilt_labware()` for the deck layout.

### [Hamilton Media Fill Module](./media_fill.md)
Fill troughs from the Hamilton Media Fill Module straight from Python — no VENUS runtime. Connect, set pump direction, start and wait for a fill, read the liquid level sensors.

---

For deep-dive production workflows, see also [Advanced Examples](./advanced/).
