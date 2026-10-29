"""Unit tests for DeckLabwareCommandsMixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.mixins.deck_labware_commands import DeckLabwareCommandsMixin
from hamilton_venus.models import CommandResponse, LayoutAddTubesToCarrierResponse, LayoutShiftLabwareResponse
from hamilton_venus.models.enums import CoreGripType, QCGType
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


class TestDeckLabwareCommands:
    def test_deck_add_carrier(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_carrier(
                labware_definition="TIP_CAR_480BC_A00",
                left_track=1,
                labware_id="Carrier1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addCarrier",
            parameters={
                "labwareName": "Carrier1",
                "labwareDefinition": "TIP_CAR_480BC_A00",
                "leftTrack": 1,
            },
        )

    def test_deck_add_carrier_to_site(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_carrier_to_site(
                labware_definition="TIP_CAR_480BC_A00",
                carrier_id="Carrier1",
                site="1",
                labware_id="SubCarrier1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addCarrierToSite",
            parameters={
                "labwareName": "SubCarrier1",
                "labwareDefinition": "TIP_CAR_480BC_A00",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_carrier_to_site_no_labware_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_carrier_to_site(
                labware_definition="TIP_CAR_480BC_A00",
                carrier_id="Carrier1",
                site="1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addCarrierToSite",
            parameters={
                "labwareDefinition": "TIP_CAR_480BC_A00",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_carrier_no_labware_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_carrier(
                labware_definition="TIP_CAR_480BC_A00",
                left_track=1,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addCarrier",
            parameters={
                "labwareDefinition": "TIP_CAR_480BC_A00",
                "leftTrack": 1,
            },
        )

    def test_deck_add_tube_carrier(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tube_carrier(
                labware_definition="SMP_CAR_24_17x75_A00",
                left_track=10,
                labware_id="TubeCarrier1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addSampleTubeCarrier",
            parameters={
                "labwareName": "TubeCarrier1",
                "labwareDefinition": "SMP_CAR_24_17x75_A00",
                "leftTrack": 10,
            },
        )

    def test_deck_add_tube_carrier_no_carrier_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tube_carrier(
                labware_definition="SMP_CAR_24_17x75_A00",
                left_track=10,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addSampleTubeCarrier",
            parameters={
                "labwareDefinition": "SMP_CAR_24_17x75_A00",
                "leftTrack": 10,
            },
        )

    def test_deck_add_tip_rack(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_rack(
                labware_definition="ST_L",
                carrier_id="Carrier1",
                site="1",
                tip_pool="TipPool1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipRack",
            parameters={
                "tipPool": "TipPool1",
                "labwareDefinition": "ST_L",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_tip_rack_without_tip_pool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_rack(
                labware_definition="ST_L",
                carrier_id="Carrier1",
                site="1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipRack",
            parameters={
                "labwareDefinition": "ST_L",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_tip_rack_with_labware_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_rack(
                labware_definition="ST_L",
                carrier_id="Carrier1",
                site="1",
                tip_pool="TipPool1",
                labware_id="MyTipRack",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipRack",
            parameters={
                "tipPool": "TipPool1",
                "labwareDefinition": "ST_L",
                "carrier": "Carrier1",
                "site": "1",
                "labwareName": "MyTipRack",
            },
        )

    def test_deck_add_tip_box(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_box(
                labware_definition="ST_L",
                carrier_id="Carrier1",
                site="5",
                tip_pool="300 uL Tips",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipBox",
            parameters={
                "tipPool": "300 uL Tips",
                "labwareDefinition": "ST_L",
                "carrier": "Carrier1",
                "site": "5",
            },
        )

    def test_deck_add_tip_box_without_tip_pool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_box(
                labware_definition="ST_L",
                carrier_id="Carrier1",
                site="5",
                labware_id="MyTipBox",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipBox",
            parameters={
                "labwareDefinition": "ST_L",
                "carrier": "Carrier1",
                "site": "5",
                "labwareName": "MyTipBox",
            },
        )

    def test_deck_add_plate(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_plate(
                labware_definition="Nun_96_Fl_HB",
                carrier_id="Carrier1",
                site="1",
                plate_id="Plate1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addPlate",
            parameters={
                "labwareName": "Plate1",
                "labwareDefinition": "Nun_96_Fl_HB",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_plate_no_plate_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_plate(
                labware_definition="Nun_96_Fl_HB",
                carrier_id="Carrier1",
                site="1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addPlate",
            parameters={
                "labwareDefinition": "Nun_96_Fl_HB",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_reservoir(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_reservoir(
                labware_definition="RES_CAR_8x100ml",
                carrier_id="Carrier1",
                site="1",
                labware_id="Reservoir1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addReservoir",
            parameters={
                "labwareName": "Reservoir1",
                "labwareDefinition": "RES_CAR_8x100ml",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_reservoir_no_labware_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_reservoir(
                labware_definition="RES_CAR_8x100ml",
                carrier_id="Carrier1",
                site="1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addReservoir",
            parameters={
                "labwareDefinition": "RES_CAR_8x100ml",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_add_tip_support(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_tip_support(
                carrier_id="Carrier1",
                site="1",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTipSupport",
            parameters={
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_deck_remove_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.remove_labware(labware_name="Plate1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.removeLabware",
            parameters={"labwareName": "Plate1"},
        )

    def test_deck_add_1ml_core_grip(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.add1mLCoreGrip",
            parameters={"type": 0},
        )

    def test_deck_add_5ml_core_grip(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_5ml_core_grip()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.add5mLCoreGrip",
        )

    def test_deck_add_qcg(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_qcg(qcg_type=QCGType.QCG)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addQCG",
            parameters={"type": 0},
        )

    def test_deck_add_channel_liquid_waste(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.add_channel_liquid_waste()

        assert result.success
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addChannelLiquidWaste",
        )

    def test_shift_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"x": 100.0, "y": 200.0, "z": 245.0, "angle": 0.0},
            )
        )

        with StarClient(config) as client:
            result = client.shift_labware(
                labware_name="Test Plate",
                relative_x=1.5,
                relative_y=-0.5,
                relative_z=0.0,
                relative_angle=0.0,
            )

        assert result.success is True
        assert isinstance(result, LayoutShiftLabwareResponse)
        assert result.return_parameters.x == 100.0
        assert result.return_parameters.y == 200.0
        assert result.return_parameters.z == 245.0
        assert result.return_parameters.angle == 0.0
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.shiftLabware",
            parameters={
                "labwareName": "Test Plate",
                "relativeX": 1.5,
                "relativeY": -0.5,
                "relativeZ": 0.0,
                "relativeAngle": 0.0,
            },
        )

    def test_shift_labware_defaults(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"x": 50.0, "y": 100.0, "z": 10.0, "angle": 0.0},
            )
        )

        with StarClient(config) as client:
            result = client.shift_labware(labware_name="Plate1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.shiftLabware",
            parameters={
                "labwareName": "Plate1",
                "relativeX": 0.0,
                "relativeY": 0.0,
                "relativeZ": 0.0,
                "relativeAngle": 0.0,
            },
        )

    def test_add_tubes_to_carrier(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "positions": [
                        {"position": "1", "x": 100.0, "y": 200.0, "z": 245.0},
                        {"position": "2", "x": 110.0, "y": 200.0, "z": 245.0},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.add_tubes_to_carrier(
                labware_name="TubeCarrier1",
                positions=[
                    {"position": "1", "tube": "Tube_1", "zOffset": 10.0},
                    {"position": "2", "tube": "Tube_2"},
                ],
            )

        assert result.success is True
        assert isinstance(result, LayoutAddTubesToCarrierResponse)
        assert len(result.return_parameters.positions) == 2
        assert result.return_parameters.positions[0].position == "1"
        assert result.return_parameters.positions[0].x == 100.0
        assert result.return_parameters.positions[1].position == "2"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addTubesToCarrier",
            parameters={
                "labwareName": "TubeCarrier1",
                "positions": [
                    {
                        "position": "1",
                        "tube": "Tube_1",
                        "xOffset": 0.0,
                        "yOffset": 0.0,
                        "zOffset": 10.0,
                    },
                    {
                        "position": "2",
                        "tube": "Tube_2",
                        "xOffset": 0.0,
                        "yOffset": 0.0,
                        "zOffset": 0.0,
                    },
                ],
            },
        )


class _DeckLabwareClient(DeckLabwareCommandsMixin):
    def __init__(self, response: CommandResponse):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(return_value=response)

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)


def test_deck_labware_mixin_deck_add_carrier_no_labware_id():
    client = _DeckLabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.add_carrier("TIP_CAR_480BC_A00", left_track=1)

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.addCarrier",
        parameters={
            "labwareDefinition": "TIP_CAR_480BC_A00",
            "leftTrack": 1,
        },
    )


def test_deck_labware_mixin_deck_add_tube_carrier_no_carrier_id():
    client = _DeckLabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.add_tube_carrier("SMP_CAR_24_17x75_A00", left_track=10)

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.addSampleTubeCarrier",
        parameters={
            "labwareDefinition": "SMP_CAR_24_17x75_A00",
            "leftTrack": 10,
        },
    )


def test_deck_labware_mixin_deck_remove_transport_tool():
    client = _DeckLabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.remove_transport_tool(tool_id=42)

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.removeTransportTool",
        parameters={"toolId": 42},
    )


def test_deck_labware_mixin_shift_labware():
    client = _DeckLabwareClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"x": 100.0, "y": 200.0, "z": 245.0, "angle": 0.0},
        )
    )

    result = client.shift_labware(
        labware_name="Test Plate",
        relative_x=0.0,
        relative_y=0.0,
        relative_z=0.0,
        relative_angle=0.0,
    )

    assert isinstance(result, LayoutShiftLabwareResponse)
    assert result.success is True
    assert result.return_parameters.x == 100.0
    assert result.return_parameters.y == 200.0
    assert result.return_parameters.z == 245.0
    assert result.return_parameters.angle == 0.0
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.shiftLabware",
        parameters={
            "labwareName": "Test Plate",
            "relativeX": 0.0,
            "relativeY": 0.0,
            "relativeZ": 0.0,
            "relativeAngle": 0.0,
        },
    )


def test_deck_labware_mixin_add_tubes_to_carrier():
    client = _DeckLabwareClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "positions": [{"position": "1", "x": 100.0, "y": 200.0, "z": 245.0}]
            },
        )
    )

    result = client.add_tubes_to_carrier(
        labware_name="TubeCarrier1",
        positions=[{"position": "1", "tube": "Tube_1", "zOffset": 10.0}],
    )

    assert isinstance(result, LayoutAddTubesToCarrierResponse)
    assert result.success is True
    assert result.return_parameters.positions[0].position == "1"
    assert result.return_parameters.positions[0].z == 245.0
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.addTubesToCarrier",
        parameters={
            "labwareName": "TubeCarrier1",
            "positions": [
                {
                    "position": "1",
                    "tube": "Tube_1",
                    "xOffset": 0.0,
                    "yOffset": 0.0,
                    "zOffset": 10.0,
                }
            ],
        },
    )
