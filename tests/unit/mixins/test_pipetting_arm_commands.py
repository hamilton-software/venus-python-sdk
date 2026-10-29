"""Unit tests for PipettingArmCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.models.enums import CoordinateMode, PipArmSpeed
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


class TestPipettingArmCommands:
    def test_pip_arm_get_x_position_default(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"position": 100.5},
            ),
        )

        with StarClient(config) as client:
            result = client.pip_arm_get_x_position()

        assert result.success is True
        assert result.return_parameters["position"] == 100.5
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.getXPosition",
            parameters={"armId": 1},
        )

    def test_pip_arm_get_x_position_right_arm(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_get_x_position(arm_id=2)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.getXPosition",
            parameters={"armId": 2},
        )

    def test_pip_arm_park_left_default(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_park_left()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.parkLeft",
            parameters={"armId": 1},
        )

    def test_pip_arm_park_left_specific_arm(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_park_left(arm_id=1)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.parkLeft",
            parameters={"armId": 1},
        )

    def test_pip_arm_park_right_default(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_park_right()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.parkRight",
            parameters={"armId": 1},
        )

    def test_pip_arm_park_right_specific_arm(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_park_right(arm_id=2)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.parkRight",
            parameters={"armId": 2},
        )

    def test_pip_arm_move_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_move(value=500.0, safety_bypass_token="OVERRIDE_SAFETY_CHECKS")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.moveTo",
            parameters={"value": 500.0, "armId": 1, "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS"},
        )

    def test_pip_arm_move_without_safety_bypass_token(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_move(value=500.0)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.moveTo",
            parameters={"value": 500.0, "armId": 1},
        )

    def test_pip_arm_move_with_all_params(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pip_arm_move(
                value=300.5,
                coordinate_mode=CoordinateMode.RELATIVE,
                arm_id=2,
                speed=PipArmSpeed.STANDARD,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="pipArm.moveTo",
            parameters={
                "value": 300.5,
                "mode": CoordinateMode.RELATIVE.value,
                "armId": 2,
                "speed": PipArmSpeed.STANDARD.value,
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )
