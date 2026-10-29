# Status and Diagnostics Commands

Comprehensive guide for front cover, status light, and pipetting arm commands for safety checks, user feedback, and diagnostics.

---

## Overview

This guide covers system status and diagnostic commands:
- Front cover lock/unlock and state checking
- Status light patterns for user feedback and progress indication
- Pipetting arm positioning and diagnostics
- Combined diagnostic workflows before main execution

---

## Front Cover Control and Safety

### Check if Front Cover is Closed

```python
from hamilton_venus import StarClient

with StarClient() as star:
    result = star.front_cover_is_closed()
    if result.return_parameters.is_closed:
        print("Front cover is closed - safe to proceed")
    else:
        print("Front cover is open - wait for operator")
```

### Lock the Front Cover

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.front_cover_lock()
    print("Front cover locked")
```

### Unlock the Front Cover

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.front_cover_unlock()
    print("Front cover unlocked")
```

---

## Status Light: Visual Feedback and Progress

`status_light_set_front_light()` is the single status-light command: it sets color, blink, and a discrete progress level (0-5, each step = 20%) in one call. Pass `progress=0` (the default) when you only care about color.

### Set Status Light Color

Use the status light to provide visual feedback to operators:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import LightColor

with StarClient() as star:
    star.instrument_init()

    # Red for error/warning
    star.status_light_set_front_light(color=LightColor.RED)
    print("Status light: RED (error/warning)")

    # Green for ready/success
    star.status_light_set_front_light(color=LightColor.GREEN)
    print("Status light: GREEN (ready/success)")

    # Blue for running
    star.status_light_set_front_light(color=LightColor.BLUE)
    print("Status light: BLUE (running)")

    # Off (set to white at zero intensity)
    star.status_light_set_front_light(color=LightColor.WHITE)
    print("Status light: WHITE (off/default)")
```

### Status Light with Blinking

Add blinking to draw attention:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import LightColor

with StarClient() as star:
    star.instrument_init()

    # Red blinking for critical alerts
    star.status_light_set_front_light(color=LightColor.RED, blink=True)
    print("Status light: RED blinking (critical alert)")

    # Normal (no blink)
    star.status_light_set_front_light(color=LightColor.GREEN, blink=False)
    print("Status light: GREEN (steady)")
```

### Progress Indication

Show progress as a discrete level from 0 (off) to 5 (100%), each step representing 20%:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import LightColor
import time

with StarClient() as star:
    star.instrument_init()

    # Simulate long-running workflow with progress feedback
    max_level = 5
    for level in range(1, max_level + 1):
        # Do work...
        time.sleep(0.5)

        # Update progress
        star.status_light_set_front_light(color=LightColor.BLUE, progress=level)
        print(f"Progress: {level * 20}%")

    print("Workflow complete!")
```

### Combined Progress and Color Feedback

Combine color and progress for comprehensive feedback:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import LightColor
import time

with StarClient() as star:
    star.instrument_init()

    try:
        # Starting
        star.status_light_set_front_light(color=LightColor.BLUE, progress=0)

        # Processing
        for level in range(1, 4):
            time.sleep(0.3)
            star.status_light_set_front_light(color=LightColor.BLUE, progress=level)

        # Finishing
        for level in range(4, 6):
            time.sleep(0.3)
            star.status_light_set_front_light(color=LightColor.GREEN, progress=level)

        print("Workflow complete")

    except Exception as e:
        star.status_light_set_front_light(color=LightColor.RED, blink=True)
        print(f"Error: {e}")
        raise
```

---

## Pipetting Arm Positioning and Diagnostics

### Get Current Pipetting Arm X Position

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Left arm
    x_pos = star.pip_arm_get_x_position(arm_id=1)
    print(f"Left arm X position: {x_pos.x}")

    # Right arm
    x_pos = star.pip_arm_get_x_position(arm_id=2)
    print(f"Right arm X position: {x_pos.x}")
```

### Park Pipetting Arm

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # Park left arm
    star.pip_arm_park_left(arm_id=1)
    print("Left arm parked left")

    # Park right arm  
    star.pip_arm_park_right(arm_id=2)
    print("Right arm parked right")
```

### Move Pipetting Arm to Specific Position

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoordinateMode, PipArmSpeed

with StarClient() as star:
    star.instrument_init()

    # Absolute move to X position
    star.pip_arm_move(
        value=500.0,
        coordinate_mode=CoordinateMode.ABSOLUTE,
        arm_id=1,
        speed=PipArmSpeed.STANDARD,
    )
    print("Arm moved to absolute position 500.0")

    # Relative move (10 units from current)
    star.pip_arm_move(
        value=10.0,
        coordinate_mode=CoordinateMode.RELATIVE,
        arm_id=1,
        speed=PipArmSpeed.FAST,
    )
    print("Arm moved +10.0 units relative")
