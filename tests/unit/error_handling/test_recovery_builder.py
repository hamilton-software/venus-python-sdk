from __future__ import annotations

import pytest

from hamilton_venus import OperatorEscalationContext
from hamilton_venus.error_handling import ErrorEntry
from hamilton_venus.error_handling.recovery_builder import (
    build_error_recovery,
    build_mixed_recovery,
    build_per_channel_recovery,
    resolve_error_recovery,
    resolve_per_channel_recovery,
)
from hamilton_venus.models import DetailedError, ErrorData, RecoveryAction, RecoveryActionDescriptor


def _sample_context_with_top_level_actions() -> OperatorEscalationContext:
    return OperatorEscalationContext(
        error=ErrorData(
            uuid="err-ctx",
            code="08",
            device_id=1,
            recovery_actions=[
                RecoveryActionDescriptor(id=101, name="Abort", index=0),
                RecoveryActionDescriptor(id=102, name="Repeat", index=1),
                RecoveryActionDescriptor(id=103, name="Execute", index=2),
            ],
        ),
        entry=ErrorEntry(actions=(RecoveryAction.ABORT,), allow_operator=True, max_retries=0),
        operation_category=None,
        error_type=None,
        top_level_actions=[
            RecoveryActionDescriptor(id=101, name="Abort", index=0),
            RecoveryActionDescriptor(id=102, name="Repeat", index=1),
            RecoveryActionDescriptor(id=103, name="Execute", index=2),
        ],
        per_channel_actions=[],
        is_per_channel_escalation=False,
    )


def _sample_context_with_channel_actions() -> OperatorEscalationContext:
    ch1 = DetailedError(
        uuid="ch-1",
        index=1,
        recovery_actions=[
            RecoveryActionDescriptor(id=201, name="Exclude", index=0),
            RecoveryActionDescriptor(id=202, name="Repeat", index=1),
        ],
    )
    ch2 = DetailedError(
        uuid="ch-2",
        index=2,
        recovery_actions=[
            RecoveryActionDescriptor(id=301, name="Exclude", index=0),
            RecoveryActionDescriptor(id=302, name="Repeat", index=1),
        ],
    )
    return OperatorEscalationContext(
        error=ErrorData(
            uuid="err-ctx-d",
            code="08",
            device_id=1,
            detailed_errors=[ch1, ch2],
            recovery_actions=[RecoveryActionDescriptor(id=401, name="Execute", index=0)],
        ),
        entry=ErrorEntry(actions=(RecoveryAction.ABORT,), allow_operator=True, max_retries=0),
        operation_category=None,
        error_type=None,
        top_level_actions=[RecoveryActionDescriptor(id=401, name="Execute", index=0)],
        per_channel_actions=[
            RecoveryActionDescriptor(id=201, name="Exclude", index=0),
            RecoveryActionDescriptor(id=202, name="Repeat", index=1),
        ],
        is_per_channel_escalation=True,
    )


def test_build_error_recovery_uses_minus_one_and_recovery_true() -> None:
    payload = build_error_recovery("err-1", RecoveryAction.ABORT, error_handling_key="k")

    assert payload.uuid == "err-1"
    assert payload.selected_action_id == -1
    assert payload.selected_action_is_recovery is True
    assert payload.error_handling_key == "k"
    assert payload.detailed_error_recoveries is None


def test_build_error_recovery_rejects_action_kind() -> None:
    with pytest.raises(ValueError, match="must be a recovery action"):
        build_error_recovery("err-1", RecoveryAction.INITIALIZE)


def test_build_per_channel_recovery_sets_minus_one_for_top_and_channels() -> None:
    payload = build_per_channel_recovery(
        "err-2",
        {
            "ch-1": RecoveryAction.REPEAT,
            "ch-2": RecoveryAction.EXCLUDE,
        },
    )

    assert payload.uuid == "err-2"
    assert payload.selected_action_id == -1
    assert payload.selected_action_is_recovery is True
    assert payload.detailed_error_recoveries is not None
    assert {d.uuid: d.selected_action_id for d in payload.detailed_error_recoveries} == {
        "ch-1": -1,
        "ch-2": -1,
    }


