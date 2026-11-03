# Hamilton VENUS SDK Documentation

Quick-reference index for the SDK documentation. If you are new to the SDK, start with [Getting Started](examples/getting_started.md).

---

## Setup and Configuration

| Guide | What it covers |
|-------|----------------|
| [Getting Started](examples/getting_started.md) | Connecting, initializing, and the basic workflow lifecycle |
| [Authentication](authentication.md) | Unauthenticated and OAuth-authenticated VENUS environments |
| [Configuration](configuration.md) | `SdkConfig`, `MethodConfig`, environment variables, and TOML |

---

## Tools

The tools are under [`tools/`](../tools/). Each desktop app's folder is ready to use and holds its guide: [AI Assistant](<../tools/Hamilton AI Assistant/ai-assistant-app.md>), [SDK Studio](<../tools/Hamilton SDK Studio/sdk-studio.md>), [Script Manager](<../tools/Hamilton Script Manager/script-manager.md>) and [Log Viewer](<../tools/Hamilton Log Viewer/log-viewer.md>). The AI assistant setup is in [`tools/ai_harness`](../tools/ai_harness/ai-assistants.md), and the [MCP guide](../tools/mcp_server/mcp-guide.md) and [error monitoring guide](../tools/mcp_server/mcp-error-monitoring.md) are in `tools/mcp_server`.

---

## Reference Guides

| Guide | What it covers |
|-------|----------------|
| [Liquid Handling Rules](guides/liquid-handling-rules.md) | Operational rules for writing and reviewing pipetting scripts so command sequences do not fail at runtime |
| [Liquid Handling Optimization](guides/hamilton-liquid-handling-optimization-guide.md) | Choosing and tuning liquid classes and pipetting settings |
| [Labware Compatibility](guides/Hamilton_Labware_Compatibility_Guide_V2.md) | Which carrier a labware fits on and the deck clearance limit |

---

## Core Examples

| Guide | What it covers |
|-------|----------------|
| [Common Patterns](examples/common_patterns.md) | Recommended patterns for transfers, error handling, TADM, and status lights |
| [Liquid Handling](examples/liquid_handling.md) | `aspirate()`, `dispense()`, `detect_liquid_level()`, settings, non-standard labware, 5mL (XL) channels |
| [Position and Well Selection](examples/position_and_well_selection.md) | Selector DSL, `normalize_positions`, `SpecResolver`, labware specs |
| [Deck and Layout](examples/deck_and_layout.md) | `add_carrier()`, `add_plate()`, `add_tip_rack()`, lidded plates |
| [Autoload](examples/autoload.md) | Loading/unloading carriers, occupancy sensing, deck audit |
| [Transport](examples/transport.md) | CO-RE and iSWAP plate transport, barcode scanning |
| [96-Channel Head (MPH96)](examples/mph96.md) | Full-plate and partial pickups, MPH96 settings |
| [Error Handling](error_handling.md) | Error profiles, operator escalation, recovery actions |
| [Error Simulation](examples/error_simulation.md) | Injecting simulated firmware errors to test recovery code without hardware |
| [Run Log](examples/advanced/run_log.md) | Structured JSON run log, configuration, crash recovery |

---

## Devices

| Guide | What it covers |
|-------|----------------|
| [Heater Shaker (HHS)](examples/heater_shaker.md) | Plate locking, shaking, and temperature control |
| [Heater Cooler (HHC)](examples/heater_cooler.md) | Setting and holding a temperature, reading status |
| [Inheco TEC (STC/MTC)](examples/inheco_tec.md) | Temperature control and shaking with Inheco TEC controllers |
| [Inheco ODTC](examples/odtc.md) | Running PCR protocols on the On-Deck Thermal Cycler |
| [Media Fill Module](examples/media_fill.md) | Pump direction, filling troughs, pumping out, liquid level sensors |
| [Media Fill Hardware Notes](media_fill_hardware_notes.md) | Real-module behavior, serial protocol, troubleshooting |
| [Tilt Module (MFX)](examples/tilt_module.md) | Tilting a plate to an angle and reading status |
| [Tilt Module Hardware Notes](tilt_module_hardware_notes.md) | Real-module behavior, orientation, troubleshooting |

---

## Reference

