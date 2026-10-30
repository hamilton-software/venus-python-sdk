# Liquid Handling Rules and Constraints

**Audience:** This document defines fundamental operational rules and constraints for Hamilton STAR and Vantage liquid handling systems. These rules apply to both manual scripting and automated code generation.

**Purpose:** Prevent common operational errors, invalid command sequences, and volume constraint violations that lead to runtime failures, wasted reagents, or hardware errors.

---

## ⚠️ Critical Rule: State Tracking is Manual

**The Hamilton VENUS system does NOT automatically track pipetting state or validate command sequences.** The Python SDK and VENUS runtime will execute commands as issued, even if they result in errors. **You must explicitly manage tip state, liquid state, and command ordering in your scripts.**

---

## Rule 1: Tip Pickup Prerequisites

### Rule Statement
**A tip MUST be picked up before calling aspirate or dispense commands.**

### Applies To
- 1 mL channels: `aspirate()`, `dispense()`, `dispense_on_the_fly()`
- 5 mL channels: `aspirate_5ml()`, `dispense_5ml()`, `dispense_on_the_fly_5ml()`
- MagPip channels (Vantage): `aspirate_magpip()`, `dispense_magpip()`, `dispense_on_the_fly_magpip()`
- MPH96 head: `aspirate_mph96()`, `dispense_mph96()`

### Valid Sequence
```python
# ✅ CORRECT
star.tip_pickup(positions=tip_rack["A1:H1"])
star.aspirate(positions=plate["A1:H1"], volumes=50.0, liquid_class="Water")
star.dispense(positions=plate["A2:H2"], volumes=50.0)
star.tip_eject()
```

### Invalid Sequence
```python
# ❌ WRONG - No tip pickup before aspirate
star.aspirate(positions=plate["A1:H1"], volumes=50.0, liquid_class="Water")
# Runtime error: channels have no tips loaded
```

### Why This Matters
Pipetting channels and the MPH96 head are **hollow probes** that require disposable tips to create the sealed air column necessary for aspiration and dispensing. Without a tip, the command will fail or produce undefined behavior.

---

## Rule 2: Aspirate Must Precede Dispense

### Rule Statement
**You MUST aspirate liquid before calling a dispense command.**

### Constraint
The dispense command **reuses the liquid class from the most recent aspirate** for the same channel(s). You cannot dispense without a prior aspirate in the same tip lifecycle.

### Valid Sequence
```python
# ✅ CORRECT - Aspirate, then dispense
star.tip_pickup(positions=tip_rack["A1:H1"])
star.aspirate(positions=source["A1:H1"], volumes=100.0, liquid_class="Water")
star.dispense(positions=dest["A1:H1"], volumes=100.0)
star.tip_eject()
```

### Invalid Sequence
```python
# ❌ WRONG - Dispense without aspirate
star.tip_pickup(positions=tip_rack["A1:H1"])
star.dispense(positions=dest["A1:H1"], volumes=100.0)
# Runtime error: no liquid class set, no liquid in tips
```

### Multi-Step Pipetting
You can aspirate once and dispense multiple times (multi-dispense pattern):

```python
# ✅ CORRECT - One aspirate, multiple dispenses
star.tip_pickup(positions=tip_rack["A1"])
star.aspirate(positions=source["A1"], volumes=200.0, liquid_class="Water", channels=[1])
star.dispense(positions=dest["A1"], volumes=100.0, channels=[1])
star.dispense(positions=dest["A2"], volumes=100.0, channels=[1])
star.tip_eject(channels=[1])
```

But you **cannot dispense more liquid than you aspirated**:

```python
# ❌ WRONG - Dispensing more than aspirated volume
star.aspirate(positions=source["A1"], volumes=100.0, liquid_class="Water", channels=[1])
star.dispense(positions=dest["A1"], volumes=150.0, channels=[1])
# Runtime error or undefined behavior: insufficient liquid in tip
```

---

## Rule 3: Tip Eject Prerequisites

### Rule Statement
**You can only eject tips that are currently loaded on the channels/MPH96 head.**

### Invalid Sequences
```python
# ❌ WRONG - Eject without pickup
star.tip_eject()  # Runtime error: no tips loaded

# ❌ WRONG - Double eject
star.tip_pickup(positions=tip_rack["A1:H1"])
star.tip_eject()
star.tip_eject()  # Runtime error: tips already ejected
```

### Valid Pattern
```python
# ✅ CORRECT
star.tip_pickup(positions=tip_rack["A1:H1"])
# ... perform pipetting ...
star.tip_eject()
```

### Tip State Tracking
If you need to check tip state programmatically:

```python
# Query current tip status
status = star.tip_check()
print(status.tips_loaded)  # [True, True, True, True, True, True, True, True]

# Or for MPH96
status = star.get_status_mph96()
print(status.tip_loaded)  # True/False
```

---

## Rule 4: Volume Constraints (No Auto-Splitting)

