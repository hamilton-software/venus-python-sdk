"""Unit tests for hamilton_venus.venus_client."""

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import (
    MethodError,
    VenusApiContractError,
    VenusConnectionError,
    VenusTimeoutError,
)
from hamilton_venus.models import (
    CmdResult,
    CommandResponse,
    ErrorData,
    ErrorHandlingResponse,
    ErrorRecovery,
    ExecutorEvent,
    InputValue,
    RunMessageQueuedEvent,
    RunState,
)
from hamilton_venus.venus_client import VenusClient

_PUSH_RUN_MESSAGE_PATH = "/api/vector/v3/run-messages"
_POP_RESPONSE_PATH = "/api/vector/v3/run-messages/action-response/pop"


def _mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> httpx.Response:
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"} if json_data is not None else {},
        request=httpx.Request("GET", "http://testserver"),
    )


def _build_command_response_data(
    request_envelope: dict[str, Any],
    *,
    response_id: str | None = None,
    response_id_field: str = "actionId",
    category: str | None = None,
    action_name: str | None = None,
    parameters: dict[str, Any] | None = None,
    status: str | None = None,
    return_status: str | None = None,
    return_code: int = 0,
    return_parameters: Any,
) -> dict[str, Any]:
    response_payload = {
        response_id_field: response_id or request_envelope["id"],
        "category": category or request_envelope["category"],
        "actionName": action_name or request_envelope["actionName"],
        "parameters": parameters if parameters is not None else request_envelope["parameters"],
        "returnCode": return_code,
        "returnParameters": return_parameters,
    }
    if status is not None:
        response_payload["status"] = status
    if return_status is not None:
        response_payload["returnStatus"] = return_status
    return {
        "hasMessage": True,
        "data": response_payload,
    }


def _make_send_command_request_side_effect(
    mock_client: AsyncMock,
    *,
    response_data_factory: Callable[[dict[str, Any]], dict[str, Any]],
    push_response_json: dict[str, Any] | None = None,
    pop_responses: list[dict[str, Any]] | None = None,
    pop_response_json: dict[str, Any] | None = None,
) -> Callable[..., httpx.Response]:
    # Replies served by the response pops before the real response (e.g. an empty queue).
    pending_pop_responses = list(pop_responses or [])

    def _request_side_effect(method, path, **kwargs):
        if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
            request_envelope = kwargs["json"]["data"]
            mock_client.request_envelope = request_envelope
            push_payload = push_response_json or {"messageId": "queue-message-1", "channel": "action"}
            mock_client.queue_message_id = push_payload.get("messageId", "")
            mock_client.response_data = response_data_factory(request_envelope)
            return _mock_response(json_data=push_payload)

        if method == "POST" and path == _POP_RESPONSE_PATH:
            if pending_pop_responses:
                return _mock_response(json_data=pending_pop_responses.pop(0))
            return _mock_response(json_data=pop_response_json or mock_client.response_data)

        raise AssertionError(f"Unexpected request: {method} {path}")

    return _request_side_effect


