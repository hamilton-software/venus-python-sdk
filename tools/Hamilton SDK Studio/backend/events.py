"""Thread-safe fan-out of run/connection events to every open page (WebSocket)."""

from __future__ import annotations

import asyncio
from typing import Any


class Broadcaster:
    """Events are published from the runner's worker thread and consumed on the event loop."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers = [(loop, q) for loop, q in self._subscribers if q is not queue]

    def publish(self, event: dict[str, Any]) -> None:
        for loop, queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # that page's loop is gone
                self.unsubscribe(queue)
