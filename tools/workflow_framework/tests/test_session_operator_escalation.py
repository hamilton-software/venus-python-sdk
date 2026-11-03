"""Regression tests for WorkflowSession's operator-escalation Abort/Cancel handling.

Real report: for a genuinely per-channel error (multiple channels, "Ch 1, 2, 3, 4"),
clicking the always-available Abort/Cancel buttons appeared to do nothing -- the modal
closed, but the errored step kept showing as running and VENUS kept waiting for a
response. Confirmed against a live VENUS instance: the SDK's own resolver
(`_error_profile_resolver.py::_submit_abort`) omits `detailed_error_recoveries` whenever
ABORT has a top-level id at all, even for a per-channel escalation -- VENUS rejects that
outright ("The detailed error recoveries are missing").

Two earlier fix attempts were each disproven by a live VENUS instance:

1. Falling back to the *top-level* action id for any channel that didn't advertise the
   action itself: VENUS rejects a per-channel entry whose id isn't genuinely in that
   exact channel's own advertised list ("not in list of recoverable actions").
2. Requiring every channel to *genuinely* advertise the action itself before building a
   per-channel `ErrorRecovery` at all: structurally correct, but never actually fires for
   real Abort/Cancel errors, since no channel ever advertises Abort/Cancel itself --
   they're error-wide, top-level-only concepts (confirmed by the user, who can trigger
   this live: "you can't individually cancel channel errors"). So this just reproduced the
   original bug by falling through to the SDK's still-broken native path.

Current, user-clarified design: Cancel/Abort's own *top-level* id is what VENUS wants as
`ErrorRecovery.selected_action_id` (not the "Execute" wrapper id, which is only for
genuine per-channel operator choices like the Repeat/Continue dropdown). The
`detailed_error_recoveries` array is still structurally required whenever the error has
`detailed_errors` at all, but every entry just carries that *same* top-level id applied
uniformly -- there is no such thing as a channel-specific Cancel/Abort to look up.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from hamilton_venus import OperatorEscalationContext
from hamilton_venus.models import RecoveryAction
from hamilton_venus.models.instrument_errors import Attribute, DetailedError, ErrorData, RecoveryActionDescriptor

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.session import WorkflowSession, _per_detail_action_ids


def _detail(uuid: str, channel: str, *, recovery_actions: list[RecoveryActionDescriptor]) -> DetailedError:
    return DetailedError(
        uuid=uuid,
        index=int(channel),
        message="Parameter out of range.",
        attributes=[Attribute(name="channel", value=channel)],
        recoveryActions=recovery_actions,
        defaultRecoveryActionId=recovery_actions[0].id if recovery_actions else 0,
    )


_REPEAT_ONLY = [
    RecoveryActionDescriptor(id=1026, name="Repeat", index=0),
    RecoveryActionDescriptor(id=1099, name="Execute", index=1),
]
_TOP_LEVEL_ACTIONS = [
    RecoveryActionDescriptor(id=99, name="Execute", index=0),
    RecoveryActionDescriptor(id=1, name="Abort", index=1),
    RecoveryActionDescriptor(id=2, name="Cancel", index=2),
]


def _per_channel_error() -> ErrorData:
    # Mirrors the exact live report: 4 channels, each only advertising Repeat/Execute for
    # itself. Abort/Cancel only ever exist in the error-wide (top-level) recovery_actions --
    # per-channel resolution for them is never expected to find anything, and shouldn't need
    # to: the top-level id is applied uniformly to every channel regardless.
    details = [_detail(f"d{ch}", ch, recovery_actions=_REPEAT_ONLY) for ch in ("1", "2", "3", "4")]
    return ErrorData(
        uuid="err-1",
        code="P1:01/32",
        title="1000ul Channel Aspirate (Single Step) - Error",
        detailedErrors=details,
        recoveryActions=_TOP_LEVEL_ACTIONS,
    )


class PerDetailActionIdsTests(unittest.TestCase):
    def test_applies_top_level_id_uniformly_even_though_no_channel_advertises_it_itself(self) -> None:
        # The exact live-confirmed case: no channel advertises cancel/abort itself, yet every
        # channel must still get an id -- Cancel/Abort are error-wide, not per-channel.
        error = _per_channel_error()
        self.assertEqual(_per_detail_action_ids("cancel", error), {"d1": 2, "d2": 2, "d3": 2, "d4": 2})
        self.assertEqual(_per_detail_action_ids("abort", error), {"d1": 1, "d2": 1, "d3": 1, "d4": 1})

    def test_ignores_a_channels_own_advertised_id_in_favor_of_the_top_level_one(self) -> None:
        # Even if a channel happens to advertise its own id for the same action name, the
        # top-level id wins -- Cancel/Abort are a single error-wide choice, not independent
        # per-channel picks.
        details = [
            _detail(
                "d1",
                "1",
                recovery_actions=[
                    RecoveryActionDescriptor(id=1026, name="Repeat", index=0),
                    RecoveryActionDescriptor(id=201, name="Abort", index=1),
                ],
            ),
        ]
        error = ErrorData(uuid="err-2", detailedErrors=details, recoveryActions=_TOP_LEVEL_ACTIONS)
        self.assertEqual(_per_detail_action_ids("abort", error), {"d1": 1})

    def test_returns_none_when_no_detailed_errors(self) -> None:
        error = ErrorData(uuid="err-3", recoveryActions=_TOP_LEVEL_ACTIONS)
        self.assertIsNone(_per_detail_action_ids("cancel", error))

    def test_returns_none_when_action_has_no_top_level_id(self) -> None:
        # Nothing to apply anywhere on this error -- fall back to the plain RecoveryAction.
        details = [_detail("d1", "1", recovery_actions=_REPEAT_ONLY)]
        error = ErrorData(uuid="err-4", detailedErrors=details, recoveryActions=[])
        self.assertIsNone(_per_detail_action_ids("abort", error))


class OperatorEscalationAbortCancelTests(unittest.IsolatedAsyncioTestCase):
    def _config(self) -> WorkflowBackendConfig:
        return WorkflowBackendConfig(run_log_root=Path(tempfile.mkdtemp(prefix="hwf_escalation_test_")))

    async def _run_escalation(self, error: ErrorData, action: str):
        session = WorkflowSession(self._config())
        session._loop = asyncio.get_running_loop()
        ctx = OperatorEscalationContext(
            error=error,
            entry=None,
            operation_category=None,
            error_type=None,
            top_level_actions=error.recovery_actions,
            per_channel_actions=[],
            is_per_channel_escalation=True,
        )
        task = asyncio.get_running_loop().run_in_executor(None, session._handle_operator_escalation, ctx)
        await asyncio.sleep(0.1)
        session.resolve_operator_prompt(error.uuid, action, None)
        return await task

    async def test_cancel_applies_top_level_id_uniformly_to_every_channel(self) -> None:
        # The exact live-confirmed case (this session's real bug report).
        result = await self._run_escalation(_per_channel_error(), "cancel")
        self.assertEqual(result.selected_action_id, 2)
        ids = {d.uuid: d.selected_action_id for d in result.detailed_error_recoveries}
        self.assertEqual(ids, {"d1": 2, "d2": 2, "d3": 2, "d4": 2})

    async def test_abort_applies_top_level_id_uniformly_to_every_channel(self) -> None:
        result = await self._run_escalation(_per_channel_error(), "abort")
        self.assertEqual(result.selected_action_id, 1)
        ids = {d.uuid: d.selected_action_id for d in result.detailed_error_recoveries}
        self.assertEqual(ids, {"d1": 1, "d2": 1, "d3": 1, "d4": 1})

    async def test_cancel_on_a_top_level_only_error_stays_a_plain_recovery_action(self) -> None:
        # No detailed_errors at all -- nothing to build a per-channel ErrorRecovery from.
        error = ErrorData(uuid="err-5", recoveryActions=_TOP_LEVEL_ACTIONS)
        result = await self._run_escalation(error, "cancel")
        self.assertEqual(result, RecoveryAction.CANCEL)

    async def test_falls_back_to_plain_recovery_action_when_action_has_no_id_anywhere(self) -> None:
        details = [_detail("d1", "1", recovery_actions=_REPEAT_ONLY)]
        error = ErrorData(uuid="err-6", detailedErrors=details, recoveryActions=[])
        result = await self._run_escalation(error, "abort")
        self.assertEqual(result, RecoveryAction.ABORT)


if __name__ == "__main__":
    unittest.main()
