"""Unit tests for HeaterShakerDeviceCommands."""

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


class TestHeaterShakerCommands:
    def test_hhs_create_star_device(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"deviceId": 1},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_create_star_device(node=1)

        assert result.return_parameters.device_id == 1
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.createStarDevice",
            parameters={"node": 1},
        )

    def test_hhs_create_usb_device(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"deviceId": 3},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_create_usb_device(node=3)

        assert result.return_parameters.device_id == 3
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.createUsbDevice",
            parameters={"node": 3},
        )

    def test_hhs_get_device_ids(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "deviceIds": [
                        {
                            "deviceId": 1,
                            "node": 1,
                            "connectUsb": False,
                            "serialNumber": "0000",
                            "firmwareVersion": "0.0S 2008-01-01",
                        }
                    ]
                },
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_get_device_ids()

        assert len(result.return_parameters.device_ids) == 1
        device = result.return_parameters.device_ids[0]
        assert device.device_id == 1
        assert device.node == 1
        assert device.connect_usb is False
        assert device.serial_number == "0000"
        assert device.firmware_version == "0.0S 2008-01-01"

    def test_hhs_get_status(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "deviceIds": [
                        {
                            "deviceId": 1,
                            "shakingSpeed": 1000,
                            "temperature": 25.0,
                            "tempControlStatus": "No error.",
                        }
                    ]
                },
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_get_status()

        status = result.return_parameters.device_ids[0]
        assert status.device_id == 1
        assert status.shaking_speed == 1000
        assert status.temperature == 25.0
        assert status.temp_control_status == "No error."

    def test_hhs_set_plate_lock_with_device_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"plateLockStatus": True},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_set_plate_lock(lock=True, device_id=1)

        assert result.return_parameters.plate_lock_status is True
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.setPlateLock",
            parameters={"lock": True, "deviceId": 1},
        )

    def test_hhs_set_plate_lock_all_devices(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"plateLockStatus": False},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_set_plate_lock(lock=False)

        assert result.return_parameters.plate_lock_status is False
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.setPlateLock",
            parameters={"lock": False},
        )

    def test_hhs_start_shaker(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"shakingStarted": "2026-06-26T15:53:56"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_start_shaker(speed=1000, time=30, device_id=1)

        assert result.return_parameters.shaking_started == "2026-06-26T15:53:56"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.startShaker",
            parameters={"speed": 1000, "time": 30, "deviceId": 1},
        )

    def test_hhs_stop_shaker(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"shakingStopped": "2026-06-26T15:57:20"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_stop_shaker()

        assert result.return_parameters.shaking_stopped == "2026-06-26T15:57:20"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.stopShaker",
        )

    def test_hhs_wait_for_shaker(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"shakingStopped": "2026-06-26T15:58:35"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_wait_for_shaker(device_id=1)

        assert result.return_parameters.shaking_stopped == "2026-06-26T15:58:35"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.waitForShaker",
            parameters={"deviceId": 1},
        )

    def test_hhs_start_temp_control(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tempControlStarted": "2026-06-26T15:56:14"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_start_temp_control(temperature=37.0)

        assert result.return_parameters.temp_control_started == "2026-06-26T15:56:14"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.startTempControl",
            parameters={"temperature": 37.0},
        )

    def test_hhs_stop_temp_control(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tempControlStopped": "2026-06-26T15:58:17"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_stop_temp_control(device_id=2)

        assert result.return_parameters.temp_control_stopped == "2026-06-26T15:58:17"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.stopTempControl",
            parameters={"deviceId": 2},
        )

    def test_hhs_wait_for_temp_control(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tempControlStopped": "2026-06-26T15:58:54"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_wait_for_temp_control()

        assert result.return_parameters.temp_control_stopped == "2026-06-26T15:58:54"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.waitForTempControl",
        )

    def test_hhs_terminate(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "HHS disconnected"},
            ),
        )

        with StarClient(config) as client:
            result = client.hhs_terminate()

        assert result.return_parameters.message == "HHS disconnected"
        star.venus.send_command.assert_awaited_once_with(
            category="Device",
            action_name="HHS.terminate",
        )
