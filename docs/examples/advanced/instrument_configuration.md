# Instrument Configuration and Diagnostics

Comprehensive guide for querying instrument configuration and running diagnostics.

## Understanding Command Categories

The instrument commands fall into logical categories in the SDK, each serving a specific purpose:

| Category | Purpose | Methods | When to Use |
|----------|---------|---------|------------|
| **Status** | Connection and readiness state | `instrument_is_connected()`, `instrument_is_idle()`, `instrument_init()`, `instrument_connect()`, `instrument_terminate()` | Startup/shutdown, connection checks |
| **Configuration** | Hardware information and setup | `instrument_get_configuration()`, `instrument_get_serial_number()`, `instrument_get_deck_tracks()`, `instrument_get_deck_dimensions()`, `instrument_get_waste_locations()`, `instrument_disable_cleanup()` | Before workflows, hardware validation |
| **Maintenance** | Service and maintenance data | `instrument_get_daily_maintenance_data()`, `instrument_get_weekly_maintenance_data()`, `instrument_get_verification_data()` | Diagnostics, preventive maintenance checks, monitoring |
| **Front Cover** | Safety cover control | `front_cover_is_closed()`, `front_cover_lock()`, `front_cover_unlock()` | Safety checks, workflow gates |
| **Pipetting Arm** | Arm positioning and diagnostics | `pip_arm_get_x_position()`, `pip_arm_park_left()`, `pip_arm_park_right()`, `pip_arm_move()` | Positioning for specific operations, diagnostics |
| **Status Light** | Visual feedback | `status_light_set_front_light()` | User feedback, progress indication |
| **Autoload** | Deck carrier loading | `autoload_move()`, `autoload_park_left()`, `autoload_park_right()`, `autoload_load_carrier_by_id()`, `autoload_load_carrier_by_track()`, `autoload_unload_carrier_by_id()`, `autoload_unload_carrier_by_track()`, `autoload_is_track_occupied()` | Automated carrier management |

---

## Overview

This guide covers:
- Getting instrument configuration
- Retrieving maintenance data
- Checking hardware status
- Querying deck geometry
- How the connect-time configuration is used to validate commands
- Pre-workflow validation
- Troubleshooting and diagnostics

---

## Basic Configuration Queries

### Get Instrument Configuration

Retrieve complete instrument configuration:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    config = star.instrument_get_configuration()

    print(f"Tracks: {config.return_parameters.tracks}")
    print(f"Max autoload track: {config.return_parameters.max_autoload_track}")

    if config.return_parameters.left_arm is not None:
        print(f"Left arm 1 mL channels: {config.return_parameters.left_arm.channels_1_ml}")
```

### Get Serial Number

Query instrument serial number for identification:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    serial = star.instrument_get_serial_number()
    print(f"Serial Number: {serial.return_parameters.serial_number}")
```

### Get Deck Information

Query deck dimensions and track information:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    dimensions = star.instrument_get_deck_dimensions()
    print(f"Deck dimensions: x={dimensions.return_parameters.x}, y={dimensions.return_parameters.y}")

    tracks = star.instrument_get_deck_tracks()
    print(f"Total tracks: {tracks.return_parameters.total_tracks}")
    print(f"Autoloadable tracks: {tracks.return_parameters.autoloadable_tracks}")

    waste = star.instrument_get_waste_locations()
    print(f"Waste locations: {waste.return_parameters.waste_locations}")
