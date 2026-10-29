"""Unit tests for AutoloadCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse, ScanPositions
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


class TestAutoloadCommands:
    def test_autoload_move(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_move(track_id=5)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.moveTo",
            parameters={"trackId": 5},
        )

    def test_autoload_park_left(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_park_left()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.parkLeft",
        )

    def test_autoload_park_right(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_park_right()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.parkRight",
        )

    def test_autoload_load_carrier_by_id_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_id(carrier_id="Carrier1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.loadCarrierById",
            parameters={"carrierId": "Carrier1"},
        )

    def test_autoload_load_carrier_by_id_with_scan(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_id(carrier_id="Carrier2", scan_positions=[1, 2, 3])

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.loadCarrierById",
            parameters={"carrierId": "Carrier2", "scanPositions": "1,2,3"},
        )

    def test_autoload_load_carrier_by_id_with_scan_enum(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_id(
                carrier_id="Carrier2", scan_positions=ScanPositions.DETECTED
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.loadCarrierById",
            parameters={"carrierId": "Carrier2", "scanPositions": "?"},
        )

    def test_autoload_load_carrier_by_track_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_track(track_id=3)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.loadCarrierByTrack",
            parameters={"trackId": 3},
        )

    def test_autoload_load_carrier_by_track_with_scan(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_track(track_id=4, scan_positions=[2, 5])

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.loadCarrierByTrack",
            parameters={"trackId": 4, "scanPositions": "2,5"},
        )

    def test_autoload_load_carrier_by_id_parses_barcode_returns(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "track": 8,
                    "carrierBarcode": "CarrierBC",
                    "carrierLabwareID": "smp_car_32_12x100_0001",
                    "barcodeReturns": [
                        {"barcode": "Barcode01", "position": "1", "barcodeMask": "%"},
                        {"barcode": "Barcode02", "position": "2", "barcodeMask": "%"},
                    ],
                },
            )
        )

        with StarClient(config) as client:
            result = client.autoload_load_carrier_by_id(
                carrier_id="smp_car_32_12x100_0001", scan_positions=[1, 2]
            )

        assert result.return_parameters.track == 8
        assert result.return_parameters.carrier_barcode == "CarrierBC"
        assert result.return_parameters.carrier_labware_id == "smp_car_32_12x100_0001"
        assert len(result.return_parameters.barcode_returns) == 2
        assert result.return_parameters.barcode_returns[0].barcode == "Barcode01"
        assert result.return_parameters.barcode_returns[0].position == "1"
        assert result.return_parameters.barcode_returns[1].barcode == "Barcode02"

    def test_autoload_unload_carrier_by_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_unload_carrier_by_id(carrier_id="Carrier3")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.unloadCarrierById",
            parameters={"carrierId": "Carrier3"},
        )

    def test_autoload_unload_carrier_by_track(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.autoload_unload_carrier_by_track(track_id=7)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.unloadCarrierByTrack",
            parameters={"trackId": 7},
        )

    def test_autoload_is_track_occupied_true(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"trackOccupied": True},
            ),
        )

        with StarClient(config) as client:
            result = client.autoload_is_track_occupied(track_id=2)

        assert result.return_parameters.is_occupied is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.isTrackOccupied",
            parameters={"trackId": 2},
        )

    def test_autoload_is_track_occupied_false(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"trackOccupied": False},
            ),
        )

        with StarClient(config) as client:
            result = client.autoload_is_track_occupied(track_id=6)

        assert result.return_parameters.is_occupied is False

    def test_autoload_get_carrier_sensor_status(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "carrierSensorStatus": [
                        {
                            "carrier": "CarrierA",
                            "sensorTrack": 12,
                            "sensorAvailable": True,
                            "status": False,
                        }
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.autoload_get_carrier_sensor_status()

        assert result.success is True
        assert result.return_parameters.carrier_sensor_status[0].carrier == "CarrierA"
        assert result.return_parameters.carrier_sensor_status[0].sensor_track == 12
        assert result.return_parameters.carrier_sensor_status[0].sensor_available is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="autoload.getCarrierSensorStatus",
        )
