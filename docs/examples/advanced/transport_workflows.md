# Transport and Gripper Workflows

Comprehensive guide for advanced transport workflows using both CO-RE grippers and iSWAP tools.

## Overview

The transport system allows you to move plates between locations using various gripper types. This guide covers:

**CO-RE Gripper Workflows:**
- Basic transport operations
- Different gripper types (1mL CO-RE, 5mL CO-RE, QCG)
- Transport modes and recovery strategies
- Gripper state management
- Error handling and edge cases

**iSWAP Transport Workflows:**
- Production workflows with error handling
- Conditional routing using the unique get/put workflow
- Batch transport operations

For basic examples, see [`../transport.md`](../transport.md).

> **Note:** The `grip_width` and `grip_open` parameters are optional. If not specified, they will be automatically calculated by the server based on the labware being transported. This makes examples cleaner and easier to read while maintaining full control when needed.

---

## Basic Plate Transport

### Simple Transport Between Locations

Move a plate from one carrier site to another:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    # Transport a plate from source to destination carrier
    star.core_transport(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="1",
        grip_height_above_bottom=8.0,
    )
    print("Plate transported successfully")
```

**Parameters explained:**
- `labware_name`: Identifier of the plate to transport (must exist in layout)
- `carrier`: Destination carrier ID where plate will be placed
- `site`: Destination site on the carrier (typically "1", "2", "3", etc.)
- `grip_height_above_bottom`: Height above plate bottom for gripper grip (mm)

---

## Checking Gripper State

### Query if Gripper is Holding a Plate

Check current gripper status before attempting transport:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    holding_result = star.core_transport_is_holding_labware()

    if holding_result.return_parameters.is_holding_labware:
        print("Gripper already has labware - clear it first")
        star.core_eject_grips()
    else:
        print("Gripper is empty - ready for next plate")
        # Proceed with transport...
```

---

## Transport Modes

### Return Mode: Place Plate Back in Original Location

Return a plate to its original position:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    # Pick up plate
    star.core_transport(
        labware_name="SourcePlate",
        carrier="ProcessingCarrier",
        site="2",
        grip_height_above_bottom=8.0,
    )

    # Do some processing...
    print("Processing plate...")

    # Return plate to original location
    star.core_transport_return_plate(mode="return")
    print("Plate returned to original position")
```

### New Mode: Place Plate in New Location (Don't Track Original)

Move a plate permanently to a new location without tracking the original:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    # Move plate to new carrier, abandon tracking of original position
    star.core_transport_return_plate(mode="new")
    print("Plate placed in new location, tracking cleared")
```

---

## Waste Management

### Transport Plate to Waste

Move the specified plate to waste collection:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.core_transport_to_waste(
        labware_name="MyPlate",
        grip_height_above_bottom=8.0,
    )
    print("Plate moved to waste")
```

---

## Managing Gripper State

### Clear Gripper Between Transports

Eject gripper if stuck or to prepare for next operation:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.core_eject_grips()
    print("Grippers cleared and ready")

    star.core_transport_tracking_clear()
    print("Transport tracking reset")
```

---

## Production Workflow: Multi-Step Transport with Error Handling

