"""Unit tests for _AsyncInstrumentClient."""

import asyncio
import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient, _trace_logger
from hamilton_venus._internal._auth import _AccessTokenProvider
from hamilton_venus._internal._sdk_paths import get_sdk_executor_hsl_path
from hamilton_venus.config import AuthConfig, MethodConfig, SdkConfig, TlsConfig
from hamilton_venus.exceptions import MethodError, VenusTimeoutError
from hamilton_venus.models import (
    CmdResult,
    ConnectionState,
    ErrorData,
    ExecutorEvent,
    InstrumentErrorHandled,
    InstrumentType,
    RunState,
    RuntimeStatusEvent,
)


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400", method=MethodConfig())


@pytest.fixture
def config_with_method():
    return SdkConfig(
        base_url="http://test:42400",
        method=MethodConfig(method_display_name="TestMethod"),
    )


@pytest.fixture
def config_with_auth():
    return SdkConfig(
        base_url="https://identity.example:42400",
        method=MethodConfig(),
        auth=AuthConfig(
            token_url="https://identity.example:42431/api/vector/v1/authorization/token",
            username="venus-user",
            password="venus-pass",
        ),
    )


class TestAsyncStarClientInit:
    def test_creates_venus_and_listener(self, config):
        sc = _AsyncInstrumentClient(config=config)
        assert sc.venus._base_url == "http://test:42400"
        assert sc.connection_state == ConnectionState.DISCONNECTED
        assert sc._auth_provider is None
        assert sc.venus._verify is True

    def test_uses_tls_ca_bundle_for_venus_verify(self):
        sc = _AsyncInstrumentClient(
            config=SdkConfig(base_url="https://test:42400", tls=TlsConfig(ca_bundle_path="")),
        )
        assert sc.venus._verify is True

    def test_uses_configured_tls_ca_bundle_for_venus_verify(self, tmp_path):
        ca_file = tmp_path / "venus-ca.pem"
        ca_file.write_text("fake CA bundle")
        sc = _AsyncInstrumentClient(
            config=SdkConfig(
                base_url="https://test:42400",
                tls=TlsConfig(ca_bundle_path=str(ca_file)),
            ),
        )
        assert sc.venus._verify == str(ca_file)

    def test_creates_auth_provider_when_auth_enabled(self, config_with_auth):
        sc = _AsyncInstrumentClient(config=config_with_auth)
        # Auth provider is created upfront if credentials are available
        assert isinstance(sc._auth_provider, _AccessTokenProvider)
        assert sc._auth_provider._verify is True

    def test_creates_auth_provider_with_tls_ca_bundle_when_configured(self, tmp_path):
        ca_file = tmp_path / "venus-ca.pem"
        ca_file.write_text("fake CA bundle")
        cfg = SdkConfig(
            base_url="https://identity.example:42400",
            auth=AuthConfig(
                token_url="https://identity.example:42431/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            tls=TlsConfig(ca_bundle_path=str(ca_file)),
        )

        sc = _AsyncInstrumentClient(config=cfg)

        assert isinstance(sc._auth_provider, _AccessTokenProvider)
        assert sc._auth_provider._verify == str(ca_file)

    def test_simulate_flag_stored(self, config):
        sc = _AsyncInstrumentClient(config=config, simulate=True)
        assert sc._simulate is True

    def test_simulate_defaults_false(self, config):
        sc = _AsyncInstrumentClient(config=config)
        assert sc._simulate is False

    def test_venus_trace_logging_defaults_false(self, config):
        sc = _AsyncInstrumentClient(config=config)
        assert sc._venus_trace_logging is False

    def test_venus_trace_logging_true_registers_callback(self, config):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        assert sc._venus_trace_logging is True
        assert len(sc._listener._trace_callbacks) > 0
        assert sc._trace_handler is not None
        assert sc._trace_handler in _trace_logger.handlers

    def test_venus_trace_logging_false_no_callback(self, config):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=False)
        assert len(sc._listener._trace_callbacks) == 0
        assert sc._trace_handler is None


