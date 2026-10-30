"""Unit tests for ChannelCommandsMixin."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import (
    AspirateSettings,
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    CommandResponse,
    DispenseSettings,
    Position,
    WellOrder,
)
from hamilton_venus.models.enums import (
    AspirateMode,
    CapacitiveLLD,
    DispenseMode,
    EjectMode,
    PressureLLD,
)
from hamilton_venus.star_client import StarClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    from hamilton_venus.models.position import LabwareLayoutSpec

    _default_spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 8, "columns": 12}})
    with (
        patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls,
        patch.object(StarClient, "get_labware_spec", return_value=_default_spec),
    ):
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


class TestChannelCommands:
    def test_tip_check(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "activeChannels": [
                        {"channel": 1, "tipType": 300, "tipName": "300uL"},
                        {"channel": 2, "tipType": 300, "tipName": "300uL"},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_check()

        assert result.success is True
        assert len(result.return_parameters.active_channels) == 2
        assert result.return_parameters.active_channels[0].tip_name == "300uL"
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.1mL.tipCheck",
        )

    def test_dispense_on_the_fly(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense_on_the_fly(
                channels=[1, 2],
                labware_name="plate 1",
                volumes=[100.0, 110.0],
                labware_surface_distance=3.0,
                excluded_positions=["A1", "B1"],
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.1mL.dispenseOnTheFly",
            parameters={
                "channels": [1, 2],
                "labwareName": "plate 1",
                "volumes": [100.0, 110.0],
                "labwareSurfaceDistance": 3.0,
                "startXOffset": 0.0,
                "xSpeed": 0.0,
                "xAccelerationDistance": 8.0,
                "dispenseDirection": 0,
                "excludedPositions": ["A1", "B1"],
            },
        )

    def test_tip_pickup_with_positions(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup(channels=[1], positions=positions)

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1],
            "positions": [{"labwareId": "Plate1", "wellId": "A1"}],
        }

    def test_tip_pickup_expands_bare_labware_to_channel_count(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup(channels=[1, 2], positions="Trough_1")

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2],
            "positions": [
                {"labwareId": "Trough_1", "wellId": "A1"},
                {"labwareId": "Trough_1", "wellId": "B1"},
            ],
        }

    def test_tip_pickup_repeats_single_well_across_channels(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup(channels=[1, 2], positions="Plate1@A1")

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2],
            "positions": [
                {"labwareId": "Plate1", "wellId": "A1"},
                {"labwareId": "Plate1", "wellId": "A1"},
            ],
        }

    def test_tip_pickup_expands_row_selector_with_requested_order(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup(
                channels=[1, 2],
                positions="Plate1@row:A",
                well_order=WellOrder.ROW_DESC,
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2],
            "positions": [
                {"labwareId": "Plate1", "wellId": "A12"},
                {"labwareId": "Plate1", "wellId": "A11"},
            ],
        }

    def test_tip_pickup_with_tip_pool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup(
                channels=[1, 2, 3],
                tip_pool="TipPool1",
                optimized_pickup=True,
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2, 3],
            "tipPool": "TipPool1",
            "optimizedPickup": True,
        }

    def test_tip_pickup_rejects_position_count_mismatch(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(ValueError, match="expanded to 2 entries"):
            client.tip_pickup(channels=[1, 2, 3], positions="Plate1@A1,B1")

    def test_tip_eject_to_positions(self, config, mock_async_star_class):
        positions = [Position(labware="Waste1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject(channels=[1], eject_mode=EjectMode.POSITIONS, positions=positions)

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1],
            "ejectMode": EjectMode.POSITIONS.value,
            "positions": [{"labwareId": "Waste1", "wellId": "A1"}],
        }

    def test_tip_eject_to_default_waste(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject()

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2, 3, 4, 5, 6, 7, 8],
            "ejectMode": EjectMode.WASTE.value,
        }

    def test_aspirate_basic(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.aspirate(channels=[1], positions=positions, volumes=100.0, liquid_class="Water")

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"]["positions"] == [
            {"labwareId": "Plate1", "wellId": "A1"}
        ]
        assert star.venus.send_command.await_args.kwargs["parameters"]["fixedHeight"] == 5.0
        assert star.venus.send_command.await_args.kwargs["parameters"]["mixPosition"] == 0.0
        assert star.venus.send_command.await_args.kwargs["parameters"]["touchOffHeight"] == 1.0
        assert "wellOrder" not in star.venus.send_command.await_args.kwargs["parameters"]
        assert "madEnabled" not in star.venus.send_command.await_args.kwargs["parameters"]
        assert "madThreshold" not in star.venus.send_command.await_args.kwargs["parameters"]
        assert "ADC" not in star.venus.send_command.await_args.kwargs["parameters"]

    def test_aspirate_with_mad_and_adc(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.aspirate(
                channels=[1],
                positions=positions,
                volumes=100.0,
                liquid_class="Water",
                mad_enabled=True,
                mad_threshold=500,
                adc=True,
            )

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params["madEnabled"] is True
        assert params["madThreshold"] == 500
        assert params["ADC"] is True

    def test_aspirate_expands_selector_list(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.aspirate(
                channels=[1, 2, 3],
                positions=["Plate_A@A1:C1"],
                volumes=100.0,
                liquid_class="Water",
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"]["positions"] == [
            {"labwareId": "Plate_A", "wellId": "A1"},
            {"labwareId": "Plate_A", "wellId": "B1"},
            {"labwareId": "Plate_A", "wellId": "C1"},
        ]

    def _sent_parameters(self, star):
        return star.venus.send_command.await_args.kwargs["parameters"]

    def test_dispense_lists_are_indexed_by_channel_slot(self, config, mock_async_star_class):
        """A one-entry list for channel 7 must land in slot 7, not slot 1 (VENUS reads array[channel - 1])."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
        )
        with StarClient(config) as client:
            client.dispense(
                channels=[7],
                positions=[Position(labware="cellplate", well="A1")],
                volumes=[1000.0],
                settings=DispenseSettings(fixed_height=[20.0], liquid_following=[False]),
            )
        params = self._sent_parameters(star)
        assert params["channels"] == [7]
        assert params["volumes"] == [0.0] * 6 + [1000.0]
        assert params["fixedHeight"] == [0.0] * 6 + [20.0]
        assert params["liquidFollowing"] == [False] * 7

    def test_aspirate_lists_follow_channel_order_for_offset_channels(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
        )
        with StarClient(config) as client:
            client.aspirate(
                channels=[2, 4],
                positions=[Position(labware="P", well="A1"), Position(labware="P", well="B1")],
                volumes=[10.0, 20.0],
                liquid_class=["LcA", "LcB"],
            )
        params = self._sent_parameters(star)
        assert params["volumes"] == [0.0, 10.0, 0.0, 20.0]
        assert params["liquidClass"] == ["", "LcA", "", "LcB"]
        assert params["positions"] == [{"labwareId": "P", "wellId": "A1"}, {"labwareId": "P", "wellId": "B1"}]

    def test_scalar_per_channel_values_are_left_for_venus_to_broadcast(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
        )
        with StarClient(config) as client:
            client.dispense(
                channels=[7],
                positions=[Position(labware="cellplate", well="A1")],
                volumes=100.0,
                settings=DispenseSettings(fixed_height=20.0),
            )
        params = self._sent_parameters(star)
        assert params["volumes"] == 100.0
        assert params["fixedHeight"] == 20.0

    def test_list_length_must_match_channel_count(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(ValueError, match="fixed_height expected 1 entries"):
            client.dispense(
                channels=[7],
                positions=[Position(labware="cellplate", well="A1")],
                volumes=[100.0],
                settings=DispenseSettings(fixed_height=[20.0, 20.0]),
            )

    def test_move_axis_lists_are_indexed_by_channel_slot(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
        )
        with StarClient(config) as client:
            client.move_axis(channels=[2], y=[120.0], z=[200.0])
        params = self._sent_parameters(star)
        assert params["y"] == [0.0, 120.0]
        assert params["z"] == [0.0, 200.0]

    def test_aspirate_uses_settings(self, config, mock_async_star_class):
        positions = [Position(labware="DeepWell1", well="B2")]
        star = mock_async_star_class.return_value
        settings = AspirateSettings(
            aspirate_mode=AspirateMode.CONSECUTIVE,
            capacitive_lld=CapacitiveLLD.MID,
            pressure_lld=PressureLLD.HIGH,
            liquid_following=True,
            tip_tracking_factor=0.5,
            submerge_depth=3.0,
            fixed_height=2.0,
            max_lld_difference=1.0,
            mix_cycles=3,
            mix_position=1.0,
            mix_volume=25.0,
            air_transport_retract_dist=10.0,
            touch_off=1,
            touch_off_height=0.5,
        )

        with StarClient(config) as client:
            result = client.aspirate(
                channels=[1],
                positions=positions,
                volumes=[50.0],
                liquid_class="AqueousFree",
                settings=settings,
            )

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params["channels"] == [1]
        assert params["positions"] == [{"labwareId": "DeepWell1", "wellId": "B2"}]
        assert params["volumes"] == [50.0]
        assert params["liquidClass"] == "AqueousFree"
        assert params["aspirateMode"] == AspirateMode.CONSECUTIVE.value
        assert params["capacitiveLLD"] == CapacitiveLLD.MID.value
        assert params["pressureLLD"] == PressureLLD.HIGH.value
        assert params["liquidFollowing"] is True
        assert params["tipTrackingFactor"] == 0.5
        assert params["submergeDepth"] == 3.0
        assert params["fixedHeight"] == 2.0
        assert params["maxLLdDifference"] == 1.0
        assert params["mixCycles"] == 3
        assert params["mixPosition"] == 1.0
        assert params["mixVolume"] == 25.0
        assert params["airTransportRetractDist"] == 10.0
        assert params["touchOff"] == 1
        assert params["touchOffHeight"] == 0.5

    def test_aspirate_rejects_setting_kwargs(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(TypeError, match="unexpected keyword argument 'mix_cycles'"):
            cast(Any, client).aspirate(channels=[1], positions="Plate1@A1", liquid_class="Water", mix_cycles=2)

    def test_aspirate_tip_tracking_factor_defaults_to_one(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            client.aspirate(channels=[1], positions="Plate1@A1", volumes=50.0, liquid_class="Water")

        assert star.venus.send_command.await_args.kwargs["parameters"]["tipTrackingFactor"] == 1.0

    def test_dispense_tip_tracking_factor_passes_through(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            client.dispense(
                channels=[1],
                positions="Plate1@A1",
                volumes=50.0,
                settings=DispenseSettings(tip_tracking_factor=2.0),
            )

        assert star.venus.send_command.await_args.kwargs["parameters"]["tipTrackingFactor"] == 2.0

    def test_dispense(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense(channels=[1], positions=positions, volumes=100.0)

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params == {
            "channels": [1],
            "positions": [{"labwareId": "Plate1", "wellId": "A1"}],
            "volumes": 100.0,
            "dispenseMode": DispenseMode.FROM_LIQUID_CLASS.value,
            "capacitiveLLD": CapacitiveLLD.OFF.value,
            "liquidFollowing": False,
            "tipTrackingFactor": 1.0,
            "submergeDepth": 2.0,
            "fixedHeight": 5.0,
            "mixCycles": 0,
            "mixPosition": 0.0,
            "mixVolume": 0.0,
            "airTransportRetractDist": 5.0,
            "touchOff": 0,
            "touchOffHeight": 1.0,
            "useSideTouch": False,
        }

    def test_dispense_uses_settings(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value
        settings = DispenseSettings(
            dispense_mode=DispenseMode.SURFACE_PART_VOLUME,
            liquid_following=True,
            submerge_depth=3.0,
            fixed_height=2.0,
            mix_cycles=3,
            mix_position=1.0,
            mix_volume=25.0,
            air_transport_retract_dist=10.0,
            touch_off=1,
            touch_off_height=0.5,
        )

        with StarClient(config) as client:
            result = client.dispense(
                channels=[1],
                positions=positions,
                volumes=[100.0],
                settings=settings,
                adc=True,
            )

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params == {
            "channels": [1],
            "positions": [{"labwareId": "Plate1", "wellId": "A1"}],
            "volumes": [100.0],
            "dispenseMode": DispenseMode.SURFACE_PART_VOLUME.value,
            "capacitiveLLD": CapacitiveLLD.OFF.value,
            "liquidFollowing": True,
            "tipTrackingFactor": 1.0,
            "submergeDepth": 3.0,
            "fixedHeight": 2.0,
            "mixCycles": 3,
            "mixPosition": 1.0,
            "mixVolume": 25.0,
            "airTransportRetractDist": 10.0,
            "touchOff": 1,
            "touchOffHeight": 0.5,
            "useSideTouch": False,
            "ADC": True,
        }

    def test_dispense_expands_selector_list(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense(
                channels=[1, 2, 3],
                positions=["Plate_A@A1:C1"],
                volumes=[100.0, 110.0, 120.0],
                settings=DispenseSettings(
                    dispense_mode=DispenseMode.JET_EMPTY_TIP,
                ),
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1, 2, 3],
            "positions": [
                {"labwareId": "Plate_A", "wellId": "A1"},
                {"labwareId": "Plate_A", "wellId": "B1"},
                {"labwareId": "Plate_A", "wellId": "C1"},
            ],
            "volumes": [100.0, 110.0, 120.0],
            "dispenseMode": DispenseMode.JET_EMPTY_TIP.value,
            "capacitiveLLD": CapacitiveLLD.OFF.value,
            "liquidFollowing": False,
            "tipTrackingFactor": 1.0,
            "submergeDepth": 2.0,
            "fixedHeight": 5.0,
            "mixCycles": 0,
            "mixPosition": 0.0,
            "mixVolume": 0.0,
            "airTransportRetractDist": 5.0,
            "touchOff": 0,
            "touchOffHeight": 1.0,
            "useSideTouch": False,
        }

    def test_move_axis_absolute(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channelStatus": [{"channel": 1, "x": 200.0, "y": 500.0, "z": 100.0}]},
            )
        )

        with StarClient(config) as client:
            result = client.move_axis(
                channels=[1, 2],
                x=200.0,
                y=[500.0, 491.0],
                z=100.0,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.1mL.moveAxis",
            parameters={
                "channels": [1, 2],
                "x": 200.0,
                "y": [500.0, 491.0],
                "z": 100.0,
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )

    def test_move_axis_without_safety_bypass_token(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channelStatus": []},
            )
        )

        with StarClient(config) as client:
            result = client.move_axis(channels=[1], z=100.0)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.1mL.moveAxis",
            parameters={"channels": [1], "z": 100.0},
        )

    def test_get_status(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channelStatus": [
                        {"channel": 1, "x": 200.0, "y": 500.0, "z": 100.0, "tipLoaded": 1},
                        {"channel": 2, "x": 200.0, "y": 491.0, "z": 100.0, "tipLoaded": 0},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_status()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.1mL.getStatus",
        )
        statuses = result.return_parameters.channel_status
        assert statuses[0].channel == 1
        assert statuses[0].x == 200.0
        assert statuses[0].tip_loaded == 1
        assert statuses[1].tip_loaded == 0

    def test_move_axis_5ml_absolute(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channelStatus": [{"channel": 1, "x": 200.0, "y": 500.0, "z": 245.0}]},
            )
        )

        with StarClient(config) as client:
            result = client.move_axis_5ml(
                channels=[1, 2, 3, 4],
                x=200.0,
                y=[500.0, 491.0, 482.0, 473.0],
                z=245.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.moveAxis",
            parameters={
                "channels": [1, 2, 3, 4],
                "x": 200.0,
                "y": [500.0, 491.0, 482.0, 473.0],
                "z": 245.0,
            },
        )

    def test_get_status_5ml(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channelStatus": [
                        {"channel": 1, "x": 200.0, "y": 500.0, "z": 245.0, "tipLoaded": 1},
                        {"channel": 2, "x": 200.0, "y": 491.0, "z": 245.0, "tipLoaded": 0},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_status_5ml()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.getStatus",
        )
        statuses = result.return_parameters.channel_status
        assert statuses[0].channel == 1
        assert statuses[0].x == 200.0
        assert statuses[0].tip_loaded == 1
        assert statuses[1].tip_loaded == 0

    def test_move_axis_relative_computes_absolute_from_status(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        status_response = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "channelStatus": [
                    {"channel": 1, "x": 200.0, "y": 500.0, "z": 100.0, "tipLoaded": 0},
                    {"channel": 2, "x": 200.0, "y": 491.0, "z": 110.0, "tipLoaded": 0},
                ]
            },
        )
        move_response = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"channelStatus": []},
        )
        star.venus.send_command = AsyncMock(side_effect=[status_response, move_response])

        with StarClient(config) as client:
            result = client.move_axis_relative(
                channels=[1, 2],
                x=10.0,
                y=[1.0, -2.0],
                z=5.0,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        assert result.success is True
        assert star.venus.send_command.await_count == 2

        status_call, move_call = star.venus.send_command.await_args_list
        assert status_call.kwargs["action_name"] == "channels.1mL.getStatus"
        assert move_call.kwargs["action_name"] == "channels.1mL.moveAxis"
        assert move_call.kwargs["parameters"] == {
            "channels": [1, 2],
            "x": 210.0,
            "y": [501.0, 489.0],
            "z": [105.0, 115.0],
            "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
        }

    def test_move_axis_relative_single_channel_int(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        status_response = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"channelStatus": [{"channel": 3, "x": 50.0, "y": 60.0, "z": 70.0, "tipLoaded": 0}]},
        )
        move_response = CommandResponse(return_status="Success", return_code=0, return_parameters={})
        star.venus.send_command = AsyncMock(side_effect=[status_response, move_response])

        with StarClient(config) as client:
            result = client.move_axis_relative(
                channels=3,
                z=-5.0,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        assert result.success is True
        move_call = star.venus.send_command.await_args_list[1]
        assert move_call.kwargs["parameters"] == {
            "channels": [3],
            "z": [0.0, 0.0, 65.0],
            "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
        }

    def test_move_axis_relative_missing_channel_in_status_raises(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        status_response = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"channelStatus": [{"channel": 1, "x": 200.0, "y": 500.0, "z": 100.0, "tipLoaded": 0}]},
        )
        star.venus.send_command = AsyncMock(return_value=status_response)

        with StarClient(config) as client, pytest.raises(ValueError, match=r"channel\(s\) \[2\]"):
            client.move_axis_relative(
                channels=[1, 2],
                z=5.0,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        # Only get_status() should have been called; move_axis() must not fire.
        star.venus.send_command.assert_awaited_once()

    def test_detect_liquid_level_basic(self, config, mock_async_star_class):
        positions = [Position(labware="Plate1", well="A1")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.detect_liquid_level(channels=[1], positions=positions)

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"]["positions"] == [
            {"labwareId": "Plate1", "wellId": "A1"}
        ]
        assert "wellOrder" not in star.venus.send_command.await_args.kwargs["parameters"]

    def test_detect_liquid_level_expands_selector_with_descending_order(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.detect_liquid_level(
                channels=[1, 2],
                positions="Plate1@row:A",
                well_order=WellOrder.ROW_DESC,
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"]["positions"] == [
            {"labwareId": "Plate1", "wellId": "A12"},
            {"labwareId": "Plate1", "wellId": "A11"},
        ]

    def test_detect_liquid_level_with_all_params(self, config, mock_async_star_class):
        positions = [Position(labware="DeepWell1", well="B2")]
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.detect_liquid_level(
                channels=[1],
                positions=positions,
                capacitive_lld=CapacitiveLLD.MID,
                pressure_lld=PressureLLD.HIGH,
            )

        assert result.success is True
        assert star.venus.send_command.await_args.kwargs["parameters"] == {
            "channels": [1],
            "positions": [{"labwareId": "DeepWell1", "wellId": "B2"}],
            "capacitiveLLD": CapacitiveLLD.MID.value,
            "pressureLLD": PressureLLD.HIGH.value,
        }

    def test_aspirate_uses_mixed_scalar_and_per_channel_inputs(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        settings = AspirateSettings(
            aspirate_mode=AspirateMode.CONSECUTIVE,
            capacitive_lld=CapacitiveLLD.HIGH,
            pressure_lld=PressureLLD.MID,
            liquid_following=False,
            touch_off=[0, 1],
        )

        with StarClient(config) as client:
            result = client.aspirate(
                channels=[1, 2],
                positions="Plate1@A1:B1",
                volumes=[10.0, 20.0],
                liquid_class="Water_DispenseJet_Empty",
                settings=settings,
            )

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params["positions"] == [
            {"labwareId": "Plate1", "wellId": "A1"},
            {"labwareId": "Plate1", "wellId": "B1"},
        ]
        assert params["volumes"] == [10.0, 20.0]
        assert params["liquidClass"] == "Water_DispenseJet_Empty"
        assert params["aspirateMode"] == AspirateMode.CONSECUTIVE.value
        assert params["capacitiveLLD"] == CapacitiveLLD.HIGH.value
        assert params["pressureLLD"] == PressureLLD.MID.value
        assert params["liquidFollowing"] is False
        assert params["touchOff"] == [0, 1]

    def test_aspirate_rejects_per_channel_length_mismatch(self, config, mock_async_star_class):
        settings = AspirateSettings(submerge_depth=[2.0])

        with StarClient(config) as client, pytest.raises(ValueError, match="submerge_depth expected 2 entries"):
            client.aspirate(
                channels=[1, 2],
                positions="Plate1@A1:B1",
                volumes=50.0,
                liquid_class="Water",
                settings=settings,
            )

    def test_dispense_supports_mixed_scalar_and_per_channel_inputs(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        settings = DispenseSettings(
            dispense_mode=DispenseMode.SURFACE_PART_VOLUME,
            liquid_following=[False, True],
            touch_off=[0, 1],
        )

        with StarClient(config) as client:
            result = client.dispense(
                channels=[1, 2],
                positions="Plate1@A1:B1",
                volumes=50.0,
                settings=settings,
            )

        assert result.success is True
        params = star.venus.send_command.await_args.kwargs["parameters"]
        assert params == {
            "channels": [1, 2],
            "positions": [
                {"labwareId": "Plate1", "wellId": "A1"},
                {"labwareId": "Plate1", "wellId": "B1"},
            ],
            "volumes": 50.0,
            "dispenseMode": DispenseMode.SURFACE_PART_VOLUME.value,
            "capacitiveLLD": CapacitiveLLD.OFF.value,
            "liquidFollowing": [False, True],
            "tipTrackingFactor": 1.0,
            "submergeDepth": 2.0,
            "fixedHeight": 5.0,
            "mixCycles": 0,
            "mixPosition": 0.0,
            "mixVolume": 0.0,
            "airTransportRetractDist": 5.0,
            "touchOff": [0, 1],
            "touchOffHeight": 1.0,
            "useSideTouch": False,
        }


class TestChannelAspirationResponse:
    def test_aspirate_returns_typed_response_with_channel_data(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "aspiratedVolume": 100.0,
                            "liquidLevel_mm": 0.5,
                            "liquidVolume_uL": 150.0,
                        },
                        {
                            "channel": 2,
                            "aspiratedVolume": 100.0,
                            "liquidLevel_mm": 0.3,
                            "liquidVolume_uL": 145.0,
                        },
                    ],
                    "TADM": {"tadmCurves": []},
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1"), Position(labware="Plate1", well="B1")]

        with StarClient(config) as client:
            result = client.aspirate(channels=[1, 2], positions=positions, volumes=100.0, liquid_class="Water")

        assert isinstance(result, ChannelAspirationResponse)
        assert result.success is True
        assert len(result.return_parameters.channels) == 2
        assert result.return_parameters.channels[0].channel == 1
        assert result.return_parameters.channels[0].aspirated_volume == 100.0
        assert result.return_parameters.channels[0].liquid_level_mm == 0.5
        assert result.return_parameters.channels[0].liquid_volume_ul == 150.0

    def test_aspirate_response_provides_access_to_tadm_curves(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "aspiratedVolume": 100.0,
                            "liquidLevel_mm": 0.5,
                            "liquidVolume_uL": 150.0,
                        }
                    ],
                    "TADM": {
                        "tadmCurves": [
                            {
                                "curveId": 2587,
                                "liquidClassName": "TestClass",
                                "stepType": 0,
                                "stepTypeName": "Aspirating",
                                "volume": 50.0,
                                "timeStamp": "2026-05-20 17:30:50",
                                "stepGuid": "test-guid",
                                "toleranceBandGuid": "test-tolerance-guid",
                                "stepNumber": 7166,
                                "curvePoints": [{"timeMs": -340, "pressure": -29}],
                                "error": 0,
                                "channelNumber": 1,
                                "tadmMode": 1,
                                "curveFlagged": 0,
                                "checkSum": -1110657860,
                            }
                        ]
                    },
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1")]

        with StarClient(config) as client:
            result = client.aspirate(channels=[1], positions=positions, volumes=100.0, liquid_class="Water")

        assert isinstance(result, ChannelAspirationResponse)
        assert result.return_parameters.tadm is not None
        assert len(result.return_parameters.tadm.tadm_curves) == 1
        curve = result.return_parameters.tadm.tadm_curves[0]
        assert curve.curve_id == 2587
        assert curve.liquid_class_name == "TestClass"
        assert curve.volume == 50.0

    def test_aspirate_response_tadm_is_none_when_absent(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "aspiratedVolume": 100.0,
                            "liquidLevel_mm": 0.5,
                            "liquidVolume_uL": 150.0,
                        }
                    ],
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1")]

        with StarClient(config) as client:
            result = client.aspirate(channels=[1], positions=positions, volumes=100.0, liquid_class="Water")

        assert isinstance(result, ChannelAspirationResponse)
        assert result.return_parameters.tadm is None


class TestChannelDispenseResponse:
    def test_dispense_returns_typed_response_with_channel_data(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "dispensedVolume": 100.0,
                        },
                        {
                            "channel": 2,
                            "dispensedVolume": 95.0,
                        },
                    ],
                    "TADM": {"tadmCurves": []},
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1"), Position(labware="Plate1", well="B1")]

        with StarClient(config) as client:
            result = client.dispense(channels=[1, 2], positions=positions, volumes=100.0)

        assert isinstance(result, ChannelDispenseResponse)
        assert result.success is True
        assert len(result.return_parameters.channels) == 2
        assert result.return_parameters.channels[0].channel == 1
        assert result.return_parameters.channels[0].dispensed_volume == 100.0
        assert result.return_parameters.channels[1].channel == 2
        assert result.return_parameters.channels[1].dispensed_volume == 95.0

    def test_dispense_response_provides_access_to_tadm_curves(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "dispensedVolume": 100.0,
                        }
                    ],
                    "TADM": {
                        "tadmCurves": [
                            {
                                "curveId": 2588,
                                "liquidClassName": "DispenseClass",
                                "stepType": 1,
                                "stepTypeName": "Dispensing",
                                "volume": 100.0,
                                "timeStamp": "2026-05-20 17:30:50",
                                "stepGuid": "dispense-guid",
                                "toleranceBandGuid": "dispense-tolerance-guid",
                                "stepNumber": 7167,
                                "curvePoints": [{"timeMs": 100, "pressure": 50}],
                                "error": 0,
                                "channelNumber": 1,
                                "tadmMode": 1,
                                "curveFlagged": 0,
                                "checkSum": 123456789,
                            }
                        ]
                    },
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1")]

        with StarClient(config) as client:
            result = client.dispense(channels=[1], positions=positions, volumes=100.0)

        assert isinstance(result, ChannelDispenseResponse)
        assert result.return_parameters.tadm is not None
        assert len(result.return_parameters.tadm.tadm_curves) == 1
        curve = result.return_parameters.tadm.tadm_curves[0]
        assert curve.curve_id == 2588
        assert curve.liquid_class_name == "DispenseClass"
        assert curve.volume == 100.0
        assert curve.step_type_name == "Dispensing"

    def test_dispense_response_tadm_is_none_when_absent(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {
                            "channel": 1,
                            "dispensedVolume": 100.0,
                        }
                    ],
                },
            )
        )
        positions = [Position(labware="Plate1", well="A1")]

        with StarClient(config) as client:
            result = client.dispense(channels=[1], positions=positions, volumes=100.0)

        assert isinstance(result, ChannelDispenseResponse)
        assert result.return_parameters.tadm is None
