"""Unit tests for FirmwareCommandsMixin."""

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
        star.venus = venus_mock

        cls.return_value = star
        yield cls


class TestFirmwareCommands:
    def test_firmware_command_sends_expected_envelope(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"return": "C0ASid0001er00/00"},
            ),
        )

        with StarClient(config) as client:
            result = client.firmware_command(
                command="C0AS",
                parameters="tm1 1 1 1 1 1 1 1",
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="firmware.command",
            parameters={
                "command": "C0AS",
                "parameters": "tm1 1 1 1 1 1 1 1",
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )
        assert result.return_parameters.return_value == "C0ASid0001er00/00"

    def test_firmware_command_defaults(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"return": ""},
            ),
        )

        with StarClient(config) as client:
            result = client.firmware_command(command="C0RF", safety_bypass_token="OVERRIDE_SAFETY_CHECKS")

        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="firmware.command",
            parameters={
                "command": "C0RF",
                "parameters": "",
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )
        assert result.return_parameters.return_value == ""

    def test_firmware_command_requires_safety_bypass_token(self, config, mock_async_star_class):
        with (
            StarClient(config) as client,
            pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'safety_bypass_token'"),
        ):
            client.firmware_command(command="C0RF")
