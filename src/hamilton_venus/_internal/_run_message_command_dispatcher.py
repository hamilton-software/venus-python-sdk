"""Internal run-message command dispatcher for the VENUS WebAPI."""

from __future__ import annotations

import asyncio
import json as json_module
import logging
import math
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import httpx
from pydantic import ValidationError

from hamilton_venus._internal._run_log import RunLog
from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import (
    MethodError,
    VenusApiContractError,
    VenusCommandAbortedError,
    VenusCommandFailedError,
    VenusTimeoutError,
)
from hamilton_venus.models import (
    CommandCommunicationMessage,
    CommandRequest,
    CommandResponse,
    ExecutorEvent,
    RunMessageQueuedEvent,
)

_RUN_MESSAGES_PREFIX = "/api/vector/v3/run-messages"
_ACTION_CHANNEL = "action"
_ACTION_RESPONSE_CHANNEL = "action-response"
_IDLE_CHANNEL = "idle"
_CONNECTED_CHANNEL = "connected"
_COMMUNICATION_CHANNEL = "communication"

_KNOWN_RUN_MESSAGE_CHANNELS = {
    _ACTION_CHANNEL,
    _ACTION_RESPONSE_CHANNEL,
    _IDLE_CHANNEL,
    _CONNECTED_CHANNEL,
    _COMMUNICATION_CHANNEL,
}

_MAX_CHANNEL_QUEUE_EVENTS = 512
# Status channels hold only the latest event; their queues never need more than one
# slot.  Using maxlen=1 prevents the overflow warning that fires when the instrument
# continuously emits idle/connected SignalR notifications that are never consumed by
# _wait_for_run_message_channel (status_is_idle uses peek_channel via HTTP instead).
#
# The action channel is where this client posts its own commands: VENUS notifies
# every post, but nothing waits for those notifications (responses come on
# action-response). Keeping only the latest one stops a long session (more than
# 512 commands, e.g. many tilt_labware / split_wells re-aims) logging an overflow
# warning on every command.
_STATUS_CHANNELS = {_IDLE_CHANNEL, _CONNECTED_CHANNEL, _ACTION_CHANNEL}
_MAX_STATUS_CHANNEL_QUEUE_EVENTS = 1
_COMMUNICATION_POLL_FALLBACK_TIMEOUT = 30.0
_MAX_COMMUNICATION_DRAIN_ITERATIONS = 1000

# Limit the cache of out-of-order command responses to avoid unbounded memory growth.
_MAX_PENDING_RESPONSES = 100

_logger = logging.getLogger(__name__)

_RequestCallable = Callable[..., Awaitable[httpx.Response]]