```

---

## Connect-Time Validation from the Instrument Configuration

When the client connects, the SDK reads `instrument_get_configuration()` once and caches what it says the hardware supports. Later commands are checked against that cache **before they are sent to VENUS**, so a request the hardware cannot run fails immediately with a clear message.

The configuration is read:

- at the end of `start()` when `auto_connect=True` (the default), and
- again after every `instrument_connect()` call.

If you start with `auto_connect=False`, nothing is cached until you call `instrument_connect()`.

### What is checked

| Check | Rule | Raises |
|-------|------|--------|
| Channel count | `len(channels)` must not exceed the channel total reported for the module (`channels1mL`, `channels5mL`, `channelsMagPip`). | `ValueError` |
| Channel numbers | Every channel number must be between 1 and the module's channel total. | `ValueError` |
| MPH96 commands (`mph96.*`) | At least one arm reports an MPH96 head. | `VenusCommandUnsupportedError` |
| Autoload commands (`autoload.*`) | The configuration reports `Autoload`. | `VenusCommandUnsupportedError` |
| iSWAP / IPG commands (`transport.iswap.*`) | At least one arm reports a gripper with a type. | `VenusCommandUnsupportedError` |
| CO-RE `front_channel` | Between the gripper's channel span and the module's channel total (see below). | `ValueError` |
| `add_qcg()` / `add_1ml_core_grip()` on STAR | The gripper tool matches the 1 mL channel type (see below). | `VenusCommandUnsupportedError` |

The hardware checks are enforced for every command with that action prefix, including calls made through `send_command()`.

### Channel counts

Systems can be configured with up to 16 channels per module, so the SDK no longer assumes 8. The limit is the channel `total` from the configuration:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # On a system configured with 12 channels this is accepted;
    # on an 8-channel system it raises
    #   ValueError: 1mL support a maximum of 8 channels, but 12 were specified: [1, 2, ..., 12]
    star.tip_pickup(channels=list(range(1, 13)), positions="TipRack@col:1")
```

Notes:

- **All channels of a command run on one arm.** Channels cannot be split across arms. When both arms have the module, the larger arm's total is the limit.
- **Channel numbers are validated too.** `channels=[9, 10]` on an 8-channel arm raises `ValueError: 1mL channel numbers must be between 1 and 8, but got: [9, 10]`, even though only two channels were requested.
- **Defaults are unchanged.** Commands that take `channels=None` still default to channels 1-8.
- **Fallback ceiling.** Until the configuration has been read, or if reading it fails, the limit is the SDK ceiling of 16 channels (`hamilton_venus.constants.MAX_CHANNELS`) and the instrument reports any excess itself. The compound commands (`serial_dilution`, `copy_plate`, ...) pre-check against this ceiling and rely on the client for the exact per-system limit.

### Optional hardware

MPH96, autoload and iSWAP/IPG commands are rejected when the configuration does not report the hardware:

```python
from hamilton_venus import StarClient, VenusCommandUnsupportedError

with StarClient() as star:
    try:
        star.aspirate_mph96(...)
    except VenusCommandUnsupportedError as exc:
        print(exc)
        # mph96.aspirate requires an MPH96 head, but the instrument configuration does not report one
```

If the configuration could not be read, these commands are **not** rejected: the SDK does not guess, and VENUS reports any error itself.

### CO-RE gripper `front_channel`

`front_channel` (on `core_transport`, `core_transport_to_waste`, `core_hold_lid` and their `core_5ml_*` versions) is the front-most channel of the gripper. The gripper also occupies the channels behind it, so the value must be at least the gripper's channel span and at most the module's channel total:

| Gripper | Used with | Channel span | Valid `front_channel` |
|---------|-----------|--------------|-----------------------|
| CO-RE gripper | Legacy channels | 2 | 2 to channel total |
| QCG (Quad CO-RE Grip) | Fluid Motion channels, and Vantage | 4 | 4 to channel total |

The limits come from the module the command belongs to: 1 mL commands use the 1 mL channel total and `core_5ml_*` commands use the 5 mL total. Omitting `front_channel` skips the check.

### Gripper tools and channel type

Each channel module reports a `type` of `"Legacy"` or `"Fluid Motion"` (`config.return_parameters.left_arm.channels_1_ml.type`). The two cannot be mixed on one instrument, and each takes exactly one gripper. On a STAR the SDK rejects the other tool:

| 1 mL channel type | `add_1ml_core_grip()` | `add_qcg()` |
|-------------------|-----------------------|-------------|
| Legacy | allowed | rejected |
| Fluid Motion | rejected | allowed |

```python
star.add_qcg()
# VenusCommandUnsupportedError: labware.addQCG adds a QCG, which needs Fluid Motion channels,
# but the instrument configuration reports Legacy 1mL channels
```

The check applies to STAR only. `add_5ml_core_grip()` is not restricted. If the channel type is missing from the configuration, or the arms disagree, neither tool is rejected.

---

## Maintenance Data Queries

### Get Daily Maintenance Data

Query daily maintenance history:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    daily = star.instrument_get_daily_maintenance_data()

    print("Daily maintenance:")
    print(f"  Status: {daily.return_parameters.status}")
    print(f"  Expiration: {daily.return_parameters.expiration_date}")
    print(f"  Processed: {daily.return_parameters.processed_date}")