Complete workflow with state tracking and error recovery:

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_transport_workflow(star, plate_name, source_carrier, dest_carrier):
    """
    Transport a plate with error handling and state tracking.
    
    Args:
        star: StarClient instance
        plate_name: Name of plate to transport
        source_carrier: Source carrier identifier
        dest_carrier: Destination carrier identifier
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if gripper already has labware
        holding_result = star.core_transport_is_holding_labware()
        if holding_result.return_parameters.is_holding_labware:
            logger.warning("Gripper busy - clearing first")
            star.core_eject_grips()
            star.core_transport_tracking_clear()
        
        # Pick up plate from source
        logger.info(f"Picking up {plate_name} from {source_carrier}")
        star.core_transport(
            labware_name=plate_name,
            carrier=source_carrier,
            site="1",
            grip_height_above_bottom=8.0,
        )
        
        # Place in destination
        logger.info(f"Placing {plate_name} in {dest_carrier}")
        star.core_transport(
            labware_name=plate_name,
            carrier=dest_carrier,
            site="1",
            grip_height_above_bottom=8.0,
        )
        
        logger.info(f"Successfully transported {plate_name}")
        return True
        
    except Exception as e:
        logger.error(f"Transport failed: {e}")
        # Attempt recovery
        try:
            star.core_eject_grips()
            star.core_transport_tracking_clear()
        except Exception:
            logger.error("Failed to recover gripper state")
        return False

# Usage
with StarClient() as star:
    star.instrument_init()
    success = safe_transport_workflow(
        star,
        plate_name="MyPlate",
        source_carrier="SourceCarrier",
        dest_carrier="DestCarrier"
    )
    
    if success:
        print("Plate transported successfully")
    else:
        print("Transport operation failed")
```

---

## Advanced: Batch Transport Operations

Transport multiple plates in sequence:

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

def batch_transport(star, transfers):
    """
    Execute multiple transport operations in sequence.
    
    Args:
        star: StarClient instance
        transfers: List of dicts with keys:
            - plate_name: Name of plate
            - from_carrier: Source carrier
            - to_carrier: Destination carrier
    
    Returns:
        dict: Results with success count and failures
    """
    results = {"success": 0, "failed": 0, "failures": []}
    
    for i, transfer in enumerate(transfers, 1):
        try:
            logger.info(f"Transfer {i}/{len(transfers)}: {transfer['plate_name']}")

            holding_result = star.core_transport_is_holding_labware()
            if holding_result.return_parameters.is_holding_labware:
                logger.warning("Gripper busy, clearing...")
                star.core_eject_grips()
                star.core_transport_tracking_clear()

            # Execute transport
            star.core_transport(
                labware_name=transfer['plate_name'],
                carrier=transfer['from_carrier'],
                site="1",
                grip_height_above_bottom=8.0,
            )

            star.core_transport(
                labware_name=transfer['plate_name'],
                carrier=transfer['to_carrier'],
                site="1",
                grip_height_above_bottom=8.0,
            )
            
            results["success"] += 1
            logger.info(f"✓ Transfer complete")
            
        except Exception as e:
            results["failed"] += 1
            results["failures"].append({
                "plate": transfer['plate_name'],
                "error": str(e)
            })
            logger.error(f"✗ Transfer failed: {e}")
    
    return results


# Usage
with StarClient() as star:
    star.instrument_init()
    transfers = [
        {"plate_name": "Plate1", "from_carrier": "SourceA", "to_carrier": "ProcessB"},
        {"plate_name": "Plate2", "from_carrier": "SourceA", "to_carrier": "ProcessB"},
        {"plate_name": "Plate3", "from_carrier": "SourceB", "to_carrier": "ProcessC"},
    ]
    
    results = batch_transport(star, transfers)
    print(f"Completed: {results['success']} successful, {results['failed']} failed")
    
    if results["failures"]:
        for failure in results["failures"]:
            print(f"  Failed: {failure['plate']} - {failure['error']}")
```

---

## Performance Considerations

### Gripper Optimization

While `grip_width` and `grip_open` are optional and auto-calculated, you can provide custom values if needed for specific plate types.

```python
# Standard 96-well plate (100-110 mm width)
standard_plate_grip = {
    "grip_height_above_bottom": 8.0,
    "grip_width": 100.0,
    "grip_open": 50.0,
}

# Deep well plate (95-105 mm width)
deep_plate_grip = {
    "grip_height_above_bottom": 5.0,
    "grip_width": 95.0,
    "grip_open": 45.0,
}

# Reservoir (variable)
reservoir_grip = {
    "grip_height_above_bottom": 12.0,
    "grip_width": 85.0,
    "grip_open": 55.0,
}
```

### Batch Operations

For high-throughput workflows, group transports into logical batches:

```python
# Group by source location to minimize gripper repositioning
transfer_batches = {
    "SourceCarrier1": [
        {"plate": "Plate1", "dest": "ProcessCarrier"},
        {"plate": "Plate2", "dest": "ProcessCarrier"},
        {"plate": "Plate3", "dest": "ProcessCarrier"},
    ],
    "SourceCarrier2": [
        {"plate": "Plate4", "dest": "ProcessCarrier"},
        {"plate": "Plate5", "dest": "ProcessCarrier"},
    ],
}
```

---

## Common Issues and Solutions

### Gripper Timeout During Transport

**Problem:** Transport command times out or fails to complete.

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.core_transport(
        labware_name="MyPlate",
        carrier="DestCarrier",
        site="1",
        grip_height_above_bottom=8.0,
    )
```

### Gripper Stuck in Open Position

**Problem:** Gripper remains open and won't close.

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    # Force-eject grippers to reset
    star.core_eject_grips()

    # Clear transport tracking
    star.core_transport_tracking_clear()

    # Verify gripper state
    holding_result = star.core_transport_is_holding_labware()
    print(f"Gripper clear: {not holding_result.return_parameters.is_holding_labware}")
```

### Transport Between Non-Adjacent Carriers

**Problem:** Gripper can't reach between far carriers.

**Solution:**
```python
from hamilton_venus import StarClient

def transport_via_staging(star, plate, from_carrier, to_carrier, staging_carrier):
    """
    Transport via staging carrier when direct transport isn't possible.
    """
    # Move from source to staging
    star.core_transport(
        labware_name=plate,
        carrier=from_carrier,
        site="1",
        grip_height_above_bottom=8.0,
    )

    # Reposition if needed
    star.core_transport_return_plate(mode="return")

    # Move from staging to destination
    star.core_transport(
        labware_name=plate,
        carrier=to_carrier,
        site="1",
        grip_height_above_bottom=8.0,
    )
```

---

## Advanced iSWAP Transport Workflows

### Production Workflow: Multi-Step iSWAP with Error Handling

Complete workflow with state tracking and error recovery:

```python
import logging
from hamilton_venus import StarClient
from hamilton_venus.models.enums import GripInverse, PlaceRotation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_iswap_workflow(star, plate_name, source_carrier, dest_carrier):
    """
    Transport a plate with error handling and state tracking.

    Args:
        star: StarClient instance
        plate_name: Name of plate to transport
        source_carrier: Source carrier identifier
        dest_carrier: Destination carrier identifier

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if gripper already has labware
        holding_result = star.iswap_is_holding_labware()
        if holding_result.return_parameters.is_holding_labware:
            logger.warning("iSWAP busy - clearing first")
            star.iswap_park()
            star.iswap_tracking_clear()

        # Pick up plate from source
        logger.info(f"Picking up {plate_name} from {source_carrier}")
        star.iswap_transport(
            labware_name=plate_name,
            carrier=source_carrier,
            site="1",
            grip_height_above_bottom=8.0,
            grip_inverse=GripInverse.GRIP_FROM_RIGHT,
        )

        # Place in destination — rotate 90° to fit the target carrier orientation
        logger.info(f"Placing {plate_name} in {dest_carrier}")
        star.iswap_transport(
            labware_name=plate_name,
            carrier=dest_carrier,
            site="1",
            grip_height_above_bottom=8.0,
            place_rotation=PlaceRotation.DEGREES_90,
        )

        logger.info(f"Successfully transported {plate_name}")
        return True

    except Exception as e:
        logger.error(f"Transport failed: {e}")
        # Attempt recovery
        try:
            star.iswap_park()
            star.iswap_tracking_clear()
        except Exception:
            logger.error("Failed to recover iSWAP state")
        return False

