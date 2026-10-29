"""Unit tests for SignalR event run log integration."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hamilton_venus._internal._run_log import RunLog
from hamilton_venus._internal._signalr_listener import _SignalRListener
from hamilton_venus.config import RunLogConfig


@pytest.fixture
def listener_with_log(tmp_path):
    """Create a _SignalRListener with a RunLog attached."""
    config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_signalr=True)
    run_log = RunLog(config, "test-session", "0.4.0")
    listener = _SignalRListener("http://localhost:42400")
    listener._run_log = run_log
    listener._run_log_config = config
    return listener, run_log, tmp_path


def _get_entries(tmp_path) -> list[dict[str, Any]]:
    jsonl_files = list(tmp_path.glob("*.jsonl"))
    if not jsonl_files:
        return []
    lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class TestSignalRRunLog:
    @pytest.mark.asyncio
    async def test_runtime_status_event_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log
        await listener._on_runtime_status([{"executorEvent": 0, "message": "idle"}])
        run_log.close()

        entries = _get_entries(tmp_path)
        status_entries = [e for e in entries if e["type"] == "runtime_status"]
        assert len(status_entries) == 1
        assert status_entries[0]["source"] == "SignalR"
        assert status_entries[0]["direction"] == "In"

    @pytest.mark.asyncio
    async def test_progress_event_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log
        await listener._on_progress_changed([{"progress": 50, "message": "halfway"}])
        run_log.close()

        entries = _get_entries(tmp_path)
        progress_entries = [e for e in entries if e["type"] == "progress"]
        assert len(progress_entries) == 1

    @pytest.mark.asyncio
    async def test_runtime_trace_event_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log
        await listener._on_runtime_trace(["Some trace message"])
        run_log.close()

        entries = _get_entries(tmp_path)
        trace_entries = [e for e in entries if e["type"] == "runtime_trace"]
        assert len(trace_entries) == 1
        assert trace_entries[0]["payload"]["trace"] == "Some trace message"

    @pytest.mark.asyncio
    async def test_run_message_queued_event_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log
        await listener._on_run_message_queued([{"channel": "action-response", "messageId": "m1", "queueDepth": 1}])
        run_log.close()

        entries = _get_entries(tmp_path)
        queued_entries = [e for e in entries if e["type"] == "run_message_queued"]
        assert len(queued_entries) == 1

    @pytest.mark.asyncio
    async def test_instrument_error_event_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log
        await listener._on_instrument_error_event(
            [
                {
                    "uuid": "err-1",
                    "deviceId": 1,
                    "message": "Tip not picked up",
                }
            ]
        )
        run_log.close()

        entries = _get_entries(tmp_path)
        error_entries = [e for e in entries if e["type"] == "instrument_error"]
        assert len(error_entries) == 1

    @pytest.mark.asyncio
    async def test_no_signalr_entries_when_disabled(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_signalr=False)
        run_log = RunLog(config, "test-session", "0.4.0")
        listener = _SignalRListener("http://localhost:42400")
        listener._run_log = run_log
        listener._run_log_config = config

        await listener._on_runtime_status([{"executorEvent": 0, "message": "idle"}])
        await listener._on_progress_changed([{"progress": 50}])
        run_log.close()

        entries = _get_entries(tmp_path)
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_connection_state_change_logged(self, listener_with_log):
        listener, run_log, tmp_path = listener_with_log

        from hamilton_venus.models import ConnectionState

        # Directly trigger state transitions without starting real connections.
        listener._set_state(ConnectionState.CONNECTING)
        listener._set_state(ConnectionState.CONNECTED)
        run_log.close()

        entries = _get_entries(tmp_path)
        state_entries = [e for e in entries if e["type"] == "connection_state_changed"]
        assert len(state_entries) == 2
        assert state_entries[0]["payload"]["old_state"] == ConnectionState.DISCONNECTED.value
        assert state_entries[0]["payload"]["new_state"] == ConnectionState.CONNECTING.value
        assert state_entries[1]["payload"]["old_state"] == ConnectionState.CONNECTING.value
        assert state_entries[1]["payload"]["new_state"] == ConnectionState.CONNECTED.value

    @pytest.mark.asyncio
    async def test_signalr_event_filter(self, tmp_path):
        config = RunLogConfig(
            enabled=True,
            output_dir=str(tmp_path),
            include_signalr=True,
            signalr_event_filter=["runtime_status"],
        )
        run_log = RunLog(config, "test-session", "0.4.0")
        listener = _SignalRListener("http://localhost:42400")
        listener._run_log = run_log
        listener._run_log_config = config

        await listener._on_runtime_status([{"executorEvent": 0, "message": "idle"}])
        await listener._on_progress_changed([{"progress": 50}])
        await listener._on_runtime_trace(["trace msg"])
        run_log.close()

        entries = _get_entries(tmp_path)
        # Only runtime_status should be logged
        assert all(e["type"] == "runtime_status" for e in entries)
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_events_dispatched_via_client(self, tmp_path):
        """Test that SignalR events are logged when dispatched through the client.

        **Note: Fragile Test**
        This test accesses `client._message_handlers`, a private attribute of the
        pysignalr.HubConnection class. This creates tight coupling to an external
        library's internal implementation. If pysignalr changes this structure
        (e.g., in a future version), this test will break.

        **Why This Approach:**
        pysignalr doesn't expose a public API for test-dispatching events without
        a real SignalR server connection. The alternative would be to mock the
        entire HubConnection, but that would test the mock rather than the actual
        event handlers. This test verifies the real handler code paths work correctly.

        **Future Improvement:**
        When pysignalr adds a public testing API or when we refactor the listener
        to decouple from pysignalr internals, this test should be updated to use
        the public API instead.
        """
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_signalr=True)
        run_log = RunLog(config, "test-session", "0.4.0")
        listener = _SignalRListener("http://localhost:42400")
        listener._run_log = run_log
        listener._run_log_config = config

        client = listener._create_client(None)
        # Access internal _message_handlers to test without real SignalR server.
        # See class docstring for fragility notes.
        handlers = client._message_handlers  # type: ignore[attr-defined]

        from hamilton_venus._internal._signalr_listener import PROGRESS_CHANGED, RUNTIME_STATUS, RUNTIME_TRACE

        for cb in handlers[RUNTIME_STATUS]:
            await cb([{"executorEvent": 0, "message": "idle"}])
        for cb in handlers[PROGRESS_CHANGED]:
            await cb([{"progress": 75, "message": "three quarters"}])
        for cb in handlers[RUNTIME_TRACE]:
            await cb(["Trace from client dispatch"])
        run_log.close()

        entries = _get_entries(tmp_path)
        types = [e["type"] for e in entries]
        assert "runtime_status" in types
        assert "progress" in types
        assert "runtime_trace" in types

    @pytest.mark.asyncio
    async def test_event_filter_via_client_dispatch(self, tmp_path):
        """Test that SignalR event filtering works when events are dispatched.

        **Note: Fragile Test**
        Like test_events_dispatched_via_client, this test accesses the private
        `_message_handlers` attribute of pysignalr.HubConnection. See that test's
        docstring for details on why this approach is necessary and future plans.
        """
        config = RunLogConfig(
            enabled=True,
            output_dir=str(tmp_path),
            include_signalr=True,
            signalr_event_filter=["runtime_status"],
        )
        run_log = RunLog(config, "test-session", "0.4.0")
        listener = _SignalRListener("http://localhost:42400")
        listener._run_log = run_log
        listener._run_log_config = config

        client = listener._create_client(None)
        # Access internal _message_handlers to test without real SignalR server.
        # See class docstring for fragility notes.
        handlers = client._message_handlers  # type: ignore[attr-defined]

        from hamilton_venus._internal._signalr_listener import (
            INSTRUMENT_ERROR_EVENT,
            PROGRESS_CHANGED,
            RUNTIME_STATUS,
            RUNTIME_TRACE,
        )

        for cb in handlers[RUNTIME_STATUS]:
            await cb([{"executorEvent": 0, "message": "idle"}])
        for cb in handlers[PROGRESS_CHANGED]:
            await cb([{"progress": 50}])
        for cb in handlers[RUNTIME_TRACE]:
            await cb(["trace msg"])
        for cb in handlers[INSTRUMENT_ERROR_EVENT]:
            await cb([{"uuid": "e1", "deviceId": 1, "message": "err"}])
        run_log.close()

        entries = _get_entries(tmp_path)
        assert all(e["type"] == "runtime_status" for e in entries)
        assert len(entries) == 1
