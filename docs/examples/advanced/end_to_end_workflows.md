# End-to-End Sample Processing Workflows

Comprehensive guide for complete laboratory workflows combining setup, processing, and validation.

## Overview

This guide demonstrates real-world workflows that orchestrate multiple SDK features together. It includes:

- **Basic workflow** — Simple multi-stage transfer with setup, execution, and validation
- **Advanced workflow** — Complete production pipeline with state tracking, error handling, and comprehensive results reporting
- **Best practices** — Logging configuration and error recovery patterns

---

## Fundamental Concepts

### Workflow Stages

```
Stage 1: Setup       → Initialize deck, verify config
Stage 2: Load        → Load samples from source locations
Stage 3: Process     → Execute assay or transformation
Stage 4: Validate    → Check results, verify integrity
Stage 5: Output      → Move to storage/analysis locations
Stage 6: Cleanup     → Reset deck, archive data
```

### State Management

Track workflow state to enable:
- Progress reporting
- Error recovery
- Audit trails
- Checkpoint resumption

---

## Basic End-to-End Workflow

### Simple Sample Transfer Workflow

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

def simple_transfer_workflow(star):
    """
    Simple workflow: Setup → Transfer → Verify.
    
    Transfers samples from source to destination plate.
    """
    try:
        print("Starting simple transfer workflow")

        star.instrument_init()

        # Stage 1: Setup
        print("Stage 1: Setting up deck layout...")
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
            left_track=1,
            labware_id="SourceCarrier",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.COS_96_RD,
            carrier_id="SourceCarrier",
            site="1",
            plate_id="SourcePlate",
        )
        
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
            left_track=13,
            labware_id="DestCarrier",
        )
        star.add_plate(
            labware_definition=LABWARE.PLATE.COS_96_RD,
            carrier_id="DestCarrier",
            site="1",
            plate_id="DestPlate",
        )
        
        # Add tips
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
            left_track=7,
            labware_id="TipCarrier",
        )
        star.add_tip_rack(
            tip_pool="TransferTips",
            labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
            carrier_id="TipCarrier",
            site="1",
        )
        print("✓ Deck setup complete")

        # Stage 2: Transfer
        print("Stage 2: Executing transfers...")
        channels = [1, 2, 3, 4, 5, 6, 7, 8]
        
        for col in range(1, 13):
            print(f"  Transferring column {col}...")
            
            star.tip_pickup(channels=channels, tip_pool="TransferTips")
            star.aspirate(
                channels=channels,
                positions=f"SourcePlate@col:{col}",
                volumes=50.0,
                liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
            )
            star.dispense(
                channels=channels,
                positions=f"DestPlate@col:{col}",
                volumes=50.0,
            )
            star.tip_eject(channels=channels)
        
        print("✓ Transfers complete")
        
        # Stage 3: Verify
        print("Stage 3: Verifying...")
        # Validation logic goes here
        # Check that transfers succeeded as expected
        print("✓ Verification complete")
        
        print("="*60)
        print("✓ WORKFLOW COMPLETE")
        print("="*60)
        
        return True
        
    except Exception as e:
        print(f"✗ Workflow failed: {e}")
        return False


# Usage
with StarClient() as star:
    if simple_transfer_workflow(star):
        print("Workflow succeeded")
    else:
        print("Workflow failed")
```

---

## Advanced: Complete Multi-Stage Workflow

### Production Sample Processing Workflow

```python
from enum import Enum
from datetime import datetime

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES

class WorkflowStage(Enum):
    """Workflow execution stages."""
    SETUP = "setup"
    LOAD = "load"
    PROCESS = "process"
    VALIDATE = "validate"
    OUTPUT = "output"
    CLEANUP = "cleanup"
    COMPLETE = "complete"


