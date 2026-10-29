"""Unit tests for VantageClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus import VantageClient, VantageClientConfig
from hamilton_venus._internal._base_sync_client import _LifecycleState
from hamilton_venus.config import SdkConfig
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.models import CommandResponse, ConnectionState, InstrumentType


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_instrument_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        instrument = MagicMock()
        instrument.start = AsyncMock()
        instrument.stop = AsyncMock()
        instrument.connection_state = ConnectionState.CONNECTED

        venus = MagicMock()
        venus.send_command = AsyncMock()

        instrument.venus = venus
        cls.return_value = instrument
        yield cls


class TestVantageClientLifecycle:
    def test_start_stop(self, config, mock_async_instrument_class):
        client = VantageClient(config)
        assert client._state == _LifecycleState.STOPPED

        client.start()
        instrument = mock_async_instrument_class.return_value
        instrument.start.assert_awaited_once_with(auto_connect=True, deck_name=None)
        assert client._state == _LifecycleState.STARTED

        client.stop()
        instrument.stop.assert_awaited_once()
        assert client._state == _LifecycleState.STOPPED

    def test_context_manager(self, config, mock_async_instrument_class):
        with VantageClient(config) as client:
            instrument = mock_async_instrument_class.return_value
            instrument.start.assert_awaited_once_with(auto_connect=True, deck_name=None)
            assert client._thread is not None
        instrument.stop.assert_awaited_once()
        assert client._loop is None

    def test_instrument_type_defaults_to_vantage(self, config, mock_async_instrument_class):
        with VantageClient(config):
            call_kwargs = mock_async_instrument_class.call_args
            assert call_kwargs.kwargs["instrument_type"] is InstrumentType.Vantage

    def test_connection_state(self, config, mock_async_instrument_class):
        with VantageClient(config) as client:
            assert client.connection_state == ConnectionState.CONNECTED


class TestVantageClientCommands:
    def test_instrument_is_connected(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.status_is_connected = AsyncMock(return_value=True)
        with VantageClient(config) as client:
            result = client.instrument_is_connected()
        assert result is True
        instrument.status_is_connected.assert_awaited_once()

    def test_send_command(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command.return_value = CommandResponse(
            category="System",
            actionName="instrument.isConnected",
            parameters={},
            returnStatus="Success",
            returnCode=0,
            returnParameters={"value": True},
        )

        with VantageClient(config) as client:
            result = client.send_command("System", "instrument.isConnected")

        assert result.success is True
        instrument.venus.send_command.assert_awaited_once_with(
            "System",
            "instrument.isConnected",
            None,
        )

    def test_previously_excluded_mixins_now_present(self, config):
        from hamilton_venus.mixins import (
            Channels5mLCommandsMixin,
            ChannelsMagPipCommandsMixin,
            CompoundCommandsMixin,
            LoadTrayCommandsMixin,
            TransportCommandsMixin,
        )

        assert issubclass(VantageClient, Channels5mLCommandsMixin)
        assert issubclass(VantageClient, ChannelsMagPipCommandsMixin)
        assert issubclass(VantageClient, TransportCommandsMixin)
        assert issubclass(VantageClient, CompoundCommandsMixin)
        assert issubclass(VantageClient, LoadTrayCommandsMixin)


class TestVantageClientConfigDefaults:
    def test_shutdown_timeout_uses_config_default(self, config):
        config.vantage_client.shutdown_timeout = 12.5
        client = VantageClient(config)
        assert client._shutdown_timeout == 12.5

    def test_error_profile_uses_config_default_standard(self, config):
        client = VantageClient(config)
        assert client._error_profile is STANDARD_PROFILE

    def test_error_profile_raises_for_unknown_config_profile_name(self, config):
        config.vantage_client.error_profile_name = "unknown"

        with pytest.raises(ValueError, match=r"Unsupported vantage_client.error_profile_name"):
            VantageClient(config)

    def test_constructor_overrides_config_defaults(self, config):
        config.vantage_client = VantageClientConfig(
            auto_connect=False,
            shutdown_timeout=11.0,
        )
        client = VantageClient(config, auto_connect=True, shutdown_timeout=22.0)
        assert client._auto_connect is True
        assert client._shutdown_timeout == 22.0
