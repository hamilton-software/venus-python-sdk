from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import cast

from hamilton_venus._internal._error_profile_resolver import (
    OperatorEscalationCallback,
    OperatorEscalationContext,
)
from hamilton_venus._internal._operator_escalation_bridge import OperatorEscalationBridge
from hamilton_venus.error_handling import ErrorEntry
from hamilton_venus.models import ErrorData, ErrorRecovery, RecoveryAction


def _sample_error() -> ErrorData:
    return ErrorData(uuid="u", code="08", device_id=1, recovery_actions=[])


def _sample_entry() -> ErrorEntry:
    return ErrorEntry(actions=(RecoveryAction.ABORT,), allow_operator=True, max_retries=0)


def _sample_context() -> OperatorEscalationContext:
    return OperatorEscalationContext(
        error=_sample_error(),
        entry=_sample_entry(),
        operation_category=None,
        error_type=None,
        top_level_actions=[],
        per_channel_actions=[],
        is_per_channel_escalation=False,
    )


class TestOperatorEscalationBridge:
    def test_resolver_callback_none_when_no_callback(self) -> None:
        bridge = OperatorEscalationBridge(None, shutdown_timeout=0.5)

        assert bridge.resolver_callback is None

    def test_sync_callback_runs_on_worker_thread_and_returns_action(self) -> None:
        callback_thread_names: list[str] = []

        def operator_cb(context: OperatorEscalationContext) -> RecoveryAction:
            assert context.error.uuid == "u"
            callback_thread_names.append(threading.current_thread().name)
            return RecoveryAction.ABORT

        bridge = OperatorEscalationBridge(operator_cb, shutdown_timeout=0.5)
        bridge.start()
        try:
            resolver_callback = cast(OperatorEscalationCallback, bridge.resolver_callback)
            result: RecoveryAction | None = asyncio.run(resolver_callback(_sample_context()))
        finally:
            bridge.stop("test done")

        assert result == RecoveryAction.ABORT
        assert callback_thread_names == ["hamilton-venus-operator-escalation"]

    def test_async_callback_result_is_awaited(self) -> None:
        async def operator_cb(context: OperatorEscalationContext) -> RecoveryAction:
            assert context.error.uuid == "u"
            await asyncio.sleep(0)
            return RecoveryAction.REPEAT

        bridge = OperatorEscalationBridge(operator_cb, shutdown_timeout=0.5)
        bridge.start()
        try:
            resolver_callback = cast(OperatorEscalationCallback, bridge.resolver_callback)
            result: RecoveryAction | None = asyncio.run(resolver_callback(_sample_context()))
        finally:
            bridge.stop("test done")

        assert result == RecoveryAction.REPEAT

    def test_sync_callback_can_return_error_recovery_payload(self) -> None:
        def operator_cb(context: OperatorEscalationContext) -> ErrorRecovery:
            assert context.error.uuid == "u"
            return ErrorRecovery(
                date="2026-01-01T00:00:00Z",
                uuid=context.error.uuid,
                selected_action_id=-1,
                selected_action_is_recovery=True,
                error_handling_key="hamiltonvenussdk",
            )

        bridge = OperatorEscalationBridge(operator_cb, shutdown_timeout=0.5)
        bridge.start()
        try:
            resolver_callback = cast(OperatorEscalationCallback, bridge.resolver_callback)
            result = asyncio.run(resolver_callback(_sample_context()))
        finally:
            bridge.stop("test done")

        assert isinstance(result, ErrorRecovery)
        assert result.uuid == "u"

    def test_stop_before_result_fails_pending_future(self) -> None:
        blocked = threading.Event()
        entered = threading.Event()

        def operator_cb(context: OperatorEscalationContext) -> RecoveryAction:
            assert context.error.uuid == "u"
            entered.set()
            blocked.wait(timeout=1.0)
            return RecoveryAction.ABORT

        bridge = OperatorEscalationBridge(operator_cb, shutdown_timeout=0.01)
        bridge.start()
        resolver_callback = cast(OperatorEscalationCallback, bridge.resolver_callback)

        async def _invoke() -> RecoveryAction | None:
            result = resolver_callback(_sample_context())
            if isinstance(result, Awaitable):
                return await result
            return result

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        future = asyncio.run_coroutine_threadsafe(_invoke(), loop)
        entered.wait(timeout=1.0)

        try:
            bridge.stop("forced stop")
            try:
                result = future.result(timeout=1.0)
                assert result == RecoveryAction.ABORT
            except RuntimeError as exc:
                assert str(exc) == "forced stop"
        finally:
            blocked.set()
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1.0)
            loop.close()
