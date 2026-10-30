# Common Workflow Patterns

Reusable patterns for typical Hamilton STAR SDK workflows. Use these as templates for your own scripts.

Pattern 1 builds its deck in code. The other patterns assume a deck (loaded with `deck_name=...` or built as in Pattern 1) that already contains the tip pool `"TransferTips"` and plates `"SourcePlate"` and `"DestPlate"`.

---

## Pattern 1: Setup → Execute → Cleanup (Standard)

The most common pattern for a complete workflow with setup, execution, and cleanup.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

def standard_workflow():
    """
    Standard workflow pattern:
    1. Setup deck layout
    2. Initialize instrument
    3. Execute operations
    4. Cleanup
    """
    with StarClient() as star:
        star.instrument_init()
        # Setup phase
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=1,
            labware_id="TipCarrier",
        )
        star.add_tip_rack(
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
            carrier_id="TipCarrier",
            site="1",
            tip_pool="TransferTips",
        )
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
            left_track=10,
            labware_id="PlateCarrier",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.COS_96_RD,
            carrier_id="PlateCarrier",
            site="1",
            plate_id="SourcePlate",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.COS_96_RD,
            carrier_id="PlateCarrier",
            site="2",
            plate_id="DestPlate",
        )

        # Execution phase
        star.tip_pickup(tip_pool="TransferTips")
        star.aspirate(
            positions="SourcePlate@col:1",
            volumes=100.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        )
        star.dispense(
            positions="DestPlate@col:1",
            volumes=100.0,
        )
        star.tip_eject()

        # Cleanup happens automatically when exiting the context manager

standard_workflow()
```

---

## Pattern 2: Load Saved Deck → Execute

Use a previously saved deck configuration to skip manual layout building.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

def load_saved_deck_workflow():
    """
    Quick workflow using a previously saved deck.
    Loads the deck at startup, then executes.
    """
    with StarClient(deck_name="MyProductionDeck") as star:
        star.instrument_init()

        # Operations are ready to go
        star.tip_pickup(tip_pool="TransferTips")
        star.aspirate(
            positions="SourcePlate@col:1",
            volumes=50.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        )
        star.dispense(
            positions="DestPlate@col:1",
            volumes=50.0,
        )
        star.tip_eject()

load_saved_deck_workflow()
```

---

## Pattern 3: Exception Handling

The `with StarClient(...) as star:` context manager guarantees that the client
disconnects and shuts down cleanly regardless of whether an exception is raised
inside the block — you do **not** need a nested `try/except` for cleanup.
Place your `except` clauses **outside** the `with` block: the context manager
runs first (client disconnects), then the exception propagates up to be caught.

Catch `VenusCommandFailedError` and `VenusTimeoutError` before the base
`VenusError` class, since they are subclasses of it.

```python
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings

channels = [1, 2, 3, 4, 5, 6, 7, 8]
liquid_class = LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_PART
aspirate_settings = AspirateSettings()
dispense_settings = DispenseSettings()

try:
    with StarClient(deck_name="example_deck") as star:
        star.instrument_init()

        star.tip_pickup(channels=channels, tip_pool="TransferTips")
        star.aspirate(
            channels=channels,
            positions="SourcePlate@col:1",
            volumes=50.0,
            liquid_class=liquid_class,
            settings=aspirate_settings,
        )
        star.dispense(
            channels=channels,
            positions="DestPlate@col:1",
            volumes=50.0,
            settings=dispense_settings,
        )
        star.tip_eject(channels=channels)

        print("Workflow complete")

# VenusCommandFailedError and VenusTimeoutError are subclasses of VenusError,
# so they must be caught before the base class.
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e
```

### Using `start()` / `stop()` explicitly

If a `with` block doesn't fit your structure (e.g. a long-running service or
class-based wrapper), call `start()` and `stop()` directly. Use `try/finally`
to ensure `stop()` is always called — this is exactly what the context manager
does internally.

