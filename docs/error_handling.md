# Error Handling

The Hamilton VENUS Python SDK includes a declarative error handling system that automatically responds to known errors. Error handling profiles let you specify recovery strategies without manual intervention, or with controlled operator escalation when recovery actions are exhausted.

## Quick Start

The SDK provides a built-in default profile that works for most users. No configuration is needed:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    # Assumes the deck has a tip rack assigned to the "TransferTips" tip pool
    # (see examples/deck_and_layout.md).
    result = star.tip_pickup(tip_pool="TransferTips")
```

If an error occurs, the SDK automatically looks up the configured recovery actions, attempts them in order with retries, and escalates if needed. That's it.

## Overview

### Error Handling Profiles

An **error handling profile** is a set of rules that maps error types to recovery actions:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction, TipPickupError

profile = ErrorProfile(
    name="My_Profile",
    default=ErrorEntry(
        actions=(),
        allow_operator=True,
    ),
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.REPEAT,),
                max_retries=3,
                allow_operator=True,
            ),
        },
    },
)
```

### Components

**ErrorProfile**: Container for all error handling rules
- `name`: Human-readable identifier
- `default`: Fallback for unspecified errors
- `operations`: Maps operation names to error handlers
- `error_defaults`: Cross-operation defaults by error type name (optional)
- `operation_defaults`: Operation-specific default overrides (optional)

**ErrorEntry**: Rule for handling a specific error type
- `actions`: Ordered tuple of recovery actions to attempt
- `max_retries`: Maximum times to retry REPEAT actions (default: 1)
- `allow_operator`: Whether to escalate to operator on action exhaustion (default: True). When True, the SDK invokes the registered `on_operator_error_escalation` callback if one is provided; otherwise it defers to the legacy VENUS operator dialog by submitting `selected_action_id=-1`. When False, the SDK submits ABORT.

