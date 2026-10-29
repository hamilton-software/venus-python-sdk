"""Unit tests for ConfigurationCommandsMixin."""

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


class TestConfigurationCommands:
    def test_instrument_get_configuration(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "LeftArm": {
                        "armId": 1,
                        "gripper": {"type": "iSWAP"},
                        "MPH96": {
                            "total": 96,
                            "raster": 9.0,
                            "type": "MPH96",
                            "capacity": 300.0,
                            "xMin": 100.0,
                            "xMax": 1225.0,
                            "yMin": 17.0,
                            "yMax": 605.5,
                        },
                    },
                    "RightArm": {"armId": 2, "MPH96": None},
                    "type": "STAR",
                    "Autoload": True,
                    "tracks": 54,
                    "MaxAutoloadTrack": 40,
                },
            )
        )

        with StarClient(config) as client:
            result = client.instrument_get_configuration()

        assert result.success is True
        assert result.return_parameters.left_arm is not None
        assert result.return_parameters.left_arm.gripper.type == "iSWAP"
        assert result.return_parameters.left_arm.mph96 is not None
        assert result.return_parameters.left_arm.mph96.total == 96
        assert result.return_parameters.left_arm.mph96.raster == 9.0
        assert result.return_parameters.left_arm.mph96.type == "MPH96"
        assert result.return_parameters.left_arm.mph96.capacity == 300.0
        assert result.return_parameters.left_arm.mph96.x_min == 100.0
        assert result.return_parameters.left_arm.mph96.x_max == 1225.0
        assert result.return_parameters.left_arm.mph96.y_min == 17.0
        assert result.return_parameters.left_arm.mph96.y_max == 605.5
        assert result.return_parameters.right_arm.mph96 is None
        assert result.return_parameters.type == "STAR"
        assert result.return_parameters.max_autoload_track == 40
        assert result.return_parameters.tracks == 54

    def test_instrument_get_configuration_with_detailed_channels(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "LeftArm": {
                        "armId": 1,
                        "gripper": {"type": "IPG"},
                        "MPH96": {
                            "total": 96,
                            "raster": 9.0,
                            "type": "MPH96",
                            "capacity": 300.0,
                            "xMin": 100.0,
                            "xMax": 1225.0,
                            "yMin": 17.0,
                            "yMax": 605.5,
                        },
                        "MPH384": False,
                        "channels1mL": {
                            "total": 8,
                            "raster": 9,
                            "type": "Fluid Motion",
                            "capacity": 1000,
                            "maxY": [605.5, 596.5, 587.5, 578.5, 569.5, 560.5, 551.5, 542.5],
                            "minY": [143, 134, 125, 116, 107, 98, 89, 80],
                        },
                        "channels5mL": {
                            "total": 4,
                            "raster": 18,
                            "type": "Legacy",
                            "capacity": 5000,
                            "maxY": [524.5, 506.5, 488.5, 470.5],
                            "minY": [71, 53, 35, 17],
                        },
                        "channelsMagPip": {
                            "total": 4,
                            "raster": 18,
                            "type": "Legacy",
                            "capacity": 750,
                        },
                        "xMin": 100,
                        "xMax": 1225,
                    },
                    "RightArm": {},
                    "type": "STAR",
                    "Autoload": True,
                    "tracks": 54,
                    "MaxAutoloadTrack": 54,
                },
            )
        )

        with StarClient(config) as client:
            result = client.instrument_get_configuration()

        assert result.success is True
        assert result.return_parameters.left_arm is not None
        assert result.return_parameters.left_arm.gripper is not None
        assert result.return_parameters.left_arm.gripper.type == "IPG"
        assert result.return_parameters.left_arm.mph96 is not None
        assert result.return_parameters.left_arm.mph96.total == 96
        assert result.return_parameters.left_arm.mph384 is False
        assert result.return_parameters.left_arm.channels_1_ml is not None
        assert result.return_parameters.left_arm.channels_1_ml.total == 8
        assert result.return_parameters.left_arm.channels_1_ml.raster == 9
        assert result.return_parameters.left_arm.channels_1_ml.type == "Fluid Motion"
        assert result.return_parameters.left_arm.channels_1_ml.capacity == 1000
        assert result.return_parameters.left_arm.channels_5_ml is not None
        assert result.return_parameters.left_arm.channels_5_ml.total == 4
        assert result.return_parameters.left_arm.channels_5_ml.type == "Legacy"
        assert result.return_parameters.left_arm.channels_mag_pip is not None
        assert result.return_parameters.left_arm.channels_mag_pip.total == 4
        assert result.return_parameters.left_arm.x_min == 100
        assert result.return_parameters.left_arm.x_max == 1225
        assert result.return_parameters.type == "STAR"
        assert result.return_parameters.max_autoload_track == 54
        assert result.return_parameters.tracks == 54

    def test_instrument_disable_cleanup(self, config, mock_async_star_class):
        with StarClient(config) as client:
            result = client.instrument_disable_cleanup()

        assert result.success is True

    def test_instrument_get_serial_number(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"serialNumber": "SN123456"},
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_serial_number()

        assert result.return_parameters.serial_number == "SN123456"

    def test_instrument_get_deck_tracks(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalTracks": 8,
                    "autoloadableTracks": 4,
                    "activeTracks": [3, 4, 5, 6, 7, 8],
                },
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_deck_tracks()

        assert result.success is True
        assert result.return_parameters.total_tracks == 8
        assert result.return_parameters.autoloadable_tracks == 4
        assert result.return_parameters.active_tracks == [3, 4, 5, 6, 7, 8]

    def test_instrument_get_deck_dimensions(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"x": 1250.0, "y": 850.0},
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_deck_dimensions()

        assert result.return_parameters.x == 1250.0
        assert result.return_parameters.y == 850.0

    def test_instrument_get_waste_locations(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "wasteLocations": [
                        {
                            "1": {
                                "x": 10.0,
                                "y": 20.0,
                                "z": 30.0,
                                "carrier": "WasteCarrier",
                                "labwareName": "Waste_1",
                                "isDefault": True,
                                "isMPH384Waste": True,
                            },
                            "2": {
                                "x": 40.0,
                                "y": 50.0,
                                "z": 60.0,
                                "carrier": "DropWaste",
                                "labwareName": "MagPipWaste_1",
                                "isDefault": True,
                                "isMagPipWaste": True,
                            },
                        }
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.instrument_get_waste_locations()

        assert result.success is True
        assert result.return_parameters.waste_locations[0]["1"].carrier == "WasteCarrier"
        assert result.return_parameters.waste_locations[0]["1"].labware_name == "Waste_1"
        assert result.return_parameters.waste_locations[0]["1"].z == 30.0
        assert result.return_parameters.waste_locations[0]["1"].is_default is True
        assert result.return_parameters.waste_locations[0]["1"].is_mph384_waste is True
        assert result.return_parameters.waste_locations[0]["1"].is_mag_pip_waste is False
        assert result.return_parameters.waste_locations[0]["2"].is_mag_pip_waste is True