```python
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES

star = StarClient(deck_name="example_deck")
star.start()
try:
    star.instrument_init()

    star.tip_pickup(tip_pool="TransferTips")
    star.aspirate(
        positions="SourcePlate@col:1",
        volumes=50.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    )
    star.dispense(positions="DestPlate@col:1", volumes=50.0)
    star.tip_eject()

    print("Workflow complete")
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"SDK error: {e}")
    raise SystemExit(1) from e
finally:
    star.stop()
```

---

## Pattern 4: Multi-Iteration Workflow with Progress Tracking

Loop through multiple iterations with progress feedback.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models.enums import LightColor

def multi_iteration_workflow(num_iterations: int = 3):
    """
    Workflow that processes multiple samples with progress tracking.
    """
    with StarClient(deck_name="MyDeck") as star:
        star.instrument_init()

        channels = [1, 2, 3, 4, 5, 6, 7, 8]
        total_processed = 0

        try:
            for iteration in range(1, num_iterations + 1):
                print(f"\n=== Iteration {iteration}/{num_iterations} ===")

                # Progress feedback -- status_light_set_front_light()'s progress is a
                # discrete 0-5 level (each step = 20%), not a continuous percentage.
                level = round(iteration / num_iterations * 5)
                star.status_light_set_front_light(color=LightColor.BLUE, progress=level)

                # Pickup
                star.tip_pickup(channels=channels, tip_pool="TransferTips")

                # Aspirate
                star.aspirate(
                    channels=channels,
                    positions=f"SourcePlate@col:{iteration}",
                    volumes=100.0,
                    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
                )

                # Dispense
                star.dispense(
                    channels=channels,
                    positions=f"DestPlate@col:{iteration}",
                    volumes=100.0,
                )

                # Eject
                star.tip_eject(channels=channels)

                total_processed += len(channels)
                print(f"Processed {len(channels)} tips (total: {total_processed})")

            # Success
            star.status_light_set_front_light(color=LightColor.GREEN, progress=5)
            print(f"\nWorkflow complete: {total_processed} total operations")

        except Exception as e:
            # Error state
            star.status_light_set_front_light(color=LightColor.RED)
            print(f"Error during workflow: {e}")
            raise
```

---

## Pattern 5: Reusable Settings (Settings Objects)

Define settings once, reuse across multiple operations.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings

def workflow_with_reusable_settings():
    """
    Define settings once, then reuse them across multiple commands.
    Reduces repetition and ensures consistency.
    """
    # Define reusable settings
    aspirate_settings = AspirateSettings(
        mix_cycles=3,
        mix_volume=50.0,
        liquid_following=False,
    )

    dispense_settings = DispenseSettings(
        mix_cycles=2,
        mix_volume=25.0,
    )

    with StarClient() as star:
        star.instrument_init()

        channels = [1, 2, 3, 4, 5, 6, 7, 8]

        # Reuse settings across multiple columns
        for col in range(1, 13):
            star.tip_pickup(channels=channels, tip_pool="TransferTips")

            star.aspirate(
                channels=channels,
                positions=f"SourcePlate@col:{col}",
                volumes=100.0,
                liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
                settings=aspirate_settings,  # Reuse
            )

            star.dispense(
                channels=channels,
                positions=f"DestPlate@col:{col}",
                volumes=100.0,
                settings=dispense_settings,  # Reuse
            )

            star.tip_eject(channels=channels)

workflow_with_reusable_settings()
```

---

## Pattern 6: Checkpoint and Resume

Save state at key points to enable resumption after interruptions.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
import json
from datetime import datetime

