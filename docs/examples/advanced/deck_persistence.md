# Deck Persistence and Layout Management

Comprehensive guide for saving and loading deck layouts for complex instrument configurations.

## Overview

Deck persistence allows you to save complex deck configurations and reload them later. This guide covers:
- Saving deck layouts
- Loading previously saved layouts
- Loading the last-used layout
- Overwriting existing saves
- Layout versioning strategies
- Error handling and recovery

---

## Fundamental Concepts

### Deck Layout Files

The instrument stores deck layout configurations that include:
- Carrier definitions and positions
- Labware placements
- Tip rack configurations
- Gripper tool assignments

### Workflow Benefits

```
Complex Setup → Save to File → Reuse Later → Consistent Results
```

---

## Basic Operations

### Save a Deck Layout

Save current deck configuration:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient() as star:
    # Set up complex layout
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=1,
        labware_id="PlateCarrier1",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="SourcePlate",
    )
    
    # Save for later use
    star.deck_save(deck_name="MyDeckLayout")
    print("Deck layout saved as 'MyDeckLayout'")
```

### Load a Saved Deck Layout

Reload a previously saved configuration by passing `deck_name` to the constructor — the deck is loaded automatically during `start()`, before auto-connect fires:

```python
from hamilton_venus import StarClient

with StarClient(deck_name="MyDeckLayout") as star:
     carriers = star.get_added_carriers()
     print(f"Loaded carriers: {carriers}")
```

If you need to choose the deck at runtime, load it explicitly instead:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.deck_load(deck_name="MyDeckLayout")
    print("Deck layout 'MyDeckLayout' loaded")

    carriers = star.get_added_carriers()
    print(f"Loaded carriers: {carriers}")
```

### Load the Last-Used Deck

Load the instrument's previous configuration:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Load the previously used deck
    star.deck_load(deck_name="LastDeck", previous=True)
    print("Last-used deck layout loaded")
```

### Save with Overwrite

Replace an existing saved layout:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Modified layout
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
        left_track=10,
        labware_id="TipCarrier2",
    )
    
    # Save, overwriting previous version
    star.deck_save(deck_name="MyDeckLayout", overwrite=True)
    print("Deck layout updated (overwritten)")
```

---

## Production Workflow: Template-Based Layouts

### Save and Reuse Deck Templates

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeckTemplate:
    """Manage reusable deck layout templates."""
    
    def __init__(self, star):
        self.star = star
        self.templates = {}
    
    def create_template(self, template_name, setup_func):
        """
        Create a new deck template by executing setup function.
        
        Args:
            template_name: Name for this template
            setup_func: Function that configures the deck
        """
        try:
            logger.info(f"Creating template '{template_name}'...")
            
            # Execute setup function
            setup_func(self.star)
            
            # Save as template
            self.star.deck_save(deck_name=template_name, overwrite=True)
            self.templates[template_name] = True
            
            logger.info(f"Template '{template_name}' created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create template '{template_name}': {e}")
            return False
    
    def load_template(self, template_name):
        """Load a previously saved template."""
        try:
            logger.info(f"Loading template '{template_name}'...")
            self.star.deck_load(deck_name=template_name)
            logger.info(f"Template '{template_name}' loaded")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load template '{template_name}': {e}")
            return False
    
    def list_available_templates(self):
        """List all saved deck layouts."""
        try:
            saved = self.star.deck_get_saved()
            names = saved.return_parameters.saved_decks
            logger.info(f"Available saved decks: {names}")
            return names
        except Exception as e:
            logger.error(f"Failed to list saved decks: {e}")
            return []


# Template definitions
def setup_liquid_transfer_deck(star):
    """Standard deck for liquid transfer workflows."""
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.TIP_CAR_480BC,
        left_track=1,
        labware_id="TipCarrier1",
    )
    star.add_tip_rack(
        labware_definition="Tips_1000uL",
        carrier_id="TipCarrier1",
        site="1",
        tip_pool="TransferTips",
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=10,
        labware_id="PlateCarrier1",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="PlateCarrier1",
        site="1",
        plate_id="SourcePlate",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="PlateCarrier1",
        site="2",
        plate_id="DestPlate",
    )


def setup_mph96_deck(star):
    """Deck for 96-channel head operations."""
    star.add_carrier(
        labware_definition="TIP_CAR_960BC_A00",
        left_track=1,
        labware_id="TipCarrier96",
    )
    star.add_tip_rack(
        tip_pool="Tips96",
        labware_definition="Tips96_1000uL",
        carrier_id="TipCarrier96",
        site="1",
    )
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=10,
        labware_id="PlateCarrier96",
    )
    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="PlateCarrier96",
        site="1",
        plate_id="SourcePlate",
    )


