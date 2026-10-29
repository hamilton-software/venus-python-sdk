"""_SignalRListener — internal SignalR listener for the Hamilton VENUS WebAPI hub."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

from pydantic import ValidationError
from pysignalr.client import SignalRClient
from pysignalr.messages import CompletionMessage

from hamilton_venus._internal._run_log import RunLog
from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import VenusConnectionError
from hamilton_venus.models import (
    ConnectionState,
    ErrorData,
    InstrumentErrorHandled,
    LabwareLoadedStateChangedEvent,
    LabwarePositionStateChangedEvent,
    ProgressChangedEvent,
    RunMessageQueuedEvent,
    RuntimeStatusEvent,
)

_logger = logging.getLogger(__name__)

RUNTIME_STATUS = "NewRuntimeStatus"
PROGRESS_CHANGED = "OnProgressChanged"
RUNTIME_ERROR = "NewRuntimeError"
RUNTIME_TRACE = "NewRuntimeTrace"
LOAD_METHOD = "OnLoadMethod"
UNLOAD_METHOD = "OnUnloadMethod"
DEVICE_CREATED = "OnDeviceCreated"
INSTRUMENT_CHANGED = "OnInstrumentChanged"
RUN_MESSAGE_QUEUED = "OnRunMessageQueued"
LABWARE_STATE_CHANGED = "LabwareStateChanged"
LABWARE_POSITION_STATE_CHANGED = "LabwarePositionStateChanged"
LABWARE_LOADED_STATE_CHANGED = "LabwareLoadedStateChanged"
INSTRUMENT_ERROR_EVENT = "InstrumentErrorEvent"
INSTRUMENT_ERROR_NOTIFICATION = "InstrumentErrorNotification"
DEVICE_ERROR_HANDLED_RESPONSE = "DeviceErrorHandledResponse"

RuntimeStatusCallback = Callable[[RuntimeStatusEvent], Awaitable[None]]
ProgressCallback = Callable[[ProgressChangedEvent], Awaitable[None]]
ErrorCallback = Callable[[list[Any]], Awaitable[None]]
TraceCallback = Callable[[list[Any]], Awaitable[None]]
ConnectionStateCallback = Callable[[ConnectionState], Awaitable[None]]
RunMessageQueuedCallback = Callable[[RunMessageQueuedEvent], Awaitable[None]]
LabwarePositionStateChangedCallback = Callable[[LabwarePositionStateChangedEvent], Awaitable[None]]
LabwareLoadedStateChangedCallback = Callable[[LabwareLoadedStateChangedEvent], Awaitable[None]]
InstrumentErrorCallback = Callable[[ErrorData], Awaitable[None]]
# The server sends this event as a plain string notification, unlike the other
# two error events which carry structured (Pydantic-deserializable) payloads.
InstrumentErrorNotificationCallback = Callable[[str], Awaitable[None]]
DeviceErrorHandledCallback = Callable[[InstrumentErrorHandled], Awaitable[None]]


class _SignalRListener:
    """Manages a SignalR connection to the VENUS WebAPI hub at ``/signalr``.

    Automatically reconnects with exponential backoff when the connection drops
    unexpectedly (i.e. not via an explicit :meth:`stop` call).

    Parameters
    ----------
    base_url:
        Base URL of the VENUS WebAPI.
    headers:
        Optional extra HTTP headers.
    ping_interval:
        Interval in seconds between keep-alive pings.
    connection_timeout:
        Timeout in seconds for the initial connection handshake.
    max_size:
        Maximum WebSocket frame size in bytes.
    max_reconnect_attempts:
        Maximum number of consecutive reconnection attempts before giving up.
        Set to ``0`` to disable automatic reconnection.
    reconnect_backoff:
        Base delay in seconds between reconnection attempts.  Each subsequent
        attempt doubles the delay (exponential backoff).
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        ping_interval: int = 10,
        connection_timeout: int = 10,
        max_size: int | None = 1_048_576,
        max_reconnect_attempts: int = 5,
        reconnect_backoff: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._hub_url = self._base_url + "/signalr"
        self._headers = headers or {}
        self._ping_interval = ping_interval
        self._connection_timeout = connection_timeout
        self._max_size = max_size
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_backoff = reconnect_backoff

        self._state = ConnectionState.DISCONNECTED
        self._run_task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._fatal_error: Exception | None = None
        self._client: SignalRClient | None = None
        self._run_log: RunLog | None = None
        self._run_log_config: RunLogConfig = RunLogConfig()

        self._runtime_status_callbacks: list[RuntimeStatusCallback] = []
        self._progress_callbacks: list[ProgressCallback] = []
        self._error_callbacks: list[ErrorCallback] = []
        self._trace_callbacks: list[TraceCallback] = []
        self._connection_state_callbacks: list[ConnectionStateCallback] = []
        self._run_message_queued_callbacks: list[RunMessageQueuedCallback] = []
        self._labware_position_state_changed_callbacks: list[LabwarePositionStateChangedCallback] = []
        self._labware_loaded_state_changed_callbacks: list[LabwareLoadedStateChangedCallback] = []
        self._instrument_error_callbacks: list[InstrumentErrorCallback] = []
        self._instrument_error_notification_callbacks: list[InstrumentErrorNotificationCallback] = []
        self._device_error_handled_callbacks: list[DeviceErrorHandledCallback] = []

    def set_run_log(self, run_log: RunLog | None) -> None:
        self._run_log = run_log

    def set_run_log_config(self, run_log_config: RunLogConfig) -> None:
        self._run_log_config = run_log_config

    async def _build_headers(self) -> dict[str, str] | None:
        return self._headers or None

    def _create_client(self, headers: dict[str, str] | None) -> SignalRClient:
        client = SignalRClient(
            url=self._hub_url,
            headers=headers,
            ping_interval=self._ping_interval,
            connection_timeout=self._connection_timeout,
            max_size=self._max_size,
        )
        client.on(RUNTIME_STATUS, self._on_runtime_status)
        client.on(PROGRESS_CHANGED, self._on_progress_changed)
        client.on(RUNTIME_ERROR, self._on_runtime_error)
        client.on(RUNTIME_TRACE, self._on_runtime_trace)
        client.on(LOAD_METHOD, self._on_load_method)
        client.on(UNLOAD_METHOD, self._on_unload_method)
        client.on(DEVICE_CREATED, self._on_device_created)
        client.on(INSTRUMENT_CHANGED, self._on_instrument_changed)
        client.on(RUN_MESSAGE_QUEUED, self._on_run_message_queued)
        client.on(LABWARE_STATE_CHANGED, self._on_labware_state_changed)
        client.on(LABWARE_POSITION_STATE_CHANGED, self._on_labware_position_state_changed)
        client.on(LABWARE_LOADED_STATE_CHANGED, self._on_labware_loaded_state_changed)
        client.on(INSTRUMENT_ERROR_EVENT, self._on_instrument_error_event)
        client.on(INSTRUMENT_ERROR_NOTIFICATION, self._on_instrument_error_notification)
        client.on(DEVICE_ERROR_HANDLED_RESPONSE, self._on_device_error_handled_response)
        client.on_open(self._on_open)
        client.on_close(self._on_close)
        client.on_error(self._on_error)
        return client

    async def _build_client(self) -> SignalRClient:
        return self._create_client(await self._build_headers())

    @property
    def state(self) -> ConnectionState:
        """Current :class:`ConnectionState` of the SignalR connection."""
        return self._state

    @property
    def fatal_error(self) -> Exception | None:
        """Terminal listener error, if the run loop has failed permanently."""
        return self._fatal_error

    def on_runtime_status(self, callback: RuntimeStatusCallback) -> None:
        """Register a callback invoked on each ``NewRuntimeStatus`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a :class:`RuntimeStatusEvent`.
        """
        self._runtime_status_callbacks.append(callback)

    def on_progress(self, callback: ProgressCallback) -> None:
        """Register a callback invoked on each ``OnProgressChanged`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a :class:`ProgressChangedEvent`.
        """
        self._progress_callbacks.append(callback)

    def on_runtime_error(self, callback: ErrorCallback) -> None:
        """Register a callback invoked on each ``NewRuntimeError`` event.

        Parameters
        ----------
        callback:
            An async callable accepting the raw argument list from SignalR.
        """
        self._error_callbacks.append(callback)

    def on_runtime_trace(self, callback: TraceCallback) -> None:
        """Register a callback invoked on each ``NewRuntimeTrace`` event.

        Parameters
        ----------
        callback:
            An async callable accepting the raw argument list from SignalR.
        """
        self._trace_callbacks.append(callback)

    def on_connection_state(self, callback: ConnectionStateCallback) -> None:
        """Register a callback invoked whenever the connection state changes.

        Parameters
        ----------
        callback:
            An async callable accepting the new :class:`ConnectionState`.
        """
        self._connection_state_callbacks.append(callback)

    def on_run_message_queued(self, callback: RunMessageQueuedCallback) -> None:
        """Register a callback invoked on each ``OnRunMessageQueued`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a :class:`RunMessageQueuedEvent`.
        """
        self._run_message_queued_callbacks.append(callback)

    def on_labware_position_state_changed(self, callback: LabwarePositionStateChangedCallback) -> None:
        """Register a callback invoked on each ``LabwarePositionStateChanged`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a :class:`LabwarePositionStateChangedEvent`.
        """
        self._labware_position_state_changed_callbacks.append(callback)

    def on_labware_loaded_state_changed(self, callback: LabwareLoadedStateChangedCallback) -> None:
        """Register a callback invoked on each ``LabwareLoadedStateChanged`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a :class:`LabwareLoadedStateChangedEvent`.
        """
        self._labware_loaded_state_changed_callbacks.append(callback)

    def on_instrument_error(self, callback: InstrumentErrorCallback) -> None:
        """Register a callback invoked on each ``InstrumentErrorEvent`` event.

        Parameters
        ----------
        callback:
            An async callable accepting an :class:`ErrorData`.
        """
        self._instrument_error_callbacks.append(callback)

    def on_instrument_error_notification(self, callback: InstrumentErrorNotificationCallback) -> None:
        """Register a callback invoked on each ``InstrumentErrorNotification`` event.

        Parameters
        ----------
        callback:
            An async callable accepting a notification string.
        """
        self._instrument_error_notification_callbacks.append(callback)

    def on_device_error_handled(self, callback: DeviceErrorHandledCallback) -> None:
        """Register a callback invoked on each ``DeviceErrorHandledResponse`` event.

        Parameters
        ----------
        callback:
            An async callable accepting an :class:`InstrumentErrorHandled`.
        """
        self._device_error_handled_callbacks.append(callback)

    async def start(self) -> None:
        """Start the SignalR connection in a background task.

        If the listener is already running, this is a no-op.
        """
        if self._run_task is not None and not self._run_task.done():
            return
        self._stop_requested = False
        self._fatal_error = None
        self._set_state(ConnectionState.CONNECTING)
        self._run_task = asyncio.create_task(self._run_loop(), name="signalr-listener")
        self._run_task.add_done_callback(self._run_task_done)

    async def stop(self) -> None:
        """Gracefully stop the SignalR connection.

        Cancels the background listener task and waits for it to finish.
        Safe to call multiple times or when already stopped.
        """
        self._stop_requested = True
        if self._run_task is None or self._run_task.done():
            if self._run_task is not None and not self._run_task.cancelled():
                with contextlib.suppress(Exception):
                    self._run_task.exception()
            self._run_task = None
            self._set_state(ConnectionState.DISCONNECTED)
            return
        self._set_state(ConnectionState.DISCONNECTING)
        self._run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._run_task
        self._run_task = None
        self._set_state(ConnectionState.DISCONNECTED)

    async def _run_loop(self) -> None:
        attempt = 0
        while not self._stop_requested:
            try:
                self._client = await self._build_client()
                if attempt > 0:
                    self._set_state(ConnectionState.CONNECTING)
                await self._client.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_requested:
                    return
                attempt += 1
                if self._max_reconnect_attempts == 0 or attempt > self._max_reconnect_attempts:
                    _logger.error("SignalR connection failed after %d attempts: %s", attempt, exc)
                    fatal_error = VenusConnectionError(f"SignalR connection failed after {attempt} attempts: {exc}")
                    self._fatal_error = fatal_error
                    self._set_state(ConnectionState.ERROR)
                    raise fatal_error from exc
                delay = self._reconnect_backoff * (2 ** (attempt - 1))
                _logger.warning(
                    "SignalR connection lost (attempt %d/%d), reconnecting in %.1fs: %s",
                    attempt,
                    self._max_reconnect_attempts,
                    delay,
                    exc,
                )
                self._set_state(ConnectionState.DISCONNECTED)
                await asyncio.sleep(delay)
            else:
                attempt = 0
                if not self._stop_requested:
                    self._set_state(ConnectionState.DISCONNECTED)

    def _set_state(self, new_state: ConnectionState) -> None:
        if new_state == self._state:
            return
        old_state = self._state
        _logger.debug("SignalR state: %s -> %s", old_state.name, new_state.name)
        self._state = new_state
        self._log_event("connection_state_changed", {
            "old_state": old_state.value, "new_state": new_state.value,
        })
        for cb in self._connection_state_callbacks:
            task: asyncio.Task[None] = asyncio.create_task(cast(Coroutine[Any, Any, None], cb(new_state)))
            self._background_tasks.add(task)
            task.add_done_callback(self._task_done)

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Record a SignalR event in the run log if enabled."""
        if self._run_log is None or not self._run_log_config.include_signalr:
            return
        event_filter = self._run_log_config.signalr_event_filter
        if event_filter and event_type not in event_filter:
            return
        self._run_log.record("SignalR", "In", event_type, payload)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            _logger.error("Error in connection-state callback", exc_info=task.exception())

    def _run_task_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _on_open(self) -> None:
        _logger.info("SignalR connection opened")
        self._set_state(ConnectionState.CONNECTED)

    async def _on_close(self) -> None:
        _logger.info("SignalR connection closed")
        if self._state != ConnectionState.DISCONNECTING:
            self._set_state(ConnectionState.DISCONNECTED)

    async def _on_error(self, message: CompletionMessage) -> None:
        _logger.error("SignalR error: %s", message.error)
        self._set_state(ConnectionState.ERROR)

    async def _on_runtime_status(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            if isinstance(payload, dict):
                event = RuntimeStatusEvent.model_validate(payload)
            else:
                event = RuntimeStatusEvent.model_validate({"executorEvent": payload, "message": ""})
            self._log_event("runtime_status", event.model_dump())
            for cb in self._runtime_status_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error processing RuntimeStatus event")

    async def _on_progress_changed(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            event = ProgressChangedEvent.model_validate(payload if isinstance(payload, dict) else {})
            self._log_event("progress", event.model_dump())
            for cb in self._progress_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error processing ProgressChanged event")

    async def _on_runtime_error(self, arguments: list[Any]) -> None:
        self._log_event("runtime_error", {"arguments": arguments})
        for cb in self._error_callbacks:
            try:
                await cb(arguments)
            except Exception:
                _logger.exception("Error in runtime-error callback")

    async def _on_runtime_trace(self, arguments: list[Any]) -> None:
        trace_text = str(arguments[0]) if arguments else ""
        self._log_event("runtime_trace", {"trace": trace_text})
        for cb in self._trace_callbacks:
            try:
                await cb(arguments)
            except Exception:
                _logger.exception("Error in runtime-trace callback")

    async def _on_load_method(self, arguments: list[Any]) -> None:
        _logger.debug("OnLoadMethod received: %s", arguments)

    async def _on_unload_method(self, arguments: list[Any]) -> None:
        _logger.debug("OnUnloadMethod received: %s", arguments)

    async def _on_device_created(self, arguments: list[Any]) -> None:
        _logger.debug("OnDeviceCreated received: %s", arguments)

    async def _on_instrument_changed(self, arguments: list[Any]) -> None:
        _logger.info("SignalR OnInstrumentChanged: %s", arguments)

    async def _on_run_message_queued(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            _logger.debug("OnRunMessageQueued raw payload: %r", payload)
            event = RunMessageQueuedEvent.model_validate(payload if isinstance(payload, dict) else {})
            _logger.debug(
                "OnRunMessageQueued parsed: channel=%r, message_id=%r, queue_depth=%r",
                event.channel,
                event.message_id,
                event.queue_depth,
            )
            self._log_event("run_message_queued", event.model_dump())
            for cb in self._run_message_queued_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error in run-message-queued callback")

    async def _on_labware_state_changed(self, arguments: list[Any]) -> None:
        _logger.debug("LabwareStateChanged event received (unhandled): %r", arguments)

    async def _on_labware_position_state_changed(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            _logger.debug("LabwarePositionStateChanged raw payload: %r", payload)
            event = LabwarePositionStateChangedEvent.model_validate(payload if isinstance(payload, dict) else {})
            self._log_event("labware_position_changed", event.model_dump())
            for cb in self._labware_position_state_changed_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error in labware-position-state-changed callback")

    async def _on_labware_loaded_state_changed(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            _logger.debug("LabwareLoadedStateChanged raw payload: %r", payload)
            event = LabwareLoadedStateChangedEvent.model_validate(payload if isinstance(payload, dict) else {})
            self._log_event("labware_loaded_changed", event.model_dump())
            for cb in self._labware_loaded_state_changed_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error in labware-loaded-state-changed callback")

    @staticmethod
    def _parse_instrument_error(payload: Any) -> ErrorData:
        """Parse an instrument error event, falling back to its identifying fields.

        VENUS waits for the error handler to answer every error, so an event that
        fails full validation must still reach the resolver: it is passed on with
        only uuid/device/code/message/title, which the resolver escalates (no
        recovery actions to choose from) instead of the error going unanswered.
        """
        data = payload if isinstance(payload, dict) else {}
        try:
            return ErrorData.model_validate(data)
        except ValidationError:
            _logger.exception(
                "InstrumentErrorEvent uuid=%r failed full validation; dispatching identifying fields only",
                data.get("uuid"),
            )
            reduced = {key: data.get(key) for key in ("uuid", "deviceId", "code", "message", "title")}
            return ErrorData.model_validate({key: value for key, value in reduced.items() if value is not None})

    async def _on_instrument_error_event(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            _logger.info("InstrumentErrorEvent raw payload: %r", payload)
            event = self._parse_instrument_error(payload)
            _logger.info(
                "InstrumentErrorEvent parsed: uuid=%r, device_id=%r, message=%r",
                event.uuid,
                event.device_id,
                event.message,
            )
            self._log_event("instrument_error", event.model_dump())
            for cb in self._instrument_error_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error in instrument-error-event callback")

    async def _on_instrument_error_notification(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else ""
            notification = str(payload)
            _logger.info("InstrumentErrorNotification: %s", notification)
            self._log_event("instrument_error_notification", {"message": notification})
            for cb in self._instrument_error_notification_callbacks:
                await cb(notification)
        except Exception:
            _logger.exception("Error in instrument-error-notification callback")

    async def _on_device_error_handled_response(self, arguments: list[Any]) -> None:
        try:
            payload = arguments[0] if arguments else {}
            _logger.info("DeviceErrorHandledResponse raw payload: %r", payload)
            event = InstrumentErrorHandled.model_validate(payload if isinstance(payload, dict) else {})
            _logger.info(
                "DeviceErrorHandledResponse parsed: uuid=%r, recovery_action=%r",
                event.uuid,
                event.recovery_action,
            )
            self._log_event("device_error_handled", event.model_dump())
            for cb in self._device_error_handled_callbacks:
                await cb(event)
        except Exception:
            _logger.exception("Error in device-error-handled-response callback")

