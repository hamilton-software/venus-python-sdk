# Advanced Examples and Workflows

This directory contains comprehensive, production-ready examples for advanced Hamilton STAR SDK workflows. Each guide covers specific functionality in depth with multiple scenarios and real-world use cases.

Most workflow examples in this directory use `StarClient()` because many instrument, channel, deck, layout, transport, system, and liquid-class commands require prior `instrument_init()`. When a guide demonstrates manual startup control, it calls `instrument_init()` explicitly instead.

## Quick Navigation

### [Status and Diagnostics](./status_and_diagnostics.md)
Front cover control, status light feedback, and pipetting arm diagnostics for safety checks and troubleshooting.

**Covers:**
- Front cover lock/unlock and state checking
- Status light color and progress indication for user feedback
- Pipetting arm positioning and diagnostics
- Complete pre-flight diagnostic workflow
- Troubleshooting specific issues

---

### [Transport Workflows](./transport_workflows.md)
Detailed workflows for advanced plate transport using CO-RE grippers and iSWAP tools, including production workflows and conditional routing.

**Covers:**

**CO-RE Gripper Workflows:**
- Advanced plate transport patterns using CO-RE grippers
- Gripper type selection (1mL CO-RE, 5mL CO-RE, QCG)
- Transport mode variations (return, new, waste)
- Checking and managing gripper state
- Exception handling and recovery

**iSWAP Transport Workflows:**
- Production workflows with error handling and state tracking
- Conditional routing using the unique get/put workflow
- Batch transport operations with multiple plates

**Basic examples:** See [`../transport.md`](../transport.md) for basic CO-RE and iSWAP transport examples.

---

### [Liquid Class Management](./liquid_class_management.md)
Advanced workflows for querying liquid class metadata and syncing named definitions.

**Covers:**
- Pulling named liquid class definitions from the instrument
- Pushing named liquid class definitions back to the instrument
- Querying available devices, liquids, and tip types
- Filtering liquid classes with `get_liquid_classes()`
- Verifying required liquid classes before a run

---

### [Gripper Operations & Layout](./gripper_operations.md)
Comprehensive guide to gripper setup, configuration, and advanced layout management with transport tools.

**Covers:**
- Adding different grip types to layout (1mL, 5mL, QCG)
- Querying transport tool inventory
- Removing and replacing tools
- Complex gripper workflows
- Multi-tool coordination
- Gripper state management

---

### [Deck Persistence & Layout Management](./deck_persistence.md)
Advanced deck layout save/load workflows for complex instrument configurations.

**Covers:**
- Saving deck layouts to persistent storage
- Loading previously saved layouts
- Loading the last-used deck configuration
- Overwriting existing layouts
- Deck layout versioning strategies
- Recovery from layout errors

---

### [Tip Pool Management](./tip_pool_management.md)
Tip pool counter queries and updates.

**Covers:**
- Querying tip counter names and per-pool status
- Inspecting structured available-tip and missing-rack data
- Setting counters with the grouped rack structure expected by the backend
- Resetting and initializing counters
- Production monitoring patterns

---

### [TADM](./tadm.md)
Total Aspiration and Dispense Monitoring — pressure curves, flagged channels, and raw data export.

**Covers:**
- Reading TADM curves from `aspirate()` and `dispense()` results
- Detecting flagged (out-of-spec) and errored curves
- Exporting raw pressure-vs-time points for offline analysis
- Using `CopyPlateResult.tadm_curves` for compound operations
- `TADMMonitor` production class for accumulating results across steps

---

### [Labware Builder](./labware_builder.md)
Building labware definitions from scratch in Python.

**Covers:**
- Describing round and rectangular wells
- Building plate, reservoir, and tube definitions
- Clearance, liquid seeking, cLLD and touch-off settings
- Registering a built definition and using it on the deck

---

### [Custom Labware](./custom_labware.md)
Importing non-catalog labware — definitions, `.lay` files, and rack sites.

**Covers:**
- Adding, updating, and deleting labware definitions via the API
- Importing a full deck layout from a VENUS `.lay` file
- Querying racks inside a `.lay` file before importing
- Mounting a rack from a `.lay` file as a site on existing labware
- Production patterns for registering and validating custom definitions

---

### [Instrument Configuration & Diagnostics](./instrument_configuration.md)
Querying instrument state, maintenance gating, and running diagnostics.

**Covers:**
- Getting instrument configuration, serial number, deck geometry
- Maintenance gating — blocking or warning based on expiration and mandatory status
- Pre-execution validation workflows
- Health checks and startup diagnostics

---

### [End-to-End Sample Processing Workflows](./end_to_end_workflows.md)
Complete production workflows orchestrating multiple operations with command error handling.

**Covers:**
- Multi-stage workflow orchestration (setup, load, process, validate, output, cleanup)
- Basic transfer workflow example
- Advanced production workflow with state tracking and results reporting
- Exception handling and recovery patterns
- Logging configuration best practices

---

### [Run Log](./run_log.md)
Structured JSON run log for post-run analytics and AI/LIMS integration.

**Covers:**
- Enabling the run log with a single constructor flag
- Full `RunLogConfig` options (output directory, redaction, filtering)
- Output file naming and location
- Reading log entries programmatically
- Embedding VENUS's firmware COM trace (`.trc`) for the run's window

---

## When to Use These Guides

### Use the main [examples](../) for:
✅ Quick copy-paste workflows  
✅ "Hello world" getting started  
✅ Basic liquid transfer patterns  
✅ Standard deck configuration  

### Use these advanced guides for:
✅ Complex multi-stage workflows  
✅ Production automation scripts  
✅ Understanding exception handling and command errors  
✅ Optimizing for specific use cases  
✅ Building reusable libraries  
