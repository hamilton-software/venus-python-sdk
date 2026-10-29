"""Unit tests for Channels5mLCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import (
    AspirateSettings,
    CommandResponse,
    DispenseSettings,
)
from hamilton_venus.models.enums import (
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


class TestChannels5mLCommands:
    """Test suite for 5mL channel commands."""

    # =========== Tip Pickup Tests ===========
    def test_tip_pickup_5ml_with_pool(self, config, mock_async_star_class):
        """Test picking 5mL tips from a managed pool."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup_5ml(channels=[1, 2, 3], tip_pool="TransferTips")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.tipPickup",
            parameters={
                "channels": [1, 2, 3],
                "tipPool": "TransferTips",
                "optimizedPickup": True,
            },
        )

    def test_tip_pickup_5ml_defaults(self, config, mock_async_star_class):
        """Test that tip_pickup_5ml defaults to all 8 channels."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup_5ml(tip_pool="TransferTips")

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_tip_pickup_5ml_optimized_false(self, config, mock_async_star_class):
        """Test disabling optimized pickup for 5mL tips."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup_5ml(channels=[1, 2], tip_pool="TransferTips", optimized_pickup=False)

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["optimizedPickup"] is False

    def test_tip_pickup_5ml_with_positions(self, config, mock_async_star_class):
        """Test picking 5mL tips from explicit positions."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup_5ml(
                channels=[1, 2, 3],
                positions=[
                    {"labwareId": "TipRack_1", "wellId": "A1"},
                    {"labwareId": "TipRack_1", "wellId": "A2"},
                    {"labwareId": "TipRack_1", "wellId": "A3"},
                ],
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["action_name"] == "channels.5mL.tipPickup"
        assert "positions" in call_args.kwargs["parameters"]

    # =========== Tip Eject Tests ===========
    def test_tip_eject_5ml_waste(self, config, mock_async_star_class):
        """Test ejecting 5mL tips to waste (default)."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml(channels=[1, 2, 3])

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.tipEject",
            parameters={
                "channels": [1, 2, 3],
                "ejectMode": "waste",
            },
        )

    def test_tip_eject_5ml_return(self, config, mock_async_star_class):
        """Test returning 5mL tips to pickup position."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml(channels=[1, 2, 3], eject_mode=EjectMode.RETURN)

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["ejectMode"] == "return"

    def test_tip_eject_5ml_to_pool(self, config, mock_async_star_class):
        """Test returning 5mL tips to a tip pool."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml(
                channels=[1, 2, 3],
                eject_mode=EjectMode.TIP_POOL,
                tip_pool="TransferTips",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["ejectMode"] == "tipPool"
        assert call_args.kwargs["parameters"]["tipPool"] == "TransferTips"

    def test_tip_eject_5ml_to_positions(self, config, mock_async_star_class):
        """Test ejecting 5mL tips to explicit positions."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml(
                channels=[1, 2, 3],
                eject_mode=EjectMode.POSITIONS,
                positions=[
                    {"labwareId": "TipRack_1", "wellId": "A1"},
                    {"labwareId": "TipRack_1", "wellId": "A2"},
                    {"labwareId": "TipRack_1", "wellId": "A3"},
                ],
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["ejectMode"] == "positions"
        assert "positions" in call_args.kwargs["parameters"]

    # =========== Tip Check Tests ===========
    def test_tip_check_5ml(self, config, mock_async_star_class):
        """Test checking active 5mL channel tips."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "activeChannels": [
                        {"channel": 1, "tipType": 5000, "tipName": "5mL Volume Tip"},
                        {"channel": 2, "tipType": 5000, "tipName": "5mL Volume Tip"},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.tip_check_5ml()

        assert result.success is True
        assert len(result.return_parameters.active_channels) == 2
        assert result.return_parameters.active_channels[0].tip_name == "5mL Volume Tip"
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.tipCheck",
        )

    # =========== Aspirate Tests ===========
    def test_aspirate_5ml_basic(self, config, mock_async_star_class):
        """Test basic aspiration with 5mL channels."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {"channel": 1, "aspiratedVolume": 100},
                        {"channel": 2, "aspiratedVolume": 100},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["action_name"] == "channels.5mL.aspirate"
        assert call_args.kwargs["parameters"]["channels"] == [1, 2]
        assert call_args.kwargs["parameters"]["volumes"] == 100.0

    def test_aspirate_5ml_per_channel_volumes(self, config, mock_async_star_class):
        """Test aspirate with per-channel volume control."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=[100.0, 150.0],
                liquid_class="Water_DispenseJet_Empty",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["volumes"] == [100.0, 150.0]

    def test_aspirate_5ml_with_settings(self, config, mock_async_star_class):
        """Test aspirate with custom AspirateSettings."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            capacitive_lld=CapacitiveLLD.MAX,
            mix_cycles=3,
            mix_volume=50.0,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["capacitiveLLD"] == CapacitiveLLD.MAX
        assert call_args.kwargs["parameters"]["mixCycles"] == 3

    def test_aspirate_5ml_with_mad_and_adc(self, config, mock_async_star_class):
        """Test aspirate with MAD and ADC parameters."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
                mad_enabled=True,
                mad_threshold=200,
                adc=True,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["madEnabled"] is True
        assert call_args.kwargs["parameters"]["madThreshold"] == 200
        assert call_args.kwargs["parameters"]["ADC"] is True

    def test_aspirate_5ml_per_channel_mismatch(self, config, mock_async_star_class):
        """Test aspirate raises error on per-channel volume/channel count mismatch."""
        with StarClient(config) as client, pytest.raises(ValueError, match="volumes expected 2 entries"):
            client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=[100.0, 150.0, 200.0],
                liquid_class="Water_DispenseJet_Empty",
            )

    def test_aspirate_5ml_channel_validation(self, config, mock_async_star_class):
        """Test aspirate raises error when exceeding max 5mL channels."""
        with StarClient(config) as client, pytest.raises(ValueError, match="5mL support a maximum of 16"):
            client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=list(range(1, 18)),
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
            )

    # =========== Dispense Tests ===========
    def test_dispense_5ml_basic(self, config, mock_async_star_class):
        """Test basic dispensing with 5mL channels."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "channels": [
                        {"channel": 1, "dispensedVolume": 100},
                        {"channel": 2, "dispensedVolume": 100},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["action_name"] == "channels.5mL.dispense"
        assert call_args.kwargs["parameters"]["channels"] == [1, 2]

    def test_dispense_5ml_with_settings(self, config, mock_async_star_class):
        """Test dispense with custom DispenseSettings."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            dispense_mode=DispenseMode.JET_EMPTY_TIP,
            mix_cycles=2,
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["dispenseMode"] == DispenseMode.JET_EMPTY_TIP
        assert call_args.kwargs["parameters"]["mixCycles"] == 2

    def test_dispense_5ml_with_adc(self, config, mock_async_star_class):
        """Test dispense with the ADC parameter."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                adc=True,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["ADC"] is True

    def test_dispense_5ml_defaults(self, config, mock_async_star_class):
        """Test that dispense_5ml defaults to all 8 channels."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                volumes=100.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1, 2, 3, 4, 5, 6, 7, 8]

    # =========== Liquid Level Detection Tests ===========
    def test_detect_liquid_level_5ml(self, config, mock_async_star_class):
        """Test liquid level detection with 5mL channels."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.detect_liquid_level_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                capacitive_lld=CapacitiveLLD.MAX,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["action_name"] == "channels.5mL.detectLiquidLevel"
        assert call_args.kwargs["parameters"]["channels"] == [1, 2]
        assert call_args.kwargs["parameters"]["capacitiveLLD"] == CapacitiveLLD.MAX
        assert call_args.kwargs["parameters"]["pressureLLD"] == PressureLLD.OFF
        assert "positions" in call_args.kwargs["parameters"]

    def test_detect_liquid_level_5ml_with_pressure_lld(self, config, mock_async_star_class):
        """Test liquid level detection with pressure LLD."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.detect_liquid_level_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                capacitive_lld=CapacitiveLLD.HIGH,
                pressure_lld=PressureLLD.MAX,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["pressureLLD"] == PressureLLD.MAX

    # =========== Dispense On The Fly Tests ===========
    def test_dispense_on_the_fly_5ml(self, config, mock_async_star_class):
        """Test dispense on the fly with 5mL channels."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense_on_the_fly_5ml(
                channels=[1, 2],
                labware_name="plate 1",
                volumes=100.0,
                labware_surface_distance=3.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.5mL.dispenseOnTheFly",
            parameters={
                "channels": [1, 2],
                "labwareName": "plate 1",
                "volumes": 100.0,
                "labwareSurfaceDistance": 3.0,
                "startXOffset": 0.0,
                "xSpeed": 0.0,
                "xAccelerationDistance": 8.0,
                "dispenseDirection": 0,
                "excludedPositions": [],
            },
        )

    def test_dispense_on_the_fly_5ml_with_excluded_positions(self, config, mock_async_star_class):
        """Test dispense on the fly with excluded positions."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.dispense_on_the_fly_5ml(
                channels=[1, 2],
                labware_name="plate 1",
                volumes=[100.0, 110.0],
                labware_surface_distance=3.0,
                excluded_positions=["A1", "B1"],
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["excludedPositions"] == ["A1", "B1"]
        assert call_args.kwargs["parameters"]["volumes"] == [100.0, 110.0]

    # =========== Action Name Verification Tests ===========
    def test_action_names_are_5ml_format(self, config, mock_async_star_class):
        """Verify all 5mL command action names use channels.5mL.* format."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        action_names = []

        with StarClient(config) as client:
            client.tip_pickup_5ml(tip_pool="Test")
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.tip_eject_5ml()
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.aspirate_5ml(
                positions="Plate_1@col:1",
                volumes=100.0,
                liquid_class="Test",
            )
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.dispense_5ml(positions="Plate_1@col:1", volumes=100.0)
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.detect_liquid_level_5ml(positions="Plate_1@col:1")
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.tip_check_5ml()
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

            client.dispense_on_the_fly_5ml(
                channels=[1],
                labware_name="test",
                volumes=100.0,
                labware_surface_distance=3.0,
            )
            action_names.append(star.venus.send_command.await_args.kwargs["action_name"])

        expected_actions = [
            "channels.5mL.tipPickup",
            "channels.5mL.tipEject",
            "channels.5mL.aspirate",
            "channels.5mL.dispense",
            "channels.5mL.detectLiquidLevel",
            "channels.5mL.tipCheck",
            "channels.5mL.dispenseOnTheFly",
        ]

        assert action_names == expected_actions
