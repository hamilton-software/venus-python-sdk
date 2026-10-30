# Error Handling Profiles

This directory contains pre-configured JSON profiles for error handling strategies.
Users can discover and customize profiles by editing the JSON files directly.

**For comprehensive user documentation, see [Error Handling](../../../../docs/error_handling.md)**

## Available Profiles

### `standard.json`

The default profile for typical lab runs. Provides:
- Per-error-type recovery rules for tip_pickup, aspirate, and dispense operations
- Sensible defaults for handling common error scenarios
- Allows operator escalation when all recovery actions are exhausted

**Use case**: General-purpose lab automation with human oversight.

**See also**: [Quick Start](../../../../docs/error_handling.md#quick-start) in the main documentation

## Profile Structure

Each profile JSON file contains:

```json
{
  "name": "Profile Name",
  "default": {
    "actions": ["ACTION1", "ACTION2"],
    "max_retries": 1,
    "allow_operator": true,
    "inputs": {}
  },
  "operations": {
    "operation_name": {
      "ERROR_TYPE": {
        "actions": ["ACTION1", "ACTION2"],
        "max_retries": 2,
        "allow_operator": true,
        "inputs": {}
      }
    }
  },
  "operation_defaults": {
    "operation_name": {
      "actions": ["ACTION1"],
      "max_retries": 0,
      "allow_operator": false,
      "inputs": {}
    }
  }
}
```

### Field Descriptions

- **name**: Human-readable profile identifier
- **default**: Fallback error handling entry for all unspecified errors
- **operations**: Registry of operation-specific error handlers
  - Key: operation name (e.g., "tip_pickup", "aspirate", "dispense")
  - Value: mapping of error types to recovery entries
- **operation_defaults**: Operation-specific default entries
  - Overrides global default for specific operations if defined

### Error Entry Fields

- **actions**: Ordered list of recovery actions to attempt
- **max_retries**: Maximum attempts for REPEAT actions (default: 1)
- **allow_operator**: Whether to escalate to the operator on action exhaustion (default: true). When true, the SDK calls the registered `on_operator_error_escalation` callback if one is provided, or otherwise defers to the legacy VENUS operator dialog by submitting `selected_action_id=-1`. When false, the SDK submits ABORT.
- **inputs**: Mapping of actions to required input values (currently empty)

## Customizing Profiles

**See [Using Custom Profiles](../../../../docs/error_handling.md#using-custom-profiles) in the main documentation for detailed examples.**

### Quick Reference: Edit JSON Directly

Modify the JSON files to adjust recovery behavior for specific error types:

```json
{
  "TIP_PRESENT": {
    "actions": ["EXCLUDE", "ABORT"],
    "max_retries": 1,
    "allow_operator": false,
    "inputs": {}
  }
}
```

### Quick Reference: Use Python API

Load and modify profiles programmatically:

```python
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile_loaders import profile_from_json_file

# Load from file
profile = profile_from_json_file("custom_profile.json")

# Or create a variant
variant = STANDARD_PROFILE.with_overrides(
    name="Strict_Mode",
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.ABORT,),
                max_retries=0,
            ),
        },
    },
)

# Export modified profile
from hamilton_venus.error_handling.profile_loaders import profile_to_json_file
profile_to_json_file(variant, "strict_profile.json")
```

For more complete examples, see:
- [Creating Custom Profiles](../../../../docs/error_handling.md#creating-custom-profiles)
- [Profile Persistence](../../../../docs/error_handling.md#profile-persistence)

## Recovery Actions

Available recovery actions:
- `ABORT`: Stop execution
- `REPEAT`: Retry the failed operation
- `NEXT`: Skip to next item
- `EXCLUDE`: Remove from processing
- `CONTINUE`: Proceed without action
- `WASTE`: Discard content
- `BOTTOM`: Move to bottom
- `AIR`: Add air gap
- `AVAILABLE`: Use available content

For details on which actions are valid for each error type, see the main documentation:
→ [Error Types by Operation](../../../../docs/error_handling.md#error-types-by-operation)

## Error Types

### tip_pickup
- TIP_PRESENT
- NO_TIP
- EXECUTION
- HARDWARE
- NOT_EXECUTED
- OTHER

### aspirate
- IMPROPER
- CLOT
- INSUFFICIENT
- LIQUID_LEVEL
- NO_TIP
- EXECUTION
- HARDWARE
- UNEXPECTED_CLLD
- ANTI_DROP
- OTHER

### dispense
- INSUFFICIENT
- PRESSURE_LLD
- CLOT
- IMPROPER
- LIQUID_LEVEL
- NOT_ASPIRATED
- EXECUTION
- HARDWARE
- UNEXPECTED_CLLD
- ANTI_DROP
- OTHER

For details on each error type, see:
→ [Error Types by Operation](../../../../docs/error_handling.md#error-types-by-operation)

## Next Steps

1. **Quick Start**: Read [Quick Start](../../../../docs/error_handling.md#quick-start) in the main documentation
2. **Understanding Profiles**: See [Overview](../../../../docs/error_handling.md#overview)
3. **Using Custom Profiles**: See [Using Custom Profiles](../../../../docs/error_handling.md#using-custom-profiles)
4. **Operator Escalation**: See [Operator Escalation](../../../../docs/error_handling.md#operator-escalation)
5. **Full Reference**: See [docs/error_handling.md](../../../../docs/error_handling.md)