### Rule Statement
**The system does NOT automatically split volumes larger than the tip capacity into multiple operations.** If you request a volume that exceeds the tip's maximum capacity, **the command will be rejected with an error.**

### Tip Capacity Reference

| Tip Type | Maximum Volume |
|----------|----------------|
| 50 µL tips | 50 µL |
| 300 µL tips | 300 µL |
| 1000 µL (1 mL) tips | 1000 µL |
| 5 mL tips | 5000 µL |

### Invalid Command
```python
# ❌ WRONG - Volume exceeds 1 mL tip capacity
star.tip_pickup(positions=tip_rack_1ml["A1"])
star.aspirate(
    positions=source["A1"],
    volumes=1500.0,  # Exceeds 1000 µL maximum!
    liquid_class="Water",
    channels=[1]
)
# Runtime error: requested volume exceeds tip capacity
```

### Manual Volume Splitting Required

If you need to transfer volumes larger than tip capacity, **you must explicitly split the operation** into multiple aspirate/dispense cycles:

```python
# ✅ CORRECT - Manually split 1500 µL transfer using 1 mL tips
total_volume = 1500.0
tip_capacity = 1000.0
cycles = math.ceil(total_volume / tip_capacity)  # 2 cycles

star.tip_pickup(positions=tip_rack_1ml["A1"], channels=[1])

for i in range(cycles):
    volume_this_cycle = min(tip_capacity, total_volume - (i * tip_capacity))
    
    star.aspirate(
        positions=source["A1"],
        volumes=volume_this_cycle,
        liquid_class="Water",
        channels=[1]
    )
    star.dispense(
        positions=dest["A1"],
        volumes=volume_this_cycle,
        channels=[1]
    )

star.tip_eject(channels=[1])
```

### Volume Best Practices

1. **Always validate volume against tip capacity before issuing commands**
2. **Use the appropriate tip type for your volume range**:
   - < 50 µL → 50 µL tips
   - 50-300 µL → 300 µL tips  
   - 300-1000 µL → 1 mL tips
   - 1000-5000 µL → 5 mL tips
3. **For large volumes, consider using larger tips** instead of splitting operations (better accuracy, fewer cycles)

---

## Rule 5: Liquid Class Must Be Specified on Aspirate

### Rule Statement
**The `liquid_class` parameter is REQUIRED on every aspirate command.** It cannot be omitted or set to `None`.

### Why This Matters
The liquid class defines:
- Aspiration/dispense speeds
- Air gaps and pre/post-dispense volumes
- Over-aspiration settings
- Flow rates and acceleration profiles

Without a liquid class, the system cannot execute the pipetting operation.

### Valid Command
```python
# ✅ CORRECT
star.aspirate(
    positions=plate["A1"],
    volumes=100.0,
    liquid_class="Water",  # Required!
    channels=[1]
)
```

### Invalid Command
```python
# ❌ WRONG
star.aspirate(
    positions=plate["A1"],
    volumes=100.0,
    # Missing liquid_class parameter!
    channels=[1]
)
# Error: liquid_class is required
```

### Dispense Inherits Liquid Class
The `dispense` command **automatically uses the liquid class from the most recent aspirate** for that channel. You do not (and cannot) specify a different liquid class on dispense.

---

## Rule 6: Channel/Probe Coordination

### Rule Statement
**Commands apply only to the specified channels or head.** You cannot mix channel types in a single command.

### Channel Types
- **1 mL channels (1-8)**: Independent channels, use `channels=[1,2,3...]`
- **5 mL channels**: Independent channels, use `channels=[1,2,3...]` with `*_5ml()` methods
- **MagPip channels (Vantage only)**: Independent channels, use `channels=[1,2,3...]` with `*_magpip()` methods
- **MPH96 head**: Single 96-probe unit, no channel selection (operates on all 96 probes or a defined pattern)

### Invalid Mixed Command
```python
# ❌ WRONG - Cannot mix 1 mL and 5 mL channels
star.tip_pickup(positions=tip_rack["A1:H1"], channels=[1, 2, 3, 4, 5, 6, 7, 8])
# There is no way to pick up 1 mL tips on some channels and 5 mL tips on others in one call
```

### Valid Separate Commands
```python
# ✅ CORRECT - Separate commands for different channel types
star.tip_pickup(positions=tip_rack_1ml["A1:D1"], channels=[1, 2, 3, 4])
star.tip_pickup_5ml(positions=tip_rack_5ml["A1:A4"], channels=[1, 2, 3, 4])
```

---

## Rule 7: Position Sequences Must Match Channel Count

### Rule Statement
**The number of positions provided must match the number of channels executing the command.**

### Valid Patterns

#### Option 1: One position per channel
```python
# ✅ CORRECT - 4 channels, 4 positions
star.tip_pickup(
    positions=tip_rack["A1:D1"],  # A1, B1, C1, D1
    channels=[1, 2, 3, 4]
)
```

