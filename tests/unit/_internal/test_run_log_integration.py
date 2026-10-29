"""Integration tests for StarClient run log integration."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hamilton_venus._internal._run_log import RunLog
from hamilton_venus._internal._run_message_command_dispatcher import _RunMessageCommandDispatcher
from hamilton_venus.config import RunLogConfig, SdkConfig
from hamilton_venus.models import RunMessageQueuedEvent


@pytest.fixture()
def config() -> SdkConfig:
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture()
def mock_async_star_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        instance = cls.return_value
        instance.start = AsyncMock()
        instance.stop = AsyncMock()
        instance.connection_state = "Connected"
        yield cls


def _read_final_json(directory: Path) -> dict:
    json_files = list(directory.glob("*.json"))
    # Exclude .meta.json
    json_files = [f for f in json_files if not f.name.endswith(".meta.json")]
    assert len(json_files) == 1, f"Expected 1 .json file, found {len(json_files)}: {json_files}"
    return json.loads(json_files[0].read_text(encoding="utf-8"))


class TestRunLogIntegration:
    def test_run_log_true_enables_end_to_end(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        # run_log=True with no output_dir: the log goes to the LogFiles directory.
        monkeypatch.setattr(
            "hamilton_venus._internal._com_trace.registry_logfiles_dir", lambda: str(tmp_path)
        )

        with StarClient(config, run_log=True) as star:
            assert isinstance(star._run_log_config, RunLogConfig)
            assert star._run_log_config.enabled is True
            assert isinstance(star._run_log, RunLog)
            assert mock_async_star_class.call_args.kwargs["run_log"] is star._run_log

        json_files = [f for f in tmp_path.glob("*.json") if not f.name.endswith(".meta.json")]
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert "schema_version" in data
        assert "log" in data
        sources = [e["source"] for e in data["log"]]
        assert sources[0] == "SDK"
        assert sources[-1] == "SDK"

    def test_run_log_true_creates_json_file(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        run_log_config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=run_log_config):
            pass

        data = _read_final_json(tmp_path)
        assert "schema_version" in data
        assert "log" in data

    def test_run_log_false_produces_no_file(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        with StarClient(config, run_log=False):
            pass

        assert list(tmp_path.glob("*.json")) == []
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_run_log_config_instance_accepted(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=rlc):
            pass

        json_files = [f for f in tmp_path.glob("*.json") if not f.name.endswith(".meta.json")]
        assert len(json_files) == 1

    def test_session_start_entry_present(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=rlc, simulate=True):
            pass

        data = _read_final_json(tmp_path)
        first = data["log"][0]
        assert first["source"] == "SDK"
        assert first["type"] == "session_start"
        assert "sdk_version" in first["payload"]
        assert "script_name" in first["payload"]
        assert first["payload"]["simulate"] is True

    def test_session_end_entry_present(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=rlc):
            pass

        data = _read_final_json(tmp_path)
        last = data["log"][-1]
        assert last["source"] == "SDK"
        assert last["type"] == "session_end"
        assert last["payload"]["reason"] == "normal"
        assert "duration_seconds" in last["payload"]

    def test_session_end_reason_error_on_exception(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with pytest.raises(ValueError, match="boom"), StarClient(config, run_log=rlc):
            raise ValueError("boom")

        data = _read_final_json(tmp_path)
        last = data["log"][-1]
        assert last["payload"]["reason"] == "error"
        assert last["payload"]["error_type"] == "ValueError"
        assert "boom" in last["payload"]["error_message"]

    def test_jsonl_temp_removed_after_finalize(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=rlc):
            pass

        assert list(tmp_path.glob("*.jsonl")) == []
        assert list(tmp_path.glob("*.meta.json")) == []
        json_files = [f for f in tmp_path.glob("*.json") if not f.name.endswith(".meta.json")]
        assert len(json_files) == 1

    def test_run_log_exported_from_package(self) -> None:
        from hamilton_venus import RunLogConfig  # noqa: F401

    def test_console_proxy_disabled_when_console_capture_false(
        self,
        config: SdkConfig,
        mock_async_star_class,
        tmp_path: Path,
    ) -> None:
        from hamilton_venus.star_client import StarClient

        original_print = builtins.print
        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path), console_capture=False)
        with StarClient(config, run_log=rlc):
            assert builtins.print is original_print


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    content = json.dumps(json_data).encode() if json_data is not None else b""
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"} if json_data is not None else {},
        request=httpx.Request("GET", "http://testserver"),
    )


class TestFullCommandRoundtripLogged:
    @pytest.mark.asyncio
    async def test_full_command_roundtrip_logged(self, tmp_path: Path) -> None:
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        run_log = RunLog(config, "roundtrip-test", "0.4.0")

        push_path = "/api/vector/v3/run-messages"
        pop_path = "/api/vector/v3/run-messages/action-response/pop"

        async def mock_request(method, path, *, json=None, error_prefix=""):
            if method == "POST" and path == push_path:
                return _mock_response(200, {"messageId": "cmd-abc"})
            if method == "POST" and path == pop_path:
                return _mock_response(
                    200,
                    {
                        "hasMessage": True,
                        "data": {
                            "actionId": "cmd-abc",
                            "category": "Channels",
                            "actionName": "aspirate",
                            "parameters": {"volume": 50.0},
                            "returnCode": 0,
                            "returnParameters": {"aspiratedVolume": 50.0},
                            "returnStatus": "Success",
                        },
                    },
                )
            return _mock_response(200, {})

        dispatcher = _RunMessageCommandDispatcher(mock_request)
        dispatcher._run_log = run_log

        await dispatcher.notify_run_message_queued(
            RunMessageQueuedEvent(channel="action-response"),
        )
        await dispatcher.send_command(
            "Channels",
            "aspirate",
            {"volume": 50.0},
            default_timeout=5.0,
        )

        run_log.close()
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]

        cmd_requests = [e for e in entries if e["type"] == "command_request"]
        cmd_responses = [e for e in entries if e["type"] == "command_response"]
        assert len(cmd_requests) == 1
        assert len(cmd_responses) == 1
        assert cmd_requests[0]["payload"]["command_id"] == cmd_responses[0]["payload"]["id"]
        assert cmd_requests[0]["payload"]["action_name"] == "aspirate"
        assert cmd_responses[0]["payload"]["returnStatus"] == "Success"


class TestAsyncStarClientRunLogWiring:
    """Verify _AsyncInstrumentClient correctly wires RunLog to sub-components."""

    def test_run_log_wired_to_venus_client(self, tmp_path, config):
        run_log_config = RunLogConfig(enabled=True, include_http=True, output_dir=str(tmp_path))
        run_log = RunLog(run_log_config, "wire-test", "0.4.0")

        from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

        client = _AsyncInstrumentClient(
            config,
            run_log=run_log,
            run_log_config=run_log_config,
        )

        assert client._venus._run_log is run_log
        assert client._venus._run_log_config is run_log_config
        assert client._venus._command_dispatcher._run_log is run_log
        assert client._listener._run_log is run_log
        assert client._listener._run_log_config is run_log_config

        run_log.close()

    def test_no_run_log_leaves_defaults(self, config):
        from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

        client = _AsyncInstrumentClient(config)

        assert client._venus._run_log is None
        assert client._venus._run_log_config == RunLogConfig()

    def test_run_log_false_leaves_defaults(self, config, mock_async_star_class):
        """Explicitly passing run_log=False to StarClient should result in disabled run log.

        According to the design (section 7.3), both None and False should result in
        disabled run logging.
        """
        from hamilton_venus.star_client import StarClient

        with StarClient(config, run_log=False) as star:
            # StarClient should not have created a RunLog instance
            assert star._run_log is None
            # And should be using the default (disabled) config
            assert star._run_log_config.enabled is False
