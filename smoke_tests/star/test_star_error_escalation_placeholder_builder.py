from logging import DEBUG

from hamilton_venus import (
    OperatorEscalationContext,
    RecoveryAction,
    StarClient,
    build_error_recovery,
    build_per_channel_recovery,
)
from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.WATER.JET_EMPTY.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY


def placeholder_builder_callback(context: OperatorEscalationContext):
    error = context.error
    print(f"Escalated error uuid={error.uuid} code={error.code} message={error.message}")

    if error.detailed_errors:
        channel_actions = {}
        if len(error.detailed_errors) > 0:
            channel_actions[error.detailed_errors[0].uuid] = RecoveryAction.EXCLUDE
        if len(error.detailed_errors) > 1:
            channel_actions[error.detailed_errors[1].uuid] = RecoveryAction.REPEAT
        if channel_actions:
            print(f"Returning placeholder per-channel recovery for {list(channel_actions.keys())}")
            return build_per_channel_recovery(error.uuid, channel_actions)

    available_top_level = {a.name.lower() for a in context.top_level_actions}
    for action in (RecoveryAction.REPEAT, RecoveryAction.NEXT, RecoveryAction.ABORT):
        if action.value in available_top_level:
            print(f"Returning placeholder top-level action: {action.value}")
            return build_error_recovery(error.uuid, action)

    print("No matching action found, falling back to ABORT")
    return RecoveryAction.ABORT


with StarClient(
    deck_name="example_deck",
    logging_level=DEBUG,
    venus_trace_logging=True,
    on_operator_error_escalation=placeholder_builder_callback,
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
