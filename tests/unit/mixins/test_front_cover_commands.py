"""Unit tests for FrontCoverCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.exceptions import VenusCommandUnsupportedError
from hamilton_venus.models import CommandResponse
from hamilton_venus.star_client import StarClient
from hamilton_venus.vantage_client import VantageClient


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
                return_parameters={"isClosed": True},
            ),
        )
        star.venus = venus_mock

        cls.return_value = star
        yield cls


class TestFrontCoverCommands:
    def test_front_cover_is_closed(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.front_cover_is_closed()

        assert result.return_parameters.is_closed is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="frontCover.isClosed",
        )

    def test_front_cover_is_closed_false(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"isClosed": False},
            )
        )

        with StarClient(config) as client:
            result = client.front_cover_is_closed()

        assert result.return_parameters.is_closed is False
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="frontCover.isClosed",
        )

    def test_front_cover_lock(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.front_cover_lock()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="frontCover.lock",
        )

    def test_front_cover_unlock(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.front_cover_unlock()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="frontCover.unlock",
        )

    def test_front_cover_is_locked_rejected_on_star(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(VenusCommandUnsupportedError, match="not supported on a STAR"):
            client._check_command_supported("Instrument", "frontCover.isLocked")

    def test_front_cover_is_locked_allowed_on_vantage(self, config, mock_async_star_class):
        with VantageClient(config) as client:
            client._check_command_supported("Instrument", "frontCover.isLocked")
