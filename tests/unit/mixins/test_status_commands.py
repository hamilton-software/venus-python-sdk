"""Unit tests for StatusCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
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

        venus_mock = MagicMock()
        venus_mock.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            ),
        )
        venus_mock.send_signal_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            ),
        )
        venus_mock.peek_channel = AsyncMock(return_value=None)
        star.venus = venus_mock

        cls.return_value = star
        yield cls


class TestStatusCommands:
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
        star.status_is_connected.assert_awaited_once()

    def test_instrument_is_idle(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.status_is_idle = AsyncMock(return_value=True)

        with StarClient(config) as client:
            result = client.instrument_is_idle()

        assert result is True
        star.status_is_idle.assert_awaited_once()

    def test_instrument_is_idle_from_channel(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.status_is_idle = AsyncMock(return_value=True)

        with StarClient(config) as client:
            result = client.instrument_is_idle()

        assert result is True
        star.status_is_idle.assert_awaited_once()

    def test_instrument_is_idle_false(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.status_is_idle = AsyncMock(return_value=False)

        with StarClient(config) as client:
            result = client.instrument_is_idle()

        assert result is False

    def test_instrument_init_default(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.instrument_init()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.init",
            parameters={"forceInit": False},
        )
        star.venus.send_signal_command.assert_not_awaited()

    def test_instrument_init_force(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.instrument_init(force_init=True)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.init",
            parameters={"forceInit": True},
        )
        star.venus.send_signal_command.assert_not_awaited()

    def test_instrument_connect_default(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "instrumentName": "ML_STAR",
                    "autoloadCurrentTrack": 54,
                    "message": "Instrument connected",
                },
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_connect()

        assert result.success is True
        assert result.return_parameters.instrument_name == "ML_STAR"
        assert result.return_parameters.autoload_current_track == 54
        assert result.return_parameters.message == "Instrument connected"
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.connect",
            parameters={"initialize": True},
        )

    def test_instrument_connect_without_initialize(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.instrument_connect(initialize=False)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="status.connect",
            parameters={"initialize": False},
        )
