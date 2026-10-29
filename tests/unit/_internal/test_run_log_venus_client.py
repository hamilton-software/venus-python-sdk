"""Unit tests for WebAPI + Command run log integration."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hamilton_venus._internal._run_log import RunLog
from hamilton_venus._internal._run_message_command_dispatcher import _RunMessageCommandDispatcher
from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import VenusConnectionError
from hamilton_venus.models import RunMessageQueuedEvent
from hamilton_venus.venus_client import VenusClient
from tests.unit.test_helpers import mock_response


class TestHttpRequestEntryRecorded:
    @pytest.fixture
    def run_log(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        yield log
        log.close()

    @pytest.fixture
    def jsonl_path(self, tmp_path):
        return lambda: next(iter(tmp_path.glob("*.jsonl")))

    @pytest.mark.asyncio
    async def test_http_request_entry_recorded(self, run_log, tmp_path):
        client = VenusClient(base_url="http://localhost:42400")
        client._run_log = run_log
        client._run_log_config = RunLogConfig(enabled=True, include_http=True)

        mock_resp = mock_response(200, {"result": "ok"})
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await client._request("GET", "/api/test", json={"key": "value"})

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        request_entries = [e for e in entries if e["type"] == "http_request"]
        assert len(request_entries) == 1
        assert request_entries[0]["payload"]["method"] == "GET"
        assert request_entries[0]["payload"]["path"] == "/api/test"
        assert request_entries[0]["payload"]["body"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_http_response_entry_recorded(self, run_log, tmp_path):
        client = VenusClient(base_url="http://localhost:42400")
        client._run_log = run_log
        client._run_log_config = RunLogConfig(enabled=True, include_http=True)

        mock_resp = mock_response(200, {"result": "ok"})
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await client._request("PUT", "/api/load")

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        response_entries = [e for e in entries if e["type"] == "http_response"]
        assert len(response_entries) == 1
        assert response_entries[0]["payload"]["status_code"] == 200
        assert response_entries[0]["payload"]["body"] == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_http_error_entry_recorded(self, run_log, tmp_path):
        client = VenusClient(base_url="http://localhost:42400", max_retries=0)
        client._run_log = run_log
        client._run_log_config = RunLogConfig(enabled=True, include_http=True)

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http

            with pytest.raises(VenusConnectionError):
                await client._request("GET", "/api/test")

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        error_entries = [e for e in entries if e["type"] == "http_error"]
        assert len(error_entries) == 1
        assert "ConnectError" in error_entries[0]["payload"]["error"]
        assert error_entries[0]["payload"]["attempt"] == 1

    @pytest.mark.asyncio
    async def test_no_entries_when_run_log_is_none(self, tmp_path):
        client = VenusClient(base_url="http://localhost:42400")
        # _run_log is None by default

        mock_resp = mock_response(200, {"result": "ok"})
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await client._request("GET", "/api/test")

        # No crash, no log files created
        assert not list(tmp_path.glob("*.jsonl"))

    @pytest.mark.asyncio
    async def test_no_entries_when_include_http_false(self, run_log, tmp_path):
        client = VenusClient(base_url="http://localhost:42400")
        client._run_log = run_log
        client._run_log_config = RunLogConfig(enabled=True, include_http=False)

        mock_resp = mock_response(200, {"result": "ok"})
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await client._request("GET", "/api/test")

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        content = jsonl_files[0].read_text(encoding="utf-8").strip()
        assert content == ""

    def test_authorization_body_field_redacted_in_http_entry(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_http=True)
        log = RunLog(config, "test-session", "0.4.0")

        # Authorization keys in the body are redacted as defense-in-depth;
        # actual HTTP headers are excluded from the logged payload entirely.
        log.record(
            "WebAPI",
            "Out",
            "http_request",
            {
                "method": "GET",
                "path": "/api/test",
                "body": {"Authorization": "Bearer secret123"},
            },
        )
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
        assert entry["payload"]["body"]["Authorization"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_redaction_applied_via_request_path(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_http=True)
        run_log = RunLog(config, "test-session", "0.4.0")

        client = VenusClient(base_url="http://localhost:42400")
        client._run_log = run_log
        client._run_log_config = config

        sensitive_request_body = {"Authorization": "Bearer req-secret", "data": "safe"}
        sensitive_response_body = {"Authorization": "Bearer resp-secret", "result": "ok"}

        mock_resp = mock_response(200, sensitive_response_body)
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await client._request("POST", "/api/test", json=sensitive_request_body)

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        request_entries = [e for e in entries if e["type"] == "http_request"]
        assert len(request_entries) == 1
        assert request_entries[0]["payload"]["body"]["Authorization"] == "[REDACTED]"
        assert request_entries[0]["payload"]["body"]["data"] == "safe"

        response_entries = [e for e in entries if e["type"] == "http_response"]
        assert len(response_entries) == 1
        assert response_entries[0]["payload"]["body"]["Authorization"] == "[REDACTED]"
        assert response_entries[0]["payload"]["body"]["result"] == "ok"

    @pytest.mark.asyncio
    async def test_http_headers_excluded_from_logged_request(self, tmp_path):
        """Verify that HTTP request headers are not included in logged http_request entries.

        VenusClient._request() logs only method, path, and body to the run log.
        HTTP headers passed to the underlying httpx client are not included in the
        logged payload, even if they contain sensitive data like Authorization.
        """
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_http=True)
        run_log = RunLog(config, "test-session", "0.4.0")

        client = VenusClient(base_url="http://localhost:42400")
        client._run_log = run_log
        client._run_log_config = config

        # Prepare response
        mock_resp = mock_response(200, {"result": "ok"})

        # Mock _send_request_with_auth_refresh to capture the actual headers
        # being passed to the HTTP client (this won't be in the log)
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            # Call _request with json body
            await client._request("POST", "/api/data", json={"key": "value"})

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        request_entries = [e for e in entries if e["type"] == "http_request"]
        assert len(request_entries) == 1

        # Verify the logged entry contains method, path, and body
        payload = request_entries[0]["payload"]
        assert payload["method"] == "POST"
        assert payload["path"] == "/api/data"
        assert payload["body"] == {"key": "value"}

        # Verify no headers field is present in the logged payload
        assert "headers" not in payload, "HTTP headers should not be included in logged payload"


class TestCommandLogging:
    @pytest.mark.asyncio
    async def test_command_request_entry_recorded(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        run_log = RunLog(config, "test-session", "0.4.0")

        push_path = "/api/vector/v3/run-messages"
        pop_path = "/api/vector/v3/run-messages/action-response/pop"

        async def mock_request(method, path, *, json=None, error_prefix=""):
            if method == "POST" and path == push_path:
                return mock_response(200, {"messageId": "msg-123"})
            if method == "POST" and path == pop_path:
                return mock_response(
                    200,
                    {
                        "hasMessage": True,
                        "data": {
                            "actionId": "msg-123",
                            "category": "Channels",
                            "actionName": "aspirate",
                            "parameters": {},
                            "returnCode": 0,
                            "returnParameters": {},
                            "returnStatus": "Success",
                        },
                    },
                )
            return mock_response(200, {})

        dispatcher = _RunMessageCommandDispatcher(mock_request)
        dispatcher._run_log = run_log

        # Queue a notification so _wait_for_run_message_channel resolves
        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await dispatcher.send_command(
            "Channels",
            "aspirate",
            {"volume": 100.0},
            default_timeout=5.0,
        )

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        cmd_requests = [e for e in entries if e["type"] == "command_request"]
        assert len(cmd_requests) == 1
        assert cmd_requests[0]["payload"]["category"] == "Channels"
        assert cmd_requests[0]["payload"]["action_name"] == "aspirate"
        assert cmd_requests[0]["payload"]["parameters"] == {"volume": 100.0}

    @pytest.mark.asyncio
    async def test_command_response_entry_recorded(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        run_log = RunLog(config, "test-session", "0.4.0")

        push_path = "/api/vector/v3/run-messages"
        pop_path = "/api/vector/v3/run-messages/action-response/pop"

        async def mock_request(method, path, *, json=None, error_prefix=""):
            if method == "POST" and path == push_path:
                return mock_response(200, {"messageId": "msg-456"})
            if method == "POST" and path == pop_path:
                return mock_response(
                    200,
                    {
                        "hasMessage": True,
                        "data": {
                            "actionId": "msg-456",
                            "category": "Channels",
                            "actionName": "dispense",
                            "parameters": {},
                            "returnCode": 0,
                            "returnParameters": {"dispensed": 95.0},
                            "returnStatus": "Success",
                        },
                    },
                )
            return mock_response(200, {})

        dispatcher = _RunMessageCommandDispatcher(mock_request)
        dispatcher._run_log = run_log

        await dispatcher.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))
        await dispatcher.send_command(
            "Channels",
            "dispense",
            {"volume": 95.0},
            default_timeout=5.0,
        )

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        cmd_responses = [e for e in entries if e["type"] == "command_response"]
        assert len(cmd_responses) == 1
        assert cmd_responses[0]["source"] == "WebAPI"
        assert cmd_responses[0]["direction"] == "In"


class TestCommandCommunicationRunLog:
    @staticmethod
    def _communication_payload(message_id: str, *, status: str = "running") -> dict[str, object]:
        return {
            "channel": "communication",
            "hasMessage": True,
            "messageId": message_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {
                "id": "liq-1",
                "category": "Channels",
                "command": "aspirate",
                "status": status,
            },
        }

    @pytest.mark.asyncio
    async def test_command_communication_entry_recorded_when_enabled(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_cmd_comms=True)
        run_log = RunLog(config, "test-session", "0.4.0")

        request = AsyncMock(
            side_effect=[
                mock_response(200, self._communication_payload("msg-comm-1", status="done")),
                mock_response(200, {"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._run_log = run_log
        dispatcher._run_log_config = config

        await dispatcher._drain_communication_channel()

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        communication_entries = [e for e in entries if e["type"] == "command_communication"]
        assert len(communication_entries) == 1

    @pytest.mark.asyncio
    async def test_command_communication_not_recorded_when_disabled(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_cmd_comms=False)
        run_log = RunLog(config, "test-session", "0.4.0")

        request = AsyncMock(
            side_effect=[
                mock_response(200, self._communication_payload("msg-comm-2", status="done")),
                mock_response(200, {"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._run_log = run_log
        dispatcher._run_log_config = config

        await dispatcher._drain_communication_channel()

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        content = jsonl_files[0].read_text(encoding="utf-8").strip()
        if content:
            entries = [json.loads(line) for line in content.splitlines()]
            communication_entries = [e for e in entries if e["type"] == "command_communication"]
            assert communication_entries == []
        else:
            assert content == ""

    @pytest.mark.asyncio
    async def test_command_communication_payload_fields_and_inactive_context(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_cmd_comms=True)
        run_log = RunLog(config, "test-session", "0.4.0")

        request = AsyncMock(
            side_effect=[
                mock_response(200, self._communication_payload("msg-comm-3", status="done")),
                mock_response(200, {"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._run_log = run_log
        dispatcher._run_log_config = config
        dispatcher._command_active = False

        await dispatcher._drain_communication_channel()

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        communication_entry = next(e for e in entries if e["type"] == "command_communication")
        payload = communication_entry["payload"]
        assert payload["messageId"] == "msg-comm-3"
        assert payload["timestamp"] == "2026-01-01T00:00:00Z"
        assert payload["data"]["id"] == "liq-1"
        assert payload["data"]["category"] == "Channels"
        assert payload["data"]["command"] == "aspirate"
        assert payload["data"]["status"] == "done"
        assert payload["active_operation_context"] is None

    @pytest.mark.asyncio
    async def test_command_communication_active_operation_context_only_during_command(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_cmd_comms=True)
        run_log = RunLog(config, "test-session", "0.4.0")

        request = AsyncMock(
            side_effect=[
                mock_response(200, self._communication_payload("msg-comm-4", status="running")),
                mock_response(200, {"channel": "communication", "hasMessage": False, "data": {}}),
                mock_response(200, self._communication_payload("msg-comm-5", status="done")),
                mock_response(200, {"channel": "communication", "hasMessage": False, "data": {}}),
            ]
        )

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher._run_log = run_log
        dispatcher._run_log_config = config
        dispatcher._last_operation_context = "System/instrument.init"

        dispatcher._command_active = True
        await dispatcher._drain_communication_channel()

        dispatcher._command_active = False
        await dispatcher._drain_communication_channel()

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        communication_entries = [e for e in entries if e["type"] == "command_communication"]
        assert communication_entries[0]["payload"]["active_operation_context"] == "System/instrument.init"
        assert communication_entries[1]["payload"]["active_operation_context"] is None
