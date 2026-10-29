"""Unit tests for the instrument access actions (door / loading tray)."""

from __future__ import annotations

from hamilton_venus.error_handling.access_actions import (
    access_action_recovery,
    access_actions,
    is_access_action_recovery,
)
from hamilton_venus.models.instrument_errors import Action, ErrorData, RecoveryActionDescriptor


def _error(*action_ids: int) -> ErrorData:
    return ErrorData(
        uuid="err-1",
        code="08",
        actions=[Action(id=action_id, name=f"action {action_id}", index=i) for i, action_id in enumerate(action_ids)],
        recovery_actions=[RecoveryActionDescriptor(id=2, name="Abort", index=0)],
    )


def test_only_listed_access_actions_are_offered():
    assert access_actions(_error()) == []
    assert access_actions(_error(4220, 4222, 77)) == [
        {"id": 4220, "key": "lower_load_tray", "label": "Lower Load Tray"},
        {"id": 4222, "key": "unlock_door", "label": "Unlock Door"},
    ]
    assert [a["label"] for a in access_actions(_error(4221, 4223))] == ["Raise Load Tray", "Lock Door"]


def test_recovery_for_a_listed_access_action():
    recovery = access_action_recovery(_error(4221, 4223), "Lock_Door")
    assert recovery is not None
    assert recovery.uuid == "err-1"
    assert recovery.selected_action_id == 4223
    assert recovery.selected_action_is_recovery is False
    assert is_access_action_recovery(recovery)


def test_no_recovery_for_an_action_that_is_not_listed():
    assert access_action_recovery(_error(4220), "raise_load_tray") is None
    assert access_action_recovery(_error(4220), "abort") is None
    assert access_action_recovery(_error(4220), None) is None