```

---

## Combined Diagnostic Workflow

Execute comprehensive pre-flight checks with all diagnostic commands:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import LightColor

def complete_diagnostic_workflow():
    """
    Comprehensive pre-flight diagnostic workflow.
    Checks front cover, pipetting arm, and all configuration.
    Returns True if all checks pass.
    """
    with StarClient() as star:
        print("=== Starting Complete Diagnostic ===\n")

        try:
            # Status light: starting (blue). status_light_set_front_light()'s progress
            # is a discrete 0-5 level (each step = 20%), not a continuous percentage --
            # the 10 checks below advance it by one level every 2 checks.
            star.status_light_set_front_light(color=LightColor.BLUE, progress=0)

            # Check 1: Front Cover
            print("1. Checking front cover...")
            front_cover = star.front_cover_is_closed()
            if not front_cover.return_parameters.is_closed:
                print("  ✗ Front cover is open!")
                star.status_light_set_front_light(color=LightColor.RED, blink=True)
                return False
            print("  ✓ Front cover closed")

            # Check 2: Pipetting Arm (level 1 - 20%)
            print("2. Checking pipetting arm...")
            arm_pos = star.pip_arm_get_x_position(arm_id=1)
            print(f"  ✓ Left arm X position: {arm_pos.return_parameters.get('xPosition', 'N/A')}")
            star.status_light_set_front_light(color=LightColor.BLUE, progress=1)

            # Check 3: Configuration
            print("3. Querying instrument configuration...")
            config = star.instrument_get_configuration()
            print(f"  ✓ Tracks: {config.return_parameters.tracks}")
            print(f"  ✓ Max autoload track: {config.return_parameters.max_autoload_track}")
            if config.return_parameters.left_arm:
                print(f"  ✓ Left arm 1mL channels: {config.return_parameters.left_arm.channels_1_ml}")

            # Check 4: Serial Number (level 2 - 40%)
            print("4. Retrieving serial number...")
            serial = star.instrument_get_serial_number()
            print(f"  ✓ Serial: {serial.return_parameters.serial_number}")
            star.status_light_set_front_light(color=LightColor.BLUE, progress=2)

            # Check 5: Deck Tracks
            print("5. Checking deck tracks...")
            tracks = star.instrument_get_deck_tracks()
            print(f"  ✓ Total tracks: {tracks.return_parameters.total_tracks}")
            print(f"  ✓ Autoloadable tracks: {tracks.return_parameters.autoloadable_tracks}")

            # Check 6: Deck Dimensions (level 3 - 60%)
            print("6. Checking deck dimensions...")
            dims = star.instrument_get_deck_dimensions()
            print(f"  ✓ X: {dims.return_parameters.x}, Y: {dims.return_parameters.y}")
            star.status_light_set_front_light(color=LightColor.BLUE, progress=3)

            # Check 7: Waste Locations
            print("7. Checking waste locations...")
            waste = star.instrument_get_waste_locations()
            print(f"  ✓ Waste locations configured: {len(waste.return_parameters.waste_locations)}")

            # Check 8: Daily Maintenance (level 4 - 80%)
            print("8. Checking daily maintenance...")
            daily = star.instrument_get_daily_maintenance_data()
            print(f"  ✓ Status: {daily.return_parameters.status}")
            print(f"  ✓ Expiration: {daily.return_parameters.expiration_date}")
            star.status_light_set_front_light(color=LightColor.BLUE, progress=4)

            # Check 9: Weekly Maintenance
            print("9. Checking weekly maintenance...")
            weekly = star.instrument_get_weekly_maintenance_data()
            print(f"  ✓ Status: {weekly.return_parameters.status}")

            # Check 10: Verification Data (level 5 - 100%)
            print("10. Checking verification data...")
            verify = star.instrument_get_verification_data()
            print(f"  ✓ Status: {verify.return_parameters.status}")
            star.status_light_set_front_light(color=LightColor.BLUE, progress=5)

            # All checks passed
            print("\n=== All Diagnostics Passed ===")
            star.status_light_set_front_light(color=LightColor.GREEN, progress=5)
            return True

        except Exception as e:
            print(f"\n✗ Diagnostic failed: {e}")
            star.status_light_set_front_light(color=LightColor.RED, blink=True)
            return False

# Run the diagnostic
if complete_diagnostic_workflow():
    print("Ready to proceed with main workflow!")
else:
    print("Address diagnostic failures before proceeding.")
```

---

## Troubleshooting with Diagnostics

Use diagnostics to troubleshoot specific issues:

```python
from hamilton_venus import StarClient

def troubleshoot_connection_issue():
    """Diagnose connection and state issues."""
    star = StarClient(auto_connect=False)

    try:
        star.start()

        # Check 1: Can we connect?
        try:
            result = star.instrument_connect(initialize=False)
            print(f"✓ Connected: {result.return_parameters.instrument_name}")
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return

        # Check 2: Are we idle?
        idle = star.instrument_is_idle()
        print(f"Idle: {idle}")
        if not idle:
            print("  Warning: Instrument not idle. A previous run may still be executing.")

        # Check 3: Safety checks
        front = star.front_cover_is_closed()
        print(f"Front cover closed: {front.return_parameters.is_closed}")
        if not front.return_parameters.is_closed:
            print("  Action: Close the front cover before proceeding")

        # Check 4: Arm position
        arm_pos = star.pip_arm_get_x_position(arm_id=1)
        x_position = arm_pos.return_parameters.get("xPosition")
        print(f"Left arm X position: {x_position}")
        if x_position is not None and x_position < 100:
            print("  Note: Arm is parked far left")

    finally:
        star.stop()

troubleshoot_connection_issue()
```

---

## Diagnostic Patterns Reference

| Need | Use This | Purpose |
|------|----------|---------|
| **Check if safe to start** | `front_cover_is_closed()` + `instrument_is_idle()` | Safety validation before operations |
| **Give user feedback** | `status_light_set_front_light()` | Visual indication of status |
| **Show progress** | `status_light_set_front_light(progress=...)` | Long-running workflow feedback (0-5 levels) |
| **Validate hardware** | `instrument_get_configuration()` | Verify expected hardware present |
| **Pre-execution checks** | All checks in "Complete Diagnostic" | Full pre-flight validation |
| **Troubleshoot issues** | Selective checks in "Troubleshooting" section | Targeted diagnostics |
| **Arm diagnostics** | `pip_arm_get_x_position()` + move commands | Position validation and diagnostics |