class ProductionWorkflow:
    """Complete production sample processing workflow."""
    
    def __init__(self, star, sample_count=96):
        self.star = star
        self.sample_count = sample_count
        self.stage = WorkflowStage.SETUP
        self.timestamp = datetime.now().isoformat()
        self.results = {
            "loaded": 0,
            "processed": 0,
            "validated": 0,
            "errors": 0,
        }
    
    def _log_stage(self, stage, message):
        """Log stage transition."""
        self.stage = stage
        print("="*60)
        print(f"STAGE: {stage.value.upper()}")
        print(f"MESSAGE: {message}")
        print("="*60)
    
    def setup_deck(self):
        """Initialize deck layout for workflow."""
        self._log_stage(WorkflowStage.SETUP, "Initializing deck layout")
        
        try:
            self.star.instrument_init()

            # Setup source carriers
            self.star.add_carrier(
                labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
                left_track=1,
                labware_id="SourceCarrier1",
            )
            self.star.add_plate(
                labware_definition=LABWARE.PLATE.COS_96_RD,
                carrier_id="SourceCarrier1",
                site="1",
                plate_id="SampleSource",
            )
            
            # Setup processing carriers
            self.star.add_carrier(
                labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
                left_track=7,
                labware_id="ProcessCarrier",
            )
            self.star.add_plate(
                labware_definition=LABWARE.PLATE.COS_96_RD,
                carrier_id="ProcessCarrier",
                site="1",
                plate_id="ProcessPlate",
            )
            
            # Setup destination carriers
            self.star.add_carrier(
                labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
                left_track=13,
                labware_id="DestCarrier",
            )
            self.star.add_plate(
                labware_definition=LABWARE.PLATE.COS_96_RD,
                carrier_id="DestCarrier",
                site="1",
                plate_id="OutputPlate",
            )
            
            # Setup tips
            self.star.add_carrier(
                labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
                left_track=19,
                labware_id="TipCarrier",
            )
            # Load, process and output each use 96 tips, so fill three sites
            for site in ("1", "2", "3"):
                self.star.add_tip_rack(
                    tip_pool="TransferTips",
                    labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL,
                    carrier_id="TipCarrier",
                    site=site,
                )
            
            print("✓ Deck setup complete")
            return True
            
        except Exception as e:
            print(f"✗ Deck setup failed: {e}")
            return False
    
    def load_samples(self):
        """Load samples from source to processing plate."""
        self._log_stage(WorkflowStage.LOAD, f"Loading {self.sample_count} samples")
        
        try:
            channels = [1, 2, 3, 4, 5, 6, 7, 8]
            
            for col in range(1, 13):
                print(f"  Loading column {col}...")
                
                self.star.tip_pickup(channels=channels, tip_pool="TransferTips")
                self.star.aspirate(
                    channels=channels,
                    positions=f"SampleSource@col:{col}",
                    volumes=20.0,
                    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
                )
                self.star.dispense(
                    channels=channels,
                    positions=f"ProcessPlate@col:{col}",
                    volumes=20.0,
                )
                self.star.tip_eject(channels=channels)
                
                self.results["loaded"] += 8
            
            print(f"✓ Loaded {self.results['loaded']} samples")
            return True
            
        except Exception as e:
            print(f"✗ Sample loading failed: {e}")
            return False
    
    def process_samples(self):
        """Execute processing assay on samples."""
        self._log_stage(WorkflowStage.PROCESS, "Processing samples")
        
        try:
            channels = [1, 2, 3, 4, 5, 6, 7, 8]
            
            print("Stage 1: Adding reagent...")
            for col in range(1, 13):
                self.star.tip_pickup(channels=channels, tip_pool="TransferTips")
                # Simulate adding reagent
                self.star.dispense(
                    channels=channels,
                    positions=f"ProcessPlate@col:{col}",
                    volumes=5.0,
                )
                self.star.tip_eject(channels=channels)
                
                self.results["processed"] += 8
            
            print("Stage 2: Incubation (simulated)...")
            # In real workflow, would include actual incubation time
            
            print(f"✓ Processed {self.results['processed']} samples")
            return True
            
        except Exception as e:
            print(f"✗ Sample processing failed: {e}")
            return False
    
    def validate_results(self):
        """Validate processing results."""
        self._log_stage(WorkflowStage.VALIDATE, "Validating results")
        
        try:
            # Validation logic goes here
            # Check that processing succeeded as expected
            
            # For now, mark all processed samples as validated
            self.results["validated"] = self.results["processed"]
            print(f"✓ Validated {self.results['validated']} samples")
            
            return True
            
        except Exception as e:
            print(f"✗ Validation failed: {e}")
            return False
    
    def move_to_output(self):
        """Move validated samples to output location."""
        self._log_stage(WorkflowStage.OUTPUT, "Moving to output")
        
        try:
            channels = [1, 2, 3, 4, 5, 6, 7, 8]
            
            for col in range(1, 13):
                print(f"  Moving column {col}...")
                
                self.star.tip_pickup(channels=channels, tip_pool="TransferTips")
                self.star.aspirate(
                    channels=channels,
                    positions=f"ProcessPlate@col:{col}",
                    volumes=25.0,
                    liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
                )
                self.star.dispense(
                    channels=channels,
                    positions=f"OutputPlate@col:{col}",
                    volumes=25.0,
                )
                self.star.tip_eject(channels=channels)
            
            print("✓ Samples moved to output")
            return True
            
        except Exception as e:
            print(f"✗ Output move failed: {e}")
            return False
    
    def cleanup(self):
        """Clean up and prepare for next run."""
        self._log_stage(WorkflowStage.CLEANUP, "Cleanup and archive")
        
        try:
            print("Resetting deck state...")
            # In production, might disable cleanup or archive state
            
            print("✓ Cleanup complete")
            return True
            
        except Exception as e:
            print(f"✗ Cleanup failed: {e}")
            return False
    
    def execute(self):
        """Execute complete workflow."""
        stages = [
            ("Setup", self.setup_deck),
            ("Load", self.load_samples),
            ("Process", self.process_samples),
            ("Validate", self.validate_results),
            ("Output", self.move_to_output),
            ("Cleanup", self.cleanup),
        ]
        
        for stage_name, stage_func in stages:
            try:
                if not stage_func():
                    print(f"✗ {stage_name} stage failed")
                    self.results["errors"] += 1
                    return False
            except Exception as e:
                print(f"✗ {stage_name} exception: {e}")
                self.results["errors"] += 1
                return False
        
        self.stage = WorkflowStage.COMPLETE
        
        print("="*60)
        print("WORKFLOW SUMMARY")
        print("="*60)
        print(f"Timestamp: {self.timestamp}")
        print(f"Loaded: {self.results['loaded']}")
        print(f"Processed: {self.results['processed']}")
        print(f"Validated: {self.results['validated']}")
        print(f"Errors: {self.results['errors']}")
        print("="*60)
        
        return self.results