class TestVenusClientLifecycle:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with VenusClient(base_url="http://testserver:42400") as c:
            assert c._base_url == "http://testserver:42400"

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"base_url": ""}, "base_url"),
            ({"base_url": "/"}, "base_url"),
            ({"base_url": "http://testserver:42400", "timeout": 0}, "timeout"),
            ({"base_url": "http://testserver:42400", "max_retries": -1}, "max_retries"),
            ({"base_url": "http://testserver:42400", "retry_backoff": -0.1}, "retry_backoff"),
            ({"base_url": "http://testserver:42400", "command_timeout": 0}, "command_timeout"),
        ],
    )
    def test_invalid_configuration_raises_value_error(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            VenusClient(**kwargs)

    @pytest.mark.asyncio
    async def test_strips_trailing_slash(self):
        c = VenusClient(base_url="http://testserver:42400/")
        assert c._base_url == "http://testserver:42400"
        await c.aclose()

    @pytest.mark.asyncio
    async def test_dispatcher_receives_initial_run_log_config(self):
        client = VenusClient(base_url="http://testserver:42400")

        assert client._command_dispatcher._run_log_config == client._run_log_config

        updated = RunLogConfig(enabled=True, include_http=True)
        client._command_dispatcher.set_run_log_config(updated)
        assert client._command_dispatcher._run_log_config is updated
        await client.aclose()


class TestVenusClientRequests:
    @pytest.mark.asyncio
    async def test_load_method(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"result": True, "message": "OK", "resetRunExecutor": False},
                )
            )
            c._client = mock_client
            result = await c.load_method("C:\\Methods\\test.hsl", simulate=True)
            assert isinstance(result, CmdResult)
            assert result.result is True
            mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_method(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"result": True, "message": ""},
                )
            )
            c._client = mock_client
            result = await c.start_method()
            assert result.result is True

    @pytest.mark.asyncio
    async def test_get_run_state(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=2))
            c._client = mock_client
            state = await c.get_run_state()
            assert state == RunState.RUNNING

    @pytest.mark.asyncio
    async def test_get_loaded_method(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data="C:\\Methods\\test.hsl",
                )
            )
            c._client = mock_client
            path = await c.get_loaded_method()
            assert path == "C:\\Methods\\test.hsl"

    @pytest.mark.asyncio
    async def test_get_current_run_data(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"methodName": "VENUS_SDK_Session", "runGuid": "abc-123-guid"},
                )
            )
            c._client = mock_client
            data = await c.get_current_run_data()
            assert data["methodName"] == "VENUS_SDK_Session"
            assert data["runGuid"] == "abc-123-guid"

    @pytest.mark.asyncio
    async def test_get_run_guid(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"methodName": "m", "runGuid": "abc-123-guid"},
                )
            )
            c._client = mock_client
            guid = await c.get_run_guid()
            assert guid == "abc-123-guid"

    @pytest.mark.asyncio
    async def test_get_run_guid_missing_field_returns_empty(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"methodName": "m"}))
            c._client = mock_client
            guid = await c.get_run_guid()
            assert guid == ""

    @pytest.mark.asyncio
    async def test_get_current_run_data_non_dict_payload_returns_empty(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=[1, 2, 3]))
            c._client = mock_client
            data = await c.get_current_run_data()
            assert data == {}

    @pytest.mark.asyncio
    async def test_get_current_run_data_empty_body_returns_empty(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=None))
            c._client = mock_client
            data = await c.get_current_run_data()
            assert data == {}

    @pytest.mark.asyncio
    async def test_get_simulation_bool_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=True))
            c._client = mock_client
            result = await c.get_simulation()
            assert result is True
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.args[1].endswith("/v2/system/configuration/simulation")

    @pytest.mark.asyncio
    async def test_get_simulation_dict_payload_simulation_key(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"simulation": False}))
            c._client = mock_client
            result = await c.get_simulation()
            assert result is False

    @pytest.mark.asyncio
    async def test_get_simulation_dict_payload_is_simulation_key(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"isSimulation": True}))
            c._client = mock_client
            result = await c.get_simulation()
            assert result is True

    @pytest.mark.asyncio
    async def test_get_simulation_invalid_payload_raises_contract_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={}))
            c._client = mock_client
            with pytest.raises(VenusApiContractError, match="GetSimulation"):
                await c.get_simulation()

    @pytest.mark.asyncio
    async def test_set_simulation_sends_correct_query_param(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=None, text=""))
            c._client = mock_client
            await c.set_simulation(True)
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.args[0] == "PUT"
            assert call_kwargs.args[1].endswith("/v2/system/configuration/simulation")
            assert call_kwargs.kwargs["params"] == {"simulationMode": "true"}

    @pytest.mark.asyncio
    async def test_set_simulation_false_sends_correct_query_param(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=None, text=""))
            c._client = mock_client
            await c.set_simulation(False)
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.kwargs["params"] == {"simulationMode": "false"}

    @pytest.mark.asyncio
    async def test_get_authentication_mode_string_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data="None"))
            c._client = mock_client
            mode = await c.get_authentication_mode()
            assert mode == "None"

    @pytest.mark.asyncio
    async def test_get_authentication_mode_dict_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"authenticationMode": "WindowsAD"}))
            c._client = mock_client
            mode = await c.get_authentication_mode()
            assert mode == "WindowsAD"

    @pytest.mark.asyncio
    async def test_get_authentication_mode_invalid_payload_raises_contract_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={}))
            c._client = mock_client
            with pytest.raises(VenusApiContractError, match="GetAuthenticationMode"):
                await c.get_authentication_mode()

    @pytest.mark.asyncio
    async def test_get_system_paths_returns_paths_map(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={
                        "paths": {
                            "Bin": "C:\\Program Files (x86)\\Hamilton\\Bin",
                            "LogFiles": "C:\\Program Files (x86)\\Hamilton\\Logfiles",
                        }
                    }
                )
            )
            c._client = mock_client
            paths = await c.get_system_paths()
            assert paths["LogFiles"] == "C:\\Program Files (x86)\\Hamilton\\Logfiles"
            assert c._client.request.call_args.args[1] == "/api/vector/v3/system/paths"

    @pytest.mark.asyncio
    async def test_get_system_paths_accepts_flat_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(json_data={"LogFiles": "D:\\Logs"})
            )
            c._client = mock_client
            paths = await c.get_system_paths()
            assert paths["LogFiles"] == "D:\\Logs"

    @pytest.mark.asyncio
    async def test_get_system_paths_invalid_payload_raises_contract_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data="nope"))
            c._client = mock_client
            with pytest.raises(VenusApiContractError, match="GetSystemPaths"):
                await c.get_system_paths()

    @pytest.mark.asyncio
    async def test_get_run_history_sends_paging_and_returns_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"spanCount": 1, "subList": [{"runGuid": "abc", "methodDisplayName": "m"}]}
                )
            )
            c._client = mock_client
            history = await c.get_run_history(limit=5, offset=11, run_state="Finished")
            assert history["subList"][0]["runGuid"] == "abc"
            call = c._client.request.call_args
            assert call.args[1] == "/api/vector/v3/files/run-history-data"
            assert call.kwargs["params"] == {
                "sortProperty": "StartTime",
                "sortOrder": 1,
                "startOffset": 11,
                "recordLimit": 5,
                "runState": "Finished",
            }

    @pytest.mark.asyncio
    async def test_get_run_history_invalid_payload_raises_contract_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=["nope"]))
            c._client = mock_client
            with pytest.raises(VenusApiContractError, match="GetRunHistory"):
                await c.get_run_history()

    @pytest.mark.asyncio
    async def test_get_run_details_returns_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"runGuid": "abc", "instruments": [{"instrumentSimulation": True}]}
                )
            )
            c._client = mock_client
            details = await c.get_run_details("abc")
            assert details["instruments"][0]["instrumentSimulation"] is True
            assert c._client.request.call_args.args[1] == "/api/vector/v3/files/detailed-run-data/abc"

    @pytest.mark.asyncio
    async def test_get_trace_returns_lines(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data=["line 1", "line 2"]))
            c._client = mock_client
            assert await c.get_trace("method", "guid") == ["line 1", "line 2"]
            call = c._client.request.call_args
            assert call.args[1] == "/api/vector/v3/files/trace"
            assert call.kwargs["params"] == {"methodName": "method", "runGuid": "guid"}

    @pytest.mark.asyncio
    async def test_get_file_asset_lowercases_path_and_returns_bytes(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"run_guid": "abc"}))
            c._client = mock_client
            data = await c.get_file_asset("C:\\LogFiles\\M_abc_SdkRunLog.json")
            assert json.loads(data) == {"run_guid": "abc"}
            assert c._client.request.call_args.kwargs["params"] == {
                "assetPath": "c:\\logfiles\\m_abc_sdkrunlog.json", "assetType": "json",
            }

    @pytest.mark.asyncio
    async def test_get_file_asset_head_stops_after_max_bytes(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, content=b'{"reason": "error", "log": [' + b"x" * 100_000 + b"]}")

        async with VenusClient(base_url="http://test:42400") as c:
            c._client = httpx.AsyncClient(base_url="http://test:42400", transport=httpx.MockTransport(handler))
            head = await c.get_file_asset_head("C:\\LogFiles\\Run_SdkRunLog.json", max_bytes=64)
        assert head == (b'{"reason": "error", "log": [' + b"x" * 100)[:64]
        assert seen["params"] == {"assetPath": "c:\\logfiles\\run_sdkrunlog.json", "assetType": "json"}

    @pytest.mark.asyncio
    async def test_get_file_asset_head_missing_file_is_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Requested file could not be found")

        async with VenusClient(base_url="http://test:42400") as c:
            c._client = httpx.AsyncClient(base_url="http://test:42400", transport=httpx.MockTransport(handler))
            assert await c.get_file_asset_head("C:\\LogFiles\\missing.json") is None

    @pytest.mark.asyncio
    async def test_set_method_variables_sends_correct_payload(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"result": True, "message": "ok"},
                )
            )
            c._client = mock_client
            result = await c.set_method_variables(["bearerToken"], ["my-token"])
            assert result.result is True
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.kwargs["json"] == {
                "variableNames": ["bearerToken"],
                "variableValues": ["my-token"],
            }

    @pytest.mark.asyncio
    async def test_set_method_variables_uses_put_to_input_endpoint(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"result": True, "message": "ok"},
                )
            )
            c._client = mock_client
            await c.set_method_variables(["x"], ["1"])
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.args[0] == "PUT"
            assert call_kwargs.args[1].endswith("/input")

    @pytest.mark.asyncio
    async def test_set_method_variables_multiple_variables(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    json_data={"result": True, "message": "ok"},
                )
            )
            c._client = mock_client
            result = await c.set_method_variables(["a", "b", "c"], ["1", "2", "3"])
            assert result.result is True
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.kwargs["json"] == {
                "variableNames": ["a", "b", "c"],
                "variableValues": ["1", "2", "3"],
            }

    @pytest.mark.asyncio
    async def test_set_method_variables_http_error_raises_method_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(status_code=400, text="bad request")
            )
            c._client = mock_client
            with pytest.raises(MethodError):
                await c.set_method_variables(["bearerToken"], ["token"])


