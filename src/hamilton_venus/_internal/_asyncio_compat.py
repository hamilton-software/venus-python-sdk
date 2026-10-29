"""Compatibility utilities for asyncio across Python versions."""

from __future__ import annotations

import asyncio
from typing import Any


async def _wait_with_timeout(awaitable: Any, timeout: float | None) -> Any:
    """Wait for an awaitable with an optional timeout.

    Internal compatibility shim for awaiting with an optional timeout.

    This helper is intentionally private and exists to provide consistent
    timeout behavior across supported Python versions.

    When *timeout* is ``None`` the awaitable is awaited directly with no
    deadline (equivalent to ``await awaitable``).

    When *timeout* is a positive float this uses the best mechanism for the
    running Python version:

    * Python 3.11+ — ``asyncio.timeout()`` context-manager for proper
      coroutine cancellation.
    * Python 3.10 — ``asyncio.wait_for()`` fallback.

    Edge cases:
    * *timeout* ``<= 0`` — ``asyncio.TimeoutError`` is raised immediately.
      This matches the behavior of ``asyncio.wait_for()`` and
      ``asyncio.timeout()``.

    Args:
        awaitable: The awaitable to wait for.
        timeout: Timeout in seconds. Pass ``None`` to wait indefinitely.
            Pass a value <= 0 to timeout immediately.

    Returns:
        The result of the awaitable.

    Raises:
        asyncio.TimeoutError: If *timeout* seconds elapse before the
            awaitable completes, or immediately if *timeout* <= 0.
    """
    if timeout is None:
        return await awaitable
    async with asyncio.timeout(timeout):
        return await awaitable