#### Option 2: One position for all channels (broadcast)
```python
# ✅ CORRECT - All 8 channels use the same labware, expanded in well order
star.tip_pickup(
    positions=tip_rack,  # Uses well_order to assign A1→chan1, A2→chan2, etc.
    channels=[1, 2, 3, 4, 5, 6, 7, 8],
    well_order=WellOrder.COL_ASC
)
```

### Invalid Pattern
```python
# ❌ WRONG - 8 channels, only 4 positions
star.tip_pickup(
    positions=tip_rack["A1:D1"],  # Only 4 positions
    channels=[1, 2, 3, 4, 5, 6, 7, 8]  # 8 channels
)
# Runtime error: position count mismatch
```

---

## Rule 8: MPH96 Patterns Must Match Operation

### Rule Statement
**When using the MPH96 head with partial tip pickups, you must use a matching `mph_pattern` for subsequent aspirate/dispense operations.**

### Example: 8-channel column pattern
```python
# ✅ CORRECT - Pattern matches across all operations
from hamilton_venus.mph96_pattern import create_column_pattern

pattern = create_column_pattern(column=1)

star.tip_pick_up_mph96_partial(mode="columns", count=1, mph_pattern=pattern)
star.aspirate_mph96(
    labware_id=plate,
    volume=50.0,
    liquid_class="Water",
    mph_pattern=pattern  # Same pattern!
)
star.dispense_mph96(
    labware_id=plate2,
    volume=50.0,
    mph_pattern=pattern  # Same pattern!
)
star.tip_eject_mph96(mph_pattern=pattern)
```

### Invalid Pattern Mismatch
```python
# ❌ WRONG - Picked up column pattern, aspirating with row pattern
pattern_col = create_column_pattern(column=1)
pattern_row = create_row_pattern(row=1)

star.tip_pick_up_mph96_partial(mode="columns", count=1, mph_pattern=pattern_col)
star.aspirate_mph96(
    labware_id=plate,
    volume=50.0,
    liquid_class="Water",
    mph_pattern=pattern_row  # WRONG PATTERN!
)
# Undefined behavior: pattern mismatch
```

---

## Rule 9: Deck Layout Must Be Defined Before Use

### Rule Statement
**Labware must be added to the deck layout before it can be used in pipetting or movement commands.**

### Valid Sequence
```python
# ✅ CORRECT - Add to layout first
carrier_id = star.add_carrier("PLT_CAR_L5AC_A00", left_track=10, labware_id="carrier1")
plate = star.add_plate("Cos_96_Rd", carrier_id, site=1, labware_id="plate1")
tip_rack = star.add_tip_rack("TIP_50ul_L5", carrier_id, site=2, labware_id="tips1")

# Now we can use the labware
star.tip_pickup(positions=tip_rack["A1:H1"])
star.aspirate(positions=plate["A1:H1"], volumes=50.0, liquid_class="Water")
```

### Invalid Sequence
```python
# ❌ WRONG - Using labware before adding to deck
star.tip_pickup(positions="tips1")  # Runtime error: labware not found
```

---

## Rule 10: Tip Pools Require Initialization

### Rule Statement
**If using managed tip pools (automatic tip tracking), the tip pool must be initialized before use.**

### Valid Sequence
```python
# ✅ CORRECT - Initialize tip pool
tip_pool = star.create_tip_pool("STF 50µL tips", tip_type="50µL", labware_type="TIP_50ul_L5")
star.initialize_tip_pool(tip_pool)

# Add tip racks to the pool
star.add_tip_rack("TIP_50ul_L5", carrier_id, site=1, tip_pool=tip_pool)
star.add_tip_rack("TIP_50ul_L5", carrier_id, site=2, tip_pool=tip_pool)

# Use the pool
star.tip_pickup(tip_pool=tip_pool, channels=[1, 2, 3, 4])
```

### Invalid Sequence
```python
# ❌ WRONG - Using uninitialized tip pool
tip_pool = star.create_tip_pool("STF 50µL tips", tip_type="50µL", labware_type="TIP_50ul_L5")
star.tip_pickup(tip_pool=tip_pool)  # Error: tip pool not initialized
```

---

## Rule 11: Liquid Class Must Match Tip Type and Dispense Mode

### Rule Statement
**Liquid classes are defined for a specific combination of liquid type, tip type, and dispense mode.** You must use a liquid class that matches:
1. The **liquid type** you are pipetting (e.g., Water, DMSO, Serum, Ethanol)
2. The **tip type** loaded on the channels (e.g., 50 µL, 300 µL, 1 mL, 5 mL)
3. The **dispense mode** you intend to use (e.g., surface dispense, jet dispense, wet contact)

### Why This Matters
Liquid classes contain pipetting parameters (speeds, air gaps, over-aspiration volumes, etc.) that are **calibrated and validated** for a specific liquid-tip-mode combination. Using a mismatched liquid class will result in:
- **Inaccurate volumes** (under/over-dispensing)
- **Runtime errors** (system rejects incompatible combinations)
- **Poor liquid handling performance** (dripping, aerosols, bubbles)

