import tkinter as tk
from logging import DEBUG

from hamilton_venus import (
    OperatorEscalationContext,
    RecoveryAction,
    StarClient,
    resolve_per_channel_recovery,
)
from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


def show_allowed_operations_dialog(context: OperatorEscalationContext):
    """Interactive operator escalation dialog example.

    This smoke test demonstrates the escalation callback pattern. Users can:
    1. Return a RecoveryAction enum (as this example does) for simple single-action
       decisions; the SDK's resolver will automatically dispatch to the correct
       submission path (top-level vs per-channel).
    2. Build and return custom ErrorRecovery payloads using build_error_recovery(),
       build_per_channel_recovery(), or build_mixed_recovery() and then resolve
       server IDs before submission for fine-grained per-channel control.
    3. Call star_client.submit_error_recovery() directly within the callback if you
       need to handle multiple channels with different actions programmatically.

    Example of advanced per-channel control:
        recovery = resolve_per_channel_recovery(
            context,
            {
                context.error.detailed_errors[0].uuid: RecoveryAction.EXCLUDE,
                context.error.detailed_errors[1].uuid: RecoveryAction.REPEAT,
            },
        )
        return recovery
    """
    error_data = context.error

    # Debug logging
    print("\n[DEBUG] Escalation context:")
    print(f"  - Error UUID: {error_data.uuid}")
    print(f"  - Error Code: {error_data.code}")
    print(f"  - Message: {error_data.message}")
    print(f"  - Is per-channel: {context.is_per_channel_escalation}")
    print(f"  - Operation category: {context.operation_category}")
    print(f"  - Error type: {context.error_type}")
    print(f"  - Top-level actions count: {len(context.top_level_actions)}")
    print(f"  - Top-level actions: {[a.name for a in context.top_level_actions]}")
    print(f"  - Per-channel actions count: {len(context.per_channel_actions)}")
    print(f"  - Per-channel actions: {[a.name for a in context.per_channel_actions]}")
    print(f"  - error.recovery_actions from raw: {[a.name for a in error_data.recovery_actions]}")
    print(f"  - Number of detailed errors: {len(error_data.detailed_errors) if error_data.detailed_errors else 0}")
    if error_data.detailed_errors:
        for i, detail in enumerate(error_data.detailed_errors[:2]):  # Show first 2
            print(f"    - Channel {i}: {len(detail.recovery_actions) if detail.recovery_actions else 0} actions")
    print()

    dialog = tk.Tk()
    dialog.title("Operator Escalation")
    dialog.geometry("700x480")
    chosen = {"action": None}

    # Build classification info string
    classification_str = ""
    if context.operation_category and context.error_type:
        classification_str = f" ({context.operation_category.name}: {context.error_type.name})"
    elif context.operation_category:
        classification_str = f" ({context.operation_category.name})"

    escalation_type = "Per-Channel" if context.is_per_channel_escalation else "Top-Level"

    header = tk.Label(
        dialog,
        text=f"{escalation_type} Error {error_data.code or ''} on device {error_data.device_id}{classification_str}",
        font=("Segoe UI", 11, "bold"),
        wraplength=660,
        justify="left",
        anchor="w",
    )
    header.pack(fill="x", padx=16, pady=(16, 6))

    message = tk.Message(dialog, text=error_data.message or "", width=660)
    message.pack(fill="x", padx=16, pady=(0, 12))

    # Show available actions
    actions_frame = tk.Frame(dialog)
    actions_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

    def pick(action: RecoveryAction):
        chosen["action"] = action
        dialog.destroy()

    labels: dict[RecoveryAction, str] = {}

    def normalize_actions(action_descriptors):
        """Convert RecoveryActionDescriptor objects to RecoveryAction enums."""
        actions: list[RecoveryAction] = []
        for action_desc in action_descriptors or []:
            # action_desc.name is like 'Execute', 'Abort', 'Cancel', 'Exclude', 'Repeat', 'Next'
            # We need to map to RecoveryAction enum values (lowercase)
            action_name = action_desc.name.lower()
            try:
                action = RecoveryAction(action_name)
                if action not in actions:
                    actions.append(action)
                    labels[action] = action_desc.name  # Store original name for display
            except ValueError:
                # Action not recognized; skip it
                pass
        return actions

    # Convert descriptor lists to RecoveryAction enums
    top_level_actions = normalize_actions(context.top_level_actions)
    per_channel_actions = normalize_actions(context.per_channel_actions)

    # Build display actions with sections
    # For per-channel escalations, show both top-level and per-channel actions
    # The resolver will handle them appropriately
    display_sections = []

    if top_level_actions:
        display_sections.append(("Top-Level Actions:", top_level_actions))

    if per_channel_actions:
        display_sections.append(("Per-Channel Actions:", per_channel_actions))

    # If no actions determined, default to ABORT/CANCEL
    if not display_sections:
        print("[WARNING] No actions available; offering fallback options")
        display_sections = [("Recovery Options:", [RecoveryAction.ABORT, RecoveryAction.CANCEL])]

    # Add section headers and buttons
    for section_label, actions_in_section in display_sections:
        tk.Label(
            actions_frame,
            text=section_label,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=0, pady=(4, 4))

        for action in actions_in_section:
            button_text = labels.get(action, action.value.title())
            tk.Button(
                actions_frame,
                text=button_text,
                width=30,
                command=lambda a=action: pick(a),
            ).pack(anchor="w", pady=2)

    dialog.mainloop()
    print(
        f"Operator dialog selection for error uuid={error_data.uuid}: "
        f"{chosen['action'].value if chosen['action'] else 'abort'}"
    )
    return chosen["action"] if chosen["action"] else RecoveryAction.ABORT


# Example: Advanced escalation callback using ErrorRecovery builder
# This callback would apply different recovery actions to different channels
def advanced_escalation_callback(context: OperatorEscalationContext):
    """Example showing how to build and return custom ErrorRecovery payloads.

    This allows fine-grained control over per-channel recovery actions.
    """
    if context.error.detailed_errors:
        channel_actions = {}
        if len(context.error.detailed_errors) > 0:
            channel_actions[context.error.detailed_errors[0].uuid] = RecoveryAction.EXCLUDE
        if len(context.error.detailed_errors) > 1:
            channel_actions[context.error.detailed_errors[1].uuid] = RecoveryAction.REPEAT

        return resolve_per_channel_recovery(context, channel_actions)

    # Fallback to top-level abort
    return RecoveryAction.ABORT


with StarClient(
    deck_name="example_deck",
    logging_level=DEBUG,
    venus_trace_logging=True,
    on_operator_error_escalation=show_allowed_operations_dialog,
) as star:
    star.instrument_init()

    init_tips_response = star.tip_pool_initialize_tip_counter("transfer_tips")
    print(f"Init tips response: {init_tips_response.model_dump(by_alias=True)}")
    reset_tips_response = star.tip_pool_reset_tip_counter("transfer_tips")
    print(f"Reset tips response: {reset_tips_response.model_dump(by_alias=True)}")

    star.tip_pickup(tip_pool="transfer_tips")
    star.aspirate(positions="source_plate@col:1", volumes=50.0, liquid_class=liquid_class)
    star.dispense(positions="dest_plate@col:1", volumes=50.0)
    star.tip_eject()