| Guide | What it covers |
|-------|----------------|
| [StarClient API Reference](star_commands.md) | Complete method listing with signatures and return types (STAR) |
| [VantageClient API Reference](vantage_commands.md) | Complete method listing with signatures and return types (Vantage) |
| [Static Catalogs](static_catalogs.md) | `LABWARE` and `LIQUID_CLASSES` catalog constants |
| [Automated Teaching](teaching.md) | Teaching plate positions with the teaching needle and Z-stall searches (`teach_well`) |

---

## Schema References

| Reference | What it covers |
|-------|----------------|
| [Labware Schema Tour](labware_schema/schema_tour.md) | Narrative walkthrough of the Hamilton labware JSON schema |
| [Labware Schema Conventions](labware_schema/conventions.md) | Naming, units, and structural conventions used throughout the labware schema |
| [Labware Schema Validation Rules](labware_schema/validation_rules.md) | Required fields, cross-field constraints, and validation behavior |
| [Labware Schema Diagram](labware_schema/schema_diagram.md) | Visual overview of the schema's structure |
| Labware JSON Schemas | Machine-readable schemas: [`labware.schema.json`](labware_schema/labware.schema.json), [`geometry.schema.json`](labware_schema/geometry.schema.json), [`alignment.schema.json`](labware_schema/alignment.schema.json), [`site.schema.json`](labware_schema/site.schema.json) |
| [Liquid Class Model](liquid_class_schema/liquid_class_model_sdk.md) | JSON structure of a liquid class definition |
| [Liquid Class Reference Values](liquid_class_schema/liquid_class_reference_values.md) | Valid enum values and per-device numeric bounds referenced by the liquid class model |

---

## Advanced Topics

| Guide | What it covers |
|-------|----------------|
| [Instrument Configuration](examples/advanced/instrument_configuration.md) | Serial number, deck geometry, maintenance gating, startup diagnostics |
| [Status and Diagnostics](examples/advanced/status_and_diagnostics.md) | Front cover, status light, pipetting arm, pre-flight checks |
| [Tip Pool Management](examples/advanced/tip_pool_management.md) | Tip counter queries, resets, low-tip warnings |
| [TADM](examples/advanced/tadm.md) | Pressure curves, flagged channels, raw data export, `copy_plate` integration |
| [Gripper Operations](examples/advanced/gripper_operations.md) | CO-RE and QCG transport tool setup, inventory, workflows |
| [Transport Workflows](examples/advanced/transport_workflows.md) | Advanced CO-RE and iSWAP workflows, batch transport, state checks |
| [Deck Persistence](examples/advanced/deck_persistence.md) | Saving, loading, and versioning deck layouts |
| [Custom Labware](examples/advanced/custom_labware.md) | Adding definitions, importing `.lay` files, mounting racks as sites |
| [Labware Builder](examples/advanced/labware_builder.md) | Building plate, reservoir, and tube definitions from scratch |
| [Liquid Class Management](examples/advanced/liquid_class_management.md) | Filtering, querying, pulling/pushing, and syncing liquid classes |
| [End-to-End Workflows](examples/advanced/end_to_end_workflows.md) | Complete protocol examples combining multiple SDK features |

---

## Command Catalogs

| Reference | What it covers |
|-------|----------------|
| [JSON Schemas — STAR](json_schemas_star.md) | Full request/response JSON examples for every STAR command |
| [JSON Schemas — Vantage](json_schemas_vantage.md) | Full request/response JSON examples for every Vantage command |
| [JSON Schemas — System](json_schemas_system.md) | Full request/response JSON examples for System-category commands |
| [JSON Schemas — Device](json_schemas_device.md) | Full request/response JSON examples for device-management commands |

---

## Compound Commands

| Guide | What it covers |
|-------|----------------|
| [Compound Commands Overview](examples/compound_commands/README.md) | Index of all six compound commands with minimal usage snippets |
| [Add Reagent](examples/compound_commands/add_reagent.md) | Reagent dispensing from one or more sources into destination wells |
| [Copy Plate](examples/compound_commands/copy_plate.md) | Full-plate transfers with `copy_plate()`, TADM access, partial copies |
| [Hit Picking](examples/compound_commands/hit_picking.md) | CSV-driven many-to-many transfers ("cherry pick") |
| [Pool Samples](examples/compound_commands/pool_samples.md) | Combine `pool_size` source wells into one destination well |
| [Replicate Samples](examples/compound_commands/replicate_samples.md) | Aliquot each source well into multiple destination wells |
| [Serial Dilution](examples/compound_commands/serial_dilution.md) | Column-wise serial dilution, by volume or by dilution factor |