class TestVenusClientErrors:
    @pytest.mark.asyncio
    async def test_http_error_raises_method_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    status_code=500,
                    text="Internal Server Error",
                )
            )
            c._client = mock_client
            with pytest.raises(MethodError) as exc_info:
                await c.start_method()
            assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_error_raises_venus_connection_error(self):
        async with VenusClient(base_url="http://test:42400", max_retries=0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
            c._client = mock_client
            with pytest.raises(VenusConnectionError):
                await c.start_method()

    @pytest.mark.asyncio
    async def test_timeout_raises_venus_timeout_error(self):
        async with VenusClient(base_url="http://test:42400", max_retries=0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            c._client = mock_client
            with pytest.raises(VenusTimeoutError):
                await c.start_method()


class TestVenusClientRetry:
    @pytest.mark.asyncio
    async def test_retries_on_connect_error(self):
        async with VenusClient(base_url="http://test:42400", max_retries=2, retry_backoff=0.01) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    httpx.ConnectError("refused"),
                    httpx.ConnectError("refused"),
                    _mock_response(json_data={"result": True, "message": ""}),
                ]
            )
            c._client = mock_client
            result = await c.start_method()
            assert result.result is True
            assert mock_client.request.await_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        async with VenusClient(base_url="http://test:42400", max_retries=1, retry_backoff=0.01) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    httpx.TimeoutException("timed out"),
                    _mock_response(json_data={"result": True, "message": ""}),
                ]
            )
            c._client = mock_client
            result = await c.start_method()
            assert result.result is True

    @pytest.mark.asyncio
    async def test_retries_on_502(self):
        async with VenusClient(base_url="http://test:42400", max_retries=1, retry_backoff=0.01) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    _mock_response(status_code=502, text="Bad Gateway"),
                    _mock_response(json_data={"result": True, "message": ""}),
                ]
            )
            c._client = mock_client
            result = await c.start_method()
            assert result.result is True
            assert mock_client.request.await_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_500(self):
        async with VenusClient(base_url="http://test:42400", max_retries=2, retry_backoff=0.01) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(
                    status_code=500,
                    text="Internal Server Error",
                )
            )
            c._client = mock_client
            with pytest.raises(MethodError):
                await c.start_method()
            assert mock_client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries_raises(self):
        async with VenusClient(base_url="http://test:42400", max_retries=2, retry_backoff=0.01) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
            c._client = mock_client
            with pytest.raises(VenusConnectionError):
                await c.start_method()
            assert mock_client.request.await_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_when_disabled(self):
        async with VenusClient(base_url="http://test:42400", max_retries=0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
            c._client = mock_client
            with pytest.raises(VenusConnectionError):
                await c.start_method()
            assert mock_client.request.await_count == 1


class TestVenusClientAuthentication:
    @pytest.mark.asyncio
    async def test_request_includes_bearer_auth_header(self):
        auth_provider = SimpleNamespace(
            get_auth_headers=AsyncMock(return_value={"Authorization": "Bearer token-1"}),
            force_refresh=AsyncMock(return_value={"Authorization": "Bearer token-2"}),
            aclose=AsyncMock(),
        )

        async with VenusClient(base_url="http://test:42400", auth_provider=auth_provider) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(json_data={"result": True, "message": ""}))
            c._client = mock_client

            result = await c.start_method()

            assert result.result is True
            auth_provider.get_auth_headers.assert_awaited_once()
            auth_provider.force_refresh.assert_not_called()
            request_call = mock_client.request.await_args_list[0]
            assert request_call.kwargs["headers"] == {"Authorization": "Bearer token-1"}

        auth_provider.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_401_refreshes_token_and_retries_once(self):
        auth_provider = SimpleNamespace(
            get_auth_headers=AsyncMock(return_value={"Authorization": "Bearer stale-token"}),
            force_refresh=AsyncMock(return_value={"Authorization": "Bearer fresh-token"}),
            aclose=AsyncMock(),
        )

        async with VenusClient(base_url="http://test:42400", auth_provider=auth_provider, max_retries=0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    _mock_response(status_code=401, text="Unauthorized"),
                    _mock_response(json_data={"result": True, "message": ""}),
                ]
            )
            c._client = mock_client

            result = await c.start_method()

            assert result.result is True
            auth_provider.get_auth_headers.assert_awaited_once()
            auth_provider.force_refresh.assert_awaited_once()
            assert mock_client.request.await_count == 2
            first_call, second_call = mock_client.request.await_args_list
            assert first_call.kwargs["headers"] == {"Authorization": "Bearer stale-token"}
            assert second_call.kwargs["headers"] == {"Authorization": "Bearer fresh-token"}

    @pytest.mark.asyncio
    async def test_401_without_success_after_refresh_raises_method_error(self):
        auth_provider = SimpleNamespace(
            get_auth_headers=AsyncMock(return_value={"Authorization": "Bearer stale-token"}),
            force_refresh=AsyncMock(return_value={"Authorization": "Bearer fresh-token"}),
            aclose=AsyncMock(),
        )

        async with VenusClient(base_url="http://test:42400", auth_provider=auth_provider, max_retries=1) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    _mock_response(status_code=401, text="Unauthorized"),
                    _mock_response(status_code=401, text="Still Unauthorized"),
                ]
            )
            c._client = mock_client

            with pytest.raises(MethodError, match="401"):
                await c.start_method()

            auth_provider.get_auth_headers.assert_awaited_once()
            auth_provider.force_refresh.assert_awaited_once()
            assert mock_client.request.await_count == 2

    @pytest.mark.asyncio
    async def test_401_refresh_then_retryable_503_eventually_succeeds(self):
        auth_provider = SimpleNamespace(
            get_auth_headers=AsyncMock(return_value={"Authorization": "Bearer stale-token"}),
            force_refresh=AsyncMock(return_value={"Authorization": "Bearer fresh-token"}),
            aclose=AsyncMock(),
        )

        async with VenusClient(
            base_url="http://test:42400",
            auth_provider=auth_provider,
            max_retries=1,
            retry_backoff=0.0,
        ) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    _mock_response(status_code=401, text="Unauthorized"),
                    _mock_response(status_code=503, text="Service Unavailable"),
                    _mock_response(json_data={"result": True, "message": ""}),
                ]
            )
            c._client = mock_client

            result = await c.start_method()

            assert result.result is True
            assert auth_provider.get_auth_headers.await_count == 2
            auth_provider.force_refresh.assert_awaited_once()
            assert mock_client.request.await_count == 3

    @pytest.mark.asyncio
    async def test_401_refresh_then_retries_exhausted_raises_method_error(self):
        auth_provider = SimpleNamespace(
            get_auth_headers=AsyncMock(return_value={"Authorization": "Bearer stale-token"}),
            force_refresh=AsyncMock(return_value={"Authorization": "Bearer fresh-token"}),
            aclose=AsyncMock(),
        )

        async with VenusClient(
            base_url="http://test:42400",
            auth_provider=auth_provider,
            max_retries=1,
            retry_backoff=0.0,
        ) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=[
                    _mock_response(status_code=401, text="Unauthorized"),
                    _mock_response(status_code=503, text="Service Unavailable"),
                    _mock_response(status_code=503, text="Service Unavailable"),
                ]
            )
            c._client = mock_client

            with pytest.raises(MethodError, match="503"):
                await c.start_method()

            assert auth_provider.get_auth_headers.await_count == 2
            auth_provider.force_refresh.assert_awaited_once()
            assert mock_client.request.await_count == 3