### Liquid Class Naming Convention
Liquid classes typically follow a naming pattern that encodes this information:

```
<Liquid>_<TipType>_<DispenseMode>[_<Modifier>]
```

**Examples:**
- `Water_50ulTip_Surface` - Water, 50 µL tips, surface dispense
- `DMSO_1000ulTip_Jet` - DMSO, 1 mL tips, jet dispense
- `Serum_300ulTip_WetContact` - Serum, 300 µL tips, wet contact dispense
- `Ethanol_1000ulTip_DispenseSurface_Part` - Ethanol, 1 mL tips, partial volume surface dispense

### Querying Available Liquid Classes
Use the SDK to find liquid classes that match your requirements:

```python
# Get all available liquid classes for 1 mL tips
response = star.get_liquid_classes(tip_type=1)  # 1 = 1mL tips
print(response.liquid_classes)

# Get liquid class details
lc_response = star.get_liquid_class("Water_1000ulTip_DispenseSurface")
print(lc_response.definition)
```

### Valid Usage Pattern
```python
# ✅ CORRECT - Liquid class matches tip type and liquid
from hamilton_venus.catalog import LIQUID_CLASSES

# Using 1 mL (1000 µL) tips
star.tip_pickup(positions=tip_rack_1ml["A1:H1"])

# Water liquid class designed for 1000 µL tips
star.aspirate(
    positions=source["A1:H1"],
    volumes=500.0,
    liquid_class=LIQUID_CLASSES.WATER_1000UL_TIP,  # Matches 1 mL tip type
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)

star.dispense(
    positions=dest["A1:H1"],
    volumes=500.0,
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)

star.tip_eject()
```

### Invalid Usage Patterns

#### ❌ Wrong: Tip type mismatch
```python
# Using 50 µL tips
star.tip_pickup(positions=tip_rack_50ul["A1:H1"])

# But using a liquid class designed for 1000 µL tips!
star.aspirate(
    positions=source["A1:H1"],
    volumes=30.0,
    liquid_class=LIQUID_CLASSES.WATER_1000UL_TIP,  # WRONG! Should use WATER_50UL_TIP
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)
# Result: Inaccurate volumes, possible runtime error
```

#### ❌ Wrong: Liquid type mismatch
```python
# Pipetting DMSO (organic solvent)
star.tip_pickup(positions=tip_rack_1ml["A1:H1"])

# But using a liquid class designed for Water!
star.aspirate(
    positions=dmso_source["A1:H1"],
    volumes=500.0,
    liquid_class=LIQUID_CLASSES.WATER_1000UL_TIP,  # WRONG! Should use DMSO_1000UL_TIP
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)
# Result: Inaccurate volumes due to different viscosity/surface tension
```

#### ❌ Wrong: Dispense mode mismatch
```python
# Using a "Surface" dispense liquid class
star.tip_pickup(positions=tip_rack_1ml["A1:H1"])
star.aspirate(
    positions=source["A1:H1"],
    volumes=500.0,
    liquid_class="Water_1000ulTip_Surface",
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)

# But trying to override with Jet dispense settings
star.dispense(
    positions=dest["A1:H1"],
    volumes=500.0,
    settings={"dispenseMode": 2},  # Attempting Jet mode with Surface LC
    channels=[1, 2, 3, 4, 5, 6, 7, 8]
)
# Result: Unpredictable behavior, settings mismatch with liquid class expectations
```

### Best Practices

#### 1. Always verify liquid class compatibility before pipetting
```python
def validate_liquid_class(liquid_class_name, expected_tip_size):
    """Validate that liquid class name matches expected tip size."""
    tip_size_map = {
        50: "50ul",
        300: "300ul", 
        1000: "1000ul",
        5000: "5000ul"
    }
    
    expected_pattern = tip_size_map.get(expected_tip_size, "")
    if expected_pattern not in liquid_class_name.lower():
        raise ValueError(
            f"Liquid class '{liquid_class_name}' does not match "
            f"expected tip size {expected_tip_size} µL"
        )

# Usage
validate_liquid_class("Water_1000ulTip_Surface", expected_tip_size=1000)  # ✅ OK
validate_liquid_class("Water_50ulTip_Surface", expected_tip_size=1000)    # ❌ Raises error
```