class _RunMessageCommandDispatcher:
    """Internal helper for command dispatch over VENUS run-message channels."""

    _SUSPENSION_FALLBACK_TIMEOUT: float = 600.0

    def __init__(self, request: _RequestCallable) -> None:
        self._request = request
        self._run_log: RunLog | None = None
        self._run_log_config: RunLogConfig | None = None
        self._channel_queues: dict[str, deque[RunMessageQueuedEvent]] = {}
        self._channel_conditions: dict[str, asyncio.Condition] = {}
        self._pending_responses: dict[str, CommandResponse] = {}
        self._command_deadline: float = math.inf
        self._suspension_counter: int = 0
        # Set by resume()/_auto_resume() to wake an in-flight, unbounded (timeout=None)
        # response wait as soon as the deadline becomes finite again -- otherwise a wait
        # already blocked with timeout=None never re-checks _command_deadline on its own.
        self._deadline_changed: asyncio.Event = asyncio.Event()
        self._saved_remaining: float | None = None
        self._suspension_timer_handle: asyncio.TimerHandle | None = None
        self._last_operation_context: str | None = None
        self._command_active: bool = False
        # Set by hold_for_operator(): an error was handed to the operator (VENUS
        # dialog), so the in-flight command's deadline stays suspended until the
        # command itself finishes -- see hold_for_operator / _release_operator_hold.
        self._operator_hold: bool = False
        self._worker_stop_event: asyncio.Event | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._abort_event: asyncio.Event = asyncio.Event()
        self._abort_runtime_status: str = ""
        self._method_paused: bool = False
        self._command_guard: Callable[[str, str], None] | None = None
        self._before_command: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None

    def _reset_abort_state(self) -> None:
        """Reset runtime-abort state for a new method session."""
        self._abort_event = asyncio.Event()
        self._abort_runtime_status = ""
        self._method_paused = False

    def set_command_guard(self, guard: Callable[[str, str], None] | None) -> None:
        """Install a ``guard(category, action_name)`` run before every command is sent.

        The guard vetoes a command by raising; nothing is sent in that case.
        """
        self._command_guard = guard

    def set_before_command(self, hook: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) -> None:
        """Install an async ``hook(category, action_name, parameters)`` awaited before
        every command is sent (after the guard) -- e.g. to push a liquid class the
        command uses. The hook may itself send commands; if it raises, nothing is sent.
        """
        self._before_command = hook

    def set_run_log(self, run_log: RunLog | None) -> None:
        self._run_log = run_log

    def set_run_log_config(self, run_log_config: RunLogConfig | None) -> None:
        self._run_log_config = run_log_config

    def suspend(self) -> None:
        """Suspend deadline tracking (counter-based; safe for dual-arm calls)."""
        self._suspension_counter += 1
        if self._suspension_counter == 1:
            loop = asyncio.get_running_loop()
            self._loop = loop
            if self._command_deadline != math.inf:
                self._saved_remaining = max(0.0, self._command_deadline - loop.time())
            else:
                self._saved_remaining = None
            self._command_deadline = math.inf
            if self._suspension_timer_handle is not None:
                self._suspension_timer_handle.cancel()
            self._suspension_timer_handle = loop.call_later(
                self._SUSPENSION_FALLBACK_TIMEOUT, self._auto_resume
            )
            _logger.debug("suspend: deadline suspended (counter=1), fallback timer set")
            # Wake the in-flight response wait: it is sleeping on a timeout computed
            # from the old deadline and would otherwise still expire on schedule.
            self._deadline_changed.set()

    def resume(self) -> None:
        """Resume deadline tracking; restores deadline when counter reaches zero."""
        if self._suspension_counter <= 0:
            _logger.warning("resume: called with counter already at %d, ignoring", self._suspension_counter)
            return
        self._suspension_counter -= 1
        if self._suspension_counter == 0 and self._operator_hold:
            _logger.debug("resume: operator hold active; deadline stays suspended until the command finishes")
            return
        if self._suspension_counter == 0:
            if self._suspension_timer_handle is not None:
                self._suspension_timer_handle.cancel()
                self._suspension_timer_handle = None
            loop = asyncio.get_running_loop()
            if self._saved_remaining is not None:
                self._command_deadline = loop.time() + self._saved_remaining
            else:
                self._command_deadline = math.inf
            self._saved_remaining = None
            _logger.debug("resume: deadline restored to %.3f", self._command_deadline)
            self._deadline_changed.set()

    def hold_for_operator(self) -> None:
        """Keep the in-flight command's deadline suspended until the command finishes.

        Called once an error has been handed to the operator (VENUS's own error
        dialog). VENUS reports such an error "handled" as soon as it accepts the
        handoff, long before anyone answers the dialog, so the usual resume would
        restart the clock while the dialog is still open. The hold ignores those
        resumes and the suspension fallback timer -- an operator may take as long
        as they need -- and is released when the command completes, fails, times
        out or is aborted (a method abort still ends the wait immediately).
        """
        self._operator_hold = True
        if self._suspension_timer_handle is not None:
            self._suspension_timer_handle.cancel()
            self._suspension_timer_handle = None
        self._command_deadline = math.inf
        self._deadline_changed.set()
        _logger.debug("hold_for_operator: deadline suspended until the in-flight command finishes")

    def pause_suspension_fallback(self) -> None:
        """Drop the suspension fallback timer while an operator decides.

        Called while an operator escalation callback (e.g. the Script Manager's
        recovery dialog) is waiting for an answer: the deadline is already
        suspended, and an operator may take longer than the 600 s fallback. The
        normal ``resume()`` once the answer is submitted restores the command's
        remaining time as usual.
        """
        if self._suspension_timer_handle is not None:
            self._suspension_timer_handle.cancel()
            self._suspension_timer_handle = None
            _logger.debug("pause_suspension_fallback: fallback timer cancelled while the operator decides")

    def _release_operator_hold(self) -> None:
        """End an operator hold when its command finishes (see hold_for_operator)."""
        if not self._operator_hold:
            return
        self._operator_hold = False
        self._suspension_counter = 0
        self._saved_remaining = None
        if self._suspension_timer_handle is not None:
            self._suspension_timer_handle.cancel()
            self._suspension_timer_handle = None
        self._command_deadline = math.inf
        _logger.debug("_release_operator_hold: command finished; operator hold released")

    @property
    def command_active(self) -> bool:
        """Whether a command sent through this dispatcher is still awaiting its response."""
        return self._command_active

    def get_operation_context(self) -> str | None:
        """Return the operation context string for the most recent command."""
        return self._last_operation_context

    def _auto_resume(self) -> None:
        """Fallback: force-resume after suspension timeout to avoid permanent deadlock."""
        _logger.warning(
            "_auto_resume: suspension fallback fired after %.0fs, forcing resume",
            self._SUSPENSION_FALLBACK_TIMEOUT,
        )
        self._suspension_counter = 0
        self._suspension_timer_handle = None
        assert self._loop is not None
        if self._saved_remaining is not None:
            self._command_deadline = self._loop.time() + self._saved_remaining
        else:
            self._command_deadline = math.inf
        self._saved_remaining = None
        self._method_paused = False
        self._deadline_changed.set()

    def _ensure_channel_state(self, channel: str) -> tuple[deque[RunMessageQueuedEvent], asyncio.Condition]:
        queue = self._channel_queues.get(channel)
        condition = self._channel_conditions.get(channel)
        if queue is None or condition is None:
            maxlen = _MAX_STATUS_CHANNEL_QUEUE_EVENTS if channel in _STATUS_CHANNELS else _MAX_CHANNEL_QUEUE_EVENTS
            queue = deque(maxlen=maxlen)
            condition = asyncio.Condition()
            self._channel_queues[channel] = queue
            self._channel_conditions[channel] = condition
        return queue, condition

    async def notify_run_message_queued(self, event: RunMessageQueuedEvent) -> None:
        """Queue a run-message notification received from the SignalR listener."""
        if event.channel not in _KNOWN_RUN_MESSAGE_CHANNELS:
            _logger.debug("Ignoring run-message event for unknown channel=%r", event.channel)
            return
        queue, condition = self._ensure_channel_state(event.channel)
        async with condition:
            if event.channel not in _STATUS_CHANNELS:
                maxlen = queue.maxlen or _MAX_CHANNEL_QUEUE_EVENTS
                if len(queue) == maxlen:
                    _logger.warning(
                        "Channel queue overflow on %r (%d); dropping oldest event for channel=%r",
                        event.channel,
                        maxlen,
                        queue[0].channel,
                    )
            queue.append(event)
            condition.notify(1)

    async def _wait_for_run_message_channel(
        self,
        channel: str,
        timeout: float | None,
        wake_event: asyncio.Event | None = None,
    ) -> None:
        """Wait for a run-message queued event on a specific channel.

        ``wake_event``, if provided, lets a concurrent ``resume()``/``_auto_resume()``
        interrupt an in-flight ``timeout=None`` wait early so the caller can re-check
        ``_command_deadline`` -- otherwise an unbounded wait never notices the deadline
        becoming finite again until a real message arrives.
        """
        queue, condition = self._ensure_channel_state(channel)

        async def _wait_for_item() -> None:
            async with condition:
                while not queue:
                    await condition.wait()
                queue.popleft()

        if timeout is not None and timeout <= 0:
            raise TimeoutError()

        wait_task = asyncio.create_task(_wait_for_item())
        abort_task = asyncio.create_task(self._abort_event.wait())
        timeout_task: asyncio.Task[None] | None = None
        wake_task: asyncio.Task[bool] | None = None
        try:
            tasks: set[asyncio.Task[Any]] = {wait_task, abort_task}
            if timeout is not None:
                timeout_task = asyncio.create_task(asyncio.sleep(timeout))
                tasks.add(timeout_task)
            if wake_event is not None:
                wake_task = asyncio.create_task(wake_event.wait())
                tasks.add(wake_task)

            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if wait_task in done:
                await wait_task
                return

            if abort_task in done:
                raise VenusCommandAbortedError(
                    "Command wait interrupted because method abort event was received"
                )

            if wake_task is not None and wake_task in done:
                wake_event.clear()  # type: ignore[union-attr]
                return

            raise TimeoutError()
        finally:
            for task in (wait_task, abort_task, timeout_task, wake_task):
                if task is not None and not task.done():
                    task.cancel()
            with suppress(asyncio.CancelledError):
                await wait_task
            with suppress(asyncio.CancelledError):
                await abort_task
            if timeout_task is not None:
                with suppress(asyncio.CancelledError):
                    await timeout_task
            if wake_task is not None:
                with suppress(asyncio.CancelledError):
                    await wake_task

    def _notify_runtime_status(self, event: ExecutorEvent, message: str = "") -> None:
        """Track runtime-status events that should abort in-flight command waits."""
        if event in (ExecutorEvent.ABORTING, ExecutorEvent.ABORTED, ExecutorEvent.TERMINATED):
            self._abort_runtime_status = f"ExecutorEvent.{event.name}"
            if message:
                self._abort_runtime_status = f"{self._abort_runtime_status}: {message}"
            self._abort_event.set()
        elif event == ExecutorEvent.PAUSED and not self._method_paused:
            self._method_paused = True
            self.suspend()
        elif event == ExecutorEvent.RUNNING and self._method_paused:
            self._method_paused = False
            self.resume()

    def _parse_queue_message_data(self, raw_data: Any, context: str) -> dict[str, Any]:
        """Parse and validate JSON data from a queue message, raising ValueError on failure."""
        if raw_data is None:
            raise ValueError(f"{context}: data field is None")
        if not isinstance(raw_data, dict):
            raise ValueError(f"{context}: data field is not a dict")
        if not raw_data:
            raise ValueError(f"{context}: data dict is empty")
        return raw_data

    @staticmethod
    def _normalize_command_response(response: CommandResponse) -> CommandResponse:
        if not response.return_status and response.status in {"Success", "Error"}:
            response.return_status = response.status
        return response

    async def _push_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any],
    ) -> str:
        """Push a command to the action channel.

        Returns the response correlation ID.

        VENUS action-response payloads correlate to the server-generated queue
        ``messageId`` returned by the push response. If that identifier is not
        returned, the dispatcher falls back to the client-generated command
        envelope ID for compatibility.
        """
        self._last_operation_context = f"{category}/{action_name}"
        request = CommandRequest(
            category=category,
            action_name=action_name,
            parameters=parameters,
        )

        post_payload = {
            "channel": _ACTION_CHANNEL,
            "data": request.model_dump(by_alias=True),
        }
        _logger.debug("_push_command: POST payload for action=%r: %r", action_name, post_payload)

        post_response = await self._request(
            "POST",
            _RUN_MESSAGES_PREFIX,
            json=post_payload,
            error_prefix=f"Command({action_name}) - push",
        )
        try:
            post_data = post_response.json()
            if not isinstance(post_data, dict):
                raise ValueError(f"Command({action_name}) push: expected dict, got {type(post_data).__name__}")
        except (json_module.JSONDecodeError, ValueError) as exc:
            raise VenusApiContractError(f"Command {action_name!r} received an invalid push response: {exc}") from exc
        queue_message_id = str(post_data.get("messageId") or "").strip()
        response_correlation_id = queue_message_id or request.id
        _logger.debug(
            "_push_command: queued action=%r, command_id=%r, queue_message_id=%r, response_correlation_id=%r",
            action_name,
            request.id,
            queue_message_id,
            response_correlation_id,
        )
        return response_correlation_id

    async def _wait_for_response(
        self,
        action_name: str,
        message_id: str,
    ) -> CommandResponse | None:
        """Wait for a matching response using SignalR notifications, caching out-of-order responses."""
        if message_id in self._pending_responses:
            _logger.debug(
                "_wait_for_response: found cached response for action=%r, message_id=%r",
                action_name,
                message_id,
            )
            return self._pending_responses.pop(message_id)

        response_channel_url = f"{_RUN_MESSAGES_PREFIX}/{_ACTION_RESPONSE_CHANNEL}"

        while True:
            remaining = self._command_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                _logger.debug(
                    "_wait_for_response: deadline reached for action=%r, attempting final pop",
                    action_name,
                )
                response, _ = await self._pop_and_process_message(
                    action_name,
                    message_id,
                    response_channel_url,
                )
                return response

            deadline_at_wait = self._command_deadline
            try:
                await self._wait_for_run_message_channel(
                    _ACTION_RESPONSE_CHANNEL,
                    None if remaining == math.inf else remaining,
                    wake_event=self._deadline_changed,
                )
            except TimeoutError:
                _logger.debug(
                    "_wait_for_response: SignalR timeout for action=%r, attempting final pop",
                    action_name,
                )
                response, _ = await self._pop_and_process_message(
                    action_name,
                    message_id,
                    response_channel_url,
                )
                if response is None and self._command_deadline != deadline_at_wait:
                    # The deadline moved while this wait was sleeping (an error
                    # suspended it) -- keep waiting rather than timing out.
                    continue
                return response

            while True:
                response, was_out_of_order = await self._pop_and_process_message(
                    action_name,
                    message_id,
                    response_channel_url,
                )
                if response is not None:
                    return response
                if not was_out_of_order or asyncio.get_running_loop().time() >= self._command_deadline:
                    break

    async def _pop_and_process_message(
        self,
        action_name: str,
        message_id: str,
        response_channel_url: str,
    ) -> tuple[CommandResponse | None, bool]:
        """Pop the next response from the queue, handling out-of-order messages.

        Pops directly rather than peeking first: the pop returns the message
        itself (or ``hasMessage: false`` on an empty queue), and a response that
        belongs to another command is cached by id below, so peeking first only
        cost an extra round trip on every command.
        """
        pop_response = await self._request(
            "POST",
            f"{response_channel_url}/pop",
            error_prefix=f"Command({action_name}) - popping response",
        )

        try:
            pop_data = pop_response.json()
            if not isinstance(pop_data, dict):
                raise ValueError(f"Command({action_name}) pop: expected dict, got {type(pop_data).__name__}")
        except (json_module.JSONDecodeError, ValueError) as exc:
            raise VenusApiContractError(f"Command {action_name!r} received an invalid response: {exc}") from exc

        _logger.debug(
            "_pop_and_process_message: pop response for action=%r: %r",
            action_name,
            pop_data,
        )

        if not pop_data.get("hasMessage"):
            _logger.debug("_pop_and_process_message: no message in queue for action=%r", action_name)
            return None, False

        try:
            response_json = self._parse_queue_message_data(
                pop_data.get("data"),
                f"Command({action_name}) pop",
            )
            cmd_response = self._normalize_command_response(CommandResponse.model_validate(response_json))
            _logger.debug(
                "_pop_and_process_message: CommandResponse for action=%r: id=%r, return_status=%r, return_code=%r",
                action_name,
                cmd_response.id,
                cmd_response.return_status,
                cmd_response.return_code,
            )
        except (json_module.JSONDecodeError, ValidationError, ValueError) as exc:
            _logger.debug(
                "Invalid command response in queue while waiting for %s, raising exception: %s",
                action_name,
                exc,
            )
            raise VenusApiContractError(f"Command {action_name!r} received an invalid response: {exc}") from exc

        if cmd_response.id != message_id:
            _logger.debug(
                "Response id %r does not match expected messageId %r, caching for other callers",
                cmd_response.id,
                message_id,
            )
            if len(self._pending_responses) >= _MAX_PENDING_RESPONSES:
                oldest_key = next(iter(self._pending_responses))
                _logger.warning(
                    "Pending responses cache full (%d), discarding oldest entry %r",
                    _MAX_PENDING_RESPONSES,
                    oldest_key,
                )
                del self._pending_responses[oldest_key]
            self._pending_responses[cmd_response.id] = cmd_response
            return None, True

        return cmd_response, False

    async def peek_channel(self, channel: str) -> dict[str, Any] | None:
        """Peek a persistent status channel and return its data dict, or *None* if empty.

        Status channels like ``connected`` and ``idle`` are never popped; they
        hold the latest instrument state and should only be read via peek.
        """
        message = await self.peek_channel_message(channel)
        return None if message is None else message[1]

    async def peek_channel_message(self, channel: str) -> tuple[str, dict[str, Any]] | None:
        """Like :meth:`peek_channel`, but also return the message's ``messageId``.

        Returns ``(message_id, data)`` (``message_id`` is ``""`` if the server sent
        none), or *None* if the channel is empty. The id tells two messages with the
        same content apart, e.g. a ``ready`` left by an earlier run from the new one.
        """
        url = f"{_RUN_MESSAGES_PREFIX}/{channel}/peek"
        response = await self._request(
            "GET",
            url,
            error_prefix=f"PeekChannel({channel})",
        )
        try:
            body = response.json()
        except Exception:
            return None
        if not isinstance(body, dict) or not body.get("hasMessage"):
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        return str(body.get("messageId") or ""), data

    async def delete_channel(self, channel: str) -> None:
        """Delete every message queued on *channel* (``DELETE /run-messages/{channel}``).

        The executor method does the same for its channels when it starts
        (``API_Helper::InitializeStatusChannels``).
        """
        await self._request(
            "DELETE",
            f"{_RUN_MESSAGES_PREFIX}/{channel}",
            error_prefix=f"DeleteChannel({channel})",
        )

    async def send_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any] | None = None,
        timeout: float | None = None,
        *,
        default_timeout: float | None,
    ) -> CommandResponse:
        """Build a command envelope, send it, and return the parsed response."""
        if self._command_guard is not None:
            self._command_guard(category, action_name)
        if self._before_command is not None:
            await self._before_command(category, action_name, parameters or {})
        self._command_active = True
        try:
            try:
                message_id = await self._push_command(category, action_name, parameters or {})
                if self._run_log is not None:
                    self._run_log.record(
                        "WebAPI",
                        "Out",
                        "command_request",
                        {
                            "command_id": message_id,
                            "category": category,
                            "action_name": action_name,
                            "parameters": parameters or {},
                        },
                    )
                command_timeout = timeout if timeout is not None else default_timeout
                self._command_deadline = (
                    asyncio.get_running_loop().time() + command_timeout
                    if command_timeout is not None
                    else math.inf
                )
                cmd_response = await self._wait_for_response(action_name, message_id)
            except MethodError as exc:
                raise VenusApiContractError(
                    f"Command {action_name!r} failed while communicating with the run-message API: {exc}"
                ) from exc
            except VenusCommandAbortedError as exc:
                detail = self._abort_runtime_status
                if detail:
                    raise VenusCommandAbortedError(
                        f"Command {action_name!r} was interrupted by method abort event ({detail})"
                    ) from exc
                raise VenusCommandAbortedError(
                    f"Command {action_name!r} was interrupted by method abort event"
                ) from exc

            if cmd_response is None:
                command_timeout = timeout if timeout is not None else default_timeout
                raise VenusTimeoutError(f"Command {action_name!r} did not receive a response within {command_timeout}s")

            if self._run_log is not None:
                self._run_log.record("WebAPI", "In", "command_response", cmd_response.model_dump(by_alias=True))

            _logger.debug(
                "send_command: command %r completed, return_status=%r, return_code=%r",
                action_name,
                cmd_response.return_status,
                cmd_response.return_code,
            )
            if not cmd_response.success:
                raise VenusCommandFailedError(cmd_response)
            return cmd_response
        finally:
            self._command_active = False
            self._release_operator_hold()

    async def send_signal_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any] | None = None,
        timeout: float | None = None,
        *,
        default_timeout: float | None,
        signal_channel: str,
    ) -> CommandResponse:
        """Push a command and wait for a signal on a non-standard channel.

        Some commands (e.g. ``instrument.init``) do not produce an
        ``action-response`` queue message.  Instead, the executor posts a
        notification to a different channel (such as ``idle``) to indicate
        completion.  This method pushes the command, waits for the SignalR
        ``OnRunMessageQueued`` event on *signal_channel*, and returns a
        synthetic :class:`CommandResponse`.
        """
        self._command_active = True
        try:
            try:
                command_timeout = timeout if timeout is not None else default_timeout
                message_id = await self._push_command(category, action_name, parameters or {})
                if self._run_log is not None:
                    self._run_log.record(
                        "WebAPI",
                        "Out",
                        "command_request",
                        {
                            "command_id": message_id,
                            "category": category,
                            "action_name": action_name,
                            "parameters": parameters or {},
                            "signal_channel": signal_channel,
                        },
                    )
                await self._wait_for_run_message_channel(signal_channel, command_timeout)
            except TimeoutError:
                raise VenusTimeoutError(
                    f"Command {action_name!r} did not receive a signal on channel "
                    f"{signal_channel!r} within {command_timeout}s"
                ) from None
            except VenusCommandAbortedError as exc:
                detail = self._abort_runtime_status
                if detail:
                    raise VenusCommandAbortedError(
                        f"Command {action_name!r} was interrupted by method abort event ({detail})"
                    ) from exc
                raise VenusCommandAbortedError(
                    f"Command {action_name!r} was interrupted by method abort event"
                ) from exc
            except MethodError as exc:
                raise VenusApiContractError(
                    f"Command {action_name!r} failed while communicating with the run-message API: {exc}"
                ) from exc

            _logger.debug(
                "send_signal_command: command %r signalled on channel=%r",
                action_name,
                signal_channel,
            )
            cmd_response = CommandResponse(
                id=message_id,
                category=category,
                action_name=action_name,
                parameters=parameters or {},
                status="completed",
                return_status="Success",
                return_code=0,
            )
            if self._run_log is not None:
                self._run_log.record("WebAPI", "In", "command_response", cmd_response.model_dump(by_alias=True))
            return cmd_response
        finally:
            self._command_active = False
            self._release_operator_hold()

    async def _drain_communication_channel(self) -> None:
        """Drain all pending messages from the communication channel.

        Pops messages from the communication queue until a pop comes back empty
        (``hasMessage: false``). Handles parsing validation and run-log recording
        of each communication message.

        Pop-only, no peek first: the pop itself returns the message or reports
        the queue empty, so peeking only doubled the requests sent to the Web
        API while VENUS is busy running the command. Draining continues even
        when nothing is recorded, since VENUS otherwise trims this queue itself
        as it grows, which costs it time on every command.

        Raises
        ------
        VenusApiContractError
            If the server returns an invalid pop response (JSON decoding or
            validation error).

        Notes
        -----
        - Uses a safety limit (_MAX_COMMUNICATION_DRAIN_ITERATIONS) to prevent
          indefinite loops if the server returns messages faster than they can
          be consumed.
        - Logs each message at DEBUG level for trace-level operational visibility.
        - Records messages to run log when enabled via include_cmd_comms config.
        - Captures the active operation context to correlate messages with
          ongoing commands.
        """
        channel_url = f"{_RUN_MESSAGES_PREFIX}/{_COMMUNICATION_CHANNEL}"
        iterations = 0
        while iterations < _MAX_COMMUNICATION_DRAIN_ITERATIONS:
            iterations += 1
            pop_response = await self._request(
                "POST",
                f"{channel_url}/pop",
                error_prefix="Communication - popping message",
            )
            try:
                popped_payload = pop_response.json()
                popped_message = CommandCommunicationMessage.model_validate(popped_payload)
            except (json_module.JSONDecodeError, ValidationError, ValueError) as exc:
                raise VenusApiContractError(f"Communication worker received an invalid pop response: {exc}") from exc
            if not popped_message.has_message:
                return
            _logger.debug(
                "Communication message: category=%s command=%s status=%s id=%s",
                popped_message.data.category,
                popped_message.data.command,
                popped_message.data.status,
                popped_message.data.id,
            )
            if (
                self._run_log is not None
                and self._run_log_config is not None
                and self._run_log_config.include_cmd_comms
            ):
                payload = popped_message.model_dump(by_alias=True)
                payload["active_operation_context"] = self._last_operation_context if self._command_active else None
                self._run_log.record("WebAPI", "In", "command_communication", payload)
        _logger.warning(
            "_drain_communication_channel: reached iteration limit (%d); channel may have more messages",
            _MAX_COMMUNICATION_DRAIN_ITERATIONS,
        )

    async def _run_communication_worker(self) -> None:
        """Background task that monitors and drains the communication channel.

        This method runs as a long-lived background task that:
        1. Performs an initial drain of all pending communication messages on startup.
        2. Waits for SignalR signals from the VENUS server indicating new messages on the
           communication channel.
        3. Drains all pending messages from the communication channel when signaled.
        4. Continues until the stop event is set.

        The method handles exceptions gracefully (except for asyncio.CancelledError, which
        is re-raised). If the initial drain, wait, or subsequent drain operations fail,
        the errors are logged but do not terminate the task. The task will retry these
        operations in the next loop iteration.

        Raises:
            asyncio.CancelledError: Re-raised to allow clean cancellation when
                stop_communication_worker is called.
        """
        if self._worker_stop_event is None:
            return
        try:
            try:
                await self._drain_communication_channel()
            except Exception:
                _logger.exception("Communication worker initial drain failed")
            while not self._worker_stop_event.is_set():
                try:
                    await self._wait_for_run_message_channel(
                        _COMMUNICATION_CHANNEL,
                        _COMMUNICATION_POLL_FALLBACK_TIMEOUT,
                    )
                except TimeoutError:
                    pass
                except VenusCommandAbortedError:
                    _logger.debug("Communication worker stopping due to method abort event")
                    break
                except Exception:
                    _logger.exception("Communication worker wait failed")
                try:
                    await self._drain_communication_channel()
                except Exception:
                    _logger.exception("Communication worker drain failed")
        except asyncio.CancelledError:
            raise

    async def start_communication_worker(self) -> None:
        """Start the background communication worker task idempotently.

        This method initializes and starts a background task (_run_communication_worker)
        that monitors and drains the communication channel. The method is idempotent —
        if the worker task is already running, it returns without creating a new task.

        The method:
        1. Creates the stop event used to signal task shutdown.
        2. Creates and schedules the background task.
        3. Returns immediately; the task runs independently in the background.

        Concurrency Requirements:
            This method is NOT thread-safe and should only be called from the async
            event loop context in which the task runs. Concurrent calls from different
            threads or without proper synchronization may result in race conditions.
            Callers must ensure that start_communication_worker and
            stop_communication_worker are called in a serialized, coordinated manner
            (typically from a single initialization/shutdown flow).

        Note:
            If called while a task is already running, this method returns immediately
            without creating a duplicate task, making it safe to call multiple times
            from the same async context.
        """
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._reset_abort_state()
        self._worker_stop_event = asyncio.Event()
        self._worker_task = asyncio.create_task(self._run_communication_worker())

    async def stop_communication_worker(self) -> None:
        """Stop the background communication worker task and clean up resources.

        This method performs a clean shutdown of the communication worker task by:
        1. Setting the stop event to signal the worker task to exit its main loop.
        2. Capturing a reference to the current task.
        3. Clearing the internal task and stop event references.
        4. Cancelling the captured task.
        5. Awaiting the task while suppressing the expected asyncio.CancelledError.

        This ensures that the worker task is fully stopped and cleaned up before
        returning. The method is safe to call even if no worker task is running.

        Note:
            This method awaits the cancellation, so it may block until the task
            finishes processing its cancellation request. Callers should be prepared
            for a brief async wait.
        """
        if self._worker_stop_event is not None:
            self._worker_stop_event.set()
        task = self._worker_task
        self._worker_task = None
        self._worker_stop_event = None
        if task is None:
            self._reset_abort_state()
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._reset_abort_state()