# Usage
with StarClient() as star:
    star.instrument_init()
    success = safe_iswap_workflow(
        star,
        plate_name="MyPlate",
        source_carrier="SourceCarrier",
        dest_carrier="DestCarrier"
    )

    if success:
        print("Plate transported successfully")
    else:
        print("Transport operation failed")
```

### Conditional Get/Put Workflow

Use the iSWAP get/put separation for decision-based routing:

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

def conditional_routing_workflow(star, plate_name, initial_carrier, routing_fn):
    """
    Pick up a plate, evaluate conditions, then place based on result.

    Args:
        star: StarClient instance
        plate_name: Name of plate to transport
        initial_carrier: Initial carrier to pick from
        routing_fn: Function that returns destination carrier based on plate info

    Returns:
        str: Destination carrier where plate was placed
    """
    try:
        # Pick up plate
        logger.info(f"Picking up {plate_name}")
        star.iswap_get_labware(
            labware_name=plate_name,
            grip_height_above_bottom=8.0,
        )

        # Evaluate conditions - simulated here
        destination = routing_fn(plate_name)
        logger.info(f"Routing {plate_name} to {destination}")

        # Place at determined destination
        star.iswap_put_labware(
            carrier=destination,
            site="1",
        )

        return destination

    except Exception as e:
        logger.error(f"Conditional routing failed: {e}")
        # Attempt recovery
        try:
            star.iswap_park()
            star.iswap_tracking_clear()
        except Exception:
            logger.error("Failed to recover iSWAP state")
        raise

# Usage example with simple routing logic
def route_by_name(plate_name):
    if "QC" in plate_name:
        return "QCCarrier"
    elif "REJECT" in plate_name:
        return "RejectCarrier"
    else:
        return "ProcessCarrier"

with StarClient() as star:
    star.instrument_init()
    dest = conditional_routing_workflow(
        star,
        plate_name="Plate_QC_001",
        initial_carrier="IncomingCarrier",
        routing_fn=route_by_name
    )
    print(f"Plate routed to: {dest}")
```

