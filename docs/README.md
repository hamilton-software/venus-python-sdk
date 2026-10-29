# Hamilton VENUS SDK Documentation

Quick-reference index for the SDK documentation. If you are new to the SDK, start with [Getting Started](examples/getting-started.md).

---

## Setup and Configuration

| Guide | What it covers |
|-------|----------------|
| [Getting Started](examples/getting-started.md) | Connecting, initializing, and the basic workflow lifecycle |
| [Authentication](authentication.md) | Unauthenticated and OAuth-authenticated VENUS environments |
| [Configuration](configuration.md) | `SdkConfig`, `MethodConfig`, environment variables, and TOML |
| [GUI Installer](gui-installer.md) | Using `VenusPythonSdkInstaller.exe`, what installs by default, and what each checkbox adds |

---

## Core Examples

| Guide | What it covers |
|-------|----------------|
| [Common Patterns](examples/common-patterns.md) | Recommended patterns for transfers, error handling, TADM, and status lights |
| [Liquid Handling](examples/liquid-handling.md) | `aspirate()`, `dispense()`, `detect_liquid_level()`, settings, non-standard labware, 5mL (XL) channels |
| [Position and Well Selection](examples/position-and-well-selection.md) | Selector DSL, `normalize_positions`, `SpecResolver`, labware specs |
| [Deck and Layout](examples/deck-and-layout.md) | `add_carrier()`, `add_plate()`, `add_tip_rack()`, lidded plates |
| [Autoload](examples/autoload.md) | Loading/unloading carriers, occupancy sensing, deck audit |
| [Transport](examples/transport.md) | CO-RE and iSWAP plate transport, barcode scanning |
| [96-Channel Head (MPH96)](examples/mph96.md) | Full-plate and partial pickups, MPH96 settings |
| [Error Handling](error_handling.md) | Error profiles, operator escalation, recovery actions |
| [Run Log](examples/advanced/run_log.md) | Structured JSON run log, configuration, crash recovery |

---

## Reference

| Guide | What it covers |
|-------|----------------|
| [StarClient API Reference](star-commands.md) | Complete method listing with signatures and return types (STAR) |
| [VantageClient API Reference](vantage-commands.md) | Complete method listing with signatures and return types (Vantage) |
| [Static Catalogs](static-catalogs.md) | `LABWARE` and `LIQUID_CLASSES` catalog constants |
| [Automated Teaching](teaching.md) | Teaching plate positions with the teaching needle and Z-stall searches (`teach_well`) |

---

## Schema References

| Reference | What it covers |
|-------|----------------|
| [Labware Schema Tour](labware_schema/schema-tour.md) | Narrative walkthrough of the Hamilton MicrolabAPI labware JSON schema |
| [Labware Schema Conventions](labware_schema/conventions.md) | Naming, units, and structural conventions used throughout the labware schema |
| [Labware Schema Validation Rules](labware_schema/validation-rules.md) | Required fields, cross-field constraints, and validation behavior |
| [Labware Schema Diagram](labware_schema/schema-diagram.md) | Visual overview of the schema's structure |
| Labware JSON Schemas | Machine-readable schemas: [`labware.schema.json`](labware_schema/labware.schema.json), [`geometry.schema.json`](labware_schema/geometry.schema.json), [`alignment.schema.json`](labware_schema/alignment.schema.json), [`site.schema.json`](labware_schema/site.schema.json) |
| [Liquid Class Model](liquid_class_schema/JSON_Liquid-Class-Model_sdk.md) | JSON structure of a liquid class definition |
| [Liquid Class Reference Values](liquid_class_schema/JSON_Liquid-Class-Reference-Values.md) | Valid enum values and per-device numeric bounds referenced by the liquid class model |

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

## Command Catalogs and Tools

| Reference | What it covers |
|-------|----------------|
| [JSON Schemas — STAR](json_schemas_STAR.md) | Full request/response JSON examples for every STAR command |
| [JSON Schemas — Vantage](json_schemas_Vantage.md) | Full request/response JSON examples for every Vantage command |
| [JSON Schemas — System](json_schemas_System.md) | Full request/response JSON examples for System-category commands |
| [JSON Schemas — Device](json_schemas_Device.md) | Full request/response JSON examples for device-management commands |
| [Vector API Tool](api_tool.html) | Standalone HTML tool for sending raw Vector WebAPI commands and inspecting responses |

---

## Compound Commands

| Guide | What it covers |
|-------|----------------|
| [Compound Commands Overview](examples/compound-commands/README.md) | Index of all six compound commands with minimal usage snippets |
| [Add Reagent](examples/compound-commands/add-reagent.md) | Reagent dispensing from one or more sources into destination wells |
| [Copy Plate](examples/compound-commands/copy-plate.md) | Full-plate transfers with `copy_plate()`, TADM access, partial copies |
| [Hit Picking](examples/compound-commands/hit-picking.md) | CSV-driven many-to-many transfers ("cherry pick") |
| [Pool Samples](examples/compound-commands/pool-samples.md) | Combine `pool_size` source wells into one destination well |
| [Replicate Samples](examples/compound-commands/replicate-samples.md) | Aliquot each source well into multiple destination wells |
| [Serial Dilution](examples/compound-commands/serial-dilution.md) | Column-wise serial dilution, by volume or by dilution factor |