```

### Get Weekly Maintenance Data

Query weekly maintenance status:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    weekly = star.instrument_get_weekly_maintenance_data()

    print("Weekly maintenance:")
    print(f"  Status: {weekly.return_parameters.status}")
    print(f"  Expiration: {weekly.return_parameters.expiration_date}")
```

### Get Verification Data

Query verification/qualification status:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    verify = star.instrument_get_verification_data()

    print("Verification:")
    print(f"  Status: {verify.return_parameters.status}")
    print(f"  Expiration: {verify.return_parameters.expiration_date}")
```

---

## Maintenance Gating

Use expiration and status data to decide whether a run should proceed. The `status` field is a free-form string set by VENUS (e.g. `"OK"`, `"Expired"`, `"DueToday"`); `is_mandatory` indicates whether the instrument will block operation if maintenance is overdue.

### Gate a Run on Maintenance Status

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_maintenance_gate(star: StarClient) -> bool:
    """
    Return True only if all maintenance checks are within acceptable limits.

    Logs a warning for upcoming expirations and an error for expired/mandatory items.
    """
    checks = {
        "daily": star.instrument_get_daily_maintenance_data(),
        "weekly": star.instrument_get_weekly_maintenance_data(),
        "verification": star.instrument_get_verification_data(),
    }

    all_ok = True
    for name, response in checks.items():
        p = response.return_parameters
        exp = p.expiration_date
        mandatory = p.is_mandatory

        if p.status and p.status.lower() not in ("ok", ""):
            if mandatory:
                logger.error(
                    "Maintenance BLOCKED: %s status='%s' (mandatory), expires %s",
                    name, p.status, exp,
                )
                all_ok = False
            else:
                logger.warning(
                    "Maintenance advisory: %s status='%s', expires %s",
                    name, p.status, exp,
                )
        else:
            logger.info("Maintenance OK: %s (expires %s)", name, exp)

    return all_ok


with StarClient() as star:
    if not check_maintenance_gate(star):
        raise RuntimeError(
            "Instrument maintenance is overdue — complete required maintenance before running"
        )
    print("Maintenance checks passed — proceeding with workflow")
```

### Log Maintenance Summary at Startup

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)


def log_maintenance_summary(star: StarClient) -> None:
    """Log all maintenance data for the run audit trail."""
    for label, method in [
        ("Daily", star.instrument_get_daily_maintenance_data),
        ("Weekly", star.instrument_get_weekly_maintenance_data),
        ("Verification", star.instrument_get_verification_data),
    ]:
        p = method().return_parameters
        logger.info(
            "%s maintenance: status=%s, expires=%s, processed=%s",
            label, p.status, p.expiration_date, p.processed_date,
        )


with StarClient() as star:
    log_maintenance_summary(star)