def test_build_per_channel_recovery_rejects_empty_channel_actions() -> None:
    with pytest.raises(ValueError, match="at least one channel UUID"):
        build_per_channel_recovery("err-3", {})


def test_build_per_channel_recovery_rejects_action_kind() -> None:
    with pytest.raises(ValueError, match="must be a recovery action"):
        build_per_channel_recovery("err-4", {"ch-1": RecoveryAction.INITIALIZE})


def test_build_mixed_recovery_without_channels_has_no_detailed_recoveries() -> None:
    payload = build_mixed_recovery("err-5")

    assert payload.selected_action_id == -1
    assert payload.selected_action_is_recovery is True
    assert payload.detailed_error_recoveries is None


def test_build_mixed_recovery_with_channels_sets_minus_one_everywhere() -> None:
    payload = build_mixed_recovery(
        "err-6",
        channel_actions={"ch-1": RecoveryAction.REPEAT},
    )

    assert payload.selected_action_id == -1
    assert payload.selected_action_is_recovery is True
    assert payload.detailed_error_recoveries is not None
    assert len(payload.detailed_error_recoveries) == 1
    assert payload.detailed_error_recoveries[0].uuid == "ch-1"
    assert payload.detailed_error_recoveries[0].selected_action_id == -1


def test_resolve_error_recovery_sets_server_id_from_context() -> None:
    context = _sample_context_with_top_level_actions()

    payload = resolve_error_recovery(context, RecoveryAction.ABORT, error_handling_key="k")

    assert payload.uuid == "err-ctx"
    assert payload.selected_action_id == 101
    assert payload.selected_action_is_recovery is True
    assert payload.error_handling_key == "k"
    assert payload.detailed_error_recoveries is None


def test_resolve_error_recovery_raises_when_action_not_advertised() -> None:
    context = _sample_context_with_top_level_actions()

    with pytest.raises(ValueError, match="not available in top-level actions"):
        resolve_error_recovery(context, RecoveryAction.EXCLUDE)


def test_resolve_per_channel_recovery_builds_execute_plus_channel_ids() -> None:
    context = _sample_context_with_channel_actions()

    payload = resolve_per_channel_recovery(
        context,
        {
            "ch-1": RecoveryAction.EXCLUDE,
            "ch-2": RecoveryAction.REPEAT,
        },
    )

    assert payload.uuid == "err-ctx-d"
    assert payload.selected_action_id == 401
    assert payload.selected_action_is_recovery is True
    assert payload.detailed_error_recoveries is not None
    assert {d.uuid: d.selected_action_id for d in payload.detailed_error_recoveries} == {
        "ch-1": 201,
        "ch-2": 302,
    }


def test_resolve_per_channel_recovery_raises_without_detailed_errors() -> None:
    context = _sample_context_with_top_level_actions()

    with pytest.raises(ValueError, match="detailed_errors is empty"):
        resolve_per_channel_recovery(context, {"ch-1": RecoveryAction.EXCLUDE})


def test_resolve_per_channel_recovery_raises_without_execute_action() -> None:
    context = _sample_context_with_channel_actions()
    context.top_level_actions = [RecoveryActionDescriptor(id=999, name="Abort", index=0)]

    with pytest.raises(ValueError, match="execute is not available"):
        resolve_per_channel_recovery(context, {"ch-1": RecoveryAction.EXCLUDE})


def test_resolve_per_channel_recovery_raises_for_unknown_channel_uuid() -> None:
    context = _sample_context_with_channel_actions()

    with pytest.raises(ValueError, match="channel uuid not found"):
        resolve_per_channel_recovery(context, {"ch-x": RecoveryAction.EXCLUDE})