#### 2. Match liquid type to your reagent
```python
# Define liquid-to-class mapping
LIQUID_CLASS_MAP = {
    "water": {
        50: "Water_50ulTip_Surface",
        300: "Water_300ulTip_Surface",
        1000: "Water_1000ulTip_DispenseSurface",
        5000: "Water_5000ulTip_Surface"
    },
    "dmso": {
        50: "DMSO_50ulTip_Surface",
        300: "DMSO_300ulTip_Surface",
        1000: "DMSO_1000ulTip_DispenseSurface",
        5000: "DMSO_5000ulTip_Surface"
    },
    "serum": {
        50: "Serum_50ulTip_Surface",
        300: "Serum_300ulTip_Surface",
        1000: "Serum_1000ulTip_DispenseSurface",
    }
}

def get_liquid_class(liquid_type, tip_size_ul):
    """Get appropriate liquid class for liquid type and tip size."""
    liquid_classes = LIQUID_CLASS_MAP.get(liquid_type.lower())
    if not liquid_classes:
        raise ValueError(f"No liquid classes defined for liquid type '{liquid_type}'")
    
    liquid_class = liquid_classes.get(tip_size_ul)
    if not liquid_class:
        raise ValueError(
            f"No liquid class for {liquid_type} with {tip_size_ul} µL tips"
        )
    
    return liquid_class

# Usage
lc = get_liquid_class("water", tip_size_ul=1000)
print(lc)  # "Water_1000ulTip_DispenseSurface"
```

#### 3. Consider creating custom liquid classes for unique liquids
If you're working with a liquid that doesn't have a pre-defined liquid class, you may need to:
1. Clone an existing liquid class with similar properties
2. Calibrate it for your specific liquid
3. Save it with a descriptive name

```python
# Example: Clone and modify for a custom buffer
base_lc = star.get_liquid_class("Water_1000ulTip_DispenseSurface")
custom_lc = base_lc.definition.copy()
custom_lc.name = "CustomBuffer_1000ulTip_DispenseSurface"
# ... modify parameters as needed ...
star.update_liquid_class(custom_lc)
```

### Tip Type Codes Reference

When querying with `get_liquid_classes(tip_type=...)`:

| Tip Size | Tip Type Code | Common Tip Names |
|----------|---------------|------------------|
| 50 µL | `0` or specific code | STF tips, 50 µL filtered/standard |
| 300 µL | `1` or specific code | 300 µL standard/filtered |
| 1000 µL (1 mL) | `2` or specific code | 1000 µL standard/filtered/wide-bore |
| 5000 µL (5 mL) | `3` or specific code | 5 mL standard/filtered |

