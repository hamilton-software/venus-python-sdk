"""_BaseSyncClient — generic synchronous facade over an async instrument client."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from enum import StrEnum
from typing import Any, TypeVar

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_Self = TypeVar("_Self", bound="_BaseSyncClient")


class _LifecycleState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    SHUTDOWN_TIMEOUT = "shutdown_timeout"


class _BaseSyncClient(ABC):
    """Abstract base for synchronous facades over async Hamilton instrument clients.

    Manages a dedicated background :class:`asyncio.AbstractEventLoop` running on
    a daemon thread.  Concrete subclasses supply :meth:`_async_start` and
    :meth:`_async_stop` to perform instrument-specific setup/teardown.

    Parameters
    ----------
    thread_name:
        Name given to the background daemon thread (useful for debugging).
    shutdown_timeout:
        Maximum seconds to wait for the background thread to stop during
        :meth:`stop`.  Covers both the async teardown and the thread
        join.  Defaults to ``30.0``.
    """

    _DEFAULT_SHUTDOWN_TIMEOUT: float = 30.0
    # After scheduling loop.stop(), give the thread this many extra seconds to
    # exit run_forever() if the main shutdown budget is already exhausted.
    # loop.stop() fires in the very next poll iteration, so 2 s is ample.
    _LOOP_STOP_GRACE_S: float = 2.0

    def __init__(
        self,
        *,
        thread_name: str = "hamilton-venus-sync",
        shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self._thread_name = thread_name
        self._shutdown_timeout = shutdown_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._state = _LifecycleState.STOPPED

    # -- abstract hooks -------------------------------------------------------

    @abstractmethod
    async def _async_start(self) -> None:
        """Instrument-specific async start logic (called on the background loop)."""

    @abstractmethod
    async def _async_stop(self) -> None:
        """Instrument-specific async stop logic (called on the background loop).

        Should be idempotent — it may be called even if :meth:`_async_start`
        never completed successfully.
        """

    # -- internal helpers -----------------------------------------------------

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Submit *coro* to the background event loop and block until it completes."""
        if self._state is not _LifecycleState.STARTED or self._loop is None:
            raise RuntimeError("Client is not started. Call start() or use 'with' statement.")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _start_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start the background event loop and connect to the instrument."""
        if self._state is _LifecycleState.SHUTDOWN_TIMEOUT:
            raise RuntimeError(
                f"Cannot start: previous shutdown timed out — background thread '{self._thread_name}' "
                "may still be running. Create a new client instance."
            )
        if self._state is not _LifecycleState.STOPPED:
            raise RuntimeError("Client is already started")
        self._state = _LifecycleState.STARTING
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._start_loop,
            args=(self._loop,),
            daemon=True,
            name=self._thread_name,
        )
        self._thread.start()
        try:
            assert self._loop is not None
            asyncio.run_coroutine_threadsafe(self._async_start(), self._loop).result()
            self._state = _LifecycleState.STARTED
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Stop the client and shut down the background loop.

        Safe to call multiple times.  The *shutdown_timeout* passed to the
        constructor limits how long the async teardown and thread join may take.
        """
        if self._state in (_LifecycleState.STOPPED, _LifecycleState.STOPPING, _LifecycleState.SHUTDOWN_TIMEOUT):
            return

        self._state = _LifecycleState.STOPPING
        deadline = time.monotonic() + self._shutdown_timeout

        if self._loop is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_stop(),
                    self._loop,
                )
                remaining = max(0.0, deadline - time.monotonic())
                future.result(timeout=remaining)
            except Exception:
                _logger.debug("Error during stop", exc_info=True)

            self._cancel_remaining_tasks(self._loop)

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            remaining = max(0.0, deadline - time.monotonic())
            self._thread.join(timeout=remaining)
            if self._thread.is_alive():
                # The shutdown budget was exhausted before loop.stop() could be
                # processed.  Give a small extra window because the callback
                # fires in the very next poll iteration (near-instant).
                self._thread.join(timeout=self._LOOP_STOP_GRACE_S)
            if self._thread.is_alive():
                # Thread is still running — closing the loop now would race with
                # it.  Retain both references so the situation is detectable and
                # re-entry is blocked; the daemon thread will be reclaimed by the
                # OS when the process exits.
                _logger.warning(
                    "Background loop thread '%s' did not stop within the shutdown timeout; "
                    "skipping loop.close() to avoid a race condition.",
                    self._thread.name,
                )
                self._state = _LifecycleState.SHUTDOWN_TIMEOUT
                return
            self._thread = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

        self._state = _LifecycleState.STOPPED

    @staticmethod
    def _cancel_remaining_tasks(loop: asyncio.AbstractEventLoop) -> None:
        # Cancel and drain all pending tasks first. Async generators (e.g. the
        # websockets send_context generator) may still be executing inside those
        # tasks; calling shutdown_asyncgens() while they are running raises
        # "aclose(): asynchronous generator is already running". Only after all
        # tasks have exited is it safe to finalise any remaining async generators.
        pending = asyncio.all_tasks(loop)
        if pending:
            for task in pending:
                task.cancel()

            async def _drain() -> None:
                await asyncio.gather(*pending, return_exceptions=True)

            if loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(_drain(), loop).result(timeout=5.0)
                except concurrent.futures.TimeoutError:
                    pass
                except Exception:
                    _logger.debug("Error draining cancelled tasks", exc_info=True)
            else:
                try:
                    loop.run_until_complete(_drain())
                except Exception:
                    _logger.debug("Error draining cancelled tasks", exc_info=True)

        # Now that all tasks have exited, finalise any async generators that
        # were not closed by the tasks themselves.
        if loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(loop.shutdown_asyncgens(), loop).result(timeout=5.0)
            except concurrent.futures.TimeoutError:
                pass
            except Exception:
                _logger.debug("Error during shutdown_asyncgens", exc_info=True)
        else:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                _logger.debug("Error during shutdown_asyncgens", exc_info=True)

    def __enter__(self: _Self) -> _Self:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

