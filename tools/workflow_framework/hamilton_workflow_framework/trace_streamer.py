"""Live trace/log streaming for a workflow app's console pane.

Two independent mechanisms feed one asyncio.Queue of `log` messages:

1. A logging.Handler attached directly to the "hamilton_venus" / "hamilton_venus.traces"
   loggers -- a clean, public extension point the SDK already uses internally for its
   own `logging_level`/`venus_trace_logging` StarClient options.
2. A tailer on the structured run-log's NDJSON (.jsonl) file. The SDK's RunLog has no
   in-process callback/observer hook, so the pragmatic and robust choice is tailing the
   file it streams to (each line is flushed immediately on write).
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_SOURCE_MAP = {
    "HTTP": "http",
    "SignalR": "signalr",
    "Console": "console",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _QueueLogHandler(logging.Handler):
    def __init__(self, queue: asyncio.Queue[dict], loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._queue = queue
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        source = "trace" if record.name.endswith(".traces") else "sdk_log"
        message = {
            "type": "log",
            "source": source,
            "level": record.levelname,
            "text": self.format(record) if self.formatter else record.getMessage(),
            "timestamp": _now_iso(),
        }
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, message)
        except RuntimeError:
            pass  # loop already closed (session tearing down)


class TraceStreamer:
    def __init__(self, queue: asyncio.Queue[dict]) -> None:
        self._queue = queue
        self._handler: _QueueLogHandler | None = None
        self._tail_task: asyncio.Task | None = None
        self._stop_tail = asyncio.Event()

    # -- logging.Handler half --------------------------------------------------

    def attach_logging(self) -> None:
        loop = asyncio.get_running_loop()
        handler = _QueueLogHandler(self._queue, loop)
        handler.setLevel(logging.DEBUG)
        for logger_name in ("hamilton_venus", "hamilton_venus.traces"):
            logging.getLogger(logger_name).addHandler(handler)
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
        self._handler = handler

    def detach_logging(self) -> None:
        if self._handler is None:
            return
        for logger_name in ("hamilton_venus", "hamilton_venus.traces"):
            logging.getLogger(logger_name).removeHandler(self._handler)
        self._handler = None

    # -- jsonl tailer half -------------------------------------------------------

    async def start_tailing(self, run_log_dir: Path, jsonl_glob: str) -> None:
        self._stop_tail.clear()
        self._tail_task = asyncio.create_task(self._tail(run_log_dir, jsonl_glob))

    async def stop_tailing(self) -> None:
        self._stop_tail.set()
        if self._tail_task is not None:
            try:
                await asyncio.wait_for(self._tail_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._tail_task.cancel()
            self._tail_task = None

    async def _push(self, source: str, level: str | None, text: str) -> None:
        await self._queue.put(
            {"type": "log", "source": source, "level": level, "text": text, "timestamp": _now_iso()}
        )

    async def _wait_for_file(self, run_log_dir: Path, jsonl_glob: str, timeout: float = 10.0) -> Path | None:
        deadline = asyncio.get_event_loop().time() + timeout
        pattern = str(run_log_dir / jsonl_glob)
        while asyncio.get_event_loop().time() < deadline:
            if self._stop_tail.is_set():
                return None
            matches = glob.glob(pattern)
            if matches:
                return Path(matches[0])
            await asyncio.sleep(0.1)
        return None

    async def _tail(self, run_log_dir: Path, jsonl_glob: str) -> None:
        jsonl_path = await self._wait_for_file(run_log_dir, jsonl_glob)
        if jsonl_path is None:
            return
        try:
            f = await asyncio.to_thread(open, jsonl_path, encoding="utf-8")
        except OSError:
            return
        try:
            while not self._stop_tail.is_set():
                line = await asyncio.to_thread(f.readline)
                if not line:
                    if self._stop_tail.is_set():
                        break
                    await asyncio.sleep(0.15)
                    continue
                await self._handle_line(line)
        finally:
            f.close()

    async def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return
        source = _SOURCE_MAP.get(entry.get("source", ""), "backend")
        entry_type = entry.get("type", "")
        payload = entry.get("payload", {})

        if entry_type == "command_request":
            text = f"-> {payload.get('category', '')}.{payload.get('actionName', '')} {json.dumps(payload.get('parameters', {}))}"
        elif entry_type == "command_response":
            text = f"<- {payload.get('actionName', '')} {payload.get('returnStatus', '')} {json.dumps(payload.get('returnParameters', {}))[:400]}"
        elif entry_type == "command_communication":
            source = "cmd_comms"
            text = json.dumps(payload)[:400]
        elif entry_type == "script_output":
            text = str(payload.get("message", payload))
        else:
            text = f"[{entry_type}] {json.dumps(payload, default=str)[:400]}"

        await self._push(source, None, text)
