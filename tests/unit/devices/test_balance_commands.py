"""Unit tests for WXS balance commands exposed by VantageClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.vantage_client import VantageClient


def _mock_vantage_client() -> tuple[MagicMock, VantageClient]:
    async_client = MagicMock()
    async_client.start = AsyncMock()
    async_client.stop = AsyncMock()
    async_client.venus.send_command = AsyncMock(
        return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
    )
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient", return_value=async_client):
        client = VantageClient(SdkConfig(base_url="http://test:42400"))
        client.start()
    return async_client, client


def test_wxs_initialize_balance_sends_connection_parameters() -> None:
    async_client, client = _mock_vantage_client()

    result = client.wxs_initialize_balance(port=4, time_out_seconds=30, trials=3)
    client.stop()

    assert result.success is True
    async_client.venus.send_command.assert_awaited_once_with(
        category="Device",
        action_name="WXS.initializeBalance",
        parameters={"port": 4, "timeOutSeconds": 30, "trials": 3},
    )


def test_wxs_tare_and_get_weight_send_optional_immediate_flags() -> None:
    async_client, client = _mock_vantage_client()

    client.wxs_tare(tare_immediately=True)
    client.wxs_get_weight(weigh_immediately=True)
    client.stop()

    assert async_client.venus.send_command.await_args_list[0].kwargs == {
        "category": "Device",
        "action_name": "WXS.tare",
        "parameters": {"tareImmidiately": True},
    }
    assert async_client.venus.send_command.await_args_list[1].kwargs == {
        "category": "Device",
        "action_name": "WXS.getWeight",
        "parameters": {"weighImmidiately": True},
    }


def test_wxs_set_scale_parameters_omits_unset_values() -> None:
    async_client, client = _mock_vantage_client()

    client.wxs_set_scale_parameters(weight_unit=3, auto_zero=False)
    client.stop()

    async_client.venus.send_command.assert_awaited_once_with(
        category="Device",
        action_name="WXS.setScaleParameters",
        parameters={"weightUnit": 3, "autoZero": False},
    )