**RecoveryAction**: Available recovery strategies (full list in the [Recovery Actions](#recovery-actions) reference table)
- `CANCEL` - Exit default error handling (always valid)
- `ABORT` - Stop execution
- `REPEAT` - Retry the failed operation
- `NEXT` - Skip to next item
- `EXCLUDE` - Remove from processing
- `CONTINUE` - Proceed without action
- `WASTE` - Discard content
- `BOTTOM` - Move to bottom
- `AIR` - Add air gap
- `AVAILABLE` - Use available content

*Note: Not all recovery actions are valid for all error types. The system validates profile actions automatically. At callback time, inspect `context.top_level_actions` and `context.per_channel_actions` to determine what the server currently allows.*

## Built-in Profiles

### STANDARD_PROFILE (Default)

Used automatically unless you specify a different profile. Provides:

- **Tip pickup errors**
- **Aspirate errors**
- **Dispense errors**
- **Operator escalation** for other error types (defers to the legacy VENUS operator dialog if no callback is registered)

```python
from hamilton_venus.error_handling import STANDARD_PROFILE

profile = STANDARD_PROFILE
```

## Using Custom Profiles

### Specify at Connection Time

```python
from hamilton_venus import StarClient
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction, TipPickupError

custom_profile = ErrorProfile(
    name="Strict_Mode",
    default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.ABORT,),
                max_retries=0,
                allow_operator=False,
            ),
        },
    },
)

with StarClient(error_profile=custom_profile) as star:
    star.instrument_init()
```

### Create Variants of Built-in Profiles

```python
from hamilton_venus import StarClient
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction, TipPickupError

strict =  STANDARD_PROFILE.with_overrides(
    name="Strict_Tip_Handling",
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.EXCLUDE,),
                max_retries=0,
            ),
        },
    },
)

with StarClient(error_profile=strict) as star:
    star.instrument_init()
```

### Load Profiles from JSON

```python
from hamilton_venus import StarClient
from hamilton_venus.error_handling.profile_loaders import profile_from_json_file

profile = profile_from_json_file("path/to/my_profile.json")
with StarClient(error_profile=profile) as star:
    star.instrument_init()
```

To save a profile for later use:

```python
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile_loaders import profile_to_json_file

variant = STANDARD_PROFILE.with_overrides(name="My_Custom")
profile_to_json_file(variant, "my_profile.json")
```

## Operator Escalation

When recovery actions are exhausted, the SDK can escalate to an operator callback. This allows your code to display a dialog and let the user choose the next action.

Both **synchronous** and **async** callbacks are supported. Sync callbacks run in a thread executor so blocking GUI dialogs don't stall the event loop. Async callbacks are awaited directly.

### Registering an Operator Callback

```python
from hamilton_venus import OperatorEscalationContext, RecoveryAction, StarClient


def my_error_handler(context: OperatorEscalationContext):
    print(f"Escalated error code={context.error.code} message={context.error.message}")
    print(f"Top-level options: {[a.name for a in context.top_level_actions]}")
    print(f"Per-channel options: {[a.name for a in context.per_channel_actions]}")
    return RecoveryAction.ABORT


with StarClient(on_operator_error_escalation=my_error_handler) as star:
    star.instrument_init()
```

### OperatorEscalationContext Fields

| Field | Type | Description |
|---|---|---|
| `error` | `ErrorData` | Raw server error payload |
| `entry` | `ErrorEntry` | Active profile entry for this escalation |
| `operation_category` | `OperationCategory \| None` | Classified operation (if available) |
| `error_type` | `Enum \| None` | Classified error type (if available) |
| `top_level_actions` | `list[RecoveryActionDescriptor]` | Server-advertised top-level actions |
| `per_channel_actions` | `list[RecoveryActionDescriptor]` | Actions common across all channels |
| `is_per_channel_escalation` | `bool` | Whether escalation came from per-channel action exhaustion |

### Operator Callback Return Values

Your callback can return:

- `RecoveryAction`: resolver submits it using the correct path (top-level or per-channel)
- `ErrorRecovery`: submitted directly as-is
- `None`: SDK falls back to `ABORT`

```python
def operator_dialog(context: OperatorEscalationContext):
    available = {a.name.lower() for a in context.top_level_actions}
    user_choice = show_dialog(list(available))  # your UI; returns e.g. "repeat"
    try:
        return RecoveryAction(user_choice)
    except ValueError:
        return None
```

### Example: GUI Dialog Integration

```python
import tkinter as tk

from hamilton_venus import OperatorEscalationContext, RecoveryAction


def operator_dialog(context: OperatorEscalationContext):
    dialog = tk.Tk()
    dialog.title("Operator Escalation")
    chosen = {"action": None}

    def normalize(action_descriptors):
        actions = []
        for descriptor in action_descriptors or []:
            name = descriptor.name.lower()
            if name in RecoveryAction._value2member_map_:
                action = RecoveryAction(name)
                if action not in actions:
                    actions.append(action)
        return actions

    top_level_actions = normalize(context.top_level_actions)
    per_channel_actions = normalize(context.per_channel_actions)

    sections = []
    if top_level_actions:
        sections.append(("Top-Level Actions", top_level_actions))
    if per_channel_actions:
        sections.append(("Per-Channel Actions", per_channel_actions))
    if not sections:
        sections.append(("Recovery Options", [RecoveryAction.ABORT, RecoveryAction.CANCEL]))

    def pick(action):
        chosen["action"] = action
        dialog.destroy()

    for title, actions in sections:
        tk.Label(dialog, text=title).pack(anchor="w", padx=12, pady=(8, 4))
        for action in actions:
            tk.Button(
                dialog,
                text=action.value.title(),
                command=lambda selected=action: pick(selected),
            ).pack(fill="x", padx=12, pady=2)

    dialog.mainloop()
    return chosen["action"] if chosen["action"] else RecoveryAction.ABORT
```

Or use an async callback if your UI layer is coroutine-based:

```python
async def async_operator_dialog(context: OperatorEscalationContext):
    await my_async_gui.show_error_dialog(context.error)
    return RecoveryAction.ABORT
```

### ErrorRecovery Builder Helpers

The SDK includes placeholder builders that keep `selected_action_id=-1` until you intentionally resolve IDs:

- `build_error_recovery(error_uuid, action, ...)`
- `build_per_channel_recovery(error_uuid, channel_actions, ...)`
- `build_mixed_recovery(error_uuid, channel_actions=..., ...)`

Use these when you need to construct payload shape first and resolve IDs later.

### Resolved Builder Helpers

For callback code that already has an `OperatorEscalationContext`, prefer the resolved helpers:

- `resolve_error_recovery(context, action, ...)`
- `resolve_per_channel_recovery(context, channel_actions, ...)`

These map your `RecoveryAction` choices to the server-assigned action IDs advertised for that exact error event.

```python
from hamilton_venus import (
    OperatorEscalationContext,
    RecoveryAction,
    resolve_per_channel_recovery,
)


def advanced_escalation_callback(context: OperatorEscalationContext):
    if context.error.detailed_errors:
        channel_actions = {}
        if len(context.error.detailed_errors) > 0:
            channel_actions[context.error.detailed_errors[0].uuid] = RecoveryAction.EXCLUDE
        if len(context.error.detailed_errors) > 1:
            channel_actions[context.error.detailed_errors[1].uuid] = RecoveryAction.REPEAT
        return resolve_per_channel_recovery(context, channel_actions)
    return RecoveryAction.ABORT
```

### Access Actions (Door and Load Tray)

While a callback is deciding, the front cover stays locked and the Vantage loading tray stays raised. VENUS lists the access actions that currently apply on the error itself (`context.error.actions`): unlock or lock the door, and on a Vantage lower or raise the load tray. They do not answer the error — the instrument carries the action out and publishes the same error again, and the callback is invoked again with it (now listing the opposite action).

```python
from hamilton_venus import RecoveryAction
from hamilton_venus.error_handling import access_action_recovery, access_actions

def handle_operator_error(context):
    offered = access_actions(context.error)   # [{"id": 4222, "key": "unlock_door", "label": "Unlock Door"}, ...]
    choice = show_dialog(context, offered)    # your UI
    if choice in {item["key"] for item in offered}:
        return access_action_recovery(context.error, choice)  # the callback is called again afterwards
    return RecoveryAction(choice)
```

Keys are `unlock_door`, `lock_door`, `lower_load_tray` and `raise_load_tray`. Any recovery, timeout or abort locks the door and raises the tray again.

### Operator Callback Best Practices

**Do:**
- Show error details clearly
- Offer only available options from `context.top_level_actions` and `context.per_channel_actions`
- Return quickly
- Log the user's choice

**Don't:**
- Raise exceptions (return `None` to abort)
- Perform long-running operations
- Assume fixed action IDs; resolve IDs from the current context when returning `ErrorRecovery`

## Creating Custom Profiles

A complete profile maps operations and error types to recovery rules:

```python
from hamilton_venus.error_handling import ErrorProfile, ErrorEntry
from hamilton_venus.models.error_types import (
    RecoveryAction,
    TipPickupError,
    AspirateError,
    DispenseError,
)

profile = ErrorProfile(
    name="My_Custom_Profile",
    default=ErrorEntry(
        actions=(),
        allow_operator=True,
    ),
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT),
                max_retries=3,
                allow_operator=True,
            ),
        },
        "aspirate": {
            AspirateError.CLOT: ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.EXCLUDE),
                max_retries=2,
            ),
        },
        "dispense": {
            DispenseError.INSUFFICIENT: ErrorEntry(
                actions=(RecoveryAction.EXCLUDE,),
                max_retries=0,
            ),
        },
    },
)
```

## Complete Example

Here's a complete working example:

```python
from hamilton_venus import (
    OperatorEscalationContext,
    RecoveryAction,
    StarClient,
    resolve_error_recovery,
)
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry
from hamilton_venus.models.error_types import TipPickupError

my_profile = STANDARD_PROFILE.with_overrides(
    name="Production_Workflow",
    operations={
        "tip_pickup": {
            TipPickupError.NO_TIP: ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT),
                max_retries=2,
                allow_operator=True,
            ),
        },
    },
)


def handle_error(context: OperatorEscalationContext):
    print(f"Operator attention: {context.error.code} ({context.error.message})")

    preferred = [RecoveryAction.NEXT, RecoveryAction.REPEAT, RecoveryAction.ABORT]
    available = {a.name.lower() for a in context.top_level_actions}
    for action in preferred:
        if action.value in available:
            return resolve_error_recovery(context, action)

    return RecoveryAction.ABORT


with StarClient(error_profile=my_profile, on_operator_error_escalation=handle_error) as star:
    star.instrument_init()
    try:
        result = star.tip_pickup(tip_pool="TransferTips")  # tip pool defined in your deck layout
    except Exception as e:
        print(f"Failed: {e}")
```

## Troubleshooting

### Operator callback not being called

- Verify `allow_operator=True` in your ErrorEntry
- Ensure the callback is registered before errors occur
- Check if retries are exhausted (callback only fires after retries)

### Profile validation fails

- Ensure operation names are correct — see the **Operation Names and Their Error Types** table in the Reference section below
- Verify the profile structure matches the ErrorProfile definition
- Check that you're using the correct error type enum for the operation
- Check that the actions you specified are in `ALLOWED_ACTIONS` for that error type — the `ValueError` message lists the allowed set. `RecoveryAction.CANCEL` is always valid and never raises.

### Errors being automatically aborted

- Verify the profile has recovery actions defined for this error
- Verify `allow_operator=True` (with `False`, the SDK submits ABORT once actions are exhausted)
- If you registered an operator callback, check that it does not return `None` (treated as ABORT)
- Review error logs to see what actions were attempted

## Reference: Operations, Error Types, and Recovery Actions

This section lists every value you may need when writing a profile, so you don't have to read source code to find them.

### Imports

All error type enums and `RecoveryAction` live in one module:

```python
from hamilton_venus.models.error_types import (
    RecoveryAction,
    # pick the error type enum(s) for your operation:
    TipPickupError, TipEjectError,
    AspirateError, DispenseError, DispenseFlyError, Aspirate2ndPhaseError,
    XLTipPickupError, XLTipEjectError,
    XLAspirateError, XLDispenseError, XLDispenseFlyError, XLMoveToPositionError,
    Head96TipPickUpError, Head96TipEjectError,
    Head96AspirateError, Head96DispenseError,
    Head96MoveError, Head96WashError, Head96EmptyWasherError,
    EasyAspirateError, EasyDispenseError,
    EasyHead96AspirateError, EasyHead96DispenseError,
    COREGripTransportError,
    ZSwapGetPlateError, ZSwapPlacePlateError, ZSwapReadBarcodeError,
    XLZSwapGetPlateError, XLZSwapPlacePlateError, XLZSwapReadBarcodeError,
    GripperError, AutoloadError, InitializeError,
    MoveToPositionError, NeedleWashError, CoverError, MagPipError,
)
```

### Operation Names and Their Error Types

The string keys used in `operations` and `operation_defaults` dicts are the `.value` of each `OperationCategory` member. The table below maps each key to its error type enum class.

| Operation key | Error type enum | Instrument / notes |
|---|---|---|
| `tip_pickup` | `TipPickupError` | 1000µL channels |
| `tip_eject` | `TipEjectError` | 1000µL channels |
| `aspirate` | `AspirateError` | 1000µL channels |
| `dispense` | `DispenseError` | 1000µL channels |
| `dispense_fly` | `DispenseFlyError` | 1000µL channels, jet dispense |
| `aspirate_2nd_phase` | `Aspirate2ndPhaseError` | 1000µL channels, 2nd phase |
| `move_to_position` | `MoveToPositionError` | 1000µL channel movement |
| `xl_tip_pickup` | `XLTipPickupError` | 5mL (XL) channels |
| `xl_tip_eject` | `XLTipEjectError` | 5mL (XL) channels |
| `xl_aspirate` | `XLAspirateError` | 5mL (XL) channels |
| `xl_dispense` | `XLDispenseError` | 5mL (XL) channels |
| `xl_dispense_fly` | `XLDispenseFlyError` | 5mL (XL) channels |
| `xl_move_to_position` | `XLMoveToPositionError` | 5mL (XL) channel movement |
| `head96_tip_pickup` | `Head96TipPickUpError` | CO-RE 96 head |
| `head96_tip_eject` | `Head96TipEjectError` | CO-RE 96 head |
| `head96_aspirate` | `Head96AspirateError` | CO-RE 96 head |
| `head96_dispense` | `Head96DispenseError` | CO-RE 96 head |
| `head96_move` | `Head96MoveError` | CO-RE 96 head movement |
| `head96_wash` | `Head96WashError` | CO-RE 96 head wash |
| `head96_empty_washer` | `Head96EmptyWasherError` | CO-RE 96 head |
| `easy_aspirate` | `EasyAspirateError` | Autoload/IDL channels |
| `easy_dispense` | `EasyDispenseError` | Autoload/IDL channels |
| `easy_head96_aspirate` | `EasyHead96AspirateError` | Easy CO-RE 96 head |
| `easy_head96_dispense` | `EasyHead96DispenseError` | Easy CO-RE 96 head |
| `core_grip_transport` | `COREGripTransportError` | CO-RE grip transport |
| `zswap_get_plate` | `ZSwapGetPlateError` | Z-Swap |
| `zswap_place_plate` | `ZSwapPlacePlateError` | Z-Swap |
| `zswap_read_barcode` | `ZSwapReadBarcodeError` | Z-Swap |
| `xl_zswap_get_plate` | `XLZSwapGetPlateError` | XL Z-Swap |
| `xl_zswap_place_plate` | `XLZSwapPlacePlateError` | XL Z-Swap |
| `xl_zswap_read_barcode` | `XLZSwapReadBarcodeError` | XL Z-Swap |
| `gripper` | `GripperError` | iSWAP / IPG gripper |
| `autoload` | `AutoloadError` | Autoload / IDL |
| `initialize` | `InitializeError` | Module initialization |
| `needle_wash` | `NeedleWashError` | Needle wash — STAR only |
| `lock_front_cover` | `CoverError` | Front cover lock |
| `magpip` | `MagPipError` | MagPip — VANTAGE only |

### Recovery Actions

| Action | Kind | Meaning |
|---|---|---|
| `CANCEL` | Recovery | Exit default error handling; always valid for every error type |
| `REPEAT` | Recovery | Retry the failed operation |
| `EXCLUDE` | Recovery | Remove the channel/well from the current run |
| `ABORT` | Recovery | Stop the run immediately |
| `CONTINUE` | Recovery | Proceed without any corrective step |
| `NEXT` | Recovery | Skip to the next item in the sequence |
| `WASTE` | Recovery | Discard the current content |
| `BOTTOM` | Recovery | Move to the bottom of the container and retry |
| `AIR` | Recovery | Add an air gap and retry |
| `AVAILABLE` | Recovery | Use whatever volume is available |
| `BARCODE` | Recovery | Retry barcode reading |
| `INITIALIZE` | Action | Re-initialize the hardware module |

### Which Actions Are Valid for Each Error Type

Not every action is valid for every error type. The SDK validates this automatically at profile construction time: if you specify an illegal action, `ErrorProfile(...)` raises a `ValueError`.

To inspect the allowed actions for a specific error type at runtime:

```python
from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS
from hamilton_venus.models.error_types import AspirateError

allowed = ALLOWED_ACTIONS[AspirateError.CLOT]
print(allowed)
# {<RecoveryAction.ABORT: 'abort'>, <RecoveryAction.EXCLUDE: 'exclude'>, <RecoveryAction.REPEAT: 'repeat'>}
```

To see all entries at once:

```python
from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS

for error_type, actions in ALLOWED_ACTIONS.items():
    print(f"{type(error_type).__name__}.{error_type.name}: {[a.value for a in actions]}")
```

The source of truth for all allowed-action sets is in:

- `src/hamilton_venus/error_handling/_actions_tip_handling.py` — tip pickup/eject
- `src/hamilton_venus/error_handling/_actions_aspirate.py` — aspiration
- `src/hamilton_venus/error_handling/_actions_dispense.py` — dispense
- `src/hamilton_venus/error_handling/_actions_transport.py` — grip/transport
- `src/hamilton_venus/error_handling/_actions_system.py` — system/utility

### Adding Operations to the Standard Profile

The `STANDARD_PROFILE` covers `tip_pickup`, `aspirate`, and `dispense` with per-error-type rules. Every other operation falls through to the global default (operator escalation; if no callback is registered the SDK defers to the legacy VENUS operator dialog via `selected_action_id=-1`). To add coverage for an additional operation — for example gripper errors — extend the profile with `with_overrides`:

```python
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry
from hamilton_venus.models.error_types import RecoveryAction, GripperError

my_profile = STANDARD_PROFILE.with_overrides(
    name="Extended",
    operations={
        "gripper": {
            GripperError.LABWARE_LOST: ErrorEntry(
                actions=(RecoveryAction.REPEAT,),
                max_retries=2,
                allow_operator=True,
            ),
            GripperError.HARDWARE: ErrorEntry(
                actions=(),
                allow_operator=True,
            ),
        },
    },
)
```

You can also supply an operation-level default that applies to all error types within that operation that don't have an explicit rule:

```python
my_profile = STANDARD_PROFILE.with_overrides(
    name="Extended",
    operations={
        "gripper": {
            GripperError.LABWARE_LOST: ErrorEntry(
                actions=(RecoveryAction.REPEAT,),
                max_retries=2,
                allow_operator=True,
            ),
        },
    },
    operation_defaults={
        "gripper": ErrorEntry(
            actions=(),
            allow_operator=True,
        ),
    },
)
```

For broad defaults by error type across all operations, use `error_defaults`:

```python
my_profile = STANDARD_PROFILE.with_overrides(
    name="NotExecutedDefault",
    error_defaults={
        "NOT_EXECUTED": ErrorEntry(
            actions=(RecoveryAction.REPEAT,),
            max_retries=1,
            allow_operator=True,
        ),
    },
)
```

When selecting a rule, the resolver applies precedence in this order:

1. exact operation+error match in `operations`
2. `error_defaults[error_type.name]`
3. `operation_defaults[operation_name]`
4. global `default`

**Note on `error_defaults` action validity:**
`error_defaults` entries are validated against every error enum member with that name across all operations. If an action is invalid for any matching error type, profile construction raises `ValueError`.

**Note on `operation_defaults` action validity:** An operation default applies to any error type in that operation that doesn't have an explicit rule. Because different error types within the same operation have different allowed actions, the SDK cannot validate `operation_defaults` actions at profile construction time. Instead, any action in an `operation_default` that is not valid for the specific error that occurred is silently skipped at runtime, and the resolver advances to the next action in the chain. `RecoveryAction.ABORT` is the only action guaranteed to be accepted for every error type and is always safe as a final fallback in an operation default.

### Profile Validation Guarantees

When you construct an `ErrorProfile`:

- Every error type in `operations` must exist in `ALLOWED_ACTIONS`. An unrecognized enum member raises `ValueError`.
- Every action in each `ErrorEntry.actions` tuple must be in `ALLOWED_ACTIONS[error_type]`. An unsupported action raises `ValueError` immediately.
- `RecoveryAction.CANCEL` is always valid for any error type and is never rejected by validation. It exits default error handling unconditionally.

This means profile errors are caught at startup, not during a run.

## See Also

- [Configuration](configuration.md) - Configure other SDK aspects
- [Authentication](authentication.md) - Secure VENUS connections
