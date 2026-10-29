# Gripper Operations and Layout Management

Comprehensive guide for setting up and managing gripper tools in deck layouts.

## Overview

Grippers (CO-RE and QCG tools) enable automated plate transport. This guide covers:
- Adding different gripper types to layouts
- Querying transport tool inventory
- Managing multiple grippers
- Advanced gripper coordination
- Troubleshooting gripper issues

---

## Gripper Types

> **Match the gripper to the channel type.** On a STAR, Fluid Motion 1 mL channels use the QCG and Legacy 1 mL channels use the CO-RE gripper; the two cannot be mixed. `add_qcg()` is rejected on Legacy channels and `add_1ml_core_grip()` on Fluid Motion channels, based on the instrument configuration. See [Connect-Time Validation](instrument_configuration.md#connect-time-validation-from-the-instrument-configuration).

### 1mL CO-RE Gripper

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType

with StarClient() as star:
    # Add with standard grip (default)
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
    
    print("1mL CO-RE gripper added with standard settings")
```

### 5mL CO-RE Gripper

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # 5mL CO-RE has no type variations
    star.add_5ml_core_grip()
    
    print("5mL CO-RE gripper added")
```

### QCG (Quad CO-RE Grip)

The QCG spans 4 channels (the standard CO-RE gripper spans 2), so its `front_channel` must be 4 or higher. It is the gripper for Fluid Motion channels and for Vantage.

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import QCGType

with StarClient() as star:
    # Add with standard QCG type (default)
    star.add_qcg(qcg_type=QCGType.QCG)
    
    print("QCG tool added with standard type")
```

---

## Basic Layout Setup with Grippers

### Complete Setup Example

Configure a deck with grippers and supporting labware:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType, QCGType
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    # Set up plate carriers
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=1,
        labware_id="SourceCarrier",
    )
    
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=10,
        labware_id="DestCarrier",
    )
    
    # Add source and destination plates
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="SourceCarrier",
        site="1",
        plate_id="SourcePlate",
    )
    
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="DestCarrier",
        site="1",
        plate_id="DestPlate",
    )
    
    # Add gripper tools for transport
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
    star.add_5ml_core_grip()
    star.add_qcg(qcg_type=QCGType.QCG)
    
    print("Deck layout with grippers configured")
```

---

## Querying Gripper Inventory

### Get All Transport Tools

```python
from hamilton_venus import StarClient

with StarClient() as star:
    tool_ids_result = star.get_transport_tool_ids()
    tools = tool_ids_result.return_parameters.transport_tools
    print(f"Available transport tools: {[t.transport_tool_id for t in tools]}")

    for tool in tools:
        try:
            tool_info = star.get_transport_tool(tool_id=tool.transport_tool_id)
            print(f"  Tool {tool.transport_tool_id}: {tool_info.return_parameters.labware_name}")
        except Exception as e:
            print(f"  Could not retrieve info for tool {tool.transport_tool_id}: {e}")
```

### Get Specific Tool by Type

```python
from hamilton_venus import StarClient

with StarClient() as star:
    try:
        tool_1ml = star.get_transport_tool(is_1ml=True)
        print(f"Found 1mL CO-RE tool ID: {tool_1ml.return_parameters.transport_tool_id}")
    except Exception:
        print("No 1mL CO-RE grip found")

    try:
        tool_qcg = star.get_transport_tool(is_qcg=True)
        print(f"Found QCG tool ID: {tool_qcg.return_parameters.transport_tool_id}")
    except Exception:
        print("No QCG tool found")
```

---

## Managing Multiple Grippers

### Production Workflow: Gripper Inventory Management

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class GripperManager:
    """Manage gripper tools in layout."""
    
    def __init__(self, star):
        self.star = star
        self.tools = {}
    
    def initialize_grippers(self, config):
        """
        Set up grippers according to configuration.
        
        Args:
            config: Dict with gripper types to add
        """
        from hamilton_venus.models.enums import CoreGripType, QCGType
        
        try:
            for gripper_type, count in config.items():
                if gripper_type == "1ml_core":
                    for i in range(count):
                        self.star.add_1ml_core_grip(
                            grip_type=CoreGripType.STANDARD
                        )
                        logger.info(f"Added 1mL CO-RE gripper #{i+1}")
                
                elif gripper_type == "5ml_core":
                    for i in range(count):
                        self.star.add_5ml_core_grip()
                        logger.info(f"Added 5mL CO-RE gripper #{i+1}")
                
                elif gripper_type == "qcg":
                    for i in range(count):
                        self.star.add_qcg(qcg_type=QCGType.QCG)
                        logger.info(f"Added QCG tool #{i+1}")
            
            self._update_inventory()
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize grippers: {e}")
            return False
    
    def _update_inventory(self):
        """Update internal tool inventory."""
        try:
            tool_ids_result = self.star.get_transport_tool_ids()
            tools = tool_ids_result.return_parameters.transport_tools
            self.tools = {t.transport_tool_id: None for t in tools}
            logger.info(f"Tool inventory updated: {len(self.tools)} tools")
        except Exception as e:
            logger.error(f"Failed to update inventory: {e}")
    
    def get_available_tools(self):
        """Get list of available tool IDs."""
        return list(self.tools.keys())
    
    def remove_tool(self, tool_id):
        """Remove a gripper tool."""
        try:
            self.star.remove_transport_tool(tool_id=tool_id)
            del self.tools[tool_id]
            logger.info(f"Removed tool {tool_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove tool {tool_id}: {e}")
            return False


# Usage
with StarClient() as star:
    manager = GripperManager(star)
    
    # Initialize grippers
    config = {
        "1ml_core": 2,
        "5ml_core": 1,
        "qcg": 1,
    }
    
    if manager.initialize_grippers(config):
        tools = manager.get_available_tools()
        print(f"Gripper setup complete. Tools: {tools}")
    else:
        print("Gripper setup failed")
```

---

## Advanced: Multi-Gripper Workflows

### Sequential Tool Usage

Use different grippers for different operations:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType

def sequential_gripper_workflow(star):
    """
    Execute workflow using different grippers.
    """
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
    star.add_5ml_core_grip()

    tools = star.get_transport_tool_ids().return_parameters.transport_tools
    tool_1ml = tools[0].transport_tool_id
    tool_5ml = tools[1].transport_tool_id

    # Use 1mL gripper for precise transfer
    print(f"Using 1mL gripper (ID: {tool_1ml}) for precise work")
    star.core_transport(
        labware_name="MicroPlate",
        carrier="Carrier1",
        site="1",
        grip_height_above_bottom=5.0,
        grip_width=50.0,
        grip_open=30.0,
    )
    
    # Use 5mL gripper for bulk transfer
    print(f"Using 5mL gripper (ID: {tool_5ml}) for bulk transfer")
    star.core_transport(
        labware_name="ReservoirPlate",
        carrier="Carrier2",
        site="1",
        grip_height_above_bottom=10.0,
        grip_width=100.0,
        grip_open=50.0,
    )


with StarClient() as star:
    star.instrument_init()
    sequential_gripper_workflow(star)
```

### Gripper Load Balancing

Distribute work across multiple grippers:

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class LoadBalancedGripperWorkflow:
    """Distribute transport operations across available grippers."""
    
    def __init__(self, star, gripper_config):
        self.star = star
        self.grippers = {}
        self.current_gripper = 0
        
        # Initialize grippers
        self._setup_grippers(gripper_config)
    
    def _setup_grippers(self, config):
        """Setup grippers as specified in config."""
        from hamilton_venus.models.enums import CoreGripType, QCGType
        
        if "1ml_core" in config:
            for i in range(config["1ml_core"]):
                self.star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
        
        if "5ml_core" in config:
            for i in range(config["5ml_core"]):
                self.star.add_5ml_core_grip()
        
        if "qcg" in config:
            for i in range(config["qcg"]):
                self.star.add_qcg(qcg_type=QCGType.QCG)
        
        # Get tool IDs
        tools = self.star.get_transport_tool_ids().return_parameters.transport_tools
        for tool in tools:
            self.grippers[tool.transport_tool_id] = {"busy": False}
        
        logger.info(f"Initialized {len(self.grippers)} grippers")
    
    def get_next_available_gripper(self):
        """Get next available gripper (round-robin)."""
        tool_ids = list(self.grippers.keys())
        
        for _ in range(len(tool_ids)):
            gripper = tool_ids[self.current_gripper % len(tool_ids)]
            self.current_gripper += 1
            
            if not self.grippers[gripper]["busy"]:
                return gripper
        
        logger.warning("No available grippers - all busy")
        return None
    
    def execute_transport(self, plate_name, source_carrier, dest_carrier):
        """Execute transport using available gripper."""
        gripper_id = self.get_next_available_gripper()
        
        if not gripper_id:
            logger.error("Cannot execute transport - no available grippers")
            return False
        
        try:
            self.grippers[gripper_id]["busy"] = True
            logger.info(f"Using gripper {gripper_id} for {plate_name}")
            
            self.star.core_transport(
                labware_name=plate_name,
                carrier=source_carrier,
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
            )
            
            self.star.core_transport(
                labware_name=plate_name,
                carrier=dest_carrier,
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Transport failed: {e}")
            return False
        
        finally:
            self.grippers[gripper_id]["busy"] = False


# Usage
with StarClient() as star:
    star.instrument_init()
    gripper_config = {
        "1ml_core": 2,
        "5ml_core": 1,
    }
    
    workflow = LoadBalancedGripperWorkflow(star, gripper_config)
    
    # Execute multiple transports
    transfers = [
        ("Plate1", "SourceCarrier", "DestCarrier"),
        ("Plate2", "SourceCarrier", "DestCarrier"),
        ("Plate3", "SourceCarrier", "DestCarrier"),
    ]
    
    for plate, source, dest in transfers:
        workflow.execute_transport(plate, source, dest)
```

---

## Troubleshooting and Maintenance

### Gripper Tool Not Found

**Problem:** Adding gripper fails or tool not visible afterward.

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Verify gripper was added
    star.add_1ml_core_grip()
    
    # Check inventory
    tool_ids_result = star.get_transport_tool_ids()
    tools = tool_ids_result.return_parameters.transport_tools
    print(f"Current tools: {[t.transport_tool_id for t in tools]}")

    if not tools:
        print("Gripper not added - check logs")
    else:
        print(f"Gripper added successfully: {[t.transport_tool_id for t in tools]}")
```

### Remove and Replace Gripper

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType

def replace_gripper(star, tool_id):
    """Remove old gripper and add new one."""
    try:
        # Remove old
        star.remove_transport_tool(tool_id=tool_id)
        print(f"Removed tool {tool_id}")
        
        # Add new
        star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
        print("Added new 1mL CO-RE grip")
        
        return True
    except Exception as e:
        print(f"Replacement failed: {e}")
        return False


with StarClient() as star:
    # Setup initial gripper
    star.add_1ml_core_grip()
    tools_result = star.get_transport_tool_ids()
    tools = tools_result.return_parameters.transport_tools

    if tools:
        replace_gripper(star, tools[0].transport_tool_id)
```

### Query Gripper Status

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.add_1ml_core_grip()
    star.add_5ml_core_grip()

    tool_ids_result = star.get_transport_tool_ids()
    tools = tool_ids_result.return_parameters.transport_tools
    print(f"Total grippers: {len(tools)}")

    for tool in tools:
        try:
            info = star.get_transport_tool(tool_id=tool.transport_tool_id)
            print(f"Tool {tool.transport_tool_id}: {info.return_parameters.labware_name}")
        except Exception as e:
            print(f"Could not get info for tool {tool.transport_tool_id}: {e}")
```

---

## Best Practices

### 1. Initialize Early

Add all grippers needed during deck setup:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType, QCGType

with StarClient() as star:
    # Add all grippers up front
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
    star.add_5ml_core_grip()
    star.add_qcg(qcg_type=QCGType.QCG)
    
    # Then set up carriers and plates
    # This ensures tools are available for transport operations
```

### 2. Validate Availability

Check grippers exist before using them:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    tool_ids_result = star.get_transport_tool_ids()

    if len(tool_ids_result.return_parameters.transport_tools) == 0:
        raise RuntimeError("No grippers configured")
    
    # Now safe to use for transport
```

### 3. Document Gripper Selection

Comment which gripper is used for which task:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.add_1ml_core_grip()
    
    star.add_5ml_core_grip()
    
    star.add_qcg()
```

---

## See Also

- [`transport_workflows.md`](./transport_workflows.md) — Using grippers to transport plates
- [`liquid_class_management.md`](./liquid_class_management.md) — Liquid handling parameters
- [`star-commands.md`](../../star-commands.md) — Full API reference
- [Basic examples](../) — Basic examples

