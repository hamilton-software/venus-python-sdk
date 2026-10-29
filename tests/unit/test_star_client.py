"""Unit tests for StarClient."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus._internal._base_sync_client import _LifecycleState
from hamilton_venus._internal._run_log import RunLog
from hamilton_venus.config import RunLogConfig, SdkConfig, StarClientConfig
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.exceptions import VenusCommandAbortedError
from hamilton_venus.models import CommandResponse, ConnectionState, InstrumentType, RecoveryAction
from hamilton_venus.star_client import StarClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        star = MagicMock()
        star.start = AsyncMock()
        star.stop = AsyncMock()
        star.connection_state = ConnectionState.CONNECTED

        venus = MagicMock()
        venus.send_command = AsyncMock()
        venus._command_timeout = 60.0

        def override_command_timeout(timeout: float):
            @contextmanager
            def _timeout_context():
                old_timeout = venus._command_timeout
                venus._command_timeout = timeout
                try:
                    yield
                finally:
                    venus._command_timeout = old_timeout

            return _timeout_context()

        star.override_command_timeout = MagicMock(side_effect=override_command_timeout)
        star.venus = venus

        cls.return_value = star
        yield cls


class TestStarClientLifecycle:
    def test_start_stop(self, config, mock_async_star_class):
        client = StarClient(config)
        assert client._state == _LifecycleState.STOPPED

        client.start()
        star = mock_async_star_class.return_value
        star.start.assert_awaited_once_with(auto_connect=True, deck_name=None)
        assert client._loop is not None
        assert client._thread is not None
        assert client._thread.is_alive()
        assert client._state == _LifecycleState.STARTED

        client.stop()
        star.stop.assert_awaited_once()
        assert client._loop is None
        assert client._thread is None
        assert client._state == _LifecycleState.STOPPED

    def test_context_manager(self, config, mock_async_star_class):
        with StarClient(config) as client:
            star = mock_async_star_class.return_value
            star.start.assert_awaited_once_with(auto_connect=True, deck_name=None)
            assert client._thread is not None
        star.stop.assert_awaited_once()
        assert client._loop is None

    def test_stop_idempotent(self, config, mock_async_star_class):
        client = StarClient(config)
        client.start()
        client.stop()
        client.stop()

    def test_start_twice_raises_and_leaves_first_start_active(self, config, mock_async_star_class):
        client = StarClient(config)
        client.start()

        with pytest.raises(RuntimeError, match="Client is already started"):
            client.start()

        star = mock_async_star_class.return_value
        star.start.assert_awaited_once_with(auto_connect=True, deck_name=None)

        client.stop()

    def test_start_failure_rolls_back_sync_resources(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.start = AsyncMock(side_effect=RuntimeError("start failed"))

        client = StarClient(config)
        with pytest.raises(RuntimeError, match="start failed"):
            client.start()

        star.stop.assert_awaited_once()
        assert client._loop is None
        assert client._thread is None
        assert client._state == _LifecycleState.STOPPED

    def test_stop_before_start_is_noop(self, config, mock_async_star_class):
        client = StarClient(config)

        client.stop()

        star = mock_async_star_class.return_value
        star.stop.assert_not_called()
        assert client._state == _LifecycleState.STOPPED

    def test_start_uses_constructor_auto_connect_when_disabled(self, config, mock_async_star_class):
        client = StarClient(config, auto_connect=False)

        client.start()

        mock_async_star_class.return_value.start.assert_awaited_once_with(auto_connect=False, deck_name=None)
        client.stop()

    def test_start_uses_config_auto_connect_default_when_not_provided(self, config, mock_async_star_class):
        config.star_client.auto_connect = False
        client = StarClient(config)

        client.start()

        mock_async_star_class.return_value.start.assert_awaited_once_with(auto_connect=False, deck_name=None)
        client.stop()

    def test_simulate_passed_to_async_instrument_client(self, config, mock_async_star_class):
        with StarClient(config, simulate=True):
            mock_async_star_class.assert_called_once_with(
                config,
                simulate=True,
                venus_trace_logging=False,
                run_log=None,
                run_log_config=config.run_log,
                error_profile=STANDARD_PROFILE,
                on_operator_error_escalation=None,
                instrument_type=InstrumentType.STAR,
            )

    def test_simulate_defaults_false(self, config, mock_async_star_class):
        with StarClient(config):
            mock_async_star_class.assert_called_once_with(
                config,
                simulate=False,
                venus_trace_logging=False,
                run_log=None,
                run_log_config=config.run_log,
                error_profile=STANDARD_PROFILE,
                on_operator_error_escalation=None,
                instrument_type=InstrumentType.STAR,
            )

    def test_send_command(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            category="System",
            actionName="instrument.isConnected",
            parameters={},
            returnStatus="Success",
            returnCode=0,
            returnParameters={"value": True},
        )

        with StarClient(config) as client:
            result = client.send_command("System", "instrument.isConnected")

        assert result.success is True
        mock_async_star_class.return_value.venus.send_command.assert_awaited_once_with(
            "System",
            "instrument.isConnected",
            None,
        )

    def test_connection_state(self, config, mock_async_star_class):
        with StarClient(config) as client:
            assert client.connection_state == ConnectionState.CONNECTED

    def test_simulate_property(self, config, mock_async_star_class):
        assert StarClient(config, simulate=True).simulate is True
        assert StarClient(config).simulate is False


class TestStarClientPassthrough:
    def test_instrument_is_connected(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.status_is_connected = AsyncMock(return_value=True)
        with StarClient(config) as client:
            result = client.instrument_is_connected()
        assert result is True
        star.status_is_connected.assert_awaited_once()

    def test_instrument_is_connected_false(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.status_is_connected = AsyncMock(return_value=False)
        with StarClient(config) as client:
            result = client.instrument_is_connected()
        assert result is False


class TestStarClientCommandTimeout:
    """Tests for set_command_timeout context manager."""

    def test_set_command_timeout_valid_timeout(self, config, mock_async_star_class):
        """Test set_command_timeout sets and restores timeout correctly."""
        star = mock_async_star_class.return_value
        star.venus._command_timeout = 60.0

        with StarClient(config) as client:
            assert star.venus._command_timeout == 60.0

            with client.set_command_timeout(120.0):
                assert star.venus._command_timeout == 120.0

            assert star.venus._command_timeout == 60.0

    def test_set_command_timeout_raises_on_zero_timeout(self, config, mock_async_star_class):
        """Test set_command_timeout raises ValueError for zero timeout."""
        with StarClient(config) as client, pytest.raises(ValueError, match="timeout must be greater than 0"):
            client.set_command_timeout(0)

    def test_set_command_timeout_raises_on_negative_timeout(self, config, mock_async_star_class):
        """Test set_command_timeout raises ValueError for negative timeout."""
        with StarClient(config) as client, pytest.raises(ValueError, match="timeout must be greater than 0"):
            client.set_command_timeout(-5.0)

    def test_set_command_timeout_nested_contexts(self, config, mock_async_star_class):
        """Test nested set_command_timeout contexts work correctly.

        When contexts are nested, the innermost context should take precedence,
        and timeouts should be restored correctly when exiting each context.
        """
        star = mock_async_star_class.return_value
        star.venus._command_timeout = 60.0

        with StarClient(config) as client:
            assert star.venus._command_timeout == 60.0

            with client.set_command_timeout(120.0):
                assert star.venus._command_timeout == 120.0

                with client.set_command_timeout(180.0):
                    assert star.venus._command_timeout == 180.0

                assert star.venus._command_timeout == 120.0

            assert star.venus._command_timeout == 60.0

    def test_set_command_timeout_exception_restores_timeout(self, config, mock_async_star_class):
        """Test timeout is restored even when exception occurs within context.

        This verifies that the try/finally block in the context manager properly
        restores the original timeout even when an exception is raised inside
        the context.
        """
        star = mock_async_star_class.return_value
        star.venus._command_timeout = 60.0

        with StarClient(config) as client:
            try:
                with client.set_command_timeout(120.0):
                    assert star.venus._command_timeout == 120.0
                    raise RuntimeError("Test exception")
            except RuntimeError:
                pass

            assert star.venus._command_timeout == 60.0

    def test_set_command_timeout_exception_propagates(self, config, mock_async_star_class):
        """Test exceptions raised within set_command_timeout context propagate.

        Verifies that exceptions from code within the context are not swallowed
        by the context manager and are properly propagated to the caller.
        """
        star = mock_async_star_class.return_value
        star.venus._command_timeout = 60.0

        with StarClient(config) as client, pytest.raises(ValueError, match="Something went wrong"):  # noqa: SIM117
            with client.set_command_timeout(120.0):
                raise ValueError("Something went wrong")

    def test_set_command_timeout_multiple_sequential_contexts(self, config, mock_async_star_class):
        """Test multiple sequential set_command_timeout contexts work independently."""
        star = mock_async_star_class.return_value
        star.venus._command_timeout = 60.0

        with StarClient(config) as client:
            with client.set_command_timeout(120.0):
                assert star.venus._command_timeout == 120.0

            assert star.venus._command_timeout == 60.0

            with client.set_command_timeout(90.0):
                assert star.venus._command_timeout == 90.0

            assert star.venus._command_timeout == 60.0

    def test_set_command_timeout_affects_send_command_default_timeout(self, config, mock_async_star_class):
        """Test set_command_timeout changes the timeout observed by command execution."""
        star = mock_async_star_class.return_value
        observed_timeouts = []
        star.venus._command_timeout = 60.0

        def _send_command_side_effect(*args, **kwargs):
            observed_timeouts.append(star.venus._command_timeout)
            return CommandResponse(
                category="System",
                actionName="instrument.isConnected",
                parameters={},
                returnStatus="Success",
                returnCode=0,
                returnParameters={"isConnected": True},
            )

        star.venus.send_command = AsyncMock(side_effect=_send_command_side_effect)

        with StarClient(config) as client:
            with client.set_command_timeout(120.0):
                client.send_command("System", "instrument.isConnected")

            client.send_command("System", "instrument.isConnected")

        assert observed_timeouts == [120.0, 60.0]


class TestStarClientLogging:
    def test_logging_handler_attached_and_removed(self, config, mock_async_star_class):
        sdk_logger = logging.getLogger("hamilton_venus")
        handlers_before = list(sdk_logger.handlers)

        with StarClient(config, logging_level=logging.DEBUG):
            handlers_during = list(sdk_logger.handlers)
            new_handlers = [h for h in handlers_during if h not in handlers_before]
            assert len(new_handlers) == 1
            assert isinstance(new_handlers[0], logging.StreamHandler)

        assert list(sdk_logger.handlers) == handlers_before

    def test_logging_level_none_does_not_add_handler(self, config, mock_async_star_class):
        sdk_logger = logging.getLogger("hamilton_venus")
        handlers_before = list(sdk_logger.handlers)

        with StarClient(config, use_config_logging_level=False, logging_level=None):
            assert list(sdk_logger.handlers) == handlers_before

    def test_logging_level_none_with_config_inheritance_uses_config_value(self, config, mock_async_star_class):
        config.star_client.logging_level = logging.ERROR
        sdk_logger = logging.getLogger("hamilton_venus")
        handlers_before = list(sdk_logger.handlers)

        with StarClient(config, logging_level=None) as client:
            assert client._logging_level == logging.ERROR
            handlers_during = list(sdk_logger.handlers)
            new_handlers = [h for h in handlers_during if h not in handlers_before]
            assert len(new_handlers) == 1

    def test_logging_level_none_explicit_without_config_inheritance_disables_handler(
        self,
        config,
        mock_async_star_class,
    ):
        config.star_client.logging_level = logging.ERROR
        sdk_logger = logging.getLogger("hamilton_venus")
        handlers_before = list(sdk_logger.handlers)

        with StarClient(config, logging_level=None, use_config_logging_level=False) as client:
            assert client._logging_level is None
            assert list(sdk_logger.handlers) == handlers_before

    def test_logging_handler_removed_on_exception(self, config, mock_async_star_class):
        sdk_logger = logging.getLogger("hamilton_venus")
        handlers_before = list(sdk_logger.handlers)

        with pytest.raises(RuntimeError), StarClient(config, logging_level=logging.INFO):
            raise RuntimeError("boom")

        assert list(sdk_logger.handlers) == handlers_before

    def test_logging_captures_output(self, config, mock_async_star_class, caplog):
        with caplog.at_level(logging.DEBUG, logger="hamilton_venus"), StarClient(config, logging_level=logging.DEBUG):
            pass

        assert any("StarClient start" in r.message for r in caplog.records)


class TestStarClientVenusTraceLogging:
    def test_venus_trace_logging_config_default_applies(self, config, mock_async_star_class):
        config.star_client.venus_trace_logging = True
        with StarClient(config):
            mock_async_star_class.assert_called_once_with(
                config,
                simulate=False,
                venus_trace_logging=True,
                run_log=None,
                run_log_config=config.run_log,
                error_profile=STANDARD_PROFILE,
                on_operator_error_escalation=None,
                instrument_type=InstrumentType.STAR,
            )

    def test_venus_trace_logging_passed_to_async_client(self, config, mock_async_star_class):
        with StarClient(config, venus_trace_logging=True):
            mock_async_star_class.assert_called_once_with(
                config,
                simulate=False,
                venus_trace_logging=True,
                run_log=None,
                run_log_config=config.run_log,
                error_profile=STANDARD_PROFILE,
                on_operator_error_escalation=None,
                instrument_type=InstrumentType.STAR,
            )

    def test_venus_trace_logging_false_passed_explicitly(self, config, mock_async_star_class):
        with StarClient(config, venus_trace_logging=False):
            mock_async_star_class.assert_called_once_with(
                config,
                simulate=False,
                venus_trace_logging=False,
                run_log=None,
                run_log_config=config.run_log,
                error_profile=STANDARD_PROFILE,
                on_operator_error_escalation=None,
                instrument_type=InstrumentType.STAR,
            )


class TestStarClientRunLogInitialization:
    def test_run_log_config_creates_run_log_instance(self, config, mock_async_star_class, tmp_path):
        """When a RunLogConfig instance is passed, a RunLog is created and forwarded."""
        run_log_config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=run_log_config):
            call_kwargs = mock_async_star_class.call_args
            assert isinstance(call_kwargs.kwargs["run_log"], RunLog)
            assert call_kwargs.kwargs["run_log_config"] is run_log_config

    def test_run_log_bool_true_creates_run_log_instance(self, config, mock_async_star_class, tmp_path, monkeypatch):
        """When run_log=True, RunLogConfig(enabled=True) is resolved and a RunLog is created."""
        monkeypatch.chdir(tmp_path)
        with StarClient(config, run_log=True):
            call_kwargs = mock_async_star_class.call_args
            assert isinstance(call_kwargs.kwargs["run_log"], RunLog)
            assert call_kwargs.kwargs["run_log_config"].enabled is True

    def test_run_log_none_uses_config_default(self, config, mock_async_star_class):
        """When run_log=None (default), the config's run_log settings are used."""
        with StarClient(config) as client:
            assert client._run_log_config is config.run_log
            # Default config has enabled=False, so no RunLog created
            call_kwargs = mock_async_star_class.call_args
            assert call_kwargs.kwargs["run_log"] is None

    def test_run_log_false_forces_disabled_even_when_config_enabled(self, config, mock_async_star_class):
        """When run_log=False, run log is force-disabled regardless of config defaults."""
        config.run_log.enabled = True
        with StarClient(config, run_log=False) as client:
            assert client._run_log_config.enabled is False
            call_kwargs = mock_async_star_class.call_args
            assert call_kwargs.kwargs["run_log"] is None
            assert call_kwargs.kwargs["run_log_config"].enabled is False

    def test_run_log_config_passed_directly(self, config, mock_async_star_class, tmp_path):
        """When a RunLogConfig is passed, it is used directly."""
        run_log_config = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_http=False)
        with StarClient(config, run_log=run_log_config):
            call_kwargs = mock_async_star_class.call_args
            assert call_kwargs.kwargs["run_log_config"] is run_log_config
            assert isinstance(call_kwargs.kwargs["run_log"], RunLog)

    def test_run_log_finalized_on_normal_exit(self, config, mock_async_star_class, tmp_path):
        """RunLog is finalized with reason='normal' on clean exit."""
        run_log_config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with StarClient(config, run_log=run_log_config) as client:
            run_log = client._run_log
            assert run_log is not None
        # After exit, run_log should be cleared
        assert client._run_log is None
        # Finalized JSON file should exist with reason='normal'
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1

        # Verify the reason field is set to 'normal'
        finalized_data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert finalized_data["reason"] == "normal"

    def test_run_log_finalized_on_error_exit(self, config, mock_async_star_class, tmp_path):
        """RunLog is finalized with reason='error' when an exception occurs."""
        run_log_config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        with pytest.raises(RuntimeError), StarClient(config, run_log=run_log_config):
            raise RuntimeError("boom")

        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1

        # Verify the reason field is set to 'error'
        finalized_data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert finalized_data["reason"] == "error"