class TestVenusClientSendCommand:
    @staticmethod
    def _server_message_id() -> str:
        """Simulate SignalR notification for tests."""
        return "12345678-1234-5678-1234-567812345678"

    @staticmethod
    async def _setup_signalr(venus_client: VenusClient) -> None:
        """Simulate SignalR notification for tests."""
        # Immediately notify that a message is queued (simulating SignalR firing)
        await venus_client.notify_run_message_queued(RunMessageQueuedEvent(channel="action-response"))

    @staticmethod
    async def _setup_signalr_with_empty_pop(venus_client: VenusClient) -> None:
        """Set up two SignalR notifications for tests with an empty first pop.

        Each call to _setup_signalr() queues one notification event to simulate
        a SignalR message arrival. When pop_responses includes an empty response
        (hasMessage: False), the first notification gets consumed by the empty
        pop in the inner loop. The second notification is then available for the
        outer loop to trigger the real response pop.
        """
        await TestVenusClientSendCommand._setup_signalr(venus_client)
        await TestVenusClientSendCommand._setup_signalr(venus_client)

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        status="Completed",
                        return_status="Success",
                        return_code=0,
                        return_parameters={"isConnected": True},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            resp = await c.send_command("System", "instrument.isConnected")

            assert isinstance(resp, CommandResponse)
            assert resp.success is True
            assert resp.status == "Completed"
            assert resp.return_parameters == {"isConnected": True}
            # Push + one pop: the response is popped directly, without a peek first.
            assert mock_client.request.await_count == 2

            push_call = mock_client.request.await_args_list[0]
            assert push_call.args == ("POST", _PUSH_RUN_MESSAGE_PATH)
            push_body = push_call.kwargs["json"]
            assert push_body["channel"] == "action"
            request_envelope = push_body["data"]
            assert request_envelope["id"]
            assert request_envelope["category"] == "System"
            assert request_envelope["actionName"] == "instrument.isConnected"
            assert request_envelope["parameters"] == {}

            pop_call = mock_client.request.await_args_list[1]
            assert pop_call.args == ("POST", _POP_RESPONSE_PATH)

    @pytest.mark.asyncio
    async def test_send_command_failure_raises_venus_command_failed_error(self):
        from hamilton_venus.exceptions import VenusCommandFailedError

        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        return_status="Error",
                        return_code=1,
                        return_parameters={"errorMessage": "not connected"},
                    ),
                    push_response_json={"channel": "action"},
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            with pytest.raises(VenusCommandFailedError) as exc_info:
                await c.send_command("System", "instrument.isConnected")

            assert exc_info.value.response.return_code == 1
            assert exc_info.value.response.return_parameters == {"errorMessage": "not connected"}
            assert mock_client.request.await_count == 2  # push + pop

    @pytest.mark.asyncio
    async def test_send_command_failure_error_message_includes_action_name(self):
        """Verify VenusCommandFailedError message includes the action name."""
        from hamilton_venus.exceptions import VenusCommandFailedError

        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        return_status="Error",
                        return_code=1,
                        return_parameters={"errorMessage": "not connected"},
                    ),
                    push_response_json={"channel": "action"},
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            with pytest.raises(VenusCommandFailedError, match=r"instrument\.isConnected failed"):
                await c.send_command("System", "instrument.isConnected")

    @pytest.mark.asyncio
    async def test_send_command_success_returns_response(self):
        """Verify a successful command response is returned normally."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        status="Completed",
                        return_status="Success",
                        return_code=0,
                        return_parameters={"isConnected": True},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            result = await c.send_command("System", "instrument.isConnected")

            assert result is not None
            assert result.success is True
            assert result.return_parameters == {"isConnected": True}

    @pytest.mark.asyncio
    async def test_send_command_passes_parameters(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        return_status="Success",
                        return_code=0,
                        return_parameters={},
                    ),
                    push_response_json={"channel": "action"},
                    pop_responses=[{"hasMessage": False}],
                )
            )
            c._client = mock_client
            await self._setup_signalr_with_empty_pop(c)

            resp = await c.send_command("Channels", "tip.pick", {"count": 8})

            assert resp.success is True
            assert mock_client.request.await_count == 3  # push, empty pop, pop

            push_call = mock_client.request.await_args_list[0]
            push_body = push_call.kwargs["json"]
            assert push_body["channel"] == "action"

            request_envelope = push_body["data"]
            assert request_envelope["category"] == "Channels"
            assert request_envelope["actionName"] == "tip.pick"
            assert request_envelope["parameters"] == {"count": 8}

    @pytest.mark.asyncio
    async def test_send_command_matches_response_by_id(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        return_status="Success",
                        return_code=0,
                        return_parameters={"isConnected": True},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            resp = await c.send_command("System", "instrument.isConnected")

            assert resp.success is True
            assert resp.id == mock_client.queue_message_id

    @pytest.mark.asyncio
    async def test_send_command_accepts_status_only_success_response(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        status="Success",
                        return_parameters={"instrumentName": "ML_STAR"},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            resp = await c.send_command("System", "instrument.init")

            assert resp.success is True
            assert resp.return_status == "Success"
            assert resp.return_parameters == {"instrumentName": "ML_STAR"}

    @pytest.mark.asyncio
    async def test_send_command_uses_custom_timeout(self):
        async with VenusClient(base_url="http://test:42400", command_timeout=10.0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id=mock_client.queue_message_id,
                        status="Completed",
                        return_status="Success",
                        return_code=0,
                        return_parameters={"isConnected": True},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            # Use custom timeout of 30 seconds
            resp = await c.send_command("System", "instrument.isConnected", timeout=30.0)

            assert isinstance(resp, CommandResponse)
            assert resp.success is True

    @pytest.mark.asyncio
    async def test_send_command_times_out_when_no_matching_response_arrives(self):
        async with VenusClient(base_url="http://test:42400", command_timeout=1.0) as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        response_id="different-command-id",
                        status="Completed",
                        return_status="Success",
                        return_code=0,
                        return_parameters={"ignored": True},
                    ),
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            with pytest.raises(VenusTimeoutError):
                await c.send_command("System", "instrument.isConnected", timeout=0.01)

    @pytest.mark.asyncio
    async def test_send_command_raises_method_error_when_push_fails(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False

            def _request_side_effect(method, path, **kwargs):
                if method == "POST" and path == _PUSH_RUN_MESSAGE_PATH:
                    return _mock_response(status_code=500, text="Internal Server Error")
                raise AssertionError(f"Unexpected request: {method} {path}")

            mock_client.request = AsyncMock(side_effect=_request_side_effect)
            c._client = mock_client

            with pytest.raises(VenusApiContractError, match="run-message API"):
                await c.send_command("System", "instrument.isConnected")

    @pytest.mark.asyncio
    async def test_send_command_tolerates_missing_queue_message_id(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                side_effect=_make_send_command_request_side_effect(
                    mock_client,
                    response_data_factory=lambda request_envelope: _build_command_response_data(
                        request_envelope,
                        status="Completed",
                        return_status="Success",
                        return_code=0,
                        return_parameters={"isConnected": True},
                    ),
                    push_response_json={"channel": "action"},
                )
            )
            c._client = mock_client
            await self._setup_signalr(c)

            resp = await c.send_command("System", "instrument.isConnected")

            assert isinstance(resp, CommandResponse)
            assert resp.success is True
            assert resp.return_parameters == {"isConnected": True}


class TestVenusClientDispatcherIntegration:
    @pytest.mark.asyncio
    async def test_notify_run_message_queued_delegates_to_dispatcher(self):
        async with VenusClient(base_url="http://test:42400") as c:
            event = RunMessageQueuedEvent(channel="action-response")
            c._command_dispatcher.notify_run_message_queued = AsyncMock()

            await c.notify_run_message_queued(event)

            c._command_dispatcher.notify_run_message_queued.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_notify_runtime_status_delegates_to_dispatcher(self):
        async with VenusClient(base_url="http://test:42400") as c:
            from unittest.mock import Mock

            c._command_dispatcher._notify_runtime_status = Mock()

            c.notify_runtime_status(ExecutorEvent.ABORTED, "aborted")

            c._command_dispatcher._notify_runtime_status.assert_called_once_with(
                ExecutorEvent.ABORTED,
                "aborted",
            )

    @pytest.mark.asyncio
    async def test_send_command_delegates_default_timeout_to_dispatcher(self):
        async with VenusClient(base_url="http://test:42400", command_timeout=10.0) as c:
            response = CommandResponse(
                category="System",
                actionName="instrument.isConnected",
                parameters={},
                returnStatus="Success",
                returnCode=0,
                returnParameters={"isConnected": True},
            )
            c._command_dispatcher.send_command = AsyncMock(return_value=response)

            result = await c.send_command("System", "instrument.isConnected")

            assert result is response
            c._command_dispatcher.send_command.assert_awaited_once_with(
                "System",
                "instrument.isConnected",
                None,
                None,
                default_timeout=10.0,
            )

    @pytest.mark.asyncio
    async def test_send_command_delegates_custom_timeout_to_dispatcher(self):
        async with VenusClient(base_url="http://test:42400", command_timeout=10.0) as c:
            response = CommandResponse(
                category="Channels",
                actionName="tip.pick",
                parameters={"count": 8},
                returnStatus="Success",
                returnCode=0,
                returnParameters={},
            )
            c._command_dispatcher.send_command = AsyncMock(return_value=response)

            result = await c.send_command("Channels", "tip.pick", {"count": 8}, timeout=30.0)

            assert result is response
            c._command_dispatcher.send_command.assert_awaited_once_with(
                "Channels",
                "tip.pick",
                {"count": 8},
                30.0,
                default_timeout=10.0,
            )


class TestTimeoutBehavior:
    """Tests for timeout behavior in asyncio-based operations."""

    @pytest.mark.asyncio
    async def test_wait_with_timeout_completes_before_timeout(self):
        """Test that _wait_with_timeout returns the result when the awaitable finishes in time."""
        from hamilton_venus._internal._asyncio_compat import _wait_with_timeout

        async def fast_awaitable():
            await asyncio.sleep(0.01)
            return "result"

        result = await _wait_with_timeout(fast_awaitable(), timeout=1.0)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_wait_with_timeout_zero_timeout_raises_timeout_error(self):
        """Test that _wait_with_timeout raises TimeoutError immediately with zero timeout."""
        from hamilton_venus._internal._asyncio_compat import _wait_with_timeout

        async def dummy_awaitable():
            await asyncio.sleep(1)
            return "result"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(dummy_awaitable(), timeout=0)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_negative_timeout_raises_timeout_error(self):
        """Test that _wait_with_timeout raises TimeoutError immediately with negative timeout."""
        from hamilton_venus._internal._asyncio_compat import _wait_with_timeout

        async def dummy_awaitable():
            await asyncio.sleep(1)
            return "result"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(dummy_awaitable(), timeout=-1)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_expires_during_await(self):
        """Test that _wait_with_timeout raises TimeoutError when awaitable takes too long."""
        from hamilton_venus._internal._asyncio_compat import _wait_with_timeout

        async def slow_awaitable():
            await asyncio.sleep(10)
            return "result"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(slow_awaitable(), timeout=0.01)


class TestSubmitErrorRecovery:
    """Tests for submit_error_recovery method."""

    @pytest.mark.asyncio
    async def test_submit_error_recovery_success(self):
        """Test successful error recovery submission."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Recovery action executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01", uuid="test_uuid_123", selected_action_id=1, error_handling_key="test_error"
            )

            result = await c.submit_error_recovery("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data == "Recovery action executed"
            assert result.message == "Success"
            assert result.success is True
            mock_client.request.assert_awaited_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == "POST"
            assert "test_uuid_123" in call_args[0][1]
            assert "/recovery" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_submit_error_recovery_with_inputs(self):
        """Test error recovery submission with inputs."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Recovery with inputs executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01",
                uuid="test_uuid_123",
                selected_action_id=1,
                error_handling_key="test_error",
                inputs=[InputValue(id=1, value="test_value")],
            )

            result = await c.submit_error_recovery("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data == "Recovery with inputs executed"
            mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_error_recovery_minimal(self):
        """Test error recovery submission with minimal fields."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Minimal recovery executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(date="2024-01-01", uuid="test_uuid_123")

            result = await c.submit_error_recovery("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.success is True
            mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_error_recovery_http_error_raises_method_error(self):
        """Test that HTTP error raises MethodError."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=500, text="Internal Server Error"))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01",
                uuid="test_uuid_123",
                selected_action_id=1,
            )

            with pytest.raises(MethodError):
                await c.submit_error_recovery("test_uuid_123", error_recovery)

    @pytest.mark.asyncio
    async def test_submit_error_recovery_accepts_null_data(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": None, "message": None, "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01", uuid="test_uuid_123", selected_action_id=1, error_handling_key="test_error"
            )

            result = await c.submit_error_recovery("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data is None
            assert result.success is True


class TestSubmitErrorAction:
    """Tests for submit_error_action method."""

    @pytest.mark.asyncio
    async def test_submit_error_action_success(self):
        """Test successful error action submission."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Action executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01", uuid="test_uuid_123", selected_action_id=1, error_handling_key="test_error"
            )

            result = await c.submit_error_action("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data == "Action executed"
            assert result.message == "Success"
            assert result.success is True
            mock_client.request.assert_awaited_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == "POST"
            assert "test_uuid_123" in call_args[0][1]
            assert "/action" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_submit_error_action_with_inputs(self):
        """Test error action submission with inputs."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Action with inputs executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01",
                uuid="test_uuid_123",
                selected_action_id=2,
                error_handling_key="test_error",
                inputs=[InputValue(id=1, value="test_value")],
            )

            result = await c.submit_error_action("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data == "Action with inputs executed"
            mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_error_action_minimal(self):
        """Test error action submission with minimal fields."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": "Minimal action executed", "message": "Success", "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(date="2024-01-01", uuid="test_uuid_123")

            result = await c.submit_error_action("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.success is True
            mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_error_action_http_error_raises_method_error(self):
        """Test that HTTP error raises MethodError."""
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=500, text="Internal Server Error"))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01",
                uuid="test_uuid_123",
                selected_action_id=1,
            )

            with pytest.raises(MethodError):
                await c.submit_error_action("test_uuid_123", error_recovery)

    @pytest.mark.asyncio
    async def test_submit_error_action_accepts_null_data(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {"data": None, "message": None, "success": True}
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            error_recovery = ErrorRecovery(
                date="2024-01-01", uuid="test_uuid_123", selected_action_id=1, error_handling_key="test_error"
            )

            result = await c.submit_error_action("test_uuid_123", error_recovery)

            assert isinstance(result, ErrorHandlingResponse)
            assert result.data is None
            assert result.success is True


class TestGetUnhandledErrors:
    @pytest.mark.asyncio
    async def test_get_unhandled_errors_success(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            response_data = {
                "data": [
                    {
                        "uuid": "err-1",
                        "deviceId": 1,
                        "code": "08",
                        "recoveryActions": [],
                    }
                ],
                "message": "ok",
                "success": True,
            }
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, json_data=response_data))
            c._client = mock_client

            result = await c.get_unhandled_errors()

            assert len(result) == 1
            assert isinstance(result[0], ErrorData)
            assert result[0].uuid == "err-1"
            call_args = mock_client.request.call_args
            assert call_args[0][0] == "GET"
            assert call_args[0][1] == "/api/vector/v2/instrument-errors/unhandled"

    @pytest.mark.asyncio
    async def test_get_unhandled_errors_204_returns_empty_list(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=204, text=""))
            c._client = mock_client

            result = await c.get_unhandled_errors()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_unhandled_errors_empty_body_returns_empty_list(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=200, text="   "))
            c._client = mock_client

            result = await c.get_unhandled_errors()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_unhandled_errors_http_error_raises_method_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(return_value=_mock_response(status_code=500, text="Internal Server Error"))
            c._client = mock_client

            with pytest.raises(MethodError):
                await c.get_unhandled_errors()

    @pytest.mark.asyncio
    async def test_get_unhandled_errors_malformed_response_raises_contract_error(self):
        async with VenusClient(base_url="http://test:42400") as c:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client.request = AsyncMock(
                return_value=_mock_response(status_code=200, json_data={"data": "bad", "message": "bad"})
            )
            c._client = mock_client

            with pytest.raises(VenusApiContractError):
                await c.get_unhandled_errors()
