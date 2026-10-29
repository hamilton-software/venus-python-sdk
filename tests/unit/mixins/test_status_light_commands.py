"""Unit tests for StatusLightCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.models.enums import LightColor
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
        star.venus = venus_mock

        cls.return_value = star
        yield cls


class TestStatusLightCommands:
    def test_status_light_set_front_light(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.status_light_set_front_light(
                color=LightColor.GREEN,
                blink=True,
                progress=5,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="statusLight.setFrontLight",
            parameters={"color": LightColor.GREEN, "blink": True, "progress": 5},
        )
