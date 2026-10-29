"""Unit tests for MaintenanceCommandsMixin."""

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


class TestMaintenanceCommands:
    def test_instrument_get_daily_maintenance_data(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "status": "Required",
                    "expirationDate": "2026-04-08",
                    "processedDate": "2026-04-07",
                },
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_daily_maintenance_data()

        assert result.return_parameters.status == "Required"
        assert result.return_parameters.expiration_date == "2026-04-08"

    def test_instrument_get_weekly_maintenance_data(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "status": "Required",
                    "expirationDate": "2026-04-14",
                },
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_weekly_maintenance_data()

        assert result.return_parameters.status == "Required"
        assert result.return_parameters.expiration_date == "2026-04-14"

    def test_instrument_get_verification_data(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "status": "Required",
                    "expirationDate": "2026-07-07",
                },
            ),
        )

        with StarClient(config) as client:
            result = client.instrument_get_verification_data()

        assert result.return_parameters.status == "Required"
        assert result.return_parameters.expiration_date == "2026-07-07"