def workflow_with_checkpoints(checkpoint_file: str = "workflow_checkpoint.json"):
    """
    Workflow with checkpoint/resume capability.
    Saves state so you can resume after interruptions.
    """
    # Load checkpoint if it exists
    checkpoint = {}
    try:
        with open(checkpoint_file, "r") as f:
            checkpoint = json.load(f)
        print(f"Resuming from checkpoint: {checkpoint}")
        start_iteration = checkpoint.get("last_iteration", 0) + 1
    except FileNotFoundError:
        start_iteration = 1
        checkpoint = {
            "started_at": datetime.now().isoformat(),
            "last_iteration": 0,
            "completed": [],
        }

    with StarClient(deck_name="MyDeck") as star:
        star.instrument_init()

        channels = [1, 2, 3, 4, 5, 6, 7, 8]

        try:
            for iteration in range(start_iteration, 13):
                print(f"\nIteration {iteration}/12")

                # Execute
                star.tip_pickup(channels=channels, tip_pool="TransferTips")
                star.aspirate(
                    channels=channels,
                    positions=f"SourcePlate@col:{iteration}",
                    volumes=100.0,
                    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
                )
                star.dispense(
                    channels=channels,
                    positions=f"DestPlate@col:{iteration}",
                    volumes=100.0,
                )
                star.tip_eject(channels=channels)

                # Save checkpoint
                checkpoint["last_iteration"] = iteration
                checkpoint["completed"].append(iteration)
                with open(checkpoint_file, "w") as f:
                    json.dump(checkpoint, f)

                print(f"Checkpoint saved. Completed: {checkpoint['completed']}")

            print(f"\nWorkflow complete! All 12 iterations finished.")

        except Exception as e:
            print(f"Error at iteration {iteration}. Checkpoint saved.")
            print(f"Resume by running the workflow again (will start at iteration {iteration + 1})")
            raise

workflow_with_checkpoints()
```

---

## Pattern 7: Pre-Flight Validation

Validate instrument state before executing main workflow.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

def workflow_with_preflight():
    """
    Execute pre-flight checks before main workflow.
    Ensures instrument is in a valid state.
    """
    with StarClient() as star:
        # Pre-flight checks
        print("Running pre-flight checks...")

        if not star.instrument_is_connected():
            print("ERROR: Instrument not connected")
            return False

        if not star.instrument_is_idle():
            print("ERROR: Instrument not idle")
            return False

        config = star.instrument_get_configuration()
        if config.return_parameters.tracks < 54:
            print("ERROR: Expected 54 tracks")
            return False

        # Check maintenance
        daily = star.instrument_get_daily_maintenance_data()
        print(f"Daily maintenance status: {daily.return_parameters.status}")

        # Check front cover
        front_cover_closed = star.front_cover_is_closed()
        if not front_cover_closed.return_parameters.is_closed:
            print("WARNING: Front cover is open")

        print("Pre-flight checks passed!\n")

        # Main workflow
        star.instrument_init()
        channels = [1, 2, 3, 4, 5, 6, 7, 8]

        star.tip_pickup(channels=channels, tip_pool="TransferTips")
        star.aspirate(
            channels=channels,
            positions="SourcePlate@col:1",
            volumes=50.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        )
        star.dispense(
            channels=channels,
            positions="DestPlate@col:1",
            volumes=50.0,
        )
        star.tip_eject(channels=channels)

        print("Main workflow complete")
        return True

workflow_with_preflight()
```

---

## Pattern 8: 96-Channel Head (MPH96) Workflow

Complete workflow using the 96-channel head for high-throughput operations.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES
from hamilton_venus.models import MPH96AspirateSettings, MPH96DispenseSettings

def mph96_workflow():
    """
    Complete workflow using 96-channel head.
    Demonstrates full-plate transfer with reusable settings.
    """
    # Define reusable MPH96 settings
    aspirate_settings = MPH96AspirateSettings(
        mix_cycles=2,
        mix_volume=50.0,
        mix_position=3.0,
    )

    dispense_settings = MPH96DispenseSettings(
        liquid_following=True,
        use_side_touch=False,
        minimize_z_move=True,
    )

    with StarClient(deck_name="MPH96Deck") as star:
        star.instrument_init()

        # Full-plate transfer
        print("MPH96 full-plate transfer:")
        star.tip_pick_up_mph96(tip_pool="Tips96")
        star.aspirate_mph96(
            labware_id="SourcePlate",
            volume=50.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_96COREHEAD_WATER_DISPENSEJET_EMPTY,
            settings=aspirate_settings,
        )
        star.dispense_mph96(
            labware_id="DestPlate",
            volume=50.0,
            settings=dispense_settings,
        )
        star.tip_eject_mph96()

        print("Full-plate transfer complete")