class TestAsyncStarClientInjectInstrumentType:
    @pytest.mark.asyncio
    async def test_inject_defaults_to_star(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

        await sc._inject_instrument_type()

        venus.set_method_variables.assert_awaited_once_with(["instrumentType"], ["STAR"])

    @pytest.mark.asyncio
    async def test_inject_sends_correct_value_for_each_type(self, config):
        for instrument in InstrumentType:
            sc = _AsyncInstrumentClient(config=config, instrument_type=instrument)
            venus = cast(Any, sc._venus)
            venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

            await sc._inject_instrument_type()

            venus.set_method_variables.assert_awaited_once_with(["instrumentType"], [instrument.value])

    @pytest.mark.asyncio
    async def test_inject_warns_and_does_not_raise_on_failure(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(side_effect=Exception("HTTP 400"))

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._inject_instrument_type()

        assert any("instrumentType" in r.message for r in caplog.records)


class TestAsyncStarClientInjectIdleCommunication:
    @pytest.mark.asyncio
    async def test_inject_defaults_to_disabled_as_integer_one(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

        await sc._inject_idle_communication()

        venus.set_method_variables.assert_awaited_once_with(["disableIdleCommunication"], [1])

    @pytest.mark.asyncio
    async def test_inject_sends_zero_when_idle_communication_enabled(self):
        config = SdkConfig(base_url="http://test:42400", method=MethodConfig(disable_idle_communication=False))
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

        await sc._inject_idle_communication()

        venus.set_method_variables.assert_awaited_once_with(["disableIdleCommunication"], [0])

    @pytest.mark.asyncio
    async def test_inject_warns_and_does_not_raise_on_failure(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(side_effect=Exception("HTTP 400"))

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._inject_idle_communication()

        assert any("disableIdleCommunication" in r.message for r in caplog.records)


class TestAsyncStarClientStatusIsIdle:
    @pytest.mark.asyncio
    async def test_idle_answered_locally_without_a_request_by_default(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock()

        assert await sc.status_is_idle() is True
        sc._venus._command_dispatcher._command_active = True
        assert await sc.status_is_idle() is False

        venus.peek_channel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idle_read_from_channel_when_idle_communication_enabled(self):
        config = SdkConfig(base_url="http://test:42400", method=MethodConfig(disable_idle_communication=False))
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isIdle": False})

        assert await sc.status_is_idle() is False
        venus.peek_channel.assert_awaited_once_with("idle")


class TestAsyncStarClientInjectStatusCommunication:
    @pytest.mark.asyncio
    async def test_inject_defaults_to_disabled_as_integer_one(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

        await sc._inject_status_communication()

        venus.set_method_variables.assert_awaited_once_with(["disableStatusCommunication"], [1])

    @pytest.mark.asyncio
    async def test_inject_sends_zero_when_status_communication_enabled(self):
        config = SdkConfig(base_url="http://test:42400", method=MethodConfig(disable_status_communication=False))
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))

        await sc._inject_status_communication()

        venus.set_method_variables.assert_awaited_once_with(["disableStatusCommunication"], [0])

    @pytest.mark.asyncio
    async def test_inject_warns_and_does_not_raise_on_failure(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.set_method_variables = AsyncMock(side_effect=Exception("HTTP 400"))

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._inject_status_communication()

        assert any("disableStatusCommunication" in r.message for r in caplog.records)


class TestAsyncStarClientOnRuntimeTrace:
    @pytest.mark.asyncio
    async def test_dict_payload_with_runtime_trace_key(self, config, capfd):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        await sc._on_runtime_trace([{"runtimeTrace": "Step 1 completed"}])
        captured = capfd.readouterr()
        assert "VenusTrace: Step 1 completed" in captured.err

    @pytest.mark.asyncio
    async def test_dict_payload_without_runtime_trace_key(self, config, capfd):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        await sc._on_runtime_trace([{"other": "data"}])
        captured = capfd.readouterr()
        assert "VenusTrace:" in captured.err

    @pytest.mark.asyncio
    async def test_string_payload(self, config, capfd):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        await sc._on_runtime_trace(["some trace string"])
        captured = capfd.readouterr()
        assert "VenusTrace: some trace string" in captured.err

    @pytest.mark.asyncio
    async def test_empty_arguments(self, config, capfd):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        await sc._on_runtime_trace([])
        captured = capfd.readouterr()
        assert "VenusTrace:" in captured.err

    @pytest.mark.asyncio
    async def test_traces_visible_without_debug_logging(self, config, capfd):
        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        logging.getLogger("hamilton_venus").setLevel(logging.WARNING)
        await sc._on_runtime_trace([{"runtimeTrace": "Always visible"}])
        captured = capfd.readouterr()
        assert "VenusTrace: Always visible" in captured.err


class TestAsyncStarClientWaitForEvent:
    @pytest.mark.asyncio
    async def test_wait_for_event_already_received(self, config):
        sc = _AsyncInstrumentClient(config=config)
        evt = RuntimeStatusEvent(executor_event=6, message="")
        await sc._on_runtime_status(evt)

        result = await sc._wait_for_event(ExecutorEvent.RUNNING, timeout=1.0)
        assert result.event == ExecutorEvent.RUNNING

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout(self, config):
        sc = _AsyncInstrumentClient(config=config)
        with pytest.raises(VenusTimeoutError):
            await sc._wait_for_event(ExecutorEvent.RUNNING, timeout=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_event_arrives_later(self, config):
        sc = _AsyncInstrumentClient(config=config)

        async def _fire_event() -> None:
            await asyncio.sleep(0.05)
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=3, message="done"))

        fire_event_task = asyncio.create_task(_fire_event())
        result = await sc._wait_for_event(ExecutorEvent.TERMINATED, timeout=2.0)
        await fire_event_task
        assert result.event == ExecutorEvent.TERMINATED

    @pytest.mark.asyncio
    async def test_wait_for_event_aborts_on_initialize_failed_already_seen(self, config):
        sc = _AsyncInstrumentClient(config=config)
        evt = RuntimeStatusEvent(executor_event=2, message="Method contains syntax errors")
        await sc._on_runtime_status(evt)

        with pytest.raises(MethodError, match="INITIALIZE_FAILED"):
            await sc._wait_for_event(ExecutorEvent.INITIALIZED, timeout=1.0)

    @pytest.mark.asyncio
    async def test_wait_for_event_aborts_on_initialize_failed_arrives_later(self, config):
        sc = _AsyncInstrumentClient(config=config)

        async def _fire_failure() -> None:
            await asyncio.sleep(0.05)
            await sc._on_runtime_status(
                RuntimeStatusEvent(executor_event=2, message="syntax errors"),
            )

        fire_task = asyncio.create_task(_fire_failure())
        with pytest.raises(MethodError, match="INITIALIZE_FAILED"):
            await sc._wait_for_event(ExecutorEvent.INITIALIZED, timeout=2.0)
        await fire_task


class TestAsyncStarClientCallbacks:
    @pytest.mark.asyncio
    async def test_on_runtime_status_unblocks_waiting_callers(self, config):
        sc = _AsyncInstrumentClient(config=config)
        waiter = asyncio.create_task(sc._wait_for_event(ExecutorEvent.INITIALIZED, timeout=1.0))

        await asyncio.sleep(0)
        event = RuntimeStatusEvent(executor_event=1, message="init")
        await sc._on_runtime_status(event)

        result = await waiter
        assert result is event

    @pytest.mark.asyncio
    async def test_on_runtime_status_notifies_dispatcher(self, config):
        sc = _AsyncInstrumentClient(config=config)
        sc._venus.notify_runtime_status = MagicMock()
        event = RuntimeStatusEvent(executor_event=4, message="aborted")

        await sc._on_runtime_status(event)

        sc._venus.notify_runtime_status.assert_called_once_with(
            ExecutorEvent.ABORTED,
            "aborted",
        )

    @pytest.mark.asyncio
    async def test_on_runtime_status_paused_logs_warning(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        event = RuntimeStatusEvent(executor_event=ExecutorEvent.PAUSED, message="")

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._on_runtime_status(event)

        assert any("paused externally" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_on_runtime_status_resumed_logs_warning(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        paused_event = RuntimeStatusEvent(executor_event=ExecutorEvent.PAUSED, message="")
        resumed_event = RuntimeStatusEvent(executor_event=ExecutorEvent.RUNNING, message="")

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._on_runtime_status(paused_event)
            await sc._on_runtime_status(resumed_event)

        messages = [r.message for r in caplog.records]
        assert any("paused externally" in m for m in messages)
        assert any("resumed" in m for m in messages)

    @pytest.mark.asyncio
    async def test_on_runtime_status_running_without_pause_does_not_log_resumed(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        event = RuntimeStatusEvent(executor_event=ExecutorEvent.RUNNING, message="")

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            await sc._on_runtime_status(event)

        assert not any("resumed" in r.message for r in caplog.records)


class TestAsyncStarClientStartWithMethod:
    @pytest.fixture(autouse=True)
    def _mock_ready_channel(self, monkeypatch):
        monkeypatch.setattr(
            _AsyncInstrumentClient,
            "_wait_for_ready",
            AsyncMock(),
        )
        monkeypatch.setattr(
            _AsyncInstrumentClient,
            "_reset_run_message_channels",
            AsyncMock(return_value=None),
        )

    @pytest.mark.asyncio
    async def test_start_loads_and_starts_method(self, config_with_method):
        sc = _AsyncInstrumentClient(config=config_with_method, simulate=True)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        load_called_with = {}

        async def fake_load(path, simulate=False, parent_window_handle=0):
            load_called_with["path"] = path
            load_called_with["simulate"] = simulate
            load_called_with["parent_window_handle"] = parent_window_handle
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=1, message="initialized"))
            return CmdResult(result=True, message="loaded")

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.load_method = fake_load
        venus.start_method = AsyncMock(return_value=CmdResult(result=True, message="started"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.send_command = AsyncMock(return_value=MagicMock())
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus._command_dispatcher.start_communication_worker = AsyncMock()

        await sc.start(auto_connect=True)

        assert load_called_with["path"] == str(get_sdk_executor_hsl_path())
        assert load_called_with["simulate"] is True
        assert load_called_with["parent_window_handle"] == 0
        venus.start_method.assert_awaited_once()
        venus.register_error_handler.assert_awaited_once_with(sc._error_handler_key)
        venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.connect",
            parameters={"initialize": False},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("simulate", [True, False])
    async def test_start_sets_system_simulation_before_load(self, config_with_method, simulate):
        sc = _AsyncInstrumentClient(config=config_with_method, simulate=simulate)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        calls: list[tuple[str, bool]] = []

        async def fake_set_simulation(value):
            calls.append(("set_simulation", value))

        async def fake_load(path, simulate=False, parent_window_handle=0):
            calls.append(("load_method", simulate))
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=1, message="initialized"))
            return CmdResult(result=True, message="loaded")

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = fake_set_simulation
        venus.load_method = fake_load
        venus.start_method = AsyncMock(return_value=CmdResult(result=True, message="started"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.send_command = AsyncMock(return_value=MagicMock())
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus._command_dispatcher.start_communication_worker = AsyncMock()

        await sc.start(auto_connect=False)

        assert calls == [("set_simulation", simulate), ("load_method", simulate)]

    @pytest.mark.asyncio
    async def test_start_defaults_auto_connect_to_true(self, config_with_method):
        sc = _AsyncInstrumentClient(config=config_with_method)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        async def fake_load(path, simulate=False, parent_window_handle=0):
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=1, message="initialized"))
            return CmdResult(result=True, message="loaded")

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.load_method = fake_load
        venus.start_method = AsyncMock(return_value=CmdResult(result=True, message="started"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.send_command = AsyncMock(return_value=MagicMock())
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus._command_dispatcher.start_communication_worker = AsyncMock()

        await sc.start()

        venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.connect",
            parameters={"initialize": False},
        )

    @pytest.mark.asyncio
    async def test_start_can_disable_auto_connect(self, config_with_method):
        sc = _AsyncInstrumentClient(config=config_with_method)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        async def fake_load(path, simulate=False, parent_window_handle=0):
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=1, message="initialized"))
            return CmdResult(result=True, message="loaded")

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.load_method = fake_load
        venus.start_method = AsyncMock(return_value=CmdResult(result=True, message="started"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.send_command = AsyncMock()
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus._command_dispatcher.start_communication_worker = AsyncMock()

        await sc.start(auto_connect=False)

        venus.send_command.assert_not_awaited()
        venus.register_error_handler.assert_awaited_once_with(sc._error_handler_key)


class TestAsyncStarClientStartTimeout:
    @pytest.fixture(autouse=True)
    def _mock_ready_channel(self, monkeypatch):
        monkeypatch.setattr(
            _AsyncInstrumentClient,
            "_wait_for_ready",
            AsyncMock(),
        )
        monkeypatch.setattr(
            _AsyncInstrumentClient,
            "_reset_run_message_channels",
            AsyncMock(return_value=None),
        )

    @pytest.mark.asyncio
    async def test_start_times_out_when_listener_fails_to_connect(self, config):
        config.timeouts.startup = 0.1
        sc = _AsyncInstrumentClient(config=config)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener._state = ConnectionState.DISCONNECTED
        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus._command_dispatcher.start_communication_worker = AsyncMock()
        venus._command_dispatcher.stop_communication_worker = AsyncMock()

        with pytest.raises(VenusTimeoutError, match="SignalR connection did not reach CONNECTED"):
            await sc.start()

        venus._command_dispatcher.stop_communication_worker.assert_awaited_once()
        listener.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_times_out_during_method_initialization(self, config_with_method):
        config_with_method.timeouts.startup = 0.1
        sc = _AsyncInstrumentClient(config=config_with_method)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path
        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.unregister_error_handler = AsyncMock()
        venus.load_method = AsyncMock(return_value=CmdResult(result=True, message="loaded"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus._command_dispatcher.start_communication_worker = AsyncMock()
        venus._command_dispatcher.stop_communication_worker = AsyncMock()

        with pytest.raises(VenusTimeoutError):
            await sc.start()

        venus.unregister_error_handler.assert_awaited_once_with(sc._error_handler_key)
        venus._command_dispatcher.stop_communication_worker.assert_awaited_once()
        listener.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_unreg_not_attempted_when_registration_failed(self, config_with_method):
        config_with_method.timeouts.startup = 0.1
        sc = _AsyncInstrumentClient(config=config_with_method)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener.stop = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path
        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock(side_effect=Exception("register failed"))
        venus.set_simulation = AsyncMock()
        venus.unregister_error_handler = AsyncMock()
        venus.load_method = AsyncMock(return_value=CmdResult(result=True, message="loaded"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus._command_dispatcher.start_communication_worker = AsyncMock()
        venus._command_dispatcher.stop_communication_worker = AsyncMock()

        with pytest.raises(VenusTimeoutError):
            await sc.start()

        venus.unregister_error_handler.assert_not_awaited()


class TestAsyncStarClientStaleAbortReset:
    """After _cleanup_stale_method, any ABORTED/TERMINATED event received during
    the stale cleanup must not poison the new session's commands."""

    @pytest.fixture(autouse=True)
    def _mock_ready_channel(self, monkeypatch):
        monkeypatch.setattr(_AsyncInstrumentClient, "_wait_for_ready", AsyncMock())
        monkeypatch.setattr(_AsyncInstrumentClient, "_reset_run_message_channels", AsyncMock(return_value=None))

    @pytest.mark.asyncio
    async def test_start_resets_abort_state_after_stale_cleanup(self, config_with_method):
        sc = _AsyncInstrumentClient(config=config_with_method, simulate=True)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        async def fake_load(path, simulate=False, parent_window_handle=0):
            await sc._on_runtime_status(
                RuntimeStatusEvent(executor_event=ExecutorEvent.INITIALIZED, message="initialized")
            )
            return CmdResult(result=True, message="loaded")

        # Simulate _cleanup_stale_method setting the abort event (e.g. a late
        # ABORTED SignalR event arrived while waiting for TERMINATED to time out).
        async def fake_cleanup_stale_method():
            sc._venus._command_dispatcher._notify_runtime_status(ExecutorEvent.ABORTED, "stale abort")

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.load_method = fake_load
        venus.start_method = AsyncMock(return_value=CmdResult(result=True, message="started"))
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.send_command = AsyncMock(return_value=MagicMock())
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus._command_dispatcher.start_communication_worker = AsyncMock()

        sc._cleanup_stale_method = fake_cleanup_stale_method

        # Must not raise VenusCommandAbortedError even though the abort event
        # was set during the simulated stale cleanup.
        await sc.start(auto_connect=False)

        assert not sc._venus._command_dispatcher._abort_event.is_set()


@patch("hamilton_venus._internal._async_instrument_client._SignalRListener")
@patch("hamilton_venus._internal._async_instrument_client.VenusClient")
class TestAsyncStarClientStopBeforeStart:
    @pytest.mark.asyncio
    async def test_stop_before_start_is_safe(self, mock_venus, mock_listener, config):
        # Mock listener and venus to avoid expensive real initialization/teardown
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        # Configure callback registration methods to return None (not coroutines)
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config)

        await sc.stop()

        mock_listener_instance.stop.assert_awaited_once()
        mock_venus_instance.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_terminates_running_method_with_instrument_category(
        self, mock_venus, mock_listener, config
    ):
        """stop() must submit status.terminate under category='Instrument' to
        match the public instrument_terminate() API and command catalog."""
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance.get_run_state = AsyncMock(return_value=RunState.RUNNING)
        mock_venus_instance.send_command = AsyncMock(return_value=MagicMock())
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config)
        cast(Any, sc)._wait_for_event = AsyncMock()

        await sc.stop()

        mock_venus_instance.send_command.assert_any_call(
            category="Instrument",
            action_name="status.terminate",
            parameters={},
        )


class TestWaitForReady:
    @pytest.mark.asyncio
    async def test_wait_for_ready_returns_when_ready(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isReady": True})

        await sc._wait_for_ready()

        venus.peek_channel.assert_awaited_once_with("ready")

    @pytest.mark.asyncio
    async def test_wait_for_ready_polls_until_ready(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(
            side_effect=[{"isReady": False}, {"isReady": False}, {"isReady": True}],
        )

        await sc._wait_for_ready()

        assert venus.peek_channel.await_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_ready_times_out(self, config):
        config.timeouts.startup = 0.15
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isReady": False})

        with pytest.raises(VenusTimeoutError, match="ready"):
            await sc._wait_for_ready()

    @pytest.mark.asyncio
    async def test_wait_for_ready_treats_none_channel_as_not_ready(self, config):
        config.timeouts.startup = 0.3
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(
            side_effect=[None, None, {"isReady": True}],
        )

        await sc._wait_for_ready()

        assert venus.peek_channel.await_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_ready_treats_missing_key_as_not_ready(self, config):
        config.timeouts.startup = 0.3
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(
            side_effect=[{}, {"other": 1}, {"isReady": True}],
        )

        await sc._wait_for_ready()

        assert venus.peek_channel.await_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_ready_times_out_when_channel_stays_none(self, config):
        config.timeouts.startup = 0.15
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value=None)

        with pytest.raises(VenusTimeoutError, match="ready"):
            await sc._wait_for_ready()

    @pytest.mark.asyncio
    async def test_wait_for_ready_raises_on_abort_event_already_seen(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isReady": False})
        await sc._on_runtime_status(
            RuntimeStatusEvent(executor_event=ExecutorEvent.ABORTING.value, message="syntax error 1302"),
        )

        with pytest.raises(MethodError, match=r"ABORTING.*syntax error 1302"):
            await sc._wait_for_ready()

    @pytest.mark.asyncio
    async def test_wait_for_ready_raises_on_aborted_event(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isReady": False})
        await sc._on_runtime_status(
            RuntimeStatusEvent(executor_event=ExecutorEvent.ABORTED.value, message="method aborted"),
        )

        with pytest.raises(MethodError, match=r"ABORTED.*method aborted"):
            await sc._wait_for_ready()

    @pytest.mark.asyncio
    async def test_wait_for_ready_raises_on_terminated_event(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock(return_value={"isReady": False})
        await sc._on_runtime_status(
            RuntimeStatusEvent(executor_event=ExecutorEvent.TERMINATED.value, message="terminated"),
        )

        with pytest.raises(MethodError, match=r"TERMINATED.*terminated"):
            await sc._wait_for_ready()

    @pytest.mark.asyncio
    async def test_wait_for_ready_abort_arrives_during_polling(self, config):
        config.timeouts.startup = 5.0
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)

        call_count = 0

        async def fake_peek(channel):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                await sc._on_runtime_status(
                    RuntimeStatusEvent(
                        executor_event=ExecutorEvent.ABORTING.value,
                        message="HSL compile error",
                    ),
                )
            return {"isReady": False}

        venus.peek_channel = fake_peek

        with pytest.raises(MethodError, match=r"ABORTING.*HSL compile error"):
            await sc._wait_for_ready()


class TestResetRunMessageChannels:
    @pytest.mark.asyncio
    async def test_deletes_the_channels_an_earlier_run_may_have_left(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.delete_channel = AsyncMock()
        venus.peek_channel_message = AsyncMock(return_value=None)

        assert await sc._reset_run_message_channels() is None

        assert [c.args[0] for c in venus.delete_channel.await_args_list] == ["ready", "action", "action-response"]
        venus.peek_channel_message.assert_awaited_once_with("ready")

    @pytest.mark.asyncio
    async def test_returns_the_id_of_a_ready_that_could_not_be_cleared(self, config, caplog):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.delete_channel = AsyncMock(side_effect=Exception("405 Method Not Allowed"))
        venus.peek_channel_message = AsyncMock(return_value=("stale-id", {"isReady": True}))

        with caplog.at_level(logging.WARNING, logger="hamilton_venus._internal._async_instrument_client"):
            assert await sc._reset_run_message_channels() == "stale-id"

        assert venus.delete_channel.await_count == 3  # a failed delete does not stop the others
        assert any("earlier run" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "leftover",
        [("id", {"isReady": False}), ("", {"isReady": True}), ("id", {})],
        ids=["not-ready", "no-id", "no-flag"],
    )
    async def test_nothing_to_ignore(self, config, leftover):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.delete_channel = AsyncMock()
        venus.peek_channel_message = AsyncMock(return_value=leftover)

        assert await sc._reset_run_message_channels() is None

    @pytest.mark.asyncio
    async def test_never_raises(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.delete_channel = AsyncMock(side_effect=Exception("down"))
        venus.peek_channel_message = AsyncMock(side_effect=Exception("down"))

        assert await sc._reset_run_message_channels() is None


class TestWaitForReadyIgnoresStaleMessage:
    @pytest.mark.asyncio
    async def test_waits_past_the_stale_ready_for_a_new_one(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel = AsyncMock()
        venus.peek_channel_message = AsyncMock(
            side_effect=[
                ("stale-id", {"isReady": True}),
                ("stale-id", {"isReady": True}),
                None,  # the executor cleared its channels
                ("new-id", {"isReady": True}),
            ]
        )

        await sc._wait_for_ready(stale_message_id="stale-id")

        assert venus.peek_channel_message.await_count == 4
        venus.peek_channel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_times_out_if_only_the_stale_ready_is_there(self, config):
        config.timeouts.startup = 0.15
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.peek_channel_message = AsyncMock(return_value=("stale-id", {"isReady": True}))

        with pytest.raises(VenusTimeoutError, match="ready"):
            await sc._wait_for_ready(stale_message_id="stale-id")


class TestStartIgnoresReadyFromEarlierRun:
    """A run that ended without clearing 'ready' must not let the next run send its first
    command before the executor has started: the executor clears its channels at start-up
    (InitializeStatusChannels), so that command would be lost and both sides would wait.
    """

    def _client(self, config_with_method, *, delete_works: bool, executor_delay: float):
        sc = _AsyncInstrumentClient(config=config_with_method, simulate=True)
        listener = cast(Any, sc._listener)
        venus = cast(Any, sc._venus)
        listener.start = AsyncMock()
        listener._state = ConnectionState.CONNECTED
        sc._method_file_manager.prepare = lambda path, name: path

        calls: list[str] = []
        queue: dict[str, tuple[str, dict]] = {"ready": ("stale-id", {"isReady": True})}  # left by an earlier run

        async def fake_load(path, simulate=False, parent_window_handle=0):
            await sc._on_runtime_status(RuntimeStatusEvent(executor_event=1, message="initialized"))
            return CmdResult(result=True, message="loaded")

        async def delete_channel(channel):
            calls.append(f"delete {channel}")
            if not delete_works:
                raise Exception("delete not supported")
            queue.pop(channel, None)

        async def executor_starts():
            # The executor clears its channels, then posts its own 'ready'.
            await asyncio.sleep(executor_delay)
            queue.pop("ready", None)
            calls.append("executor cleared channels")
            queue["ready"] = ("new-id", {"isReady": True})

        async def start_method():
            calls.append("start_method")
            asyncio.get_running_loop().create_task(executor_starts())
            return CmdResult(result=True, message="started")

        async def peek_channel_message(channel):
            return queue.get(channel)

        async def peek_channel(channel):
            message = queue.get(channel)
            return None if message is None else message[1]

        venus.get_authentication_mode = AsyncMock(return_value="None")
        venus.register_error_handler = AsyncMock()
        venus.set_simulation = AsyncMock()
        venus.load_method = fake_load
        venus.start_method = start_method
        venus.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        venus.set_method_variables = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus.delete_channel = delete_channel
        venus.peek_channel_message = peek_channel_message
        venus.peek_channel = peek_channel
        venus._command_dispatcher.start_communication_worker = AsyncMock()
        return sc, calls

    @pytest.mark.asyncio
    async def test_channels_are_cleared_before_the_method_starts(self, config_with_method):
        sc, calls = self._client(config_with_method, delete_works=True, executor_delay=0.6)

        await sc.start(auto_connect=False)

        assert calls[:4] == ["delete ready", "delete action", "delete action-response", "start_method"]
        # Ready only once the executor has cleared its channels and posted its own.
        assert calls[-1] == "executor cleared channels"

    @pytest.mark.asyncio
    async def test_stale_ready_that_cannot_be_deleted_is_not_mistaken_for_this_run(self, config_with_method):
        # The stuck scenario: the executor needs longer than the old 0.5 s grace period.
        sc, calls = self._client(config_with_method, delete_works=False, executor_delay=0.6)

        await sc.start(auto_connect=False)

        assert "executor cleared channels" in calls  # start() did not return on the stale 'ready'


class TestErrorHandlerKey:
    def test_error_handler_key_is_static(self, config):
        sc = _AsyncInstrumentClient(config=config)
        assert sc._error_handler_key == "hamiltonvenussdk"

    def test_error_handler_key_is_consistent_across_instances(self, config):
        sc1 = _AsyncInstrumentClient(config=config)
        sc2 = _AsyncInstrumentClient(config=config)
        assert sc1._error_handler_key == sc2._error_handler_key
        assert sc1._error_handler_key == "hamiltonvenussdk"


class TestInstrumentErrorCallbacks:
    @pytest.mark.asyncio
    async def test_on_instrument_error_does_not_raise(self, config):
        sc = _AsyncInstrumentClient(config=config)
        venus = cast(Any, sc._venus)
        venus.submit_error_recovery = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus.submit_error_action = AsyncMock(return_value=CmdResult(result=True, message="ok"))
        venus.get_unhandled_errors = AsyncMock(return_value=[])
        error = ErrorData(uuid="err-1", device_id=42)
        await sc._on_instrument_error(error)

    @pytest.mark.asyncio
    async def test_on_instrument_error_notification_does_not_raise(self, config, monkeypatch):
        monkeypatch.setattr(
            "hamilton_venus._internal._error_profile_resolver.asyncio.sleep",
            AsyncMock(),
        )
        sc = _AsyncInstrumentClient(config=config)
        await sc._on_instrument_error_notification("some notification")

    @pytest.mark.asyncio
    async def test_on_device_error_handled_does_not_raise(self, config):
        sc = _AsyncInstrumentClient(config=config)
        handled = InstrumentErrorHandled(uuid="err-1", recovery_action="Abort")
        await sc._on_device_error_handled(handled)


class TestErrorHandlerWiring:
    def test_listener_callbacks_wired(self, config):
        sc = _AsyncInstrumentClient(config=config)
        listener = sc._listener
        assert sc._on_instrument_error in listener._instrument_error_callbacks
        assert sc._on_instrument_error_notification in listener._instrument_error_notification_callbacks
        assert sc._on_device_error_handled in listener._device_error_handled_callbacks

    @pytest.mark.asyncio
    @patch("hamilton_venus._internal._async_instrument_client._SignalRListener")
    @patch("hamilton_venus._internal._async_instrument_client.VenusClient")
    async def test_stop_unregisters_error_handler(self, mock_venus, mock_listener, config_with_method):
        # Mock listener and venus to avoid expensive real initialization/teardown
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        # Configure callback registration methods to return None (not coroutines)
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        mock_venus_instance.unregister_error_handler = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config_with_method)
        # Simulate that the error handler was registered during start()
        sc._error_handler_registered = True

        await sc.stop()

        mock_venus_instance.unregister_error_handler.assert_awaited_once_with(sc._error_handler_key)

    @pytest.mark.asyncio
    @patch("hamilton_venus._internal._async_instrument_client._SignalRListener")
    @patch("hamilton_venus._internal._async_instrument_client.VenusClient")
    async def test_stop_skips_unregister_when_handler_not_registered(
        self, mock_venus, mock_listener, config_with_method
    ):
        # Mock listener and venus to avoid expensive real initialization/teardown
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        # Configure callback registration methods to return None (not coroutines)
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.get_run_state = AsyncMock(return_value=RunState.NOT_INITIALIZED)
        mock_venus_instance.unregister_error_handler = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config_with_method)
        # Handler was never registered (stop called without start or after registration failed)
        assert sc._error_handler_registered is False

        await sc.stop()

        # Verify unregister was NOT called since handler was never registered
        mock_venus_instance.unregister_error_handler.assert_not_awaited()


@patch("hamilton_venus._internal._async_instrument_client._SignalRListener")
@patch("hamilton_venus._internal._async_instrument_client.VenusClient")
class TestTraceHandlerCleanup:
    @pytest.mark.asyncio
    async def test_stop_removes_trace_handler(self, mock_venus, mock_listener, config):
        # Mock listener and venus to avoid expensive real initialization/teardown
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        # Configure callback registration methods to return None (not coroutines)
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener_instance.on_runtime_trace = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=True)
        original_handler = sc._trace_handler
        assert original_handler in _trace_logger.handlers

        await sc.stop()

        assert sc._trace_handler is None
        assert original_handler not in _trace_logger.handlers

    @pytest.mark.asyncio
    async def test_stop_without_trace_logging_is_safe(self, mock_venus, mock_listener, config):
        # Mock listener and venus to avoid expensive real initialization/teardown
        mock_listener_instance = MagicMock()
        mock_listener_instance.stop = AsyncMock()
        # Configure callback registration methods to return None (not coroutines)
        mock_listener_instance.on_runtime_status = MagicMock(return_value=None)
        mock_listener_instance.on_progress = MagicMock(return_value=None)
        mock_listener_instance.on_run_message_queued = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error = MagicMock(return_value=None)
        mock_listener_instance.on_instrument_error_notification = MagicMock(return_value=None)
        mock_listener_instance.on_device_error_handled = MagicMock(return_value=None)
        mock_listener.return_value = mock_listener_instance

        mock_venus_instance = AsyncMock()
        mock_venus_instance.aclose = AsyncMock()
        mock_venus_instance._command_dispatcher = MagicMock()
        mock_venus_instance._command_dispatcher.stop_communication_worker = AsyncMock()
        mock_venus.return_value = mock_venus_instance

        sc = _AsyncInstrumentClient(config=config, venus_trace_logging=False)

        await sc.stop()

        assert sc._trace_handler is None
