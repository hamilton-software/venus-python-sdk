"""Unit tests for _RunMessageCommandDispatcher."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from hamilton_venus._internal._run_message_command_dispatcher import _RunMessageCommandDispatcher
from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import VenusCommandAbortedError, VenusTimeoutError
from hamilton_venus.models import CommandResponse, ExecutorEvent, RunMessageQueuedEvent

_PUSH_RUN_MESSAGE_PATH = "/api/vector/v3/run-messages"
_POP_RESPONSE_PATH = "/api/vector/v3/run-messages/action-response/pop"
_POP_COMMUNICATION_PATH = "/api/vector/v3/run-messages/communication/pop"


def _mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> httpx.Response:
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"} if json_data is not None else {},
        request=httpx.Request("GET", "http://testserver"),
    )


def _build_command_response_data(
    request_envelope: dict[str, Any],
    *,
    response_id: str | None = None,
    response_id_field: str = "actionId",
    status: str | None = None,
    return_status: str | None = None,
    return_code: int = 0,
    return_parameters: Any,
) -> dict[str, Any]:
    response_payload = {
        response_id_field: response_id or request_envelope["id"],
        "category": request_envelope["category"],
        "actionName": request_envelope["actionName"],
        "parameters": request_envelope["parameters"],
        "returnCode": return_code,
        "returnParameters": return_parameters,
    }
    if status is not None:
        response_payload["status"] = status
    if return_status is not None:
        response_payload["returnStatus"] = return_status
    return {
        "hasMessage": True,
        "data": response_payload,
    }


def _communication_payload(message_id: str, cmd_id: str, *, status: str = "running") -> dict[str, Any]:
    return {
        "channel": "communication",
        "hasMessage": True,
        "messageId": message_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "data": {
            "id": cmd_id,
            "category": "System",
            "command": "instrument.init",
            "status": status,
        },
    }


def _make_send_command_request_side_effect(request_mock: AsyncMock):
    def _request_side_effect(method, path, **kwargs):
        if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
            request_envelope = kwargs["json"]["data"]
            request_mock.request_envelope = request_envelope
            request_mock.queue_message_id = "queue-message-1"
            request_mock.response_data = _build_command_response_data(
                request_envelope,
                response_id=request_mock.queue_message_id,
                return_status="Success",
                return_code=0,
                return_parameters={"isConnected": True},
            )
            return _mock_response(json_data={"messageId": request_mock.queue_message_id, "channel": "action"})

        # No peek branch: responses are popped directly, so a peek is an unexpected request.
        if method == "POST" and path == _POP_RESPONSE_PATH:
            return _mock_response(json_data=request_mock.response_data)

        raise AssertionError(f"Unexpected request: {method} {path}")

    return _request_side_effect


class TestRunMessageCommandDispatcherEvents:
    @pytest.mark.asyncio
    async def test_wait_for_run_message_channel_ignores_other_channels(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", timeout=1.0))
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action"))
        await asyncio.sleep(0)
        assert waiter.done() is False

        action_queue = dispatcher._channel_queues["action"]
        queued_event = action_queue.popleft()
        assert queued_event.channel == "action"

        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await waiter

    @pytest.mark.asyncio
    async def test_concurrent_waiters_do_not_cross_consume_channels(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        action_waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", timeout=1.0))
        comm_waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("communication", timeout=1.0))

        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="communication"))
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

        await asyncio.gather(action_waiter, comm_waiter)

    @pytest.mark.asyncio
    async def test_unknown_channel_event_is_ignored_and_logs_debug(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        with patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger:
            await dispatcher.notify_run_message_queued(
                RunMessageQueuedEvent(channel="future-channel", message_id="m-1")
            )

        assert "future-channel" not in dispatcher._channel_queues
        assert "future-channel" not in dispatcher._channel_conditions
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_own_command_posts_on_the_action_channel_never_overflow(self):
        # Every command this client posts is echoed on "action"; nothing consumes those.
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        with patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger:
            for idx in range(1500):
                await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action", message_id=str(idx)))

        assert [event.message_id for event in dispatcher._channel_queues["action"]] == ["1499"]
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_queue_overflow_drops_oldest_and_logs_warning(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        with patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger:
            for idx in range(513):
                await dispatcher.notify_run_message_queued(
                    RunMessageQueuedEvent(channel="action-response", message_id=str(idx))
                )

        queue = dispatcher._channel_queues["action-response"]
        assert len(queue) == 512
        first_remaining = queue.popleft()
        assert first_remaining.message_id == "1"
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_run_message_channel_aborts_when_abort_status_arrives(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", timeout=1.0))
        await asyncio.sleep(0)
        dispatcher._notify_runtime_status(ExecutorEvent.ABORTED, "method aborted")

        with pytest.raises(VenusCommandAbortedError):
            await waiter


class TestRunMessageCommandDispatcherAbortLifecycle:
    @pytest.mark.asyncio
    async def test_start_communication_worker_resets_abort_state(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.ABORTED, "method aborted")

        with patch.object(dispatcher, "_run_communication_worker", new=AsyncMock()):
            await dispatcher.start_communication_worker()

        assert dispatcher._abort_event.is_set() is False
        assert dispatcher._abort_runtime_status == ""

    @pytest.mark.asyncio
    async def test_stop_communication_worker_resets_abort_state_when_no_task(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.ABORTED, "method aborted")

        await dispatcher.stop_communication_worker()

        assert dispatcher._abort_event.is_set() is False
        assert dispatcher._abort_runtime_status == ""

    @pytest.mark.asyncio
    async def test_prior_abort_does_not_poison_next_session_wait(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.ABORTED, "method aborted")

        with pytest.raises(VenusCommandAbortedError):
            await dispatcher._wait_for_run_message_channel("action-response", timeout=0.1)

        with patch.object(dispatcher, "_run_communication_worker", new=AsyncMock()):
            await dispatcher.start_communication_worker()

        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", timeout=1.0))
        await asyncio.sleep(0)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await waiter
        await dispatcher.stop_communication_worker()


class TestRunMessageCommandDispatcherPauseResume:
    def test_notify_paused_calls_suspend(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        with patch.object(dispatcher, "suspend") as mock_suspend:
            dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
        mock_suspend.assert_called_once()
        assert dispatcher._method_paused is True

    def test_notify_running_without_prior_pause_does_not_call_resume(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        with patch.object(dispatcher, "resume") as mock_resume:
            dispatcher._notify_runtime_status(ExecutorEvent.RUNNING)
        mock_resume.assert_not_called()
        assert dispatcher._method_paused is False

    def test_notify_paused_twice_only_suspends_once(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        with patch.object(dispatcher, "suspend") as mock_suspend:
            dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
            dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
        mock_suspend.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_running_after_pause_calls_resume(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
        with patch.object(dispatcher, "resume") as mock_resume:
            dispatcher._notify_runtime_status(ExecutorEvent.RUNNING)
        mock_resume.assert_called_once()
        assert dispatcher._method_paused is False

    @pytest.mark.asyncio
    async def test_reset_abort_state_clears_method_paused(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
        assert dispatcher._method_paused is True
        dispatcher._reset_abort_state()
        assert dispatcher._method_paused is False

    @pytest.mark.asyncio
    async def test_wait_for_response_passes_none_timeout_when_paused(self):
        """While paused (_command_deadline == inf), _wait_for_run_message_channel receives
        timeout=None so no sleep task is scheduled."""
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._notify_runtime_status(ExecutorEvent.PAUSED)
        assert dispatcher._command_deadline == math.inf

        timeout_values: list[float | None] = []

        wake_events: list[asyncio.Event | None] = []

        async def capture_timeout(channel: str, timeout: float | None, wake_event: asyncio.Event | None = None) -> None:
            timeout_values.append(timeout)
            wake_events.append(wake_event)

        dispatcher._wait_for_run_message_channel = capture_timeout  # type: ignore[method-assign]

        from hamilton_venus.models import CommandResponse

        fake_response = CommandResponse(
            id="x",
            category="System",
            actionName="test",
            returnCode=0,
            returnData=[],
        )

        async def peek_side_effect(*_: object, **__: object) -> tuple[object, bool]:
            return (fake_response, False)

        dispatcher._pop_and_process_message = peek_side_effect  # type: ignore[method-assign]

        result = await dispatcher._wait_for_response("test", "x")
        assert result is fake_response
        assert timeout_values == [None]
        # the unbounded wait can be woken when the deadline becomes finite again
        assert wake_events == [dispatcher._deadline_changed]


class TestRunMessageCommandDispatcherDeadlineWake:
    """A wait started while the deadline is suspended (timeout=None, e.g. while an operator resolves an
    instrument error) must notice when resume()/_auto_resume() make the deadline finite again."""

    @pytest.mark.asyncio
    async def test_resume_sets_the_deadline_changed_event(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._command_deadline = asyncio.get_running_loop().time() + 10.0
        dispatcher.suspend()
        assert dispatcher._deadline_changed.is_set()  # suspend wakes an in-flight wait too
        dispatcher._deadline_changed.clear()
        dispatcher.suspend()  # nested
        dispatcher.resume()
        assert not dispatcher._deadline_changed.is_set()  # still suspended once
        dispatcher.resume()
        assert dispatcher._deadline_changed.is_set()

    @pytest.mark.asyncio
    async def test_auto_resume_sets_the_deadline_changed_event(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher._command_deadline = dispatcher._loop.time() + 10.0
        dispatcher.suspend()
        dispatcher._auto_resume()
        assert dispatcher._deadline_changed.is_set()

    @pytest.mark.asyncio
    async def test_unbounded_wait_returns_when_the_wake_event_is_set_and_clears_it(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        wake = asyncio.Event()
        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", None, wake_event=wake))
        await asyncio.sleep(0.01)
        assert not waiter.done()
        wake.set()
        await asyncio.wait_for(waiter, timeout=1.0)  # returns normally: the caller re-checks its deadline
        assert not wake.is_set()

    @pytest.mark.asyncio
    async def test_unbounded_wait_without_a_wake_event_keeps_waiting(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", None))
        done, _pending = await asyncio.wait({waiter}, timeout=0.1)
        assert not done
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    @pytest.mark.asyncio
    async def test_a_message_still_wins_over_an_unset_wake_event(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        wake = asyncio.Event()
        waiter = asyncio.create_task(dispatcher._wait_for_run_message_channel("action-response", 5.0, wake_event=wake))
        await asyncio.sleep(0.01)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await asyncio.wait_for(waiter, timeout=1.0)

    @pytest.mark.asyncio
    async def test_wait_for_response_rechecks_the_deadline_restored_by_resume(self):
        """Suspended (deadline inf) while waiting, then resumed with 0.3 s left: the wait must end at that
        deadline (peek -> no response) instead of blocking forever on a message that never comes."""
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 0.3
        dispatcher.suspend()

        async def peek_side_effect(*_: object, **__: object) -> tuple[object, bool]:
            return (None, False)

        dispatcher._pop_and_process_message = peek_side_effect  # type: ignore[method-assign]

        waiter = asyncio.create_task(dispatcher._wait_for_response("test", "x"))
        await asyncio.sleep(0.05)
        assert not waiter.done()  # blocked: no deadline while suspended
        dispatcher.resume()
        result = await asyncio.wait_for(waiter, timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_suspend_during_an_in_flight_wait_stops_its_clock(self):
        """An error arrives (suspend) while a command is already waiting on a short
        timeout: the wait must not expire on its original schedule."""
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 0.2
        response = object()
        deliver = asyncio.Event()

        async def peek_side_effect(*_: object, **__: object) -> tuple[object, bool]:
            return (response if deliver.is_set() else None, False)

        dispatcher._pop_and_process_message = peek_side_effect  # type: ignore[method-assign]

        waiter = asyncio.create_task(dispatcher._wait_for_response("test", "x"))
        await asyncio.sleep(0.05)
        dispatcher.suspend()  # error event: stop the clock mid-wait
        await asyncio.sleep(0.4)  # well past the original 0.2 s deadline
        assert not waiter.done()

        deliver.set()  # the response finally arrives
        dispatcher._ensure_channel_state("action-response")
        queue, condition = (
            dispatcher._channel_queues["action-response"],
            dispatcher._channel_conditions["action-response"],
        )
        async with condition:
            queue.append(object())  # type: ignore[arg-type]
            condition.notify_all()
        assert await asyncio.wait_for(waiter, timeout=2.0) is response

    @pytest.mark.asyncio
    async def test_operator_hold_during_an_in_flight_wait_stops_its_clock(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 0.2

        async def peek_side_effect(*_: object, **__: object) -> tuple[object, bool]:
            return (None, False)

        dispatcher._pop_and_process_message = peek_side_effect  # type: ignore[method-assign]

        waiter = asyncio.create_task(dispatcher._wait_for_response("test", "x"))
        await asyncio.sleep(0.05)
        dispatcher.suspend()
        dispatcher.hold_for_operator()
        dispatcher.resume()  # VENUS's early "handled" -- must not restart the clock
        await asyncio.sleep(0.4)
        assert not waiter.done()
        waiter.cancel()


class TestRunMessageCommandDispatcherResponses:
    @pytest.mark.asyncio
    async def test_wait_for_response_returns_cached_response(self):
        request = AsyncMock()
        dispatcher = _RunMessageCommandDispatcher(request)
        cached_response = CommandResponse(
            id="cached-message-id",
            category="System",
            actionName="instrument.isConnected",
            parameters={},
            returnStatus="Success",
            returnCode=0,
            returnParameters={"isConnected": True},
        )
        dispatcher._pending_responses[cached_response.id] = cached_response
        dispatcher._command_deadline = asyncio.get_running_loop().time() + 1.0

        result = await dispatcher._wait_for_response(
            "instrument.isConnected",
            cached_response.id,
        )

        assert result is cached_response
        assert cached_response.id not in dispatcher._pending_responses
        request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_for_response_catches_timeout_and_attempts_final_pop(self):
        request = AsyncMock(
            return_value=_mock_response(json_data={"hasMessage": False}),
        )
        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._command_deadline = asyncio.get_running_loop().time() + 10

        with patch.object(dispatcher, "_wait_for_run_message_channel", side_effect=asyncio.TimeoutError):
            result = await dispatcher._wait_for_response(
                "instrument.isConnected",
                "test-message-id",
            )

        assert result is None
        request.assert_awaited_once_with(
            "POST",
            _POP_RESPONSE_PATH,
            error_prefix="Command(instrument.isConnected) - popping response",
        )


class TestRunMessageCommandDispatcherSendCommand:
    @pytest.mark.asyncio
    async def test_send_command_success(self):
        request = AsyncMock()
        request.side_effect = _make_send_command_request_side_effect(request)
        dispatcher = _RunMessageCommandDispatcher(request)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

        response = await dispatcher.send_command(
            "System",
            "instrument.isConnected",
            default_timeout=30.0,
        )

        assert response.success is True
        assert response.id == request.queue_message_id
        assert response.return_parameters == {"isConnected": True}
        # Push + one pop: the response is popped directly, without a peek first.
        assert request.await_count == 2

        push_call = request.await_args_list[0]
        assert push_call.args == ("POST", _PUSH_RUN_MESSAGE_PATH)
        assert push_call.kwargs["json"]["channel"] == "action"

        pop_call = request.await_args_list[1]
        assert pop_call.args == ("POST", _POP_RESPONSE_PATH)

    @pytest.mark.asyncio
    async def test_send_command_accepts_status_only_success_response(self):
        request = AsyncMock()
        queue_message_id = "queue-message-1"
        request.side_effect = [
            _mock_response(json_data={"messageId": queue_message_id, "channel": "action"}),
            _mock_response(
                json_data={
                    "hasMessage": True,
                    "data": {
                        "actionId": queue_message_id,
                        "status": "Success",
                        "returnParameters": {"instrumentName": "ML_STAR"},
                    },
                }
            ),
            _mock_response(
                json_data={
                    "hasMessage": True,
                    "data": {
                        "actionId": queue_message_id,
                        "status": "Success",
                        "returnParameters": {"instrumentName": "ML_STAR"},
                    },
                }
            ),
        ]
        dispatcher = _RunMessageCommandDispatcher(request)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

        response = await dispatcher.send_command(
            "System",
            "instrument.init",
            default_timeout=30.0,
        )

        assert response.success is True
        assert response.return_status == "Success"
        assert response.return_parameters == {"instrumentName": "ML_STAR"}

    @pytest.mark.asyncio
    async def test_send_command_times_out_when_no_response_arrives(self):
        request = AsyncMock(
            side_effect=[
                _mock_response(json_data={"messageId": "queue-message-1", "channel": "action"}),
                _mock_response(json_data={"hasMessage": False}),
            ]
        )
        dispatcher = _RunMessageCommandDispatcher(request)

        with (
            patch.object(dispatcher, "_wait_for_run_message_channel", side_effect=asyncio.TimeoutError),
            pytest.raises(
                VenusTimeoutError,
                match=r"instrument\.isConnected",
            ),
        ):
            await dispatcher.send_command(
                "System",
                "instrument.isConnected",
                default_timeout=0.05,
            )

        assert request.await_count == 2

    @pytest.mark.asyncio
    async def test_send_command_raises_aborted_when_runtime_aborts_while_waiting(self):
        request = AsyncMock(
            side_effect=[
                _mock_response(json_data={"messageId": "queue-message-1", "channel": "action"}),
            ]
        )
        dispatcher = _RunMessageCommandDispatcher(request)

        async def _trigger_abort() -> None:
            await asyncio.sleep(0)
            dispatcher._notify_runtime_status(ExecutorEvent.ABORTING, "operator abort")

        abort_task = asyncio.create_task(_trigger_abort())
        with pytest.raises(VenusCommandAbortedError, match="instrument\\.isConnected"):
            await dispatcher.send_command(
                "System",
                "instrument.isConnected",
                default_timeout=30.0,
            )
        await abort_task

    @pytest.mark.asyncio
    async def test_suspend_sets_infinite_deadline(self):
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        dispatcher._command_deadline = deadline

        dispatcher.suspend()

        assert dispatcher._suspension_counter == 1
        assert dispatcher._saved_remaining is not None
        assert 9.9 < dispatcher._saved_remaining <= 10.0
        assert dispatcher._command_deadline == math.inf

    @pytest.mark.asyncio
    async def test_resume_restores_deadline(self):
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        original_deadline = loop.time() + 10.0
        dispatcher._command_deadline = original_deadline
        saved_remaining_before_suspend = original_deadline - loop.time()

        dispatcher.suspend()
        await asyncio.sleep(0.01)
        dispatcher.resume()

        restored_deadline = dispatcher._command_deadline
        assert restored_deadline != math.inf
        expected_remaining = saved_remaining_before_suspend - 0.01
        assert expected_remaining - 0.05 < restored_deadline - loop.time() <= expected_remaining + 0.05

    @pytest.mark.asyncio
    async def test_suspend_resume_counter_based_nesting(self):
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        dispatcher._command_deadline = deadline

        dispatcher.suspend()
        assert dispatcher._suspension_counter == 1
        assert dispatcher._command_deadline == math.inf

        dispatcher.suspend()
        assert dispatcher._suspension_counter == 2
        assert dispatcher._command_deadline == math.inf

        dispatcher.resume()
        assert dispatcher._suspension_counter == 1
        assert dispatcher._command_deadline == math.inf

        dispatcher.resume()
        assert dispatcher._suspension_counter == 0
        restored_deadline = dispatcher._command_deadline
        assert restored_deadline != math.inf
        assert 9.9 < restored_deadline - loop.time() <= 10.0

    @pytest.mark.asyncio
    async def test_operator_hold_ignores_resume_and_fallback(self):
        """After a handoff to VENUS's operator dialog the deadline stays suspended:
        VENUS's early "handled" resume and the suspension fallback timer are ignored."""
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 10.0

        dispatcher.suspend()
        dispatcher.hold_for_operator()
        assert dispatcher._suspension_timer_handle is None  # no 600 s fallback while the operator decides

        dispatcher.resume()
        assert dispatcher._suspension_counter == 0
        assert dispatcher._command_deadline == math.inf

    @pytest.mark.asyncio
    async def test_pause_suspension_fallback_keeps_remaining_time_for_resume(self):
        """While an operator callback decides there is no 600 s fallback; the answer's
        resume restores the command's remaining time."""
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 10.0

        dispatcher.suspend()
        assert dispatcher._suspension_timer_handle is not None
        dispatcher.pause_suspension_fallback()
        assert dispatcher._suspension_timer_handle is None

        dispatcher.resume()
        assert 9.9 < dispatcher._command_deadline - loop.time() <= 10.0

    @pytest.mark.asyncio
    async def test_operator_hold_released_when_command_finishes(self):
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher.suspend()
        dispatcher.hold_for_operator()

        dispatcher._release_operator_hold()

        assert dispatcher._operator_hold is False
        assert dispatcher._suspension_counter == 0
        assert dispatcher._command_deadline == math.inf
        # A later suspend/resume pair behaves normally again.
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 10.0
        dispatcher.suspend()
        dispatcher.resume()
        assert 9.9 < dispatcher._command_deadline - loop.time() <= 10.0

    @pytest.mark.asyncio
    async def test_suspend_with_infinite_deadline_saves_none(self):
        import math

        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._command_deadline = math.inf

        dispatcher.suspend()

        assert dispatcher._suspension_counter == 1
        assert dispatcher._saved_remaining is None
        assert dispatcher._suspension_timer_handle is not None
        dispatcher._suspension_timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_resume_without_suspend_logs_warning(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        with patch(
            "hamilton_venus._internal._run_message_command_dispatcher._logger",
        ) as mock_logger:
            dispatcher.resume()
            mock_logger.warning.assert_called_once()
            assert "counter already at" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_suspend_sets_fallback_timer(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 10.0

        dispatcher.suspend()

        assert dispatcher._suspension_timer_handle is not None
        dispatcher._suspension_timer_handle.cancel()

    @pytest.mark.asyncio
    async def test_resume_cancels_fallback_timer(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        dispatcher._command_deadline = loop.time() + 10.0

        dispatcher.suspend()
        timer_handle = dispatcher._suspension_timer_handle

        dispatcher.resume()

        assert dispatcher._suspension_timer_handle is None
        assert timer_handle.cancelled()

    @pytest.mark.asyncio
    async def test_auto_resume_fires_after_fallback_timeout(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        loop = asyncio.get_running_loop()
        original_deadline = loop.time() + 10.0
        dispatcher._command_deadline = original_deadline
        dispatcher._SUSPENSION_FALLBACK_TIMEOUT = 0.05

        dispatcher.suspend()
        assert dispatcher._suspension_counter == 1

        await asyncio.sleep(0.1)

        assert dispatcher._suspension_counter == 0
        assert dispatcher._suspension_timer_handle is None


class TestCommandOperationContext:
    @pytest.mark.asyncio
    async def test_operation_context_is_none_initially(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        assert dispatcher.get_operation_context() is None

    @pytest.mark.asyncio
    async def test_operation_context_set_after_send_command(self):
        request = AsyncMock()
        request.side_effect = _make_send_command_request_side_effect(request)
        dispatcher = _RunMessageCommandDispatcher(request)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

        await dispatcher.send_command(
            "System",
            "instrument.isConnected",
            default_timeout=30.0,
        )

        assert dispatcher.get_operation_context() == "System/instrument.isConnected"

    @pytest.mark.asyncio
    async def test_operation_context_updated_across_multiple_commands(self):
        request = AsyncMock()

        call_count = 0

        def side_effect(method, path, **kwargs):
            nonlocal call_count
            if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
                request_envelope = kwargs["json"]["data"]
                request.queue_message_id = f"queue-message-{call_count}"
                call_count += 1
                request.response_data = _build_command_response_data(
                    request_envelope,
                    response_id=request.queue_message_id,
                    return_status="Success",
                    return_code=0,
                    return_parameters={},
                )
                return _mock_response(json_data={"messageId": request.queue_message_id, "channel": "action"})

            if method == "POST" and path == _POP_RESPONSE_PATH:
                return _mock_response(json_data=request.response_data)

            raise AssertionError(f"Unexpected request: {method} {path}")

        request.side_effect = side_effect
        dispatcher = _RunMessageCommandDispatcher(request)

        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await dispatcher.send_command("System", "instrument.init", default_timeout=30.0)
        assert dispatcher.get_operation_context() == "System/instrument.init"

        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await dispatcher.send_command("Control", "robot.move", default_timeout=30.0)
        assert dispatcher.get_operation_context() == "Control/robot.move"

    @pytest.mark.asyncio
    async def test_operation_context_format(self):
        request = AsyncMock()
        request.side_effect = _make_send_command_request_side_effect(request)
        dispatcher = _RunMessageCommandDispatcher(request)
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

        await dispatcher.send_command(
            "MyCategory",
            "myAction.subAction",
            default_timeout=30.0,
        )

        context = dispatcher.get_operation_context()
        assert "/" in context
        category, action = context.split("/")
        assert category == "MyCategory"
        assert action == "myAction.subAction"


class TestCommunicationWorkerAndDrain:
    @pytest.mark.asyncio
    async def test_drain_communication_logs_each_message(self):
        request = AsyncMock(
            side_effect=[
                _mock_response(json_data=_communication_payload("m-1", "cmd-1", status="running")),
                _mock_response(json_data=_communication_payload("m-2", "cmd-2", status="done")),
                _mock_response(json_data={"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )
        dispatcher = _RunMessageCommandDispatcher(request)

        with patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger:
            await dispatcher._drain_communication_channel()

        assert mock_logger.debug.call_count == 2
        # Pop-only: one pop per message plus the empty pop that ends the drain, never a peek.
        assert [call.args for call in request.await_args_list] == [("POST", _POP_COMMUNICATION_PATH)] * 3

    @pytest.mark.asyncio
    async def test_drain_communication_records_active_and_inactive_operation_context(self):
        request = AsyncMock(
            side_effect=[
                _mock_response(json_data=_communication_payload("m-1", "cmd-1")),
                _mock_response(json_data={"channel": "communication", "hasMessage": False, "data": {}}),
                _mock_response(json_data=_communication_payload("m-2", "cmd-2")),
                _mock_response(json_data={"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )
        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._run_log = Mock()
        dispatcher._run_log_config = RunLogConfig(include_cmd_comms=True)
        dispatcher._last_operation_context = "System/instrument.init"

        dispatcher._command_active = False
        await dispatcher._drain_communication_channel()
        first_payload = dispatcher._run_log.record.call_args_list[0].args[3]
        assert first_payload["active_operation_context"] is None

        dispatcher._command_active = True
        await dispatcher._drain_communication_channel()
        second_payload = dispatcher._run_log.record.call_args_list[1].args[3]
        assert second_payload["active_operation_context"] == "System/instrument.init"

    @pytest.mark.asyncio
    async def test_worker_poll_fallback_calls_drain_after_timeout(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._worker_stop_event = asyncio.Event()
        drain_count = 0

        async def drain_side_effect():
            nonlocal drain_count
            drain_count += 1
            if drain_count >= 2:
                dispatcher._worker_stop_event.set()

        with (
            patch.object(dispatcher, "_drain_communication_channel", side_effect=drain_side_effect),
            patch.object(dispatcher, "_wait_for_run_message_channel", side_effect=asyncio.TimeoutError),
        ):
            await dispatcher._run_communication_worker()

        assert drain_count == 2

    @pytest.mark.asyncio
    async def test_worker_continues_after_drain_error(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._worker_stop_event = asyncio.Event()
        drain_count = 0

        async def drain_side_effect():
            nonlocal drain_count
            drain_count += 1
            if drain_count == 2:
                raise RuntimeError("drain failure")
            if drain_count == 3:
                dispatcher._worker_stop_event.set()

        with (
            patch.object(dispatcher, "_drain_communication_channel", side_effect=drain_side_effect),
            patch.object(dispatcher, "_wait_for_run_message_channel", return_value=None),
            patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger,
        ):
            await dispatcher._run_communication_worker()

        assert drain_count == 3
        assert mock_logger.exception.call_count >= 1

    @pytest.mark.asyncio
    async def test_worker_stops_cleanly_on_abort_event(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._worker_stop_event = asyncio.Event()

        with (
            patch.object(dispatcher, "_drain_communication_channel", new=AsyncMock()) as drain_mock,
            patch.object(
                dispatcher,
                "_wait_for_run_message_channel",
                side_effect=VenusCommandAbortedError("aborted"),
            ),
            patch("hamilton_venus._internal._run_message_command_dispatcher._logger") as mock_logger,
        ):
            await dispatcher._run_communication_worker()

        assert drain_mock.await_count == 1
        mock_logger.debug.assert_called_once_with("Communication worker stopping due to method abort event")
        mock_logger.exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_lifecycle_start_stop(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())

        await dispatcher.start_communication_worker()
        assert dispatcher._worker_task is not None
        assert dispatcher._worker_stop_event is not None

        await dispatcher.stop_communication_worker()
        assert dispatcher._worker_task is None
        assert dispatcher._worker_stop_event is None
        assert dispatcher._abort_event.is_set() is False
        assert dispatcher._abort_runtime_status == ""

    @pytest.mark.asyncio
    async def test_worker_initial_drain_runs_before_wait(self):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher._worker_stop_event = asyncio.Event()

        async def wait_side_effect(*args, **kwargs):
            dispatcher._worker_stop_event.set()
            return None

        with (
            patch.object(dispatcher, "_drain_communication_channel", new=AsyncMock()) as drain_mock,
            patch.object(dispatcher, "_wait_for_run_message_channel", side_effect=wait_side_effect),
        ):
            await dispatcher._run_communication_worker()

        assert drain_mock.await_count >= 2


class TestCommandGuard:
    @pytest.mark.asyncio
    async def test_guard_veto_prevents_sending(self):
        request = AsyncMock()
        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher.set_command_guard(Mock(side_effect=RuntimeError("vetoed")))

        with pytest.raises(RuntimeError, match="vetoed"):
            await dispatcher.send_command("Instrument", "mph96.aspirate", default_timeout=5.0)

        request.assert_not_called()
        assert dispatcher._command_active is False

    @pytest.mark.asyncio
    async def test_guard_receives_category_and_action(self):
        guard = Mock(side_effect=RuntimeError("stop"))
        dispatcher = _RunMessageCommandDispatcher(AsyncMock())
        dispatcher.set_command_guard(guard)

        with pytest.raises(RuntimeError):
            await dispatcher.send_command("Instrument", "autoload.moveTo", default_timeout=5.0)

        guard.assert_called_once_with("Instrument", "autoload.moveTo")


class TestStatusChannelPeekAndDelete:
    @pytest.mark.asyncio
    async def test_peek_channel_message_returns_the_message_id(self):
        request = AsyncMock(
            return_value=_mock_response(
                json_data={"channel": "ready", "hasMessage": True, "messageId": "m-1", "data": {"isReady": True}}
            )
        )
        dispatcher = _RunMessageCommandDispatcher(request)

        assert await dispatcher.peek_channel_message("ready") == ("m-1", {"isReady": True})
        assert await dispatcher.peek_channel("ready") == {"isReady": True}
        request.assert_awaited_with("GET", "/api/vector/v3/run-messages/ready/peek", error_prefix="PeekChannel(ready)")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [{"hasMessage": False}, {"hasMessage": True, "data": "x"}, ["not", "a", "dict"]],
        ids=["empty", "data-not-dict", "body-not-dict"],
    )
    async def test_peek_channel_message_none_when_nothing_usable(self, body):
        dispatcher = _RunMessageCommandDispatcher(AsyncMock(return_value=_mock_response(json_data=body)))

        assert await dispatcher.peek_channel_message("ready") is None

    @pytest.mark.asyncio
    async def test_peek_channel_message_tolerates_a_missing_id(self):
        body = {"hasMessage": True, "messageId": None, "data": {"isReady": True}}
        dispatcher = _RunMessageCommandDispatcher(AsyncMock(return_value=_mock_response(json_data=body)))

        assert await dispatcher.peek_channel_message("ready") == ("", {"isReady": True})

    @pytest.mark.asyncio
    async def test_delete_channel(self):
        request = AsyncMock(return_value=_mock_response(json_data={"messagesDeleted": 1}))
        dispatcher = _RunMessageCommandDispatcher(request)

        await dispatcher.delete_channel("ready")

        request.assert_awaited_once_with(
            "DELETE", "/api/vector/v3/run-messages/ready", error_prefix="DeleteChannel(ready)"
        )


class TestMethodWatchdog:
    """VENUS can end its method without an ABORTED event; a waiting command must not sit until its timeout."""

    @staticmethod
    def _request(run_state_values):
        states = iter(run_state_values)
        last = {"value": run_state_values[-1]}

        def side_effect(method, path, **kwargs):
            if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
                return _mock_response(json_data={"messageId": "queue-message-1", "channel": "action"})
            if method == "POST" and path == _POP_RESPONSE_PATH:  # the final pop when a wait times out
                return _mock_response(json_data={"hasMessage": False})
            if method == "GET" and path == "/api/vector/v3/execution/run-state":
                last["value"] = next(states, last["value"])
                return _mock_response(json_data=last["value"])
            raise AssertionError(f"Unexpected request: {method} {path}")

        return AsyncMock(side_effect=side_effect)

    @pytest.mark.asyncio
    async def test_a_command_fails_fast_when_the_method_is_gone(self, monkeypatch):
        import hamilton_venus._internal._run_message_command_dispatcher as module

        monkeypatch.setattr(module, "_METHOD_WATCH_INTERVAL", 0.01)
        dispatcher = _RunMessageCommandDispatcher(self._request([0]))  # NOT_INITIALIZED: no method loaded

        with pytest.raises(VenusCommandAbortedError, match="VENUS ended the method without answering"):
            await asyncio.wait_for(
                dispatcher.send_command("Deck Layout", "labware.addReservoir", default_timeout=300.0), timeout=5.0
            )

    @pytest.mark.asyncio
    async def test_a_running_method_is_left_alone(self, monkeypatch):
        import hamilton_venus._internal._run_message_command_dispatcher as module

        monkeypatch.setattr(module, "_METHOD_WATCH_INTERVAL", 0.01)
        dispatcher = _RunMessageCommandDispatcher(self._request([2]))  # RUNNING

        with pytest.raises(VenusTimeoutError):
            await dispatcher.send_command("Deck Layout", "labware.addReservoir", default_timeout=0.3)
        assert dispatcher._abort_event.is_set() is False

    @pytest.mark.asyncio
    async def test_one_odd_reading_does_not_count(self, monkeypatch):
        import hamilton_venus._internal._run_message_command_dispatcher as module

        monkeypatch.setattr(module, "_METHOD_WATCH_INTERVAL", 0.01)
        # gone, running, gone, running ... never three in a row
        dispatcher = _RunMessageCommandDispatcher(self._request([0, 2] * 40))

        with pytest.raises(VenusTimeoutError):
            await dispatcher.send_command("Deck Layout", "labware.addReservoir", default_timeout=0.3)
        assert dispatcher._abort_event.is_set() is False

    @pytest.mark.asyncio
    async def test_a_failing_run_state_lookup_never_aborts(self, monkeypatch):
        import hamilton_venus._internal._run_message_command_dispatcher as module

        monkeypatch.setattr(module, "_METHOD_WATCH_INTERVAL", 0.01)

        def side_effect(method, path, **kwargs):
            if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
                return _mock_response(json_data={"messageId": "queue-message-1", "channel": "action"})
            if path == _POP_RESPONSE_PATH:
                return _mock_response(json_data={"hasMessage": False})
            raise RuntimeError("VENUS not answering")

        dispatcher = _RunMessageCommandDispatcher(AsyncMock(side_effect=side_effect))
        with pytest.raises(VenusTimeoutError):
            await dispatcher.send_command("Deck Layout", "labware.addReservoir", default_timeout=0.3)
        assert dispatcher._abort_event.is_set() is False