mph96_workflow()
```

---

## Pattern 9: Quality Control with TADM Monitoring

Monitor TADM (Total Aspiration and Dispense Monitoring) pressure data for quality assurance and troubleshooting.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

def workflow_with_quality_monitoring():
    """
    Workflow with real-time TADM monitoring for quality control.
    Checks pressure curves and per-channel metrics to detect issues.
    """
    with StarClient(deck_name="QCDeck") as star:
        star.instrument_init()
        
        channels = [1, 2, 3, 4, 5, 6, 7, 8]

        ASPIRATE_VOLUME_TOLERANCE = 5.0  # µL

        try:
            star.tip_pickup(channels=channels, tip_pool="TransferTips")

            # Execute aspirate and capture response
            aspirate_response = star.aspirate(
                channels=channels,
                positions="SourcePlate@col:1",
                volumes=100.0,
                liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
            )

            # Check per-channel metrics
            print("=== Aspirate Quality Check ===")
            for channel_data in aspirate_response.return_parameters.channels:
                channel = channel_data.channel
                actual_volume = channel_data.aspirated_volume
                expected_volume = 100.0
                deviation = abs(actual_volume - expected_volume)

                status = "PASS" if deviation <= ASPIRATE_VOLUME_TOLERANCE else "FAIL"
                print(f"Channel {channel}: {actual_volume} µL {status}")

                if deviation > ASPIRATE_VOLUME_TOLERANCE:
                    print(f"  WARNING: Volume deviation {deviation:.1f} µL exceeds tolerance")

            # Check TADM curves for errors
            print("\n=== TADM Pressure Curve Analysis ===")
            tadm = aspirate_response.return_parameters.tadm
            critical_errors = []

            for curve in (tadm.tadm_curves if tadm is not None else []):
                channel = curve.channel_number
                liquid_class = curve.liquid_class_name

                if curve.error != 0:
                    critical_errors.append(channel)
                    print(f"✗ Channel {channel}: ERROR FLAG SET (error={curve.error})")
                    print(f"  Liquid class: {liquid_class}")
                    print(f"  Timestamp: {curve.time_stamp}")
                else:
                    print(f"✓ Channel {channel}: OK (error=0)")

                # Analyze pressure points for anomalies
                if curve.curve_points:
                    pressures = [p.pressure for p in curve.curve_points if p.pressure is not None]
                    if pressures:
                        min_p = min(pressures)
                        max_p = max(pressures)
                        avg_p = sum(pressures) / len(pressures)
                        print(f"  Pressure range: {min_p}-{max_p} mbar (avg: {avg_p:.0f})")

            # Dispense with similar monitoring
            dispense_response = star.dispense(
                channels=channels,
                positions="DestPlate@col:1",
                volumes=100.0,
            )

            print("\n=== Dispense Quality Check ===")
            for channel_data in dispense_response.return_parameters.channels:
                channel = channel_data.channel
                actual_volume = channel_data.dispensed_volume
                expected_volume = 100.0
                deviation = abs(actual_volume - expected_volume)

                status = "✓ PASS" if deviation <= ASPIRATE_VOLUME_TOLERANCE else "✗ FAIL"
                print(f"Channel {channel}: {actual_volume} µL {status}")

            star.tip_eject(channels=channels)

            # Report results
            if critical_errors:
                print(f"\nCRITICAL: {len(critical_errors)} channel(s) have TADM errors: {critical_errors}")
                print("Recommend tip inspection or liquid class adjustment")
            else:
                print("\n All channels passed quality checks")

            return len(critical_errors) == 0

        except Exception as e:
            print(f"Error during workflow: {e}")
            return False

workflow_with_quality_monitoring()
```

