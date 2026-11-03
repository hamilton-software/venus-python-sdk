"""Direct tests for recovery_from_operator_response, the operator-answer -> SDK-recovery
conversion shared by WorkflowSession and the MCP server's script runner.

The behaviour itself is exercised end to end (through a session) by
test_session_operator_escalation.py; these pin the function's own contract so a second caller
can rely on it: a missing, empty, or unrecognised answer is always ABORT (None).
"""

from __future__ import annotations

import unittest

from hamilton_venus.models import DetailedErrorRecovery, ErrorRecovery, RecoveryAction
from hamilton_venus.models.instrument_errors import Action, Attribute, DetailedError, ErrorData, RecoveryActionDescriptor

from hamilton_workflow_framework.session import recovery_from_operator_response

_TOP_LEVEL = [
    RecoveryActionDescriptor(id=99, name="Execute", index=0),
    RecoveryActionDescriptor(id=1, name="Abort", index=1),
    RecoveryActionDescriptor(id=2, name="Cancel", index=2),
]


def _detail(uuid: str, channel: str) -> DetailedError:
    actions = [RecoveryActionDescriptor(id=1026, name="Repeat", index=0)]
    return DetailedError(
        uuid=uuid,
        index=int(channel),
        message="Parameter out of range.",
        attributes=[Attribute(name="channel", value=channel)],
        recoveryActions=actions,
        defaultRecoveryActionId=1026,
    )


def _per_channel_error() -> ErrorData:
    return ErrorData(
        uuid="err-1",
        code="P1:01/32",
        detailedErrors=[_detail("d1", "1"), _detail("d2", "2")],
        recoveryActions=_TOP_LEVEL,
    )


class RecoveryFromOperatorResponseTests(unittest.TestCase):
    def test_no_answer_is_abort(self):
        lines: list[str] = []
        self.assertIsNone(recovery_from_operator_response(_per_channel_error(), None, lines.append))
        self.assertTrue(any("submitting ABORT" in line for line in lines))

    def test_empty_or_unrecognised_answers_are_abort(self):
        error = _per_channel_error()
        for response in ({}, {"kind": "action"}, {"kind": "action", "action": ""}, {"kind": "action", "action": "explode"}):
            with self.subTest(response=response):
                self.assertIsNone(recovery_from_operator_response(error, response))

    def test_empty_per_channel_selection_is_abort(self):
        self.assertIsNone(recovery_from_operator_response(_per_channel_error(), {"kind": "channels", "channel_actions": {}}))

    def test_error_wide_action_is_applied_to_every_channel_explicitly(self):
        result = recovery_from_operator_response(_per_channel_error(), {"kind": "action", "action": "Abort"})
        self.assertIsInstance(result, ErrorRecovery)
        self.assertEqual(result.selected_action_id, 1)
        self.assertEqual({d.uuid: d.selected_action_id for d in result.detailed_error_recoveries}, {"d1": 1, "d2": 1})

    def test_per_channel_picks_use_the_execute_wrapper_id(self):
        response = {"kind": "channels", "channel_actions": {"d1": 1026, "d2": "1026"}}
        result = recovery_from_operator_response(_per_channel_error(), response)
        self.assertIsInstance(result, ErrorRecovery)
        self.assertEqual(result.selected_action_id, 99)
        self.assertTrue(all(isinstance(d, DetailedErrorRecovery) for d in result.detailed_error_recoveries))
        self.assertEqual({d.uuid: d.selected_action_id for d in result.detailed_error_recoveries}, {"d1": 1026, "d2": 1026})

    def test_top_level_only_error_hands_back_a_plain_recovery_action(self):
        error = ErrorData(uuid="err-2", code="X", recoveryActions=_TOP_LEVEL)
        result = recovery_from_operator_response(error, {"kind": "action", "action": "abort"})
        self.assertIs(result, RecoveryAction.ABORT)

    def test_access_action_is_an_action_that_leaves_the_error_open(self):
        error = _per_channel_error()
        error.actions = [Action(id=4222, name="Unlock front cover", index=0)]
        result = recovery_from_operator_response(error, {"kind": "action", "action": "unlock_door"})
        self.assertIsInstance(result, ErrorRecovery)
        self.assertEqual(result.selected_action_id, 4222)
        self.assertFalse(result.selected_action_is_recovery)
        self.assertIsNone(result.detailed_error_recoveries)

    def test_access_action_the_error_does_not_list_is_abort(self):
        result = recovery_from_operator_response(_per_channel_error(), {"kind": "action", "action": "lock_door"})
        self.assertIsNone(result)

    def test_logging_is_optional(self):
        self.assertIs(
            recovery_from_operator_response(ErrorData(uuid="err-3", code="X"), {"kind": "action", "action": "abort"}),
            RecoveryAction.ABORT,
        )


if __name__ == "__main__":
    unittest.main()
