"""Unit tests for hamilton_venus._signalr_listener."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus._internal._signalr_listener import (
    DEVICE_CREATED,
    DEVICE_ERROR_HANDLED_RESPONSE,
    INSTRUMENT_CHANGED,
    INSTRUMENT_ERROR_EVENT,
    INSTRUMENT_ERROR_NOTIFICATION,
    LABWARE_LOADED_STATE_CHANGED,
    LABWARE_POSITION_STATE_CHANGED,
    LABWARE_STATE_CHANGED,
    LOAD_METHOD,
    PROGRESS_CHANGED,
    RUN_MESSAGE_QUEUED,
    RUNTIME_ERROR,
    RUNTIME_STATUS,
    RUNTIME_TRACE,
    UNLOAD_METHOD,
    _SignalRListener,
)
from hamilton_venus.models import (
    ConnectionState,
    LabwareLoadedStateChangedEvent,
    LabwarePositionStateChangedEvent,
    ProgressChangedEvent,
    RunMessageQueuedEvent,
    RuntimeStatusEvent,
)


@pytest.fixture
def mock_signalr_client():
    with patch("hamilton_venus._internal._signalr_listener.SignalRClient") as cls:
        client = MagicMock()
        client.on = MagicMock()
        client.on_open = MagicMock()
        client.on_close = MagicMock()
        client.on_error = MagicMock()
        client.run = AsyncMock()
        cls.return_value = client
        yield client


class TestSignalRListenerInit:
    def test_initial_state_is_disconnected(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        assert listener.state == ConnectionState.DISCONNECTED
        assert listener._client is None

    def test_registers_signalr_handlers(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        listener._create_client(None)
        event_names = [call.args[0] for call in mock_signalr_client.on.call_args_list]
        expected_event_names = {
            RUNTIME_STATUS,
            PROGRESS_CHANGED,
            RUNTIME_ERROR,
            RUNTIME_TRACE,
            LOAD_METHOD,
            UNLOAD_METHOD,
            DEVICE_CREATED,
            INSTRUMENT_CHANGED,
            RUN_MESSAGE_QUEUED,
            LABWARE_STATE_CHANGED,
            LABWARE_POSITION_STATE_CHANGED,
            LABWARE_LOADED_STATE_CHANGED,
            INSTRUMENT_ERROR_EVENT,
            INSTRUMENT_ERROR_NOTIFICATION,
            DEVICE_ERROR_HANDLED_RESPONSE,
        }
        assert mock_signalr_client.on.call_count == len(expected_event_names)
        assert set(event_names) == expected_event_names
        mock_signalr_client.on_open.assert_called_once()
        mock_signalr_client.on_close.assert_called_once()
        mock_signalr_client.on_error.assert_called_once()

    def test_strips_trailing_slash(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400/")
        assert listener._hub_url == "http://test:42400/signalr"


class TestSignalRListenerStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_connecting(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        mock_signalr_client.run = AsyncMock(side_effect=asyncio.CancelledError)
        await listener.start()
        assert listener.state == ConnectionState.CONNECTING
        await listener.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        mock_signalr_client.run = AsyncMock(side_effect=asyncio.CancelledError)
        await listener.start()
        task1 = listener._run_task
        await listener.start()
        assert listener._run_task is task1
        await listener.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_disconnected(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        mock_signalr_client.run = AsyncMock(side_effect=asyncio.CancelledError)
        await listener.start()
        await listener.stop()
        assert listener.state == ConnectionState.DISCONNECTED
        assert listener._run_task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        await listener.stop()
        assert listener.state == ConnectionState.DISCONNECTED


class TestSignalRListenerStateCallbacks:
    @pytest.mark.asyncio
    async def test_set_state_fires_callbacks(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_connection_state(cb)
        listener._set_state(ConnectionState.CONNECTED)
        await asyncio.sleep(0.05)
        cb.assert_awaited_once_with(ConnectionState.CONNECTED)

    @pytest.mark.asyncio
    async def test_set_state_skips_same_state(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_connection_state(cb)
        listener._set_state(ConnectionState.DISCONNECTED)
        await asyncio.sleep(0.05)
        cb.assert_not_awaited()


class TestSignalRListenerOnOpen:
    @pytest.mark.asyncio
    async def test_on_open_sets_connected(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        await listener._on_open()
        assert listener.state == ConnectionState.CONNECTED


class TestSignalRListenerOnClose:
    @pytest.mark.asyncio
    async def test_on_close_sets_disconnected(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        listener._state = ConnectionState.CONNECTED
        await listener._on_close()
        assert listener.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_on_close_during_disconnect_keeps_disconnecting(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        listener._state = ConnectionState.DISCONNECTING
        await listener._on_close()
        assert listener.state == ConnectionState.DISCONNECTING


class TestSignalRListenerOnError:
    @pytest.mark.asyncio
    async def test_on_error_sets_error_state(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        msg = MagicMock()
        msg.error = "test error"
        await listener._on_error(msg)
        assert listener.state == ConnectionState.ERROR


class TestSignalRListenerRuntimeStatus:
    @pytest.mark.asyncio
    async def test_dict_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_runtime_status(cb)
        await listener._on_runtime_status([{"executorEvent": 6, "message": "running"}])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, RuntimeStatusEvent)
        assert event.executor_event == 6
        assert event.message == "running"

    @pytest.mark.asyncio
    async def test_int_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_runtime_status(cb)
        await listener._on_runtime_status([3])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert event.executor_event == 3
        assert event.message == ""

    @pytest.mark.asyncio
    async def test_empty_arguments(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_runtime_status(cb)
        await listener._on_runtime_status([])
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=ValueError("boom"))
        listener.on_runtime_status(cb)
        await listener._on_runtime_status([{"executorEvent": 1, "message": ""}])


class TestSignalRListenerProgressChanged:
    @pytest.mark.asyncio
    async def test_dict_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_progress(cb)
        await listener._on_progress_changed([{"methodName": "test.hsl", "progressPercentage": 50.0}])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, ProgressChangedEvent)
        assert event.method_name == "test.hsl"
        assert event.progress_percentage == 50.0

    @pytest.mark.asyncio
    async def test_non_dict_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_progress(cb)
        await listener._on_progress_changed(["not a dict"])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert event.method_name == ""

    @pytest.mark.asyncio
    async def test_empty_arguments(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_progress(cb)
        await listener._on_progress_changed([])
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_progress(cb)
        await listener._on_progress_changed([{"methodName": "x", "progressPercentage": 0}])


class TestSignalRListenerErrorTrace:
    @pytest.mark.asyncio
    async def test_runtime_error_callback(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_runtime_error(cb)
        await listener._on_runtime_error(["some error data"])
        cb.assert_awaited_once_with(["some error data"])

    @pytest.mark.asyncio
    async def test_runtime_trace_callback(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_runtime_trace(cb)
        await listener._on_runtime_trace(["trace data"])
        cb.assert_awaited_once_with(["trace data"])

    @pytest.mark.asyncio
    async def test_run_message_queued_callback(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_run_message_queued(cb)
        await listener._on_run_message_queued(
            [
                {
                    "channel": "action-response",
                    "messageId": "abc",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "queueDepth": 1,
                }
            ]
        )
        cb.assert_awaited_once()
        assert cb.await_args is not None
        event = cb.await_args.args[0]
        assert isinstance(event, RunMessageQueuedEvent)
        assert event.channel == "action-response"
        assert event.message_id == "abc"
        assert event.queue_depth == 1

    @pytest.mark.asyncio
    async def test_run_message_queued_communication_channel_passthrough(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_run_message_queued(cb)
        await listener._on_run_message_queued(
            [
                {
                    "channel": "communication",
                    "messageId": "comm-123",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "queueDepth": 2,
                }
            ]
        )
        cb.assert_awaited_once()
        assert cb.await_args is not None
        event = cb.await_args.args[0]
        assert isinstance(event, RunMessageQueuedEvent)
        assert event.channel == "communication"
        assert event.message_id == "comm-123"
        assert event.queue_depth == 2

    @pytest.mark.asyncio
    async def test_run_message_queued_non_dict_payload_defaults(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_run_message_queued(cb)
        await listener._on_run_message_queued(["unexpected"])
        cb.assert_awaited_once()
        assert cb.await_args is not None
        event = cb.await_args.args[0]
        assert isinstance(event, RunMessageQueuedEvent)
        assert event.channel == ""
        assert event.message_id == ""
        assert event.queue_depth == 0

    @pytest.mark.asyncio
    async def test_error_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_runtime_error(cb)
        await listener._on_runtime_error(["err"])

    @pytest.mark.asyncio
    async def test_trace_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_runtime_trace(cb)
        await listener._on_runtime_trace(["trace"])

    @pytest.mark.asyncio
    async def test_run_message_queued_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_run_message_queued(cb)
        await listener._on_run_message_queued([{"channel": "action-response"}])


class TestSignalRListenerLabwarePositionStateChanged:
    @pytest.mark.asyncio
    async def test_dict_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_position_state_changed(cb)
        await listener._on_labware_position_state_changed(
            [
                {
                    "labwareId": "plate1",
                    "positionId": "A1",
                    "state": 1,
                }
            ]
        )
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwarePositionStateChangedEvent)
        assert event.labware_id == "plate1"
        assert event.position_id == "A1"
        assert event.state == 1

    @pytest.mark.asyncio
    async def test_non_dict_payload_defaults(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_position_state_changed(cb)
        await listener._on_labware_position_state_changed(["unexpected"])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwarePositionStateChangedEvent)
        assert event.labware_id == ""
        assert event.position_id == ""
        assert event.state == 0

    @pytest.mark.asyncio
    async def test_empty_arguments(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_position_state_changed(cb)
        await listener._on_labware_position_state_changed([])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwarePositionStateChangedEvent)

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_labware_position_state_changed(cb)
        await listener._on_labware_position_state_changed([{"labwareId": "plate1"}])


class TestSignalRListenerLabwareLoadedStateChanged:
    @pytest.mark.asyncio
    async def test_dict_payload(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_loaded_state_changed(cb)
        await listener._on_labware_loaded_state_changed(
            [
                {
                    "labwareId": "plate1",
                }
            ]
        )
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwareLoadedStateChangedEvent)
        assert event.labware_id == "plate1"

    @pytest.mark.asyncio
    async def test_non_dict_payload_defaults(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_loaded_state_changed(cb)
        await listener._on_labware_loaded_state_changed(["unexpected"])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwareLoadedStateChangedEvent)
        assert event.labware_id == ""

    @pytest.mark.asyncio
    async def test_empty_arguments(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock()
        listener.on_labware_loaded_state_changed(cb)
        await listener._on_labware_loaded_state_changed([])
        cb.assert_awaited_once()
        event = cb.call_args[0][0]
        assert isinstance(event, LabwareLoadedStateChangedEvent)

    @pytest.mark.asyncio
    async def test_callback_exception_is_caught(self, mock_signalr_client):
        listener = _SignalRListener(base_url="http://test:42400")
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        listener.on_labware_loaded_state_changed(cb)
        await listener._on_labware_loaded_state_changed([{"labwareId": "plate1"}])


def _make_reconnect_listener(run_side_effect: Any, **listener_kwargs: Any) -> tuple[_SignalRListener, Any]:
    """Helper: build a _SignalRListener with a mocked client.run."""
    max_reconnect_attempts = int(listener_kwargs.pop("max_reconnect_attempts", 5))
    reconnect_backoff = float(listener_kwargs.pop("reconnect_backoff", 0.01))
    ctx = patch("hamilton_venus._internal._signalr_listener.SignalRClient")
    cls = ctx.__enter__()
    mock_client = MagicMock()
    mock_client.on = MagicMock()
    mock_client.on_open = MagicMock()
    mock_client.on_close = MagicMock()
    mock_client.on_error = MagicMock()
    mock_client.run = AsyncMock(side_effect=run_side_effect)
    cls.return_value = mock_client
    listener = _SignalRListener(
        base_url="http://test:42400",
        max_reconnect_attempts=max_reconnect_attempts,
        reconnect_backoff=reconnect_backoff,
        **listener_kwargs,
    )
    return listener, ctx


class TestSignalRListenerReconnection:
    @pytest.mark.asyncio
    async def test_reconnects_on_failure(self):
        call_count = 0

        async def _run():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("lost connection")
            raise asyncio.CancelledError

        listener, ctx = _make_reconnect_listener(_run)
        try:
            await listener.start()
            await asyncio.sleep(0.5)
            assert call_count == 3
            await listener.stop()
        finally:
            ctx.__exit__(None, None, None)

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts(self):
        call_count = 0

        async def _run():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        listener, ctx = _make_reconnect_listener(_run, max_reconnect_attempts=2)
        try:
            await listener.start()
            await asyncio.sleep(0.5)
            assert listener.state == ConnectionState.ERROR
            assert call_count == 3
        finally:
            ctx.__exit__(None, None, None)

    @pytest.mark.asyncio
    async def test_reconnect_disabled_when_zero(self):
        call_count = 0

        async def _run():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        listener, ctx = _make_reconnect_listener(_run, max_reconnect_attempts=0)
        try:
            await listener.start()
            await asyncio.sleep(0.3)
            assert listener.state == ConnectionState.ERROR
            assert call_count == 1
        finally:
            ctx.__exit__(None, None, None)

    @pytest.mark.asyncio
    async def test_stop_during_reconnect_backoff(self):
        async def _run():
            raise ConnectionError("fail")

        listener, ctx = _make_reconnect_listener(
            _run,
            max_reconnect_attempts=10,
            reconnect_backoff=5.0,
        )
        try:
            await listener.start()
            await asyncio.sleep(0.1)
            await listener.stop()
            assert listener.state == ConnectionState.DISCONNECTED
        finally:
            ctx.__exit__(None, None, None)

    @pytest.mark.asyncio
    async def test_resets_attempt_counter_on_success(self):
        call_count = 0

        async def _run():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("first fail")
            raise asyncio.CancelledError

        listener, ctx = _make_reconnect_listener(_run, max_reconnect_attempts=3)
        try:
            await listener.start()
            await asyncio.sleep(0.3)
            assert call_count == 2
            await listener.stop()
        finally:
            ctx.__exit__(None, None, None)
