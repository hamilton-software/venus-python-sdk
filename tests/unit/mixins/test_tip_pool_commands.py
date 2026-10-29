"""Unit tests for TipPoolCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse, TipRackState
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


class TestTipPoolCommands:
    def test_tip_pool_get_tip_counters(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tipCounterNames": ["Pool1", "Pool2"]},
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_get_tip_counters()

        assert result.success is True
        assert result.return_parameters.tip_counter_names == ["Pool1", "Pool2"]

    def test_tip_pool_get_tip_counter(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalAvailableTips": 96,
                    "availableTips": [{"RackA": {"count": 80, "positions": ["1", "2"]}}],
                    "emptyTips": [{"RackA": {"count": 16, "positions": ["95", "96"]}}],
                    # Rack names (GetMissingRacks_ATML fills SeqGetLabwareId), not indices.
                    "missingRacks": ["tip_nested_300ul_0002", "tip_nested_300ul_0003"],
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_get_tip_counter(tip_pool="Pool1")

        assert result.success is True
        assert result.return_parameters.total_available_tips == 96
        assert result.return_parameters.available_tips[0]["RackA"].count == 80
        assert result.return_parameters.empty_tips[0]["RackA"].positions == ["95", "96"]
        assert result.return_parameters.missing_racks == ["tip_nested_300ul_0002", "tip_nested_300ul_0003"]

    def test_tip_pool_get_available_tips(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalAvailableTips": 48,
                    "availableTips": [{"RackB": {"count": 48, "positions": ["1", "2"]}}],
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_get_available_tips(tip_pool="Pool1")

        assert result.success is True
        assert result.return_parameters.total_available_tips == 48
        assert result.return_parameters.available_tips[0]["RackB"].count == 48

    def test_tip_pool_get_empty_tips(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalEmptyTips": 48,
                    "emptyTips": [{"RackC": {"count": 48, "positions": ["1", "2"]}}],
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_get_empty_tips(tip_pool="Pool1")

        assert result.success is True
        assert result.return_parameters.total_empty_tips == 48
        assert result.return_parameters.empty_tips[0]["RackC"].count == 48

    def test_tip_pool_get_missing_racks(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"missingRacks": ["st_l_ntr_0001", "st_l_ntr_0003"]},
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_get_missing_racks(tip_pool="Pool1")

        assert result.success is True
        assert result.return_parameters.missing_racks == ["st_l_ntr_0001", "st_l_ntr_0003"]

    def test_tip_pool_set_tip_counter(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        available_tips = [
            {
                "st_l_0001": TipRackState(
                    count=96,
                    positions=["1", "2", "3"],
                )
            }
        ]

        with StarClient(config) as client:
            result = client.tip_pool_set_tip_counter(tip_pool="Pool1", available_tips=available_tips)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="tipPool.setTipCounter",
            parameters={
                "tipPool": "Pool1",
                "availableTips": [
                    {
                        "st_l_0001": {
                            "count": 96,
                            "positions": ["1", "2", "3"],
                        }
                    }
                ],
            },
        )

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda c: c.tip_pool_initialize_tip_counter(tip_pool="Pool1"), id="initialize"),
            pytest.param(lambda c: c.tip_pool_reset_tip_counter(tip_pool="Pool1"), id="reset"),
            pytest.param(
                lambda c: c.tip_pool_set_tip_counter(tip_pool="Pool1", available_tips=[]),
                id="set",
            ),
            pytest.param(lambda c: c.tip_pool_get_tip_counters(), id="get_tip_counters"),
        ],
    )
    def test_tip_pool_commands_disable_command_timeout(self, config, mock_async_star_class, call):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tipCounterNames": []},
            )
        )

        with StarClient(config) as client:
            call(client)

        star.override_command_timeout.assert_called_once_with(None)
        star.venus.send_command.assert_awaited_once()

    def test_tip_pool_show_tip_counter_disables_command_timeout(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pool_show_tip_counter(tip_pool="Pool1")

        assert result.success is True
        star.override_command_timeout.assert_called_once_with(None)
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="tipPool.showTipCounter",
            parameters={"tipPool": "Pool1"},
        )

    def test_tip_pool_show_tip_counters_with_pools_disables_command_timeout(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "tipCounters": [
                        {
                            "tipCounter": "tips300ul",
                            "totalAvailableTips": 72,
                            "availableTips": {"tip_rack_300ul_0001": {"count": 72, "positions": ["25", "26"]}},
                            "missingRacks": [],
                        },
                        {
                            "tipCounter": "tips50ul",
                            "totalAvailableTips": 96,
                            "availableTips": {"tip_rack_50ul_0001": {"count": 96, "positions": ["1", "2"]}},
                            "missingRacks": ["tip_rack_50ul_0002"],
                        },
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_pool_show_tip_counters(tip_pools=["300 uL Tips", "50 uL Tips"])

        assert result.success is True
        star.override_command_timeout.assert_called_once_with(None)
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="tipPool.showTipCounters",
            parameters={"tipPools": ["300 uL Tips", "50 uL Tips"]},
        )
        counters = result.return_parameters.tip_counters
        assert [c.tip_counter for c in counters] == ["tips300ul", "tips50ul"]
        assert counters[0].total_available_tips == 72
        assert counters[0].available_tips["tip_rack_300ul_0001"].count == 72
        assert counters[0].available_tips["tip_rack_300ul_0001"].positions == ["25", "26"]
        assert counters[0].missing_racks == []
        assert counters[1].missing_racks == ["tip_rack_50ul_0002"]

    def test_tip_pool_show_tip_counters_without_pools_omits_the_key(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pool_show_tip_counters()

        assert result.success is True
        assert result.return_parameters.tip_counters == []
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="tipPool.showTipCounters",
            parameters={},
        )