### Batch Transport with iSWAP

Transport multiple plates in sequence with error handling:

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

def batch_iswap_transport(star, transfers):
    """
    Execute multiple transport operations in sequence.

    Args:
        star: StarClient instance
        transfers: List of dicts with keys:
            - plate_name: Name of plate
            - from_carrier: Source carrier
            - to_carrier: Destination carrier

    Returns:
        dict: Results with success count and failures
    """
    results = {"success": 0, "failed": 0, "failures": []}

    for i, transfer in enumerate(transfers, 1):
        try:
            logger.info(f"Transfer {i}/{len(transfers)}: {transfer['plate_name']}")

            holding_result = star.iswap_is_holding_labware()
            if holding_result.return_parameters.is_holding_labware:
                logger.warning("iSWAP busy, clearing...")
                star.iswap_park()
                star.iswap_tracking_clear()

            # Execute transport
            star.iswap_transport(
                labware_name=transfer['plate_name'],
                carrier=transfer['from_carrier'],
                site="1",
                grip_height_above_bottom=8.0,
            )

            star.iswap_transport(
                labware_name=transfer['plate_name'],
                carrier=transfer['to_carrier'],
                site="1",
                grip_height_above_bottom=8.0,
            )

            results["success"] += 1
            logger.info(f"✓ Transfer complete")

        except Exception as e:
            results["failed"] += 1
            results["failures"].append({
                "plate": transfer['plate_name'],
                "error": str(e)
            })
            logger.error(f"✗ Transfer failed: {e}")

    return results


# Usage
with StarClient() as star:
    star.instrument_init()
    transfers = [
        {"plate_name": "Plate1", "from_carrier": "SourceA", "to_carrier": "ProcessB"},
        {"plate_name": "Plate2", "from_carrier": "SourceA", "to_carrier": "ProcessB"},
        {"plate_name": "Plate3", "from_carrier": "SourceB", "to_carrier": "ProcessC"},
    ]

    results = batch_iswap_transport(star, transfers)
    print(f"Completed: {results['success']} successful, {results['failed']} failed")

    if results["failures"]:
        for failure in results["failures"]:
            print(f"  Failed: {failure['plate']} - {failure['error']}")
```

---

## See Also

- [`../transport.md`](../transport.md) — Basic CO-RE and iSWAP transport examples
- [`liquid_class_management.md`](./liquid_class_management.md) — Managing liquid handling parameters
- [`gripper_operations.md`](./gripper_operations.md) — Gripper setup and layout management
- [`star-commands.md`](../../star-commands.md) — Full API reference
- [Basic examples](../) — Basic examples