class TestStarClientConfigDefaults:
    def test_shutdown_timeout_uses_config_default(self, config):
        config.star_client.shutdown_timeout = 12.5
        client = StarClient(config)
        assert client._shutdown_timeout == 12.5

    def test_error_profile_uses_config_default_standard(self, config):
        client = StarClient(config)
        assert client._error_profile is STANDARD_PROFILE

    def test_error_profile_raises_for_unknown_config_profile_name(self, config):
        config.star_client.error_profile_name = "unknown"

        with pytest.raises(ValueError, match=r"Unsupported star_client.error_profile_name"):
            StarClient(config)

    def test_explicit_error_profile_overrides_unknown_config_profile_name(self, config):
        from hamilton_venus.error_handling import ErrorEntry, ErrorProfile

        config.star_client.error_profile_name = "unknown"
        custom_profile = ErrorProfile(
            name="Custom",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
        )

        client = StarClient(config, error_profile=custom_profile)

        assert client._error_profile is custom_profile

    def test_constructor_overrides_config_defaults(self, config):
        config.star_client = StarClientConfig(
            auto_connect=False,
            shutdown_timeout=11.0,
            logging_level=logging.WARNING,
            venus_trace_logging=True,
            error_profile_name="standard",
        )
        client = StarClient(
            config,
            auto_connect=True,
            shutdown_timeout=22.0,
            logging_level=logging.INFO,
            use_config_logging_level=False,
            venus_trace_logging=False,
            error_profile=STANDARD_PROFILE,
        )
        assert client._auto_connect is True
        assert client._shutdown_timeout == 22.0
        assert client._logging_level == logging.INFO
        assert client._venus_trace_logging is False
        assert client._error_profile is STANDARD_PROFILE

    def test_constructor_rejects_non_positive_shutdown_timeout_override(self, config):
        with pytest.raises(ValueError, match="shutdown_timeout must be greater than 0"):
            StarClient(config, shutdown_timeout=0)

    def test_constructor_rejects_non_numeric_shutdown_timeout_override(self, config):
        bad_shutdown_timeout: Any = "10"
        with pytest.raises(TypeError, match="shutdown_timeout must be a number greater than 0"):
            StarClient(config, shutdown_timeout=bad_shutdown_timeout)

    def test_constructor_rejects_negative_logging_level_override(self, config):
        with pytest.raises(ValueError, match="logging_level must be greater than or equal to 0"):
            StarClient(config, logging_level=-1)

    def test_constructor_rejects_non_int_logging_level_override(self, config):
        bad_logging_level: Any = "debug"
        with pytest.raises(TypeError, match="logging_level must be an int greater than or equal to 0, or None"):
            StarClient(config, logging_level=bad_logging_level)

    def test_constructor_rejects_invalid_shutdown_timeout_from_config(self, config):
        bad_shutdown_timeout: Any = "10"
        config.star_client.shutdown_timeout = bad_shutdown_timeout
        with pytest.raises(TypeError, match="shutdown_timeout must be a number greater than 0"):
            StarClient(config)

    def test_constructor_rejects_invalid_logging_level_from_config(self, config):
        bad_logging_level: Any = "debug"
        config.star_client.logging_level = bad_logging_level
        with pytest.raises(TypeError, match="logging_level must be an int greater than or equal to 0, or None"):
            StarClient(config)

    def test_use_error_profile_swaps_profile(self, config, mock_async_star_class):
        from hamilton_venus.error_handling import ErrorEntry, ErrorProfile

        star = mock_async_star_class.return_value
        star.error_resolver = MagicMock()
        star.error_resolver.active_profile = STANDARD_PROFILE

        custom_profile = ErrorProfile(
            name="Custom",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
        )

        with StarClient(config) as client, client.use_error_profile(custom_profile):
            star.error_resolver.set_active_profile.assert_called_with(custom_profile)

    def test_use_error_profile_restores_on_exit(self, config, mock_async_star_class):
        from hamilton_venus.error_handling import ErrorEntry, ErrorProfile
        from hamilton_venus.models import RecoveryAction

        star = mock_async_star_class.return_value
        star.error_resolver = MagicMock()
        star.error_resolver.active_profile = STANDARD_PROFILE

        custom_profile = ErrorProfile(
            name="Custom",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
        )

        with StarClient(config) as client:
            with client.use_error_profile(custom_profile):
                pass
            calls = star.error_resolver.set_active_profile.call_args_list
            assert calls[0].args[0] is custom_profile
            assert calls[1].args[0] is STANDARD_PROFILE

    def test_use_error_profile_restores_on_exception(self, config, mock_async_star_class):
        from hamilton_venus.error_handling import ErrorEntry, ErrorProfile
        from hamilton_venus.models import RecoveryAction

        star = mock_async_star_class.return_value
        star.error_resolver = MagicMock()
        star.error_resolver.active_profile = STANDARD_PROFILE

        custom_profile = ErrorProfile(
            name="Custom",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
        )

        with StarClient(config) as client:
            with pytest.raises(RuntimeError), client.use_error_profile(custom_profile):
                raise RuntimeError("error inside profile")
            calls = star.error_resolver.set_active_profile.call_args_list
            assert calls[0].args[0] is custom_profile
            assert calls[1].args[0] is STANDARD_PROFILE

    def test_use_error_profile_raises_when_client_not_started(self, config):
        from hamilton_venus.error_handling import ErrorEntry, ErrorProfile

        custom_profile = ErrorProfile(
            name="Custom",
            default=ErrorEntry(actions=(RecoveryAction.ABORT,), max_retries=0),
        )

        client = StarClient(config)

        with pytest.raises(RuntimeError, match="Client is not started"), client.use_error_profile(custom_profile):
            pass


class TestStarClientAbortGuard:
    def test_send_command_abort_triggers_stop(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(side_effect=VenusCommandAbortedError("aborted"))

        client = StarClient(config)
        client.start()

        with pytest.raises(VenusCommandAbortedError):
            client.send_command("System", "instrument.isConnected")

        assert client._state == _LifecycleState.STOPPED
        star.stop.assert_awaited()

    def test_abort_exception_propagates_after_stop(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(side_effect=VenusCommandAbortedError("method aborting"))

        client = StarClient(config)
        client.start()

        exc: VenusCommandAbortedError | None = None
        try:
            client.send_command("System", "instrument.isConnected")
        except VenusCommandAbortedError as e:
            exc = e

        assert exc is not None
        assert "method aborting" in str(exc)
        assert client._state == _LifecycleState.STOPPED

    def test_other_exceptions_do_not_trigger_stop(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(side_effect=RuntimeError("unexpected"))

        client = StarClient(config)
        client.start()

        with pytest.raises(RuntimeError, match="unexpected"):
            client.send_command("System", "instrument.isConnected")

        assert client._state == _LifecycleState.STARTED
        client.stop()
