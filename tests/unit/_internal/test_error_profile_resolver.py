"""Unit tests for ErrorProfileResolver."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hamilton_venus._internal._error_classifier import ErrorClassifier
from hamilton_venus._internal._error_profile_resolver import (
    CommandDeadlineControl,
    ErrorProfileResolver,
    OperatorEscalationCallback,
)
from hamilton_venus.error_handling.access_actions import access_action_recovery
from hamilton_venus.error_handling.profile import ErrorEntry, ErrorProfile
from hamilton_venus.models.error_types import (
    AspirateError,
    OperationCategory,
    RecoveryAction,
    TipPickupError,
)
from hamilton_venus.models.instrument_errors import (
    Action,
    DetailedError,
    ErrorData,
    ErrorRecovery,
    InstrumentErrorHandled,
    RecoveryActionDescriptor,
)


@pytest.fixture(autouse=True)
def _no_resolver_sleep(monkeypatch):
    """Skip the resolver's real retry/reconcile delays to keep tests fast.

    The resolver uses ``asyncio.sleep`` for production backoff between recovery
    submissions and reconciliation rechecks. These tests assert on resolution
    behavior and state progression, not on wall-clock timing, so the sleeps are
    replaced with an instant no-op.
    """
    monkeypatch.setattr(
        "hamilton_venus._internal._error_profile_resolver.asyncio.sleep",
        AsyncMock(),
    )


def _recovery_action(id: int, name: str) -> RecoveryActionDescriptor:
    return RecoveryActionDescriptor(id=id, name=name, index=0)
def _error(
    uuid: str = "abc-123",
    code: str | None = "08",
    timeout: int = -1,
    recovery_actions: list[RecoveryActionDescriptor] | None = None,
    detailed_errors: list[DetailedError] | None = None,
) -> ErrorData:
    return ErrorData(
        uuid=uuid,
        code=code,
        timeout=timeout,
        recovery_actions=recovery_actions
        or [
            _recovery_action(1, "cancel"),
            _recovery_action(2, "abort"),
            _recovery_action(3, "exclude"),
            _recovery_action(4, "continue"),
        ],
        detailed_errors=detailed_errors,
    )


def _make_deadline_control(operation_context: str | None = None) -> MagicMock:
    ctrl = MagicMock(spec=CommandDeadlineControl)
    ctrl.get_operation_context.return_value = operation_context
    return ctrl


def _make_resolver(
    profile: ErrorProfile | None = None,
    operation_context: str | None = None,
    error_handler_key: str = "sdk-key",
    classifier: ErrorClassifier | None = None,
    on_operator_error_escalation: OperatorEscalationCallback | None = None,
) -> tuple[ErrorProfileResolver, AsyncMock, MagicMock]:
    if profile is None:
        profile = ErrorProfile(
            name="default",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
        )
    venus = AsyncMock()
    venus.get_unhandled_errors.return_value = []
    deadline_ctrl = _make_deadline_control(operation_context)
    resolver = ErrorProfileResolver(
        venus_client=venus,
        deadline_control=deadline_ctrl,
        profile=profile,
        classifier=classifier if classifier is not None else ErrorClassifier(),
        error_handler_key=error_handler_key,
        on_operator_error_escalation=on_operator_error_escalation,
    )
    return resolver, venus, deadline_ctrl


class TestErrorProfileResolverInit:
    def test_active_profile_property(self):
        profile = ErrorProfile(
            name="test",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
        )
        resolver, _, _ = _make_resolver(profile=profile)
        assert resolver.active_profile is profile

    def test_set_profile_replaces_active_profile(self):
        resolver, _, _ = _make_resolver()
        new_profile = ErrorProfile(
            name="new",
            default=ErrorEntry(actions=(RecoveryAction.CANCEL,)),
        )
        resolver.set_active_profile(new_profile)
        assert resolver.active_profile is new_profile

    def test_stats_initial(self):
        resolver, _, _ = _make_resolver()
        stats = resolver.stats
        assert stats["active_retry_count"] == 0


@pytest.mark.asyncio
class TestOnInstrumentError:
    async def test_no_error_fast_path_skips_resolution(self):
        resolver, venus, deadline_ctrl = _make_resolver()
        await resolver.on_instrument_error(_error(code="00"))
        venus.submit_error_recovery.assert_not_called()
        venus.submit_error_action.assert_not_called()
        deadline_ctrl.suspend.assert_not_called()

    async def test_suspends_deadline_on_error(self):
        resolver, _venus, deadline_ctrl = _make_resolver()
        await resolver.on_instrument_error(_error(code="08"))
        deadline_ctrl.suspend.assert_called_once()

    async def test_resumes_deadline_after_resolution(self):
        resolver, _venus, deadline_ctrl = _make_resolver()
        await resolver.on_instrument_error(_error(code="08"))
        deadline_ctrl.resume.assert_called_once()

    async def test_resumes_deadline_even_when_venus_raises(self):
        resolver, venus, deadline_ctrl = _make_resolver()
        venus.submit_error_recovery.side_effect = RuntimeError("network error")
        venus.submit_error_action.side_effect = RuntimeError("network error")
        await resolver.on_instrument_error(_error(code="08"))
        deadline_ctrl.resume.assert_called_once()

    async def test_logs_instrument_error_at_error_level(self, caplog):
        resolver, _venus, _deadline_ctrl = _make_resolver()

        with caplog.at_level(logging.ERROR):
            await resolver.on_instrument_error(_error(code="08", uuid="err-123"))

        assert any(
            rec.levelno == logging.ERROR
            and "Instrument error:" in rec.getMessage()
            and "NO_TIP" in rec.getMessage()
            and "tip_pickup" in rec.getMessage()
            and "err-123" in rec.getMessage()
            for rec in caplog.records
        )

    async def test_timeout_expired_skips_submission(self):
        resolver, venus, _deadline_ctrl = _make_resolver()
        await resolver.on_instrument_error(_error(code="08", timeout=0))
        venus.submit_error_recovery.assert_not_called()
        venus.submit_error_action.assert_not_called()

    async def test_timeout_minus_one_is_not_expired(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        await resolver.on_instrument_error(_error(code="08", timeout=-1))
        venus.submit_error_recovery.assert_called_once()

    async def test_submits_recovery_for_tip_pickup_abort(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        await resolver.on_instrument_error(_error(code="08"))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.error_handling_key == "sdk-key"
        assert payload.uuid == "abc-123"

    async def test_submits_action_for_action_kind(self):
        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.action_to_server_id.return_value = 99
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.INITIALIZE,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)
        await resolver.on_instrument_error(_error(code="99"))
        venus.submit_error_action.assert_called_once()

    async def test_repeat_action_advances_to_next_action_after_max_retries(self):
        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.stats = {"classification_miss_count": 0}

        def _action_to_server_id(action: RecoveryAction, actions):
            return next((desc.id for desc in actions if desc.name == action.value), None)

        mock_classifier.action_to_server_id.side_effect = _action_to_server_id
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.CONTINUE),
                max_retries=2,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)
        recovery_actions = [
            _recovery_action(1, "repeat"),
            _recovery_action(2, "continue"),
        ]
        error = _error(code="08", recovery_actions=recovery_actions)

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        assert venus.submit_error_recovery.call_count == 3
        assert [call.args[1].selected_action_id for call in venus.submit_error_recovery.call_args_list] == [1, 1, 2]

    async def test_cycles_exhausted_submits_abort(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        error = _error(code="08")
        await resolver.on_instrument_error(error)
        assert venus.submit_error_recovery.call_count == 1
        venus.reset_mock()
        await resolver.on_instrument_error(error)
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        abort_id = next((a.id for a in error.recovery_actions if a.name == "abort"), None)
        assert payload.selected_action_id == abort_id

    async def test_skips_action_not_advertised_by_server(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.CONTINUE, RecoveryAction.ABORT), max_retries=2),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(2, "abort")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 2

    async def test_exact_profile_entry_used_over_default(self):
        exact_entry = ErrorEntry(actions=(RecoveryAction.EXCLUDE,), max_retries=1)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
            operations={
                "tip_pickup": {TipPickupError.NO_TIP: exact_entry},
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(3, "exclude")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 3

    async def test_error_default_used_when_no_exact_match(self):
        error_default = ErrorEntry(actions=(RecoveryAction.EXCLUDE,), max_retries=1)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
            error_defaults={
                "NO_TIP": error_default,
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(3, "exclude")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 3

    async def test_error_default_used_before_operation_default(self):
        error_default = ErrorEntry(actions=(RecoveryAction.EXCLUDE,), max_retries=1)
        op_default = ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.CONTINUE,), max_retries=1),
            error_defaults={
                "NO_TIP": error_default,
            },
            operation_defaults={
                "tip_pickup": op_default,
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(3, "exclude"), _recovery_action(2, "abort")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 3

    async def test_operation_default_used_when_no_exact_or_error_default_match(self):
        op_default = ErrorEntry(actions=(RecoveryAction.EXCLUDE,), max_retries=1)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
            operation_defaults={
                "tip_pickup": op_default,
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(3, "exclude")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 3

    async def test_error_handler_key_in_payload(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile, error_handler_key="my-handler")
        await resolver.on_instrument_error(_error(code="08"))
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.error_handling_key == "my-handler"

    async def test_no_valid_actions_escalates_to_abort(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.CONTINUE,), max_retries=3, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(2, "abort")]
        await resolver.on_instrument_error(_error(code="08", recovery_actions=recovery_actions))
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 2

    async def test_detailed_error_abort_submits_top_level_abort_on_every_channel(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(2, "abort"), _recovery_action(9, "execute")]
        detailed_errors = [
            DetailedError(
                uuid="detail-1",
                index=1,
                recovery_actions=[_recovery_action(20, "continue")],
            )
        ]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        # ABORT not advertised for channel → exhausted → top-level ABORT submitted,
        # repeated on every channel (VENUS rejects a per-channel error without them)
        assert payload.selected_action_id == 2
        assert [(d.uuid, d.selected_action_id) for d in payload.detailed_error_recoveries] == [("detail-1", 2)]

    async def test_detailed_error_cancel_submits_top_level_cancel_on_every_channel(self):
        """VENUS offers CANCEL only for the whole error, never per channel: a channel whose
        profile picks CANCEL cancels the whole error instead of falling back to ABORT."""
        profile = ErrorProfile(
            name="cancel_all",
            default=ErrorEntry(actions=(RecoveryAction.CANCEL,), max_retries=0, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(1, "cancel"), _recovery_action(2, "abort"), _recovery_action(9, "execute")]
        detailed_errors = [
            DetailedError(uuid="detail-1", index=1, recovery_actions=[_recovery_action(20, "repeat")]),
            DetailedError(uuid="detail-2", index=2, recovery_actions=[_recovery_action(21, "repeat")]),
        ]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 1
        assert [(d.uuid, d.selected_action_id) for d in payload.detailed_error_recoveries] == [
            ("detail-1", 1),
            ("detail-2", 1),
        ]

    async def test_detailed_error_cancel_not_offered_falls_back_to_abort(self):
        profile = ErrorProfile(
            name="cancel_all",
            default=ErrorEntry(actions=(RecoveryAction.CANCEL,), max_retries=0, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        recovery_actions = [_recovery_action(2, "abort"), _recovery_action(9, "execute")]
        detailed_errors = [DetailedError(uuid="detail-1", index=1, recovery_actions=[_recovery_action(20, "repeat")])]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 2

    async def test_detailed_error_abort_fallback_to_channel_recovery_actions(self):
        """When ABORT is absent from top-level recovery_actions, search per-channel lists."""
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        # Top-level only has execute — no abort
        top_actions = [_recovery_action(9, "execute")]
        # Per-channel has abort with a different ID
        ch_abort_id = 55
        detailed_errors = [
            DetailedError(
                uuid="ch-1",
                index=1,
                recovery_actions=[_recovery_action(ch_abort_id, "abort"), _recovery_action(26, "repeat")],
            ),
            DetailedError(
                uuid="ch-2",
                index=2,
                recovery_actions=[_recovery_action(ch_abort_id, "abort"), _recovery_action(26, "repeat")],
            ),
        ]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=top_actions, detailed_errors=detailed_errors)
        )
        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        # ABORT found via per-channel fallback
        assert payload.selected_action_id == ch_abort_id
        recoveries = {r.uuid: r.selected_action_id for r in payload.detailed_error_recoveries}
        assert recoveries == {"ch-1": ch_abort_id, "ch-2": ch_abort_id}

    async def test_detailed_errors_per_channel_independent_actions(self):
        """Channels with different error types each receive their own profile action."""

        def _action_to_server_id(action, recovery_actions):
            if recovery_actions:
                for desc in recovery_actions:
                    if desc.name == action.value:
                        return desc.id
            return None

        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.classify_code.side_effect = [
            (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP),
            (OperationCategory.ASPIRATE, AspirateError.CLOT),
        ]
        mock_classifier.action_to_server_id.side_effect = _action_to_server_id

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
            operations={
                "tip_pickup": {
                    TipPickupError.NO_TIP: ErrorEntry(actions=(RecoveryAction.EXCLUDE,)),
                },
                "aspirate": {
                    AspirateError.CLOT: ErrorEntry(actions=(RecoveryAction.REPEAT,)),
                },
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)

        recovery_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]
        detailed_errors = [
            DetailedError(uuid="ch-1", index=1, code="08", recovery_actions=[_recovery_action(30, "exclude")]),
            DetailedError(uuid="ch-2", index=2, code="04", recovery_actions=[_recovery_action(40, "repeat")]),
        ]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )

        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 9
        recoveries = {r.uuid: r.selected_action_id for r in payload.detailed_error_recoveries}
        assert recoveries["ch-1"] == 30
        assert recoveries["ch-2"] == 40

    async def test_detailed_error_logs_selected_channel_actions_at_warning_level(self, caplog):
        def _action_to_server_id(action, recovery_actions):
            if recovery_actions:
                for desc in recovery_actions:
                    if desc.name == action.value:
                        return desc.id
            return None

        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.classify_code.side_effect = [
            (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP),
            (OperationCategory.ASPIRATE, AspirateError.CLOT),
        ]
        mock_classifier.action_to_server_id.side_effect = _action_to_server_id

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
            operations={
                "tip_pickup": {
                    TipPickupError.NO_TIP: ErrorEntry(actions=(RecoveryAction.EXCLUDE,)),
                },
                "aspirate": {
                    AspirateError.CLOT: ErrorEntry(actions=(RecoveryAction.REPEAT,)),
                },
            },
        )
        resolver, _venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)

        recovery_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]
        detailed_errors = [
            DetailedError(uuid="ch-1", index=1, code="08", recovery_actions=[_recovery_action(30, "exclude")]),
            DetailedError(uuid="ch-2", index=2, code="04", recovery_actions=[_recovery_action(40, "repeat")]),
        ]

        with caplog.at_level(logging.WARNING):
            await resolver.on_instrument_error(
                _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
            )

        assert any(
            rec.levelno == logging.WARNING
            and "Recovering 2 channel(s) with action:" in rec.getMessage()
            and "exclude x1, repeat x1" in rec.getMessage()
            for rec in caplog.records
        )

    async def test_detailed_errors_channel_abort_submits_top_level_abort(self):
        """If any channel resolves to ABORT, a top-level ABORT is submitted."""

        def _action_to_server_id(action, recovery_actions):
            if recovery_actions:
                for desc in recovery_actions:
                    if desc.name == action.value:
                        return desc.id
            return None

        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.classify_code.side_effect = [
            (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP),
            (OperationCategory.ASPIRATE, AspirateError.CLOT),
        ]
        mock_classifier.action_to_server_id.side_effect = _action_to_server_id

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
            operations={
                "tip_pickup": {
                    TipPickupError.NO_TIP: ErrorEntry(actions=(RecoveryAction.ABORT,), allow_operator=False),
                },
                "aspirate": {
                    AspirateError.CLOT: ErrorEntry(actions=(RecoveryAction.REPEAT,)),
                },
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)

        recovery_actions = [_recovery_action(2, "abort"), _recovery_action(9, "execute")]
        detailed_errors = [
            DetailedError(uuid="ch-1", index=1, code="08", recovery_actions=[_recovery_action(2, "abort")]),
            DetailedError(uuid="ch-2", index=2, code="04", recovery_actions=[_recovery_action(40, "repeat")]),
        ]
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )

        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 2
        assert {d.selected_action_id for d in payload.detailed_error_recoveries} == {payload.selected_action_id}

    async def test_operator_callback_action_submits_recovery(self):
        operator_cb = Mock(return_value=RecoveryAction.NEXT)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)
        payloads = [call.args[1] for call in venus.submit_error_recovery.call_args_list]
        assert payloads[0].selected_action_id == 1105
        assert payloads[1].selected_action_id == 1105
        operator_cb.assert_called_once()

    async def test_operator_callback_cancel_on_per_channel_error_includes_every_channel(self):
        """An error-wide Cancel on a per-channel error must carry every channel --
        VENUS rejects it otherwise ("The detailed error recoveries are missing.")."""
        operator_cb = Mock(return_value=RecoveryAction.CANCEL)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        error = _error(
            code="N1:02/23",
            recovery_actions=[
                _recovery_action(1, "execute"),
                _recovery_action(1139, "abort"),
                _recovery_action(2, "cancel"),
            ],
            detailed_errors=[
                DetailedError(uuid="ch-1", index=0, recovery_actions=[_recovery_action(1026, "repeat")]),
                DetailedError(uuid="ch-2", index=1, recovery_actions=[_recovery_action(1026, "repeat")]),
            ],
        )
        await resolver.on_instrument_error(error)
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 2
        assert [(d.uuid, d.selected_action_id) for d in payload.detailed_error_recoveries] == [("ch-1", 2), ("ch-2", 2)]

    async def test_operator_callback_wait_drops_suspension_fallback(self):
        """While the operator callback (e.g. a recovery dialog) decides, the
        suspension fallback is dropped; the deadline is resumed once it answers."""
        operator_cb = Mock(return_value=RecoveryAction.NEXT)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(), max_retries=0, allow_operator=True),
        )
        resolver, _venus, deadline_ctrl = _make_resolver(
            profile=profile, on_operator_error_escalation=operator_cb
        )
        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        )
        operator_cb.assert_called_once()
        deadline_ctrl.pause_suspension_fallback.assert_called_once()
        assert deadline_ctrl.resume.call_count == deadline_ctrl.suspend.call_count
        deadline_ctrl.hold_for_operator.assert_not_called()

    async def test_operator_callback_none_falls_back_to_abort(self):
        operator_cb = Mock(return_value=None)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)
        payloads = [call.args[1] for call in venus.submit_error_recovery.call_args_list]
        assert payloads[0].selected_action_id == 1105
        assert payloads[1].selected_action_id == 2
        operator_cb.assert_called_once()

    async def test_allow_operator_without_callback_defers_to_legacy_dialog(self):
        """When allow_operator=True and no callback is registered, submit selected_action_id=-1."""
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)
        payloads = [call.args[1] for call in venus.submit_error_recovery.call_args_list]
        assert payloads[0].selected_action_id == 1105
        assert payloads[1].selected_action_id == -1
        assert payloads[1].selected_action_is_recovery is False
        assert payloads[1].detailed_error_recoveries is None

    async def test_detailed_error_without_callback_defers_to_legacy_dialog_per_channel(self):
        """Regression test: a per-channel/detailed error escalating with no
        operator callback registered must submit detailed_error_recoveries
        (one entry per channel, each selected_action_id=0 -- R&D's suggestion,
        2026-09-25; the top-level id stays -1), not a bare top-level -1
        submission -- VENUS rejects that with HTTP 400 when the original error
        itself carried detailed_errors."""
        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.classify_code.return_value = (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP)
        mock_classifier.action_to_server_id.return_value = None  # no advertised action -> escalate immediately

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
            operations={
                "tip_pickup": {
                    TipPickupError.NO_TIP: ErrorEntry(actions=(RecoveryAction.REPEAT,), allow_operator=True),
                },
            },
        )
        resolver, venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)

        recovery_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]
        detailed_errors = [
            DetailedError(uuid="ch-1", index=1, code="08", recovery_actions=[]),
            DetailedError(uuid="ch-2", index=2, code="08", recovery_actions=[]),
        ]

        await resolver.on_instrument_error(
            _error(code="08", recovery_actions=recovery_actions, detailed_errors=detailed_errors)
        )

        venus.submit_error_recovery.assert_called_once()
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == -1
        assert payload.detailed_error_recoveries is not None
        recoveries = {r.uuid: r.selected_action_id for r in payload.detailed_error_recoveries}
        assert recoveries == {"ch-1": 0, "ch-2": 0}

    async def test_legacy_operator_handoff_leaves_deadline_suspended(self):
        """When deferring to the legacy operator dialog, the command deadline
        must remain suspended (not resumed) after on_instrument_error returns,
        since a human still needs to respond via the legacy callback."""
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, deadline_ctrl = _make_resolver(profile=profile)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])

        await resolver.on_instrument_error(error)
        resume_count_after_first = deadline_ctrl.resume.call_count

        await resolver.on_instrument_error(error)

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        assert payload.selected_action_id == -1

        deadline_ctrl.suspend.assert_called()
        # The second (legacy handoff) call must not resume the deadline.
        assert deadline_ctrl.resume.call_count == resume_count_after_first

        # The handoff puts the deadline on an operator hold ...
        deadline_ctrl.hold_for_operator.assert_called_once()
        # ... and VENUS's "handled" event (sent as soon as it accepts the handoff,
        # while its dialog is still open) must not resume it.
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid=error.uuid, recovery_action="unknown"))
        assert deadline_ctrl.resume.call_count == resume_count_after_first

    async def test_disallow_operator_without_callback_falls_back_to_abort(self):
        """When allow_operator=False and no callback is registered, submit ABORT (not legacy fallback)."""
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=False),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)
        payloads = [call.args[1] for call in venus.submit_error_recovery.call_args_list]
        assert payloads[0].selected_action_id == 1105
        assert payloads[1].selected_action_id == 2

    async def test_operator_callback_error_recovery_normalizes_uuid_and_key(self):
        operator_cb = Mock(
            return_value=ErrorRecovery(
                date=datetime.now(UTC).isoformat(),
                uuid="different-uuid",
                selected_action_id=1105,
                selected_action_is_recovery=True,
                error_handling_key="",
            )
        )
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(
            profile=profile,
            on_operator_error_escalation=operator_cb,
            error_handler_key="sdk-key",
        )
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        assert payload.uuid == error.uuid
        assert payload.error_handling_key == "sdk-key"
        assert payload.selected_action_id == 1105

    async def test_operator_callback_error_recovery_forces_recovery_flag(self):
        operator_cb = Mock(
            return_value=ErrorRecovery(
                date=datetime.now(UTC).isoformat(),
                uuid="abc-123",
                selected_action_id=1105,
                selected_action_is_recovery=False,
                error_handling_key="k",
            )
        )
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        assert payload.selected_action_is_recovery is True

    async def test_operator_callback_access_action_keeps_error_open(self):
        """An access action goes to /action, and the operator is asked again on the republish."""
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        error.actions = [Action(id=4220, name="Lower tray", index=0)]
        republished = error.model_copy(update={"actions": [Action(id=4221, name="Raise tray", index=0)]})
        operator_cb = Mock(side_effect=[access_action_recovery(error, "lower_load_tray"), RecoveryAction.ABORT])
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, deadline_ctrl = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        venus.submit_error_action.assert_called_once()
        action_payload = venus.submit_error_action.call_args.args[1]
        assert action_payload.selected_action_id == 4220
        assert action_payload.selected_action_is_recovery is False
        assert action_payload.error_handling_key == "sdk-key"
        assert venus.submit_error_recovery.call_count == 1  # only the profile's NEXT so far
        # The deadline stays suspended until the error is published again.
        assert deadline_ctrl.suspend.call_count == 2
        assert deadline_ctrl.resume.call_count == 1

        await resolver.on_instrument_error(republished)

        assert operator_cb.call_count == 2
        assert operator_cb.call_args_list[1].args[0].error is republished
        assert venus.submit_error_recovery.call_args_list[-1].args[1].selected_action_id == 2
        assert deadline_ctrl.suspend.call_count == 2
        assert deadline_ctrl.resume.call_count == 2

    async def test_operator_is_asked_again_when_access_action_is_refused(self):
        error = _error(code="08", recovery_actions=[_recovery_action(1105, "next"), _recovery_action(2, "abort")])
        error.actions = [Action(id=4222, name="Unlock front cover", index=0)]
        operator_cb = Mock(side_effect=[access_action_recovery(error, "unlock_door"), RecoveryAction.ABORT])
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, deadline_ctrl = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        venus.submit_error_action.side_effect = RuntimeError("400")
        venus.get_unhandled_errors.return_value = [error]

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        assert operator_cb.call_count == 2
        assert venus.submit_error_recovery.call_args_list[-1].args[1].selected_action_id == 2
        assert deadline_ctrl.resume.call_count == deadline_ctrl.suspend.call_count == 2

    async def test_error_published_again_while_operator_decides_is_ignored(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.NEXT,), max_retries=0, allow_operator=True),
        )
        resolver, venus, deadline_ctrl = _make_resolver(profile=profile, on_operator_error_escalation=Mock())
        error = _error(code="08")
        resolver._escalating.add(error.uuid)

        await resolver.on_instrument_error(error)

        deadline_ctrl.suspend.assert_not_called()
        venus.submit_error_recovery.assert_not_called()

    async def test_detailed_error_channel_states_cleaned_up_on_device_error_handled(self):
        """Per-channel retry states are removed when the top-level UUID is handled."""
        mock_classifier = MagicMock(spec=ErrorClassifier)
        mock_classifier.stats = {"classification_miss_count": 0}
        mock_classifier.classify.return_value = (None, None)
        mock_classifier.classify_code.return_value = (None, None)
        mock_classifier.action_to_server_id.side_effect = lambda action, ra: (
            next((d.id for d in ra if d.name == action.value), None) if ra else None
        )

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.REPEAT,), max_retries=5),
        )
        resolver, _venus, _ = _make_resolver(profile=profile, classifier=mock_classifier)

        ch_actions = [_recovery_action(5, "repeat")]
        detailed_errors = [
            DetailedError(uuid="ch-1", index=1, code="08", recovery_actions=ch_actions),
            DetailedError(uuid="ch-2", index=2, code="08", recovery_actions=ch_actions),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(5, "repeat")]
        await resolver.on_instrument_error(
            _error(uuid="top-1", code="08", recovery_actions=top_actions, detailed_errors=detailed_errors)
        )

        assert resolver.stats["active_retry_count"] == 2

        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-1", recovery_action="repeat"))
        assert resolver.stats["active_retry_count"] == 0

    async def test_detailed_error_retry_state_carries_over_across_events(self):
        """Retry count accumulates across independent error events with new channel UUIDs.

        Each instrument retry generates a new error event with new channel UUIDs.
        The carry-over mechanism must preserve retry state so that max_retries is
        exhausted after the expected number of events, not after infinite events.
        """
        ch_actions = [_recovery_action(26, "repeat"), _recovery_action(2, "abort")]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.REPEAT, RecoveryAction.ABORT), max_retries=2),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        def _make_event(top_uuid: str, ch_uuid_1: str, ch_uuid_2: str) -> ErrorData:
            return _error(
                uuid=top_uuid,
                code="08",
                recovery_actions=top_actions,
                detailed_errors=[
                    DetailedError(uuid=ch_uuid_1, index=0, code="75", recovery_actions=ch_actions),
                    DetailedError(uuid=ch_uuid_2, index=1, code="75", recovery_actions=ch_actions),
                ],
            )

        # Event 1: retry_count=0 → REPEAT (count goes to 1)
        await resolver.on_instrument_error(_make_event("top-1", "ch1a", "ch1b"))
        payload1 = venus.submit_error_recovery.call_args[0][1]
        recoveries1 = {r.uuid: r.selected_action_id for r in payload1.detailed_error_recoveries}
        assert recoveries1 == {"ch1a": 26, "ch1b": 26}

        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-1", recovery_action="execute"))
        # Both channels should be in carry-over (last_action was REPEAT)
        assert len(resolver._channel_carry_over) == 2

        # Event 2: new channel UUIDs, but carry-over reused → retry_count=1 → REPEAT (count → 2)
        await resolver.on_instrument_error(_make_event("top-2", "ch2a", "ch2b"))
        payload2 = venus.submit_error_recovery.call_args[0][1]
        recoveries2 = {r.uuid: r.selected_action_id for r in payload2.detailed_error_recoveries}
        assert recoveries2 == {"ch2a": 26, "ch2b": 26}
        # Carry-over consumed by event 2 init
        assert len(resolver._channel_carry_over) == 0

        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-2", recovery_action="execute"))
        # retry_count=2 but last_action is still REPEAT (budget exhaustion happens on NEXT call)
        # → states carried over for event 3 to consume
        assert len(resolver._channel_carry_over) == 2

        # Event 3: carry-over reused → retry_count=2 >= max_retries=2 → action advances to ABORT
        await resolver.on_instrument_error(_make_event("top-3", "ch3a", "ch3b"))
        last_payload = venus.submit_error_recovery.call_args[0][1]
        abort_action_id = next(d.id for d in top_actions if d.name == "abort")
        assert last_payload.selected_action_id == abort_action_id
        assert {d.selected_action_id for d in last_payload.detailed_error_recoveries} == {
            last_payload.selected_action_id
        }

    async def test_detailed_error_non_repeat_action_carries_over_across_events(self):
        ch_actions = [
            _recovery_action(26, "repeat"),
            _recovery_action(1105, "next"),
            _recovery_action(1030, "exclude"),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT, RecoveryAction.EXCLUDE),
                max_retries=3,
                allow_operator=False,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        def _make_event(top_uuid: str, ch_uuid_1: str, ch_uuid_2: str) -> ErrorData:
            return _error(
                uuid=top_uuid,
                code="08",
                recovery_actions=top_actions,
                detailed_errors=[
                    DetailedError(uuid=ch_uuid_1, index=0, code="75", recovery_actions=ch_actions),
                    DetailedError(uuid=ch_uuid_2, index=1, code="75", recovery_actions=ch_actions),
                ],
            )

        await resolver.on_instrument_error(_make_event("top-1", "e1c1", "e1c2"))
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-1", recovery_action="execute"))
        payload1 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids1 = {r.selected_action_id for r in payload1.detailed_error_recoveries}
        assert ids1 == {26}

        await resolver.on_instrument_error(_make_event("top-2", "e2c1", "e2c2"))
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-2", recovery_action="execute"))
        payload2 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids2 = {r.selected_action_id for r in payload2.detailed_error_recoveries}
        assert ids2 == {26}

        await resolver.on_instrument_error(_make_event("top-3", "e3c1", "e3c2"))
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-3", recovery_action="execute"))
        payload3 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids3 = {r.selected_action_id for r in payload3.detailed_error_recoveries}
        assert ids3 == {26}

        await resolver.on_instrument_error(_make_event("top-4", "e4c1", "e4c2"))
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-4", recovery_action="execute"))
        payload4 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids4 = {r.selected_action_id for r in payload4.detailed_error_recoveries}
        assert ids4 == {1105}

        await resolver.on_instrument_error(_make_event("top-5", "e5c1", "e5c2"))
        await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="top-5", recovery_action="execute"))
        payload5 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids5 = {r.selected_action_id for r in payload5.detailed_error_recoveries}
        assert ids5 == {1030}

        await resolver.on_instrument_error(_make_event("top-6", "e6c1", "e6c2"))
        payload6 = venus.submit_error_recovery.call_args_list[-1].args[1]
        assert payload6.selected_action_id == 2
        assert {d.selected_action_id for d in payload6.detailed_error_recoveries} == {payload6.selected_action_id}

    async def test_detailed_error_operator_selected_action_keeps_escalation_mode_across_events(self):
        operator_cb = Mock(return_value=RecoveryAction.NEXT)
        ch_actions = [
            _recovery_action(26, "repeat"),
            _recovery_action(1105, "next"),
            _recovery_action(1030, "exclude"),
            _recovery_action(2, "abort"),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT, RecoveryAction.EXCLUDE),
                max_retries=3,
                allow_operator=True,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)

        def _make_event(top_uuid: str, ch_uuid_1: str, ch_uuid_2: str) -> ErrorData:
            return _error(
                uuid=top_uuid,
                code="08",
                recovery_actions=top_actions,
                detailed_errors=[
                    DetailedError(uuid=ch_uuid_1, index=0, code="75", recovery_actions=ch_actions),
                    DetailedError(uuid=ch_uuid_2, index=1, code="75", recovery_actions=ch_actions),
                ],
            )

        for i in range(1, 7):
            await resolver.on_instrument_error(_make_event(f"top-{i}", f"e{i}c1", f"e{i}c2"))
            await resolver.on_device_error_handled(InstrumentErrorHandled(uuid=f"top-{i}", recovery_action="execute"))

        payload6 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids6 = {r.selected_action_id for r in payload6.detailed_error_recoveries}
        assert ids6 == {1105}

        await resolver.on_instrument_error(_make_event("top-7", "e7c1", "e7c2"))
        payload7 = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids7 = {r.selected_action_id for r in payload7.detailed_error_recoveries}
        assert ids7 == {1105}
        operator_cb.assert_called()

    async def test_detailed_error_reconciles_pending_then_clear_without_resubmit(self, monkeypatch):
        sleep_mock = AsyncMock(return_value=None)
        monkeypatch.setattr("hamilton_venus._internal._error_profile_resolver.asyncio.sleep", sleep_mock)

        ch_actions = [_recovery_action(26, "repeat")]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.REPEAT,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        event = _error(
            uuid="top-reconcile-1",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="r1", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="r2", index=1, code="75", recovery_actions=ch_actions),
            ],
        )
        venus.get_unhandled_errors.side_effect = [
            [_error(uuid="top-reconcile-1")],
            [],
        ]

        await resolver.on_instrument_error(event)

        assert venus.submit_error_recovery.call_count == 1
        assert venus.get_unhandled_errors.call_count == 2

    async def test_detailed_error_reconciliation_retries_after_max_checks(self, monkeypatch):
        sleep_mock = AsyncMock(return_value=None)
        monkeypatch.setattr("hamilton_venus._internal._error_profile_resolver.asyncio.sleep", sleep_mock)

        ch_actions = [_recovery_action(26, "repeat")]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.REPEAT,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        event = _error(
            uuid="top-reconcile-2",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="s1", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="s2", index=1, code="75", recovery_actions=ch_actions),
            ],
        )
        venus.get_unhandled_errors.side_effect = [
            [_error(uuid="top-reconcile-2")],
            [_error(uuid="top-reconcile-2")],
        ]

        await resolver.on_instrument_error(event)

        assert venus.submit_error_recovery.call_count == 2
        assert venus.get_unhandled_errors.call_count == 2

    async def test_operator_callback_context_per_channel_actions_uses_name_intersection(self):
        operator_cb = Mock(return_value=RecoveryAction.ABORT)
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0, allow_operator=True),
        )
        resolver, _venus, _ = _make_resolver(profile=profile, on_operator_error_escalation=operator_cb)
        detailed_errors = [
            DetailedError(
                uuid="ch-1",
                index=1,
                recovery_actions=[
                    RecoveryActionDescriptor(id=101, name="Repeat", index=0),
                    RecoveryActionDescriptor(id=102, name="Exclude", index=1),
                ],
            ),
            DetailedError(
                uuid="ch-2",
                index=2,
                recovery_actions=[
                    RecoveryActionDescriptor(id=201, name="repeat", index=0),
                    RecoveryActionDescriptor(id=202, name="EXCLUDE", index=1),
                ],
            ),
        ]
        error = _error(
            code="08",
            recovery_actions=[_recovery_action(2, "abort")],
            detailed_errors=detailed_errors,
        )

        await resolver.on_instrument_error(error)
        await resolver.on_instrument_error(error)

        context = operator_cb.call_args.args[0]
        assert {a.name.lower() for a in context.per_channel_actions} == {"repeat", "exclude"}


@pytest.mark.asyncio
class TestOnDeviceErrorHandled:
    async def test_logs_resolution_at_warning_level(self, caplog):
        resolver, _venus, _ = _make_resolver()

        await resolver.on_instrument_error(_error(uuid="resolved-1", code="08"))

        with caplog.at_level(logging.WARNING):
            await resolver.on_device_error_handled(InstrumentErrorHandled(uuid="resolved-1", recovery_action="execute"))

        assert any(
            rec.levelno == logging.WARNING and "Error resolved" in rec.getMessage() and "resolved-1" in rec.getMessage()
            for rec in caplog.records
        )

    async def test_removes_tracking_entry(self):
        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=3),
        )
        resolver, _venus, _ = _make_resolver(profile=profile)
        await resolver.on_instrument_error(_error(uuid="u1", code="08"))
        assert resolver.stats["active_retry_count"] == 1

        handled = InstrumentErrorHandled(uuid="u1", recovery_action="abort")
        await resolver.on_device_error_handled(handled)
        assert resolver.stats["active_retry_count"] == 0

    async def test_handles_unknown_uuid_gracefully(self):
        resolver, _, _ = _make_resolver()
        handled = InstrumentErrorHandled(uuid="unknown", recovery_action="cancel")
        await resolver.on_device_error_handled(handled)
        assert resolver.stats["active_retry_count"] == 0

    async def test_prunes_stale_entries(self):
        resolver, _venus, _ = _make_resolver(
            profile=ErrorProfile(
                name="p",
                default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=5),
            )
        )
        resolver._retry_tracking_ttl_seconds = 0
        await resolver.on_instrument_error(_error(uuid="stale-1", code="08"))
        assert resolver.stats["active_retry_count"] == 1
        for state in resolver._retry_tracking.values():
            state.created_at -= 1

        handled = InstrumentErrorHandled(uuid="other-uuid", recovery_action="abort")
        await resolver.on_device_error_handled(handled)
        assert resolver.stats["active_retry_count"] == 0


@pytest.mark.asyncio
class TestOnInstrumentErrorNotification:
    async def test_notification_advances_same_uuid_after_repeat_budget_exhausted(self):
        ch_actions = [
            _recovery_action(26, "repeat"),
            _recovery_action(1105, "next"),
            _recovery_action(1030, "exclude"),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT, RecoveryAction.EXCLUDE),
                max_retries=3,
                allow_operator=False,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        event = _error(
            uuid="93f0c3ac",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="a3", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="b3", index=1, code="75", recovery_actions=ch_actions),
            ],
        )

        await resolver.on_instrument_error(event)
        await resolver.on_instrument_error(event)

        venus.get_unhandled_errors.return_value = [_error(uuid="93f0c3ac")]
        call_count_before = venus.submit_error_recovery.call_count
        await resolver.on_instrument_error_notification("93f0c3ac")
        assert venus.submit_error_recovery.call_count == call_count_before + 1

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids = {r.selected_action_id for r in payload.detailed_error_recoveries}
        assert ids == {26}

        await resolver.on_instrument_error(event)

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids = {r.selected_action_id for r in payload.detailed_error_recoveries}
        assert ids == {1105}

        venus.get_unhandled_errors.return_value = []
        call_count_before = venus.submit_error_recovery.call_count
        await resolver.on_instrument_error_notification("93f0c3ac")
        assert venus.submit_error_recovery.call_count == call_count_before

    async def test_notification_skips_when_unhandled_check_inconclusive(self):
        ch_actions = [
            _recovery_action(26, "repeat"),
            _recovery_action(1105, "next"),
            _recovery_action(2, "abort"),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT),
                max_retries=2,
                allow_operator=False,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        event = _error(
            uuid="n0",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="d1", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="d2", index=1, code="75", recovery_actions=ch_actions),
            ],
        )

        await resolver.on_instrument_error(event)
        call_count_before = venus.submit_error_recovery.call_count
        venus.get_unhandled_errors.side_effect = RuntimeError("bad json")

        await resolver.on_instrument_error_notification("n0")
        assert venus.submit_error_recovery.call_count == call_count_before

    async def test_notification_recovers_from_failed_resolve_without_consuming_state(self):
        ch_actions = [
            _recovery_action(26, "repeat"),
            _recovery_action(1105, "next"),
            _recovery_action(2, "abort"),
        ]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(
                actions=(RecoveryAction.REPEAT, RecoveryAction.NEXT),
                max_retries=2,
                allow_operator=False,
            ),
        )
        resolver, venus, _ = _make_resolver(profile=profile)

        event = _error(
            uuid="n1",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="c1", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="c2", index=1, code="75", recovery_actions=ch_actions),
            ],
        )

        await resolver.on_instrument_error(event)
        await resolver.on_instrument_error(event)

        venus.submit_error_recovery.side_effect = [RuntimeError("transient"), None]

        venus.get_unhandled_errors.return_value = [_error(uuid="n1")]
        call_count_before = venus.submit_error_recovery.call_count
        await resolver.on_instrument_error_notification("n1")
        assert venus.submit_error_recovery.call_count == call_count_before + 1

        venus.get_unhandled_errors.return_value = []
        await resolver.on_instrument_error(event)

        payload = venus.submit_error_recovery.call_args_list[-1].args[1]
        ids = {r.selected_action_id for r in payload.detailed_error_recoveries}
        assert ids == {1105}

    async def test_reconcile_retries_identical_payload_once_after_repeated_pending(self):
        ch_actions = [_recovery_action(26, "repeat")]
        top_actions = [_recovery_action(9, "execute"), _recovery_action(2, "abort")]

        profile = ErrorProfile(
            name="p",
            default=ErrorEntry(actions=(RecoveryAction.REPEAT,), max_retries=3),
        )
        resolver, venus, _ = _make_resolver(profile=profile)
        venus.get_unhandled_errors.side_effect = [
            [_error(uuid="same-top")],
            [_error(uuid="same-top")],
        ]

        event = _error(
            uuid="same-top",
            code="08",
            recovery_actions=top_actions,
            detailed_errors=[
                DetailedError(uuid="same-ch1", index=0, code="75", recovery_actions=ch_actions),
                DetailedError(uuid="same-ch2", index=1, code="75", recovery_actions=ch_actions),
            ],
        )

        await resolver.on_instrument_error(event)

        assert venus.submit_error_recovery.call_count == 2


@pytest.mark.asyncio
class TestSetProfile:
    async def test_new_errors_use_new_profile(self):
        profile1 = ErrorProfile(
            name="p1",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=1),
        )
        profile2 = ErrorProfile(
            name="p2",
            default=ErrorEntry(actions=(RecoveryAction.EXCLUDE,), max_retries=1),
        )
        resolver, venus, _ = _make_resolver(profile=profile1)
        resolver.set_active_profile(profile2)

        recovery_actions = [_recovery_action(3, "exclude")]
        await resolver.on_instrument_error(_error(uuid="new-err", code="08", recovery_actions=recovery_actions))
        payload = venus.submit_error_recovery.call_args[0][1]
        assert payload.selected_action_id == 3
