from logging import DEBUG

from hamilton_venus import (
    OperatorEscalationContext,
    RecoveryAction,
    StarClient,
    resolve_error_recovery,
    resolve_per_channel_recovery,
)
from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY
ERROR_HANDLING_KEY = "hamiltonvenussdk"


def resolved_builder_callback(context: OperatorEscalationContext):
    error = context.error
    print(f"Escalated error uuid={error.uuid} code={error.code} message={error.message}")

    if context.is_per_channel_escalation and error.detailed_errors:
        per_channel_available = {a.name.lower() for a in context.per_channel_actions}
        exclude_allowed = RecoveryAction.EXCLUDE.value in per_channel_available
        repeat_allowed = RecoveryAction.REPEAT.value in per_channel_available

        if exclude_allowed or repeat_allowed:
            channel_actions: dict[str, RecoveryAction] = {}
            for index, detail in enumerate(error.detailed_errors):
                action = RecoveryAction.EXCLUDE if exclude_allowed else RecoveryAction.REPEAT
                if index == 1 and repeat_allowed:
                    action = RecoveryAction.REPEAT
                channel_actions[detail.uuid] = action
            print(f"Returning resolved per-channel recovery for all channels ({len(channel_actions)})")
            return resolve_per_channel_recovery(
                context,
                channel_actions,
                error_handling_key=ERROR_HANDLING_KEY,
            )

    available_top_level = {a.name.lower() for a in context.top_level_actions}
    for action in (RecoveryAction.REPEAT, RecoveryAction.NEXT, RecoveryAction.ABORT):
        if action.value in available_top_level:
            print(f"Returning resolved top-level action: {action.value}")
            return resolve_error_recovery(
                context,
                action,
                error_handling_key=ERROR_HANDLING_KEY,
            )

    print("No matching action found, falling back to ABORT")
    return RecoveryAction.ABORT


with StarClient(
    deck_name="example_deck",
    logging_level=DEBUG,
    venus_trace_logging=True,
    on_operator_error_escalation=resolved_builder_callback,
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
