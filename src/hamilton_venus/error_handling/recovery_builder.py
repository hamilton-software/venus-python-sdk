"""Utilities for constructing ErrorRecovery payloads in operator escalation callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from hamilton_venus.models import RecoveryAction
from hamilton_venus.models.error_types import ActionKind
from hamilton_venus.models.instrument_errors import (
    DetailedError,
    DetailedErrorRecovery,
    ErrorRecovery,
    RecoveryActionDescriptor,
)

if TYPE_CHECKING:
    from hamilton_venus import OperatorEscalationContext


def _validate_recovery_action(action: RecoveryAction, field_name: str) -> None:
    if action.kind != ActionKind.RECOVERY:
        raise ValueError(f"{field_name} must be a recovery action, got: {action.value}")


def _validate_channel_actions(channel_actions: dict[str, RecoveryAction]) -> None:
    if not channel_actions:
        raise ValueError("channel_actions must include at least one channel UUID")
    for action in channel_actions.values():
        _validate_recovery_action(action, "channel action")


def _resolve_action_id(
    action: RecoveryAction,
    descriptors: list[RecoveryActionDescriptor],
    *,
    source: str,
) -> int:
    for descriptor in descriptors:
        if descriptor.name.lower() == action.value:
            return descriptor.id
    raise ValueError(f"{action.value} is not available in {source}")


def _resolve_execute_id(context: OperatorEscalationContext) -> int:
    for descriptor in context.top_level_actions:
        if descriptor.name.lower() == "execute":
            return descriptor.id
    raise ValueError("execute is not available in top-level actions")


def _detailed_error_by_uuid(
    detailed_errors: list[DetailedError],
    channel_uuid: str,
) -> DetailedError:
    for detail in detailed_errors:
        if detail.uuid == channel_uuid:
            return detail
    raise ValueError(f"channel uuid not found in detailed errors: {channel_uuid}")


def resolve_error_recovery(
    context: OperatorEscalationContext,
    action: RecoveryAction,
    *,
    error_handling_key: str = "",
) -> ErrorRecovery:
    _validate_recovery_action(action, "action")
    now_str = datetime.now(UTC).isoformat()
    selected_action_id = _resolve_action_id(
        action,
        context.top_level_actions,
        source="top-level actions",
    )
    return ErrorRecovery(
        date=now_str,
        uuid=context.error.uuid,
        selected_action_id=selected_action_id,
        selected_action_is_recovery=True,
        error_handling_key=error_handling_key,
    )


def resolve_per_channel_recovery(
    context: OperatorEscalationContext,
    channel_actions: dict[str, RecoveryAction],
    *,
    error_handling_key: str = "",
) -> ErrorRecovery:
    _validate_channel_actions(channel_actions)
    detailed_errors = context.error.detailed_errors or []
    if not detailed_errors:
        raise ValueError("context.error.detailed_errors is empty")

    now_str = datetime.now(UTC).isoformat()
    detailed_recoveries = []
    for channel_uuid, action in channel_actions.items():
        detail = _detailed_error_by_uuid(detailed_errors, channel_uuid)
        selected_action_id = _resolve_action_id(
            action,
            detail.recovery_actions or [],
            source=f"channel actions for {channel_uuid}",
        )
        detailed_recoveries.append(
            DetailedErrorRecovery(
                date=now_str,
                uuid=channel_uuid,
                selected_action_id=selected_action_id,
            )
        )

    return ErrorRecovery(
        date=now_str,
        uuid=context.error.uuid,
        selected_action_id=_resolve_execute_id(context),
        selected_action_is_recovery=True,
        detailed_error_recoveries=detailed_recoveries,
        error_handling_key=error_handling_key,
    )


def build_error_recovery(
    error_uuid: str,
    action: RecoveryAction,
    *,
    error_handling_key: str = "",
    is_recovery: bool = True,
) -> ErrorRecovery:
    """Build a top-level error recovery payload.

    This helper intentionally sets selected_action_id=-1. The caller must resolve
    and set server-assigned action IDs before submitting when required by VENUS.
    """
    _validate_recovery_action(action, "action")
    if not is_recovery:
        raise ValueError("is_recovery must be True for build_error_recovery")

    now_str = datetime.now(UTC).isoformat()
    return ErrorRecovery(
        date=now_str,
        uuid=error_uuid,
        selected_action_id=-1,
        selected_action_is_recovery=True,
        error_handling_key=error_handling_key,
    )


def build_per_channel_recovery(
    error_uuid: str,
    channel_actions: dict[str, RecoveryAction],
    *,
    error_handling_key: str = "",
    is_recovery: bool = True,
) -> ErrorRecovery:
    """Build a per-channel error recovery payload with detailed channel selections.

    This helper intentionally sets selected_action_id=-1 for top-level and per-channel
    entries. The caller must resolve and set server-assigned action IDs before
    submitting when required by VENUS.
    """
    _validate_channel_actions(channel_actions)
    if not is_recovery:
        raise ValueError("is_recovery must be True for build_per_channel_recovery")

    now_str = datetime.now(UTC).isoformat()
    detailed_recoveries = [
        DetailedErrorRecovery(
            date=now_str,
            uuid=channel_uuid,
            selected_action_id=-1,
        )
        for channel_uuid in channel_actions
    ]
    return ErrorRecovery(
        date=now_str,
        uuid=error_uuid,
        selected_action_id=-1,
        selected_action_is_recovery=True,
        detailed_error_recoveries=detailed_recoveries,
        error_handling_key=error_handling_key,
    )


def build_mixed_recovery(
    error_uuid: str,
    channel_actions: dict[str, RecoveryAction] | None = None,
    *,
    error_handling_key: str = "",
) -> ErrorRecovery:
    """Build an error recovery payload with optional per-channel recoveries.

    This helper intentionally sets selected_action_id=-1. The caller must resolve
    and set server-assigned action IDs before submitting when required by VENUS.
    """
    now_str = datetime.now(UTC).isoformat()
    detailed_recoveries = None
    if channel_actions is not None:
        _validate_channel_actions(channel_actions)
        detailed_recoveries = [
            DetailedErrorRecovery(
                date=now_str,
                uuid=channel_uuid,
                selected_action_id=-1,
            )
            for channel_uuid in channel_actions
        ]

    return ErrorRecovery(
        date=now_str,
        uuid=error_uuid,
        selected_action_id=-1,
        selected_action_is_recovery=True,
        detailed_error_recoveries=detailed_recoveries,
        error_handling_key=error_handling_key,
    )