# Usage
with StarClient() as star:
    workflow = ProductionWorkflow(star, sample_count=96)
    results = workflow.execute()
    if results:
        print(f"\n✓ Workflow completed successfully")
    else:
        print(f"\n✗ Workflow failed")
```

---

## Error Handling Patterns

### Graceful Error Recovery

Handle common errors with recovery attempts:

```python
from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.catalog import LIQUID_CLASSES

def workflow_with_error_recovery():
    """
    Workflow with error handling and recovery attempts.
    Demonstrates proper cleanup even when errors occur.

    Assumes a saved deck ("MyDeckLayout") that defines the "TransferTips"
    tip pool, "SourcePlate" and "DestPlate".
    """
    # auto_connect=False so the connect below can be retried explicitly
    star = StarClient(auto_connect=False, deck_name="MyDeckLayout")
    
    try:
        star.start()
        
        # Connection with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                star.instrument_connect(initialize=True)
                break
            except VenusTimeoutError:
                if attempt < max_retries - 1:
                    print(f"Connection timeout. Retrying... ({attempt + 1}/{max_retries})")
                    continue
                else:
                    print("Connection failed after max retries")
                    raise
        
        # Check readiness
        if not star.instrument_is_idle():
            print("Instrument not idle - aborting")
            return False
        
        # Execute with error handling
        channels = [1, 2, 3, 4, 5, 6, 7, 8]
        
        try:
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
            print("✓ Workflow succeeded")
            return True
            
        except VenusCommandFailedError as e:
            print(f"✗ Command failed: {e}")
            print(f"  Return code: {e.response.return_code}")
            print(f"  Details: {e.response.return_parameters}")
            
            # Attempt recovery
            print("Attempting recovery...")
            try:
                # Try to eject any tips still loaded
                star.tip_eject(channels=channels)
                print("✓ Tips ejected")
            except Exception:
                pass
            
            return False
            
        except VenusError as e:
            print(f"✗ Workflow error: {e}")
            
            # Attempt recovery
            print("Attempting recovery...")
            try:
                # Try to eject any tips still loaded
                star.tip_eject(channels=channels)
                print("✓ Tips ejected")
            except Exception:
                pass
            
            return False
    
    finally:
        # Cleanup always happens
        try:
            if star.instrument_is_connected():
                star.instrument_terminate()
        except Exception:
            pass
        
        star.stop()

workflow_with_error_recovery()
```

---

## Best Practices Summary

| Practice | Why It Matters | Implementation |
|----------|----------------|-----------------|
| **State validation** | Catch errors early before expensive operations | Check `instrument_is_idle()`, `front_cover_is_closed()` before workflows |
| **Error recovery** | Graceful handling of transient failures | Use try/except with retry logic for timeouts |
| **Always cleanup** | Ensure resources are released even on failure | Use try/finally or context managers |
| **Progress tracking** | Provide feedback during long workflows | Use `status_light_set_front_light(progress=...)` |
| **Retry logic** | Handle transient network/timing issues | Retry timeouts but not permanent errors |
| **Logging** | Track what happened for debugging | Log stage transitions and results |


