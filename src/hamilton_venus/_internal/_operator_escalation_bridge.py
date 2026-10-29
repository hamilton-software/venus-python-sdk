from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import cast

from hamilton_venus._internal._error_profile_resolver import (
    OperatorEscalationCallback,
    OperatorEscalationContext,
)
from hamilton_venus.models import ErrorRecovery, RecoveryAction

_logger = logging.getLogger(__name__)


class _EscalationDispatcher:
    def __init__(self) -> None:
        self._queue: deque[
            tuple[
                OperatorEscalationContext,
                asyncio.AbstractEventLoop,
                asyncio.Future[RecoveryAction | ErrorRecovery | None],
            ]
        ] = deque()
        self._event: threading.Event | None = None
        self._lock = threading.Lock()

    async def run(self, context: OperatorEscalationContext) -> RecoveryAction | ErrorRecovery | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RecoveryAction | ErrorRecovery | None] = loop.create_future()
        with self._lock:
            self._queue.append((context, loop, future))
            queue_size = len(self._queue)
            event = self._event
        _logger.info(
            "OperatorEscalationBridge.dispatch: queued uuid=%s queue_size=%d worker_attached=%s",
            context.error.uuid,
            queue_size,
            event is not None,
        )
        if event is not None:
            event.set()
        return await future

    def attach_event(self, event: threading.Event) -> None:
        with self._lock:
            self._event = event
            should_set = bool(self._queue)
        if should_set:
            event.set()

    def detach_event(self, event: threading.Event) -> None:
        with self._lock:
            if self._event is event:
                self._event = None

    def drain(
        self,
    ) -> list[
        tuple[
            OperatorEscalationContext,
            asyncio.AbstractEventLoop,
            asyncio.Future[RecoveryAction | ErrorRecovery | None],
        ]
    ]:
        pending: list[
            tuple[
                OperatorEscalationContext,
                asyncio.AbstractEventLoop,
                asyncio.Future[RecoveryAction | ErrorRecovery | None],
            ]
        ] = []
        with self._lock:
            while self._queue:
                pending.append(self._queue.popleft())
        return pending

    def fail_pending(self, exc: BaseException) -> None:
        pending = self.drain()
        for _, loop, future in pending:
            loop.call_soon_threadsafe(future.set_exception, exc)

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._queue)


class OperatorEscalationBridge:
    def __init__(
        self,
        callback: OperatorEscalationCallback | None,
        *,
        shutdown_timeout: float,
    ) -> None:
        self._callback = callback
        self._shutdown_timeout = shutdown_timeout
        self._dispatcher = _EscalationDispatcher()
        self._callback_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def resolver_callback(self) -> OperatorEscalationCallback | None:
        if self._callback is None:
            return None

        async def callback(context: OperatorEscalationContext) -> RecoveryAction | ErrorRecovery | None:
            return await self._dispatcher.run(context)

        return callback

    def start(self) -> None:
        if self._callback is None:
            _logger.info("OperatorEscalationBridge.start: no callback provided; bridge disabled")
            return
        if self._thread is not None:
            _logger.info("OperatorEscalationBridge.start: bridge already running")
            return
        self._callback_event.clear()
        self._stop_event.clear()
        self._dispatcher.attach_event(self._callback_event)
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="hamilton-venus-operator-escalation",
        )
        self._thread.start()
        _logger.info("OperatorEscalationBridge.start: worker thread started")

    def stop(self, reason: str) -> None:
        if self._thread is not None:
            self._stop_event.set()
            self._callback_event.set()
            self._thread.join(timeout=self._shutdown_timeout)
            self._thread = None
        self._dispatcher.detach_event(self._callback_event)
        self._dispatcher.fail_pending(RuntimeError(reason))

    def _drain(self) -> None:
        callback = self._callback
        if callback is None:
            _logger.info("OperatorEscalationBridge._drain: callback missing; skipping")
            return

        pending = self._dispatcher.drain()
        if not pending:
            return

        _logger.info("OperatorEscalationBridge._drain: processing %d pending escalation(s)", len(pending))
        for context, loop, future in pending:
            if future.done():
                continue
            _logger.debug(
                "OperatorEscalationBridge._drain: about to invoke callback for "
                "uuid=%s with top_level=%d per_channel=%d",
                context.error.uuid,
                len(context.top_level_actions),
                len(context.per_channel_actions),
            )
            try:
                selected_action = callback(context)
                if asyncio.iscoroutine(selected_action):
                    selected_action = asyncio.run(selected_action)
                resolved_action = cast(RecoveryAction | ErrorRecovery | None, selected_action)
                if isinstance(resolved_action, RecoveryAction):
                    action_for_log = resolved_action.value
                elif isinstance(resolved_action, ErrorRecovery):
                    action_for_log = "error_recovery"
                else:
                    action_for_log = None
                _logger.info(
                    "OperatorEscalationBridge._drain: callback returned action=%s for uuid=%s",
                    action_for_log,
                    context.error.uuid,
                )
            except Exception as exc:
                _logger.exception(
                    "OperatorEscalationBridge._drain: callback raised for uuid=%s",
                    context.error.uuid,
                )
                loop.call_soon_threadsafe(future.set_exception, exc)
                continue
            loop.call_soon_threadsafe(future.set_result, resolved_action)

    def _loop(self) -> None:
        while True:
            self._callback_event.wait()
            self._callback_event.clear()

            self._drain()

            if self._stop_event.is_set() and not self._dispatcher.has_pending:
                break
