"""Unit tests for MPH96CommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse, MPH96AspirateSettings, MPH96DispenseSettings
from hamilton_venus.models.enums import (
    AspirateMode,
    Axis,
    CapacitiveLLD,
    CoordinateMode,
    DispenseMode,
    EjectMode,
    MPH96Pattern,
    MPH96PreAirAspirate,
    MphPickupMode,
    MphPickupSide,
)
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


class TestMPH96Commands:
    def test_mph96_clear_tip_support(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"remainingTips": 96},
            )
        )

        with StarClient(config) as client:
            result = client.mph96_clear_tip_support(tip_pool="300ul tips")

        assert result.success is True
        assert result.return_parameters.remaining_tips == 96
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.clearTipSupport",
            parameters={"tipPool": "300ul tips"},
        )

    def test_get_status_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"mph96Status": {"x": 100.0, "y": 200.0, "z": 50.0, "tipLoaded": 1}},
            )
        )

        with StarClient(config) as client:
            result = client.get_status_mph96()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.getStatus",
        )
        status = result.return_parameters.mph96_status
        assert status.x == 100.0
        assert status.y == 200.0
        assert status.z == 50.0
        assert status.tip_loaded == 1

    def test_tip_pick_up_mph96_with_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pick_up_mph96(
                labware_id="TipRack1",
                pre_air_aspirate=MPH96PreAirAspirate.DISABLED,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.tipPickup",
            parameters={
                "labwareId": "TipRack1",
                "preAirAspirate": MPH96PreAirAspirate.DISABLED.value,
            },
        )

    def test_tip_pick_up_mph96_with_tip_pool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pick_up_mph96(
                tip_pool="TipPool1",
                pre_air_aspirate=MPH96PreAirAspirate.CUSTOM_VOLUME,
                pre_air_volume=50.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.tipPickup",
            parameters={
                "tipPool": "TipPool1",
                "preAirAspirate": MPH96PreAirAspirate.CUSTOM_VOLUME.value,
                "preAirVolume": 50.0,
            },
        )

    def test_tip_pick_up_mph96_partial(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pick_up_mph96_partial(
                mode=MphPickupMode.COLUMNS,
                count=1,
                tip_pool="TipPool1",
                mph_pickup_side=MphPickupSide.RIGHT,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.tipPickupPartial",
            parameters={
                "tipPool": "TipPool1",
                "mode": MphPickupMode.COLUMNS.value,
                "count": 1,
                "mphPickupSide": MphPickupSide.RIGHT.value,
                "preAirAspirate": MPH96PreAirAspirate.DISABLED.value,
            },
        )

    def test_tip_pick_up_mph96_partial_default_side(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pick_up_mph96_partial(
                mode=MphPickupMode.COLUMNS,
                count=4,
                tip_pool="TipPool1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.tipPickupPartial",
            parameters={
                "tipPool": "TipPool1",
                "mode": MphPickupMode.COLUMNS.value,
                "count": 4,
                "mphPickupSide": MphPickupSide.LEFT.value,
                "preAirAspirate": MPH96PreAirAspirate.DISABLED.value,
            },
        )

    def test_tip_eject_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_mph96(
                labware_id="Waste1",
                mph_pattern=MPH96Pattern.CUSTOM,
                mph_selection=["A1", "B1"],
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.tipEject",
            parameters={
                "labwareName": "Waste1",
                "mphPattern": MPH96Pattern.CUSTOM.value,
                "mphSelection": ["A1", "B1"],
                "ejectMode": EjectMode.WASTE.value,
            },
        )

    def test_aspirate_mph96_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.aspirate_mph96(
                labware_id="Plate1",
                volume=50.0,
                liquid_class="Water",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.aspirate",
            parameters={
                "labwareName": "Plate1",
                "volume": 50.0,
                "liquidClass": "Water",
                "aspirateMode": AspirateMode.NORMAL.value,
                "capacitiveLLD": CapacitiveLLD.OFF.value,
                "liquidFollowing": False,
                "tipTrackingFactor": 1.0,
                "submergeDepth": 2.0,
                "fixedHeight": 5.0,
                "mixCycles": 0,
                "mixPosition": 0.0,
                "mixVolume": 0.0,
                "airTransportRetractDist": 5.0,
            },
        )

    def test_aspirate_mph96_with_settings(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        plate_selection = [1, 1, 0, 0]

        with StarClient(config) as client:
            result = client.aspirate_mph96(
                labware_id="Plate1",
                mph_pattern=plate_selection,
                volume=100.0,
                liquid_class="CustomLiquid",
                settings=MPH96AspirateSettings(
                    aspirate_mode=AspirateMode.CONSECUTIVE,
                    capacitive_lld=CapacitiveLLD.MID,
                    liquid_following=True,
                    submerge_depth=1.5,
                    fixed_height=3.0,
                    mix_cycles=2,
                    mix_position=0.5,
                    mix_volume=30.0,
                    air_transport_retract_dist=10.0,
                ),
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.aspirate",
            parameters={
                "labwareName": "Plate1",
                "mphSelection": plate_selection,
                "volume": 100.0,
                "liquidClass": "CustomLiquid",
                "aspirateMode": AspirateMode.CONSECUTIVE.value,
                "capacitiveLLD": CapacitiveLLD.MID.value,
                "liquidFollowing": True,
                "tipTrackingFactor": 1.0,
                "submergeDepth": 1.5,
                "fixedHeight": 3.0,
                "mixCycles": 2,
                "mixPosition": 0.5,
                "mixVolume": 30.0,
                "airTransportRetractDist": 10.0,
            },
        )

    def test_dispense_mph96_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense_mph96(
                labware_id="Plate1",
                volume=50.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.dispense",
            parameters={
                "labwareName": "Plate1",
                "volume": 50.0,
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
                "useSideTouch": False,
                "minimizeZMove": False,
            },
        )

    def test_dispense_mph96_with_settings(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        plate_selection = [1, 0, 1, 0]

        with StarClient(config) as client:
            result = client.dispense_mph96(
                labware_id="Plate1",
                mph_pattern=plate_selection,
                volume=75.0,
                settings=MPH96DispenseSettings(
                    dispense_mode=DispenseMode.JET_EMPTY_TIP,
                    capacitive_lld=CapacitiveLLD.MID,
                    liquid_following=True,
                    submerge_depth=1.0,
                    fixed_height=3.5,
                    mix_cycles=3,
                    mix_position=1.0,
                    mix_volume=20.0,
                    air_transport_retract_dist=8.0,
                ),
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.dispense",
            parameters={
                "labwareName": "Plate1",
                "mphSelection": plate_selection,
                "volume": 75.0,
                "dispenseMode": DispenseMode.JET_EMPTY_TIP.value,
                "capacitiveLLD": CapacitiveLLD.MID.value,
                "liquidFollowing": True,
                "tipTrackingFactor": 1.0,
                "submergeDepth": 1.0,
                "fixedHeight": 3.5,
                "mixCycles": 3,
                "mixPosition": 1.0,
                "mixVolume": 20.0,
                "airTransportRetractDist": 8.0,
                "useSideTouch": False,
                "minimizeZMove": False,
            },
        )

    def test_aspirate_mph96_tip_tracking_factor(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            client.aspirate_mph96(labware_id="Plate1", volume=50.0, liquid_class="Water")
            default_params = star.venus.send_command.await_args.kwargs["parameters"]
            assert default_params["tipTrackingFactor"] == 1.0

            client.aspirate_mph96(
                labware_id="Plate1",
                volume=50.0,
                liquid_class="Water",
                settings=MPH96AspirateSettings(tip_tracking_factor=0.5),
            )
            assert star.venus.send_command.await_args.kwargs["parameters"]["tipTrackingFactor"] == 0.5

    def test_dispense_mph96_with_dispense_flags_in_settings(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense_mph96(
                labware_id="Plate1",
                volume=50.0,
                settings=MPH96DispenseSettings(
                    use_side_touch=True,
                    minimize_z_move=True,
                ),
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.dispense",
            parameters={
                "labwareName": "Plate1",
                "volume": 50.0,
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
                "useSideTouch": True,
                "minimizeZMove": True,
            },
        )

    def test_park_back_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_park_back()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.parkBack",
        )

    def test_park_front_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_park_front()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.parkFront",
        )

    def test_move_axis_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_move_axis(
                axis=Axis.Z,
                value=100.0,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
                mode=CoordinateMode.ABSOLUTE,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.moveAxis",
            parameters={
                "axis": Axis.Z.value,
                "value": 100.0,
                "mode": CoordinateMode.ABSOLUTE.value,
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )

    def test_move_axis_mph96_with_bypass(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_move_axis(
                axis=Axis.X,
                value=50.0,
                mode=CoordinateMode.RELATIVE,
                safety_bypass_token="OVERRIDE_SAFETY_CHECKS",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.moveAxis",
            parameters={
                "axis": Axis.X.value,
                "value": 50.0,
                "mode": CoordinateMode.RELATIVE.value,
                "safetyBypassToken": "OVERRIDE_SAFETY_CHECKS",
            },
        )

    def test_move_axis_mph96_without_safety_bypass_token(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_move_axis(axis=Axis.Z, value=100.0)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.moveAxis",
            parameters={
                "axis": Axis.Z.value,
                "value": 100.0,
                "mode": CoordinateMode.ABSOLUTE.value,
            },
        )

    def test_detect_liquid_level_mph96(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        plate_selection = [1, 1, 0, 0]

        with StarClient(config) as client:
            result = client.mph96_detect_liquid_level(
                labware_id="Plate1",
                mph_pattern=plate_selection,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.detectLiquidLevel",
            parameters={
                "labwareName": "Plate1",
                "mphSelection": plate_selection,
                "capacitiveLLD": CapacitiveLLD.MAX.value,
            },
        )

    def test_detect_liquid_level_mph96_defaults(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_detect_liquid_level(labware_id="Plate1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.detectLiquidLevel",
            parameters={
                "labwareName": "Plate1",
                "capacitiveLLD": CapacitiveLLD.MAX.value,
            },
        )

    def test_detect_liquid_level_mph96_custom_lld(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.mph96_detect_liquid_level(
                labware_id="Plate1",
                capacitive_lld=CapacitiveLLD.HIGH,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="mph96.detectLiquidLevel",
            parameters={
                "labwareName": "Plate1",
                "capacitiveLLD": CapacitiveLLD.HIGH.value,
            },
        )