```

### `MaintenanceDataReturnParameters` Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Maintenance status string set by VENUS (e.g. `"OK"`, `"Expired"`) |
| `expiration_date` | `str \| None` | Date after which maintenance is considered overdue |
| `processed_date` | `str \| None` | Date the maintenance was last processed |
| `processed_status` | `str \| None` | Status at the time of last processing |
| `processed_code` | `int \| None` | Numeric code from last processing |
| `is_mandatory` | `bool \| None` | Whether the instrument will block operation when overdue |

---

## Production Workflow: Pre-Execution Validation

### Complete System Health Check

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InstrumentHealthCheck:
    """Validate instrument is ready for execution."""
    
    def __init__(self, star):
        self.star = star
        self.checks = {}
    
    def check_connection(self):
        """Verify instrument is connected."""
        try:
            connected = self.star.instrument_is_connected()
            self.checks["connected"] = connected
            
            if connected:
                logger.info("✓ Instrument connected")
            else:
                logger.error("✗ Instrument not connected")
            
            return connected
        except Exception as e:
            logger.error(f"✗ Connection check failed: {e}")
            self.checks["connected"] = False
            return False
    
    def check_idle(self):
        """Verify instrument is idle."""
        try:
            idle = self.star.instrument_is_idle()
            self.checks["idle"] = idle
            
            if idle:
                logger.info("✓ Instrument is idle")
            else:
                logger.warning("⚠️ Instrument is busy")
            
            return idle
        except Exception as e:
            logger.error(f"✗ Idle check failed: {e}")
            self.checks["idle"] = False
            return False
    
    def check_configuration(self):
        """Verify configuration is accessible."""
        try:
            config = self.star.instrument_get_configuration()
            self.checks["config_accessible"] = True
            
            logger.info("✓ Configuration accessible")
            logger.info(f"  Configuration: {config.return_parameters}")
            
            return True
        except Exception as e:
            logger.error(f"✗ Configuration check failed: {e}")
            self.checks["config_accessible"] = False
            return False
    
    def check_maintenance(self):
        """Check if maintenance is due."""
        try:
            daily = self.star.instrument_get_daily_maintenance_data()
            
            # Check if maintenance overdue
            # (implementation depends on specific maintenance data structure)
            maintenance_due = False  # Example logic
            
            self.checks["maintenance_ok"] = not maintenance_due
            
            if maintenance_due:
                logger.warning("⚠️ Maintenance may be due")
            else:
                logger.info("✓ Maintenance status OK")
            
            return not maintenance_due
        except Exception as e:
            logger.warning(f"⚠️ Could not check maintenance: {e}")
            # Don't fail entire check for this
            return True
    
    def check_deck_accessible(self):
        """Verify deck information is accessible."""
        try:
            dimensions = self.star.instrument_get_deck_dimensions()
            tracks = self.star.instrument_get_deck_tracks()
            
            self.checks["deck_accessible"] = True
            
            logger.info("✓ Deck information accessible")
            logger.info(f"  Dimensions: {dimensions}")
            logger.info(f"  Tracks: {tracks.return_parameters.total_tracks}")
            
            return True
        except Exception as e:
            logger.error(f"✗ Deck check failed: {e}")
            self.checks["deck_accessible"] = False
            return False
    
    def run_all_checks(self, require_idle=True):
        """Run complete health check suite."""
        logger.info("="*60)
        logger.info("INSTRUMENT HEALTH CHECK")
        logger.info("="*60)
        
        results = []
        
        # Critical checks
        results.append(("Connection", self.check_connection()))
        
        if require_idle:
            results.append(("Idle", self.check_idle()))
        
        results.append(("Configuration", self.check_configuration()))
        results.append(("Deck", self.check_deck_accessible()))
        
        # Non-critical checks
        results.append(("Maintenance", self.check_maintenance()))
        
        # Summary
        logger.info("="*60)
        logger.info("SUMMARY")
        logger.info("="*60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            logger.info(f"{name:.<40} {status}")
        
        logger.info(f"Total: {passed}/{total} checks passed")
        logger.info("="*60)
        
        return all(result for _, result in results)
    
    def get_report(self):
        """Get detailed check report."""
        return {
            "all_checks": self.checks,
            "passed": sum(1 for v in self.checks.values() if v),
            "total": len(self.checks),
        }


# Usage
with StarClient() as star:
    health = InstrumentHealthCheck(star)
    
    if health.run_all_checks(require_idle=True):
        print("✓ Instrument ready for execution")
    else:
        print("✗ Instrument not ready - fix issues before proceeding")
        report = health.get_report()
        print(f"Report: {report}")
```

---

## Workflow: Startup Diagnostics