---

## Pattern 10: Combining StarClient/VantageClient with a Standalone Device Client

The Hamilton Heater Cooler (HHC) and Inheco ODTC are **pure Python and do not use the
VENUS runtime** — each has its own standalone client (`HeaterCoolerClient`,
`ODTCClient`) that needs no `StarClient`/`VantageClient` at all (see
[Heater Cooler](./heater_cooler.md) / [Inheco ODTC](./odtc.md)). A workflow that uses
one of these *alongside* the instrument — chilling a plate on the HHC while the arm
pipettes elsewhere, say — combines the two clients with a single `with` statement,
since neither depends on the other's lifecycle:

```python
from hamilton_venus import HeaterCoolerClient, StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

def chill_and_transfer():
    """Chill a plate on the HHC while the instrument runs a transfer."""
    with HeaterCoolerClient(simulate=True) as hhc, StarClient(simulate=True) as star:
        hhc.hhc_connect("COM4")
        star.instrument_init()

        # Start chilling; don't block -- the instrument work below runs concurrently
        # with the HHC ramping toward its target.
        hhc.hhc_start_temp_control(target=4.0)

        star.tip_pickup(tip_pool="TransferTips")
        star.aspirate(
            positions="SourcePlate@col:1",
            volumes=100.0,
            liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
        )
        star.dispense(positions="DestPlate@col:1", volumes=100.0)
        star.tip_eject()

        # Now confirm the HHC actually reached band before using the plate.
        hhc.hhc_wait_for_temp_control()
        hhc.hhc_stop_temp_control()

chill_and_transfer()
```

Both context managers exit (and clean up) together, in reverse order, even if a step
raises — `StarClient` disconnects, `HeaterCoolerClient.close()` releases the
connection and, on 64-bit Python, the 32-bit COM worker subprocess.

**If the device work is brief or only needed for one section**, nest a narrower `with
HeaterCoolerClient(...) as hhc:` block around just that part instead of holding it
open for the whole script — it costs nothing to open/close repeatedly, unlike
`StarClient`, which you generally want to enter once per script:

```python
with StarClient(simulate=True) as star:
    star.instrument_init()
    # ... instrument-only steps ...

    with HeaterCoolerClient(simulate=True) as hhc:
        hhc.hhc_connect("COM4")
        hhc.hhc_start_temp_control(target=4.0, wait=True)
        hhc.hhc_stop_temp_control()

    # ... more instrument-only steps ...
```

The same pattern applies to `ODTCClient`, and to combining more than one standalone
device client (e.g. `HeaterCoolerClient` and `ODTCClient` together, with or without a
`StarClient`) — just add more names to the `with` statement.

---

## Quick Reference: When to Use Each Pattern

| Pattern | Best For | Key Features |
|---------|----------|--------------|
| **Pattern 1: Standard** | Most workflows | Setup → Execute → Cleanup |
| **Pattern 2: Saved Deck** | Repeated workflows | Faster startup with pre-saved layout |
| **Pattern 3: Error Handling** | Production code | Flat try/except outside `with` block; cleanup is guaranteed by the context manager |
| **Pattern 4: Multi-Iteration** | Batch processing | Progress tracking and iteration management |
| **Pattern 5: Reusable Settings** | Repeated operations | Consistency and reduced code duplication |
| **Pattern 6: Checkpoints** | Long workflows | Resume after interruptions |
| **Pattern 7: Pre-Flight** | Critical operations | Validate state before execution |
| **Pattern 8: MPH96** | High-throughput | 96-channel head operations |
| **Pattern 9: Quality Monitoring** | QC and diagnostics | TADM curves, pressure analysis, channel metrics |
| **Pattern 10: Combined Clients** | HHC/ODTC + instrument in one script | One `with` for independent clients; nest narrower blocks when device use is brief |