# Usage
with StarClient() as star:
    manager = DeckTemplate(star)
    
    # Create templates
    manager.create_template("LiquidTransfer", setup_liquid_transfer_deck)
    manager.create_template("MPH96Ops", setup_mph96_deck)
    
    # List available
    templates = manager.list_available_templates()
    print(f"Available templates: {templates}")
    
    # Load and use
    manager.load_template("LiquidTransfer")
    # Now ready to execute liquid transfer workflow
```

---

## Advanced: Layout Versioning

### Track Layout Versions with Timestamps

```python
import logging
from datetime import datetime
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class VersionedDeckLayout:
    """Manage versioned deck layouts."""
    
    def __init__(self, star):
        self.star = star
        self.layout_name = None
    
    def save_versioned(self, base_name):
        """
        Save layout with version timestamp.
        
        Args:
            base_name: Base name for this layout
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_name = f"{base_name}_{timestamp}"
        
        try:
            self.star.deck_save(deck_name=versioned_name, overwrite=False)
            self.layout_name = versioned_name
            logger.info(f"Saved versioned layout: {versioned_name}")
            return versioned_name
        except Exception as e:
            logger.error(f"Failed to save versioned layout: {e}")
            return None
    
    def get_layout_history(self, base_name):
        """
        Get all versions of a layout.
        
        Returns:
            List of version names for this base layout
        """
        try:
            saved = self.star.deck_get_saved()
            versions = [name for name in saved.return_parameters.saved_decks if name.startswith(base_name)]
            versions.sort()
            return versions
        except Exception as e:
            logger.error(f"Failed to get layout history: {e}")
            return []
    
    def restore_previous_version(self, base_name):
        """Restore the most recent previous version."""
        versions = self.get_layout_history(base_name)
        
        if len(versions) < 2:
            logger.warning("No previous version available")
            return False
        
        # Get second-to-last version (most recent previous)
        previous_version = versions[-2]
        
        try:
            self.star.deck_load(deck_name=previous_version)
            logger.info(f"Restored previous version: {previous_version}")
            return True
        except Exception as e:
            logger.error(f"Failed to restore version: {e}")
            return False


# Usage
with StarClient() as star:
    manager = VersionedDeckLayout(star)
    
    # Make changes and save versioned
    v1 = manager.save_versioned("ProductionLayout")
    print(f"Saved: {v1}")
    
    # Make more changes
    star.add_reservoir(
        labware_definition="RES_CAR_8x100ml",
        carrier_id="PlateCarrier1",
        site="1",
        labware_id="Reservoir1",
    )
    v2 = manager.save_versioned("ProductionLayout")
    print(f"Saved: {v2}")
    
    # View history
    history = manager.get_layout_history("ProductionLayout")
    print(f"Layout versions: {history}")
    
    # Revert if needed
    manager.restore_previous_version("ProductionLayout")
```

---

## Workflow: Load, Verify, and Validate

### Comprehensive Layout Verification

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class DeckLayoutValidator:
    """Validate loaded deck layout meets requirements."""
    
    def __init__(self, star):
        self.star = star
    
    def validate_layout(self, requirements):
        """
        Verify loaded layout has required components.
        
        Args:
            requirements: Dict with required components
                - min_carriers: Minimum number of carriers
                - required_plates: List of required plate IDs
                - required_tip_pools: List of required tip pools
        
        Returns:
            dict: Validation results
        """
        results = {
            "valid": True,
            "carriers": 0,
            "plates": [],
            "tips": [],
            "warnings": [],
            "errors": []
        }
        
        try:
            # Check carriers
            carriers = self.star.get_added_carriers()
            plates = self.star.get_added_plates()
            tip_racks = self.star.get_added_tip_racks()
            results["tips"] = tip_racks
            
            return results
            
        except Exception as e:
            results["valid"] = False
            results["errors"].append(f"Validation error: {e}")
            return results
    
    def load_and_validate(self, deck_name, requirements):
        """Load deck and validate in one operation."""
        try:
            logger.info(f"Loading deck '{deck_name}'...")
            self.star.deck_load(deck_name=deck_name)
            
            logger.info("Validating layout...")
            results = self.validate_layout(requirements)
            
            if results["valid"]:
                logger.info("Layout validation passed ✓")
            else:
                logger.error("Layout validation failed ✗")
                for error in results["errors"]:
                    logger.error(f"  - {error}")
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to load and validate: {e}")
            return {"valid": False, "errors": [str(e)]}


# Usage
with StarClient() as star:
    validator = DeckLayoutValidator(star)
    
    requirements = {
        "min_carriers": 2,
        "required_plates": ["SourcePlate", "DestPlate"],
        "required_tip_pools": ["TransferTips"],
    }
    
    results = validator.load_and_validate("MyDeckLayout", requirements)
    
    if results["valid"]:
        print(f"Deck ready: {results['carriers']} carriers, "
              f"{len(results['plates'])} plates")
    else:
        print("Deck validation failed - check configuration")
```

---

## Workflow: Previous vs. New Layout Modes

### Toggle Between Layouts

```python
from hamilton_venus import StarClient

def switch_to_previous_deck(star):
    """Switch to the previously used deck layout."""
    try:
        star.deck_load(deck_name="PreviousDeck", previous=True)
        print("Switched to previous deck layout")
        return True
    except Exception as e:
        print(f"Failed to load previous deck: {e}")
        return False


def create_new_deck(star):
    """Create and save a new deck layout."""
    try:
        # Configure new layout
        star.add_carrier(
            labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
            left_track=1,
            labware_id="NewCarrier",
        )
        
        # Save as new named layout
        star.deck_save(deck_name="NewLayout")
        print("New deck layout created and saved")
        return True
    except Exception as e:
        print(f"Failed to create new deck: {e}")
        return False


# Usage
with StarClient() as star:
    # Create and save new layout
    create_new_deck(star)
    
    # Later, switch back to previous
    switch_to_previous_deck(star)
```

---

## Best Practices

### 1. Save After Complex Setups

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Complex setup
    star.add_carrier(...)
    star.add_tip_rack(...)
    star.add_plate(...)
    star.add_1ml_core_grip()
    
    # Save immediately for reuse
    star.deck_save(deck_name="ComplexSetup")
```

### 2. Use Meaningful Names

```python
# Good names - descriptive and timestamp for tracking
"LiquidTransfer_Production_20240115"
"MPH96_HighThroughput_20240115"
"Experiment_Protocol_Rev3_20240115"

# Poor names - too vague
"Deck1"
"Setup"
"Test"
```

### 3. Document Layout Configuration

```python
# Add comments about what each layout contains
# LiquidTransfer_Production:
#   - 1 Tip carrier with 1000µL tips
#   - 2 Plate carriers with source and destination 96-well plates
#   - 1mL CO-RE gripper for transport
#
# MPH96_HighThroughput:
#   - 1 96-channel tip carrier with 1000µL tips
#   - 1 Plate carrier with 96-well plates
#   - 5mL CO-RE gripper for large plate handling
```

### 4. Validate After Loading

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Load layout
    star.deck_load(deck_name="MyLayout")
    
    # Verify it has what we expect
    carriers = star.get_added_carriers()
    plates = star.get_added_plates()
    
    assert len(carriers) > 0, "No carriers in layout"
    assert len(plates) > 0, "No plates in layout"
```

---

## Common Issues and Solutions

### Layout Not Found

**Problem:** `deck_load()` fails with "layout not found".

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    # List available layouts
    saved = star.deck_get_saved()
    layout_names = saved.return_parameters.saved_decks
    print(f"Available layouts: {layout_names}")

    # Then load with correct name
    if "MyLayout" in layout_names:
        star.deck_load(deck_name="MyLayout")
    else:
        print(f"'MyLayout' not found. Available: {layout_names}")
```

### Cannot Overwrite Without Permission

**Problem:** `deck_save()` with `overwrite=False` fails because name exists.

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Option 1: Use overwrite flag
    star.deck_save(deck_name="MyLayout", overwrite=True)
    
    # Option 2: Use versioned naming
    from datetime import datetime
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    star.deck_save(deck_name=f"MyLayout_{version}")
```

### Deck State Mismatch

**Problem:** Loaded deck has different state than expected.

**Solution:**
```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Get previous (pre-load) state
    previous = star.deck_get_previous()
    print(f"Previous deck available: {previous.return_parameters.deck_available}")

    # Get current saved state
    saved = star.deck_get_saved()
    print(f"Saved decks: {saved.return_parameters.saved_decks}")

    # Load specific saved deck
    star.deck_load(deck_name="KnownGoodLayout")

    # Verify
    print(f"Current carriers: {star.get_added_carriers()}")
```

---

## See Also

- [`gripper_operations.md`](./gripper_operations.md) — Setting up grippers in layouts
- [`transport_workflows.md`](./transport_workflows.md) — Using saved layouts for transport
- [`star-commands.md`](../../star-commands.md) — Full API reference
- [Basic examples](../) — Basic examples