### Complete Initialization with Diagnostics

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class StartupDiagnostics:
    """Run diagnostics during startup."""
    
    def __init__(self, star):
        self.star = star
        self.diagnostics = {}
    
    def log_system_info(self):
        """Log system information."""
        try:
            serial = self.star.instrument_get_serial_number()
            config = self.star.instrument_get_configuration()
            
            logger.info("="*60)
            logger.info("SYSTEM INFORMATION")
            logger.info("="*60)
            logger.info(f"Serial Number: {serial}")
            logger.info(f"Configuration: {config}")
            
            self.diagnostics["serial_number"] = serial
            self.diagnostics["configuration"] = str(config)
            
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
    
    def log_deck_info(self):
        """Log deck configuration."""
        try:
            dimensions = self.star.instrument_get_deck_dimensions()
            tracks = self.star.instrument_get_deck_tracks()
            waste = self.star.instrument_get_waste_locations()
            
            logger.info("="*60)
            logger.info("DECK INFORMATION")
            logger.info("="*60)
            logger.info(f"Dimensions: {dimensions}")
            logger.info(f"Tracks: {tracks}")
            logger.info(f"Waste Locations: {waste}")
            
            self.diagnostics["deck_dimensions"] = str(dimensions)
            self.diagnostics["tracks"] = str(tracks)
            self.diagnostics["waste_locations"] = str(waste)
            
        except Exception as e:
            logger.error(f"Failed to get deck info: {e}")
    
    def log_maintenance_status(self):
        """Log maintenance information."""
        try:
            daily = self.star.instrument_get_daily_maintenance_data()
            weekly = self.star.instrument_get_weekly_maintenance_data()
            verify = self.star.instrument_get_verification_data()
            
            logger.info("="*60)
            logger.info("MAINTENANCE STATUS")
            logger.info("="*60)
            logger.info(f"Daily: {daily}")
            logger.info(f"Weekly: {weekly}")
            logger.info(f"Verification: {verify}")
            
            self.diagnostics["daily_maintenance"] = str(daily)
            self.diagnostics["weekly_maintenance"] = str(weekly)
            self.diagnostics["verification"] = str(verify)
            
        except Exception as e:
            logger.warning(f"Could not get maintenance info: {e}")
    
    def run_startup(self):
        """Run complete startup diagnostics."""
        try:
            # Initialize (skipped if already initialized; pass force_init=True to re-initialize)
            logger.info("Initializing instrument...")
            self.star.instrument_init(force_init=False)
            logger.info("✓ Initialization complete")
            
            # Collect diagnostics
            self.log_system_info()
            self.log_deck_info()
            self.log_maintenance_status()
            
            logger.info("="*60)
            logger.info("✓ STARTUP DIAGNOSTICS COMPLETE")
            logger.info("="*60)
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Startup diagnostics failed: {e}")
            return False
    
    def get_diagnostics(self):
        """Get collected diagnostics."""
        return self.diagnostics


# Usage
with StarClient(logging_level=logging.DEBUG) as star:
    startup = StartupDiagnostics(star)
    
    if startup.run_startup():
        diags = startup.get_diagnostics()
        print(f"Diagnostics collected: {len(diags)} items")
    else:
        print("Startup failed")
```

---

## Query Pattern: Configuration Validation

### Validate Configuration Matches Expectations

```python
from hamilton_venus import StarClient
import logging

logger = logging.getLogger(__name__)

def validate_configuration(star, expected_config):
    """
    Validate instrument configuration matches expectations.
    
    Args:
        star: StarClient instance
        expected_config: Dict with expected values
    
    Returns:
        bool: True if configuration matches
    """
    try:
        actual = star.instrument_get_configuration()
        
        mismatches = []
        
        for key, expected_value in expected_config.items():
            actual_value = getattr(actual.return_parameters, key, None)
            
            if actual_value != expected_value:
                mismatches.append(
                    f"{key}: expected {expected_value}, got {actual_value}"
                )
        
        if mismatches:
            logger.error("Configuration mismatches:")
            for mismatch in mismatches:
                logger.error(f"  - {mismatch}")
            return False
        else:
            logger.info("✓ Configuration validated")
            return True
            
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return False


# Usage
with StarClient() as star:
    expected = {
        # Populate with expected values from ConfigurationReturnParameters
        # e.g., "tracks": 16,
    }
    
    if validate_configuration(star, expected):
        print("Configuration is valid")
    else:
        print("Configuration does not match expectations")
```

---

## Troubleshooting Workflow

### Diagnose and Report Issues

```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

