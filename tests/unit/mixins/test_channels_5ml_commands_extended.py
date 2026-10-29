"""Extended unit tests for Channels5mLCommandsMixin - edge cases and advanced scenarios."""

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
    AspirateMode,
    CapacitiveLLD,
    DispenseMode,
    PressureLLD,
    WellOrder,
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


class TestChannels5mLCommandsExtended:
    """Extended test suite for 5mL channel commands with edge cases."""

    # =========== Well Order Tests ===========
    def test_aspirate_5ml_with_row_order(self, config, mock_async_star_class):
        """Test aspirate with row-wise well ordering."""
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
                positions="Plate_1@A1:H1",
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                volumes=100.0,
                liquid_class="Water",
                well_order=WellOrder.ROW_ASC,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert "positions" in call_args.kwargs["parameters"]

    # =========== Dispense Mode Tests ===========
    def test_dispense_5ml_jet_part_mode(self, config, mock_async_star_class):
        """Test dispense with jet-partial mode."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            dispense_mode=DispenseMode.JET_PART_VOLUME,
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=50.0,
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["dispenseMode"] == DispenseMode.JET_PART_VOLUME

    def test_dispense_5ml_spray_mode(self, config, mock_async_star_class):
        """Test dispense with surface-part volume mode."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            dispense_mode=DispenseMode.SURFACE_PART_VOLUME,
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=25.0,
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["dispenseMode"] == DispenseMode.SURFACE_PART_VOLUME

    # =========== Aspirate Mode Tests ===========
    def test_aspirate_5ml_mode_air_gap(self, config, mock_async_star_class):
        """Test aspirate with aspirate-all mode."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            aspirate_mode=AspirateMode.ASPIRATE_ALL,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=200.0,
                liquid_class="Oil",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["aspirateMode"] == AspirateMode.ASPIRATE_ALL

    # =========== Mixing Settings Tests ===========
    def test_dispense_5ml_with_mixing(self, config, mock_async_star_class):
        """Test dispense with comprehensive mixing settings."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            mix_cycles=5,
            mix_volume=75.0,
            mix_position=2.0,
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2, 3],
                volumes=100.0,
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["mixCycles"] == 5
        assert call_args.kwargs["parameters"]["mixVolume"] == 75.0
        assert call_args.kwargs["parameters"]["mixPosition"] == 2.0

    # =========== Touch-off Settings Tests ===========
    def test_dispense_5ml_with_touchoff(self, config, mock_async_star_class):
        """Test dispense with touch-off settings."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            touch_off=True,
            touch_off_height=2.5,
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
        assert call_args.kwargs["parameters"]["touchOff"]
        assert call_args.kwargs["parameters"]["touchOffHeight"] == 2.5

    def test_dispense_5ml_with_side_touch(self, config, mock_async_star_class):
        """Test dispense with side-touch setting."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            use_side_touch=True,
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
        assert call_args.kwargs["parameters"]["useSideTouch"] is True

    # =========== Liquid Following Tests ===========
    def test_aspirate_5ml_with_liquid_following(self, config, mock_async_star_class):
        """Test aspirate with liquid following enabled."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            liquid_following=True,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=150.0,
                liquid_class="Water",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["liquidFollowing"] is True

    # =========== Submerge Depth Tests ===========
    def test_aspirate_5ml_with_submerge_depth(self, config, mock_async_star_class):
        """Test aspirate with custom submerge depth."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            submerge_depth=5.0,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=200.0,
                liquid_class="Water",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["submergeDepth"] == 5.0

    # =========== Fixed Height Tests ===========
    def test_aspirate_5ml_with_fixed_height(self, config, mock_async_star_class):
        """Test aspirate with fixed height instead of LLD."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            fixed_height=10.5,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["fixedHeight"] == 10.5

    # =========== Air Transport Tests ===========
    def test_dispense_5ml_with_air_transport(self, config, mock_async_star_class):
        """Test dispense with air transport retraction distance."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = DispenseSettings(
            air_transport_retract_dist=2.0,
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
        assert call_args.kwargs["parameters"]["airTransportRetractDist"] == 2.0

    # =========== Dispense On The Fly Advanced Tests ===========
    def test_dispense_on_the_fly_5ml_with_different_directions(self, config, mock_async_star_class):
        """Test dispense on the fly with different dispense directions."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.dispense_on_the_fly_5ml(
                channels=[1, 2],
                labware_name="plate 1",
                volumes=100.0,
                labware_surface_distance=3.0,
                dispense_direction=1,  # Different direction
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["dispenseDirection"] == 1

    def test_dispense_on_the_fly_5ml_with_custom_speed(self, config, mock_async_star_class):
        """Test dispense on the fly with custom X speed."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.dispense_on_the_fly_5ml(
                channels=[1, 2, 3],
                labware_name="plate 1",
                volumes=100.0,
                labware_surface_distance=3.0,
                x_speed=25.0,
                x_acceleration_distance=12.0,
                start_x_offset=5.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["xSpeed"] == 25.0
        assert call_args.kwargs["parameters"]["xAccelerationDistance"] == 12.0
        assert call_args.kwargs["parameters"]["startXOffset"] == 5.0

    # =========== DSL Position Selection Tests ===========
    def test_aspirate_5ml_dsl_row_selection(self, config, mock_async_star_class):
        """Test aspirate with row-based DSL position selection."""
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
                positions="Plate_1@row:A",
                channels=[1, 2, 3, 4, 5, 6, 7, 8],
                volumes=100.0,
                liquid_class="Water",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert "positions" in call_args.kwargs["parameters"]

    def test_aspirate_5ml_dsl_range_selection(self, config, mock_async_star_class):
        """Test aspirate with range-based DSL position selection."""
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
                positions="Plate_1@A1:H8",
                channels=[1, 2, 3, 4],
                volumes=100.0,
                liquid_class="Water",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert "positions" in call_args.kwargs["parameters"]

    # =========== Partial Channel Usage Tests ===========
    def test_aspirate_5ml_single_channel(self, config, mock_async_star_class):
        """Test aspirate using only a single channel."""
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
                channels=[1],
                volumes=50.0,
                liquid_class="Water",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1]

    def test_aspirate_5ml_four_channels(self, config, mock_async_star_class):
        """Test aspirate using only 4 channels in sequential mode."""
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
                channels=[1, 3, 5, 7],
                volumes=100.0,
                liquid_class="Water",
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1, 3, 5, 7]

    # =========== LLD Sensitivity Tests ===========
    def test_detect_liquid_level_5ml_low_sensitivity(self, config, mock_async_star_class):
        """Test LLD with low capacitive sensitivity."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.detect_liquid_level_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2, 3],
                capacitive_lld=CapacitiveLLD.LOW,
                pressure_lld=PressureLLD.LOW,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["capacitiveLLD"] == CapacitiveLLD.LOW
        assert call_args.kwargs["parameters"]["pressureLLD"] == PressureLLD.LOW

    def test_detect_liquid_level_5ml_capacitive_only(self, config, mock_async_star_class):
        """Test LLD with only capacitive detection."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.detect_liquid_level_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                capacitive_lld=CapacitiveLLD.HIGH,
                pressure_lld=PressureLLD.OFF,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["capacitiveLLD"] == CapacitiveLLD.HIGH
        assert call_args.kwargs["parameters"]["pressureLLD"] == PressureLLD.OFF

    # =========== Tip Pool Eject Variations ===========
    def test_tip_eject_5ml_all_channels_default(self, config, mock_async_star_class):
        """Test eject using default all-8-channels configuration."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml()

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert call_args.kwargs["parameters"]["ejectMode"] == "waste"

    def test_tip_eject_5ml_specific_channels(self, config, mock_async_star_class):
        """Test eject using specific subset of channels."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_eject_5ml(channels=[2, 4, 6, 8])

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [2, 4, 6, 8]

    # =========== Tip Pickup Variations ===========
    def test_tip_pickup_5ml_without_pool(self, config, mock_async_star_class):
        """Test picking tips without specifying a pool."""
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.tip_pickup_5ml(channels=[1, 2, 3])

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["channels"] == [1, 2, 3]
        assert "tipPool" not in call_args.kwargs["parameters"] or call_args.kwargs["parameters"]["tipPool"] is None

    # =========== Complex Settings Combination Tests ===========
    def test_aspirate_5ml_all_settings(self, config, mock_async_star_class):
        """Test aspirate with comprehensive AspirateSettings."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": []},
            )
        )

        settings = AspirateSettings(
            aspirate_mode=AspirateMode.ASPIRATE_ALL,
            capacitive_lld=CapacitiveLLD.HIGH,
            pressure_lld=PressureLLD.HIGH,
            liquid_following=True,
            submerge_depth=4.0,
            max_lld_difference=10.0,
            mix_cycles=3,
            mix_volume=50.0,
        )

        with StarClient(config) as client:
            result = client.aspirate_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=150.0,
                liquid_class="Water",
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["aspirateMode"] == AspirateMode.ASPIRATE_ALL
        assert call_args.kwargs["parameters"]["capacitiveLLD"] == CapacitiveLLD.HIGH
        assert call_args.kwargs["parameters"]["liquidFollowing"] is True

    def test_dispense_5ml_all_settings(self, config, mock_async_star_class):
        """Test dispense with comprehensive DispenseSettings."""
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
            capacitive_lld=CapacitiveLLD.MAX,
            liquid_following=False,
            submerge_depth=3.0,
            mix_cycles=2,
            mix_position=1.5,
            mix_volume=40.0,
            air_transport_retract_dist=1.5,
            touch_off=True,
            touch_off_height=2.0,
            use_side_touch=False,
        )

        with StarClient(config) as client:
            result = client.dispense_5ml(
                positions="Plate_1@col:1",
                channels=[1, 2, 3],
                volumes=100.0,
                settings=settings,
            )

        assert result.success is True
        call_args = star.venus.send_command.await_args
        assert call_args.kwargs["parameters"]["dispenseMode"] == DispenseMode.JET_EMPTY_TIP
        assert call_args.kwargs["parameters"]["touchOff"]
        assert not call_args.kwargs["parameters"]["useSideTouch"]