*(Exact codes may vary by system configuration - check your instrument's liquid class database)*

### Dispense Mode Reference

Common dispense modes referenced in liquid class names:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Surface** | Tip touches liquid surface during dispense | Standard aqueous solutions, reduces splashing |
| **Jet** | Dispense from above surface | Fast dispense, empty wells, volatile liquids |
| **Wet Contact** | Tip pre-wet, then dispense at surface | Viscous liquids, serum, protein solutions |
| **Empty** | Blowout all liquid from tip | Ensure complete transfer, viscous liquids |
| **Part** | Partial volume dispense | Multi-dispense, aliquoting |

### Error Messages Related to Liquid Class Mismatch

If you see errors like:
- `"Liquid class not found"`
- `"Invalid liquid class for tip type"`
- `"Dispense mode incompatible with liquid class"`
- `"Volume settings exceed liquid class limits"`

**Solution:** Verify that:
1. The liquid class exists in your instrument's database
2. The liquid class name matches the loaded tip type
3. The liquid class is appropriate for the liquid you're pipetting
4. Your volume and settings are within the liquid class's validated range

---

## Rule 12: Plate Transport Capabilities Depend on Hardware

### Rule Statement
**Different plate transport mechanisms have different capabilities:**
- **CO-RE Gripper and QCG** (using 1 mL pipetting channels): Can move plates **within the deck only** (on-deck transports)
- **iSWAP/IPG**: Required for **off-deck transports** (e.g., to/from incubators, stackers, readers) and **plate orientation rotations** (90°/180° turns)

### Why This Matters
Attempting to use the wrong transport mechanism will result in:
- **Runtime errors** (hardware not capable of the requested operation)
- **Method failures** (command rejected by the system)
- **Invalid deck positions** (trying to move plates to locations the hardware cannot reach)

### Hardware Capabilities Summary

| Transport Hardware | On-Deck Moves | Off-Deck Moves | Rotations | Uses Channels |
|-------------------|---------------|----------------|-----------|---------------|
| **CO-RE Gripper** | ✅ Yes | ❌ No | ❌ No | Yes (1 mL channels) |
| **QCG (Quad Core Gripper)** | ✅ Yes | ❌ No | ❌ No | Yes (1 mL channels) |
| **iSWAP** | ✅ Yes | ✅ Yes | ✅ Yes | No (independent arm) |
| **IPG (Integrated Plate Gripper)** | ✅ Yes | ✅ Yes | ✅ Yes | No (independent arm) |

### CO-RE Gripper and QCG Constraints

#### What They Can Do
- Move plates **between deck positions** (carrier to carrier)
- Pick up and place plates on the deck
- Transfer plates within the autoload area

#### What They CANNOT Do
- ❌ Move plates **off the deck** (to external devices like incubators, readers, stackers)
- ❌ Rotate plate orientation (90° or 180° turns)
- ❌ Operate when **tips are loaded** on the 1 mL channels (they use the same pipetting arm)

#### Valid Usage: CO-RE Gripper (On-Deck)
```python
# ✅ CORRECT - Moving plate between two deck positions
star.core_gripper_get(
    labware_id="source_plate",
    grip_width=123.0,
    grip_height=8.0
)

star.core_gripper_place(
    labware_id="dest_carrier",
    site=1,
    grip_width=123.0
)
```

#### Invalid Usage: CO-RE Gripper (Off-Deck)
```python
# ❌ WRONG - Cannot move to off-deck device with CO-RE gripper
star.core_gripper_get(labware_id="plate_on_deck")
star.core_gripper_place(labware_id="external_incubator")  
# Runtime error: CO-RE gripper cannot reach off-deck positions
```

#### Channel Conflict
```python
# ❌ WRONG - CO-RE gripper uses 1 mL channels; tips must be empty
star.tip_pickup(positions=tip_rack["A1:H1"])  # Tips loaded on channels 1-8

star.core_gripper_get(labware_id="plate1")  
# Runtime error: Cannot use CO-RE gripper while tips are loaded
```

**Solution:** Always eject tips before using CO-RE gripper/QCG:
```python
# ✅ CORRECT
star.tip_pickup(positions=tip_rack["A1:H1"])
star.aspirate(positions=plate["A1:H1"], volumes=50.0, liquid_class="Water")
star.dispense(positions=plate2["A1:H1"], volumes=50.0)
star.tip_eject()  # Eject tips first!

# Now safe to use CO-RE gripper
star.core_gripper_get(labware_id="plate1")
star.core_gripper_place(labware_id="carrier2", site=1)
```

### iSWAP and IPG Capabilities

#### What They Can Do
- ✅ Move plates **on-deck** (carrier to carrier)
- ✅ Move plates **off-deck** (to/from external devices)
- ✅ **Rotate plate orientation** (90°, 180°, 270°)
- ✅ Operate **independently** (do not interfere with pipetting channels)

#### Valid Usage: iSWAP (Off-Deck Transport)
```python
# ✅ CORRECT - iSWAP can move to off-deck locations
star.iswap_get(
    labware_id="plate_on_deck",
    grip_mode="plate",
    open_position=85.0
)

star.iswap_place(
    labware_id="external_reader_nest",  # Off-deck device
    grip_mode="plate"
)
```

#### Valid Usage: iSWAP (Plate Rotation)
```python
# ✅ CORRECT - iSWAP can rotate plates
star.iswap_get(labware_id="plate1", grip_mode="plate")

# Rotate 180° before placing
star.iswap_place(
    labware_id="carrier2",
    site=1,
    grip_mode="plate",
    rotation=180  # Rotate the plate 180°
)
```

#### Concurrent Operation
```python
# ✅ CORRECT - iSWAP operates independently of pipetting channels
# Can use iSWAP while tips are loaded (unlike CO-RE gripper)
star.tip_pickup(positions=tip_rack["A1:H1"])  # Tips loaded

# iSWAP can still operate
star.iswap_get(labware_id="plate1", grip_mode="plate")
star.iswap_place(labware_id="carrier2", site=1)

# Continue pipetting
star.aspirate(positions=plate2["A1:H1"], volumes=50.0, liquid_class="Water")
```

### Choosing the Right Transport Method

#### Decision Tree

```
Do you need to move a plate off-deck OR rotate it?
├─ YES → Use iSWAP or IPG (if available)
└─ NO → On-deck only?
    ├─ Do you have iSWAP/IPG available?
    │   ├─ YES → Prefer iSWAP/IPG (no channel conflict, more flexibility)
    │   └─ NO → Use CO-RE Gripper or QCG
    └─ Are tips currently loaded on 1 mL channels?
        ├─ YES → Must use iSWAP/IPG OR eject tips first
        └─ NO → Can use CO-RE Gripper or QCG
```

#### Best Practice: Check Available Hardware
```python
# Query instrument configuration to determine available hardware
config = star.instrument_get_configuration()

# Check for transport options
has_iswap = "iSWAP" in str(config)  # Check config for iSWAP
has_core_gripper = "CO-RE Gripper" in str(config)

if requires_off_deck_transport or requires_rotation:
    if not has_iswap:
        raise RuntimeError(
            "Off-deck transport or rotation requested but iSWAP/IPG not available"
        )
    # Use iSWAP
else:
    # On-deck only - prefer iSWAP if available, otherwise CO-RE gripper
    if has_iswap:
        # Use iSWAP (no tip conflicts)
        pass
    elif has_core_gripper:
        # Ensure tips are ejected first
        pass
    else:
        raise RuntimeError("No plate transport hardware available")
```

### Common Patterns

#### Pattern 1: Off-Deck Incubation (Requires iSWAP/IPG)
```python
# ✅ Move plate to off-deck incubator
star.iswap_get(labware_id="assay_plate", grip_mode="plate")
star.iswap_place(labware_id="incubator_nest_1", grip_mode="plate")

# ... wait for incubation ...
time.sleep(300)  # 5 min incubation

# Retrieve from incubator
star.iswap_get(labware_id="incubator_nest_1", grip_mode="plate")
star.iswap_place(labware_id="deck_carrier", site=1, grip_mode="plate")
```

#### Pattern 2: On-Deck Reorganization (Can Use CO-RE Gripper)
```python
# ✅ Move plates around on deck with CO-RE gripper
# Make sure no tips are loaded
star.tip_eject()  # Just in case

# Reorganize deck
star.core_gripper_get(labware_id="plate1", grip_width=123.0)
star.core_gripper_place(labware_id="carrier3", site=1, grip_width=123.0)

star.core_gripper_get(labware_id="plate2", grip_width=123.0)
star.core_gripper_place(labware_id="carrier1", site=1, grip_width=123.0)
```

#### Pattern 3: Plate Rotation for Barcode Reading (Requires iSWAP/IPG)
```python
# ✅ Rotate plate so barcode faces the reader
star.iswap_get(labware_id="plate1", grip_mode="plate")

# Rotate 90° to orient barcode toward reader
star.iswap_place(
    labware_id="carrier_with_reader",
    site=1,
    grip_mode="plate",
    rotation=90
)
```

### Hardware-Specific Command References

#### CO-RE Gripper Commands (STAR)
- `core_gripper_get()` - Pick up plate/carrier
- `core_gripper_place()` - Place plate/carrier
- See [Transport Guide](../examples/transport.md) for full details

#### QCG Commands (STAR)
- `qcg_get()` - Pick up plate/carrier
- `qcg_place()` - Place plate/carrier

#### iSWAP Commands (STAR & Vantage)
- `iswap_get()` - Pick up plate/carrier
- `iswap_place()` - Place plate/carrier
- `iswap_park()` - Park the iSWAP arm
- Supports `rotation` parameter for plate orientation changes

#### IPG Commands (Vantage)
- Similar to iSWAP commands
- Integrated into Vantage instrument design

### Error Messages Related to Transport

| Error Message | Likely Cause | Solution |
|--------------|--------------|----------|
| "CO-RE gripper cannot reach position" | Attempting off-deck move with CO-RE gripper | Use iSWAP/IPG instead |
| "Transport hardware conflict" | Tips loaded while trying to use CO-RE gripper/QCG | Eject tips first |
| "Rotation not supported" | Attempting rotation with CO-RE gripper/QCG | Use iSWAP/IPG instead |
| "iSWAP not available" | Calling iSWAP commands without iSWAP hardware | Check hardware config; use available transport |
| "Invalid labware position" | Target position not accessible to the transport hardware | Verify labware is on-deck for CO-RE gripper, or off-deck device is configured for iSWAP |

---

## Common Error Patterns and Solutions

### Error: "No tips loaded"
**Cause:** Attempted to aspirate/dispense without picking up tips first.

**Solution:** Add `tip_pickup()` before the pipetting command.

### Error: "No liquid class set" or "Cannot dispense"
**Cause:** Attempted to dispense without aspirating first.

**Solution:** Ensure `aspirate()` is called before `dispense()`.

### Error: "Volume exceeds tip capacity"
**Cause:** Requested volume is larger than the tip's maximum capacity.

**Solution:** Either use larger tips or manually split the transfer into multiple cycles (see Rule 4).

### Error: "Position count mismatch"
**Cause:** Number of positions doesn't match the number of active channels.

**Solution:** Provide one position per channel, or one position for all channels to broadcast (see Rule 7).

### Error: "Tips already loaded"
**Cause:** Attempted to pick up tips when channels already have tips loaded.

**Solution:** Eject current tips with `tip_eject()` before picking up new ones, or check tip state with `tip_check()`.

### Error: "Labware not found"
**Cause:** Referenced a labware ID that hasn't been added to the deck layout.

**Solution:** Use `add_carrier()`, `add_plate()`, `add_tip_rack()`, etc. to add labware before referencing it.

### Error: "Liquid class not found" or "Invalid liquid class for tip type"
**Cause:** The specified liquid class doesn't exist or doesn't match the loaded tip type.

**Solution:** 
- Verify the liquid class name is correct and exists in the instrument database
- Check that the liquid class is designed for the tip type you're using (e.g., use `Water_1000ulTip` with 1 mL tips, not 50 µL tips)
- Query available liquid classes: `star.get_liquid_classes(tip_type=...)`

### Error: Inaccurate pipetting volumes (over/under-dispensing)
**Cause:** Using a liquid class that doesn't match the actual liquid properties (viscosity, surface tension, volatility).

**Solution:** Use a liquid class specifically calibrated for your liquid type (e.g., use DMSO liquid classes for DMSO, not Water liquid classes).

### Error: "CO-RE gripper cannot reach position" or "Transport hardware conflict"
**Cause:** Attempting to use CO-RE Gripper/QCG for off-deck transport, or trying to use it while tips are loaded.

**Solution:**
- For off-deck moves or rotations: Use iSWAP/IPG instead
- For on-deck moves with loaded tips: Either use iSWAP/IPG, or eject tips first with `tip_eject()`

### Error: "Rotation not supported" or "iSWAP not available"
**Cause:** Attempting plate rotation with CO-RE Gripper, or calling iSWAP commands when hardware is not installed.

**Solution:**
- Check instrument configuration to verify available transport hardware
- Use iSWAP/IPG for plate rotations
- Redesign method if required hardware is not available

---

## Best Practices for Robust Scripts

1. **Always check tip state before pickup** if your script may run multiple times or has complex branching:
   ```python
   status = star.tip_check()
   if not status.tips_loaded[0]:  # Channel 1
       star.tip_pickup(positions=tip_rack["A1"], channels=[1])
   ```

2. **Validate volumes against tip capacity** before issuing commands:
   ```python
   def validate_volume(volume, tip_type):
       capacities = {"50µL": 50, "300µL": 300, "1mL": 1000, "5mL": 5000}
       if volume > capacities[tip_type]:
           raise ValueError(f"Volume {volume}µL exceeds {tip_type} capacity")
   ```

3. **Use try-finally for tip cleanup** to avoid orphaned tips on errors:
   ```python
   star.tip_pickup(positions=tip_rack["A1:H1"])
   try:
       star.aspirate(positions=source["A1:H1"], volumes=50.0, liquid_class="Water")
       star.dispense(positions=dest["A1:H1"], volumes=50.0)
   finally:
       star.tip_eject()  # Always eject, even if pipetting fails
   ```

4. **Document your liquid handling sequences** with comments explaining the state at each step:
   ```python
   # State: channels empty, no tips
   star.tip_pickup(positions=tip_rack["A1:H1"])
   # State: tips loaded on channels 1-8
   
   star.aspirate(positions=source["A1:H1"], volumes=100.0, liquid_class="Water")
   # State: channels have 100µL of water
   
   star.dispense(positions=dest["A1:H1"], volumes=100.0)
   # State: channels empty, tips still loaded
   
   star.tip_eject()
   # State: channels empty, no tips
   ```

5. **For generated code, always validate the command sequence** before execution to catch state errors early.

---

## For LLM Code Generators

If you are an LLM generating Hamilton liquid handling scripts, **always**:

1. ✅ Validate that every `aspirate`/`dispense` is preceded by `tip_pickup` in the same tip lifecycle
2. ✅ Validate that every `dispense` is preceded by `aspirate` with sufficient volume
3. ✅ Check that requested volumes do not exceed tip capacity
4. ✅ Ensure `tip_eject` is only called when tips are loaded
5. ✅ Verify labware is added to the deck before being referenced
6. ✅ Confirm that `liquid_class` is specified on every aspirate
7. ✅ Verify the liquid class matches the tip type being used (e.g., don't use `Water_1000ulTip` with 50 µL tips)
8. ✅ Ensure the liquid class is appropriate for the liquid being pipetted (e.g., don't use `Water` LC for DMSO)
9. ✅ Match position count to channel count
10. ✅ Use consistent MPH96 patterns across pickup, aspirate, dispense, and eject
11. ✅ Choose the correct transport hardware:
    - Use iSWAP/IPG for off-deck moves or plate rotations
    - CO-RE Gripper/QCG only for on-deck moves, and only when tips are NOT loaded
12. ✅ Eject tips before using CO-RE Gripper or QCG (they share the 1 mL pipetting arm)

**When in doubt, explicitly comment your assumptions about system state in the generated code.**

---

## Summary Table

| Rule | Constraint | Violation Consequence |
|------|-----------|----------------------|
| 1 | Tip pickup before aspirate/dispense | Runtime error: no tips loaded |
| 2 | Aspirate before dispense | Runtime error: no liquid class set |
| 3 | Only eject loaded tips | Runtime error: no tips to eject |
| 4 | Volume ≤ tip capacity | Runtime error: volume exceeds capacity |
| 5 | Liquid class required on aspirate | Runtime error: missing required parameter |
| 6 | No mixing channel types in one command | Runtime error: invalid channel configuration |
| 7 | Position count = channel count | Runtime error: position mismatch |
| 8 | Consistent MPH96 patterns | Undefined behavior or wrong wells accessed |
| 9 | Add labware to deck before use | Runtime error: labware not found |
| 10 | Initialize tip pools before use | Runtime error: tip pool not found |
| 11 | Liquid class must match tip type, liquid, and mode | Inaccurate volumes, runtime error, poor performance |
| 12 | Use appropriate transport for operation | Runtime error: hardware cannot perform operation |

---

## Document Version

- **Version:** 1.1
- **Last Updated:** 2026-09-29
- **Applies To:** Hamilton STAR and Vantage systems via Python SDK
- **Changelog:**
  - v1.1: Added Rule 12 (Plate Transport Capabilities)
  - v1.0: Initial release with Rules 1-11