class InstrumentDiagnostics:
    """Diagnose instrument issues."""
    
    def __init__(self, star):
        self.star = star
        self.issues = []
    
    def check_connectivity(self):
        """Diagnose connectivity issues."""
        try:
            if not self.star.instrument_is_connected():
                self.issues.append("Instrument not connected")
                logger.error("✗ Connection issue detected")
                return False
            
            logger.info("✓ Connectivity OK")
            return True
            
        except Exception as e:
            self.issues.append(f"Connectivity check failed: {e}")
            logger.error(f"✗ Connectivity check error: {e}")
            return False
    
    def check_responsiveness(self):
        """Diagnose responsiveness issues."""
        try:
            # Try a simple query
            _ = self.star.instrument_get_serial_number()
            logger.info("✓ Responsiveness OK")
            return True
            
        except Exception as e:
            self.issues.append(f"Instrument not responding: {e}")
            logger.error(f"✗ Responsiveness issue: {e}")
            return False
    
    def check_idle_state(self):
        """Check if instrument is stuck."""
        try:
            if not self.star.instrument_is_idle():
                self.issues.append("Instrument is busy")
                logger.warning("⚠️ Instrument not idle")
                return False
            
            logger.info("✓ Idle state OK")
            return True
            
        except Exception as e:
            self.issues.append(f"Idle check failed: {e}")
            return False
    
    def run_diagnostics(self):
        """Run complete diagnostics suite."""
        logger.info("Starting diagnostics...")
        
        self.check_connectivity()
        self.check_responsiveness()
        self.check_idle_state()
        
        if self.issues:
            logger.error(f"Found {len(self.issues)} issues:")
            for issue in self.issues:
                logger.error(f"  - {issue}")
            return False
        else:
            logger.info("✓ No issues detected")
            return True
    
    def get_report(self):
        """Get diagnostics report."""
        return {
            "issues": self.issues,
            "issue_count": len(self.issues),
            "status": "OK" if not self.issues else "ERRORS",
        }


# Usage
with StarClient() as star:
    diag = InstrumentDiagnostics(star)
    
    if diag.run_diagnostics():
        print("Instrument is healthy")
    else:
        report = diag.get_report()
        print(f"Issues found: {report}")
```

---

## Best Practices

### 1. Check on Startup

```python
from hamilton_venus import StarClient

with StarClient() as star:
    # Always verify connection first
    if not star.instrument_is_connected():
        raise RuntimeError("Instrument not connected")
```

### 2. Validate Before Operations

```python
# Before executing critical workflows
if not star.instrument_is_idle():
    logger.error("Instrument busy - cannot start workflow")
    exit(1)

config = star.instrument_get_configuration()
```

### 3. Log Diagnostics

```python
import logging

# Log configuration for audit trail
serial = star.instrument_get_serial_number()
logger.info(f"Using instrument: {serial.return_parameters.serial_number}")

# Log deck info for documentation
dimensions = star.instrument_get_deck_dimensions()
logger.info(f"Deck: {dimensions}")
```

### 4. Monitor Maintenance

```python
# Check maintenance periodically (maintenance_due() is your own helper;
# see Maintenance Gating above for an example)
daily = star.instrument_get_daily_maintenance_data()
weekly = star.instrument_get_weekly_maintenance_data()

if maintenance_due(weekly):
    logger.warning("Scheduled maintenance approaching")
```

---

## Common Issues and Solutions

### Connection Lost

**Problem:** Connection to instrument drops unexpectedly.

**Solution:**
```python
import logging
import time
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

with StarClient() as star:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if star.instrument_is_connected():
                break
        except Exception:
            if attempt < max_retries - 1:
                logger.warning(f"Reconnecting (attempt {attempt+1}/{max_retries})")
                time.sleep(5)
            else:
                raise RuntimeError("Failed to reconnect")
```

### Instrument Busy

**Problem:** Instrument won't respond; stuck in busy state.

**Solution:**
```python
import logging
import time
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

with StarClient() as star:
    # Wait for idle state
    max_wait = 300  # 5 minutes
    start = time.time()
    
    while not star.instrument_is_idle():
        if time.time() - start > max_wait:
            raise RuntimeError("Instrument timeout - still busy")
        
        logger.info("Waiting for instrument to idle...")
        time.sleep(10)
    
    logger.info("Instrument now idle")
```

### Configuration Mismatch

**Problem:** Expected configuration doesn't match actual.

**Solution:**
```python
import logging
from hamilton_venus import StarClient

logger = logging.getLogger(__name__)

with StarClient() as star:
    config = star.instrument_get_configuration()
    
    # Log actual vs expected
    logger.info(f"Actual config: {config}")
    logger.info("Expected: [your expected values]")
    
    # Decide whether to proceed or fail (validate_critical_params() is your own helper;
    # see validate_configuration() above)
    if not validate_critical_params(config):
        raise RuntimeError("Critical config mismatch")
```

---

## See Also

- [`tip_pool_management.md`](./tip_pool_management.md) — Tip pool counter management
- [`star_commands.md`](../../star_commands.md) — Full API reference
- [Basic examples](../) — Basic examples

