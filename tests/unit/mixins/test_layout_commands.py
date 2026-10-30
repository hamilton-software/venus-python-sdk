"""Unit tests for LayoutCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.models.enums import InstrumentType
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


class TestLayoutCommands:
    def test_move_carrier(self, config, mock_async_star_class):
        """Test moving a carrier in the layout."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Carrier moved"},
            )
        )

        with StarClient(config) as client:
            result = client.move_carrier(
                labware_name="Carrier1",
                left_track=40,
            )

        assert result.success is True
        assert result.return_parameters.message == "Carrier moved"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "labware.moveCarrier"
        assert call_args.kwargs["parameters"] == {
            "labwareName": "Carrier1",
            "leftTrack": 40,
            "site": "",
        }

    def test_add_ntr(self, config, mock_async_star_class):
        """Test adding nested tip rack to the layout."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalTips": 96,
                    "tipPoolName": "300ul tips",
                    "labwareName": "st_l_ntr_0001",
                    "tipType": 0,
                },
            )
        )

        with StarClient(config) as client:
            result = client.add_ntr(
                labware_definition="ST_L_NTR",
                carrier_id="Carrier1",
                site="5",
                stack=4,
                tip_pool="300 uL Tips",
            )

        assert result.success is True
        assert result.return_parameters.total_tips == 96
        assert result.return_parameters.tip_pool_name == "300ul tips"
        assert result.return_parameters.labware_name == "st_l_ntr_0001"
        assert result.return_parameters.tip_type == 0
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "labware.addNTR"
        assert call_args.kwargs["parameters"] == {
            "labwareDefinition": "ST_L_NTR",
            "carrier": "Carrier1",
            "site": "5",
            "stack": 4,
            "tipPool": "300 uL Tips",
        }

    def test_add_ntr_with_labware_id_and_no_tip_pool(self, config, mock_async_star_class):
        """Omitting tip_pool and setting labware_id should be reflected in the wire parameters."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "totalTips": 96,
                    "tipPoolName": "auto-generated-pool",
                    "labwareName": "MyNTR",
                    "tipType": 0,
                },
            )
        )

        with StarClient(config) as client:
            result = client.add_ntr(
                labware_definition="ST_L_NTR",
                carrier_id="Carrier1",
                site="5",
                stack=4,
                labware_id="MyNTR",
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "labware.addNTR"
        assert call_args.kwargs["parameters"] == {
            "labwareDefinition": "ST_L_NTR",
            "carrier": "Carrier1",
            "site": "5",
            "stack": 4,
            "labwareName": "MyNTR",
        }

    def test_add_transport_site(self, config, mock_async_star_class):
        """Test adding a transport site to the layout."""
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"siteAdded": "odtc"},
            )
        )

        with StarClient(config) as client:
            result = client.add_transport_site(
                site_name="ODTC",
                x_center=-24.1,
                y_center=252.6,
                z_bottom=201.5,
                angle_index=1,
            )

        assert result.success is True
        assert result.return_parameters.site_added == "odtc"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "labware.addTransportSite"
        assert call_args.kwargs["parameters"] == {
            "siteName": "ODTC",
            "xCenter": -24.1,
            "yCenter": 252.6,
            "zBottom": 201.5,
            "angleIndex": 1,
        }

    def test_add_lidded_plate(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "labwareName": "Plate1",
                    "lidName": "Plate1_lid",
                },
            )
        )

        with StarClient(config) as client:
            result = client.add_lidded_plate(
                labware_definition="Nun_96_Fl_HB",
                carrier_id="Carrier1",
                site="1",
                plate_id="Plate1",
                lid_definition="Nunc_Lid",
            )

        assert result.success is True
        assert result.return_parameters.labware_name == "Plate1"
        assert result.return_parameters.lid_name == "Plate1_lid"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addLiddedPlate",
            parameters={
                "labwareName": "Plate1",
                "labwareDefinition": "Nun_96_Fl_HB",
                "lidDefinition": "Nunc_Lid",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_add_lidded_plate_without_plate_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "labwareName": "GeneratedPlate",
                    "lidName": "GeneratedPlate_lid",
                },
            )
        )

        with StarClient(config) as client:
            result = client.add_lidded_plate(
                labware_definition="Nun_96_Fl_HB",
                carrier_id="Carrier1",
                site="2",
            )

        assert result.success is True
        assert result.return_parameters.labware_name == "GeneratedPlate"
        assert result.return_parameters.lid_name == "GeneratedPlate_lid"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addLiddedPlate",
            parameters={
                "labwareDefinition": "Nun_96_Fl_HB",
                "lidDefinition": "Nunc_Lid",
                "carrier": "Carrier1",
                "site": "2",
            },
        )

    def test_add_lid(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareName": "Plate1_lid"},
            )
        )

        with StarClient(config) as client:
            result = client.add_lid(
                labware_definition="Nunc_Lid",
                carrier_id="Carrier1",
                site="1",
                lid_id="Plate1_lid",
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addLid",
            parameters={
                "labwareName": "Plate1_lid",
                "labwareDefinition": "Nunc_Lid",
                "carrier": "Carrier1",
                "site": "1",
            },
        )

    def test_add_liquid_waste_rejected_for_star(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client, pytest.raises(ValueError, match="only supported for Vantage"):
            client.add_liquid_waste(track=44)

        star.venus.send_command.assert_not_awaited()

    def test_add_liquid_waste_with_track_vantage(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareName": "liquid_waste"},
            )
        )

        with StarClient(config, instrument_type=InstrumentType.Vantage) as client:
            result = client.add_liquid_waste(track=44)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addLiquidWaste",
            parameters={"track": 44},
        )

    def test_add_qcg_track_rejected_for_star(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client, pytest.raises(ValueError, match="only supported for Vantage"):
            client.add_qcg(track=30)

        star.venus.send_command.assert_not_awaited()

    def test_add_qcg_with_track_vantage(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config, instrument_type=InstrumentType.Vantage) as client:
            result = client.add_qcg(track=30)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.addQCG",
            parameters={"type": 0, "track": 30},
        )

    def test_get_transport_tool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "transportToolID": 10,
                    "labwareName": "QCG",
                    "transportToolPositions": [{"carrier": "Carrier1", "site": "2"}],
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_transport_tool(tool_id=10)

        assert result.success is True
        assert result.return_parameters.transport_tool_id == 10
        assert result.return_parameters.labware_name == "QCG"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getTransportTool",
            parameters={"toolId": 10},
        )

    def test_get_transport_tool_ids(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "transportTools": [
                        {"transportToolID": 1, "labwareName": "CoreGrip"},
                        {"transportToolID": 10, "labwareName": "QCG"},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_transport_tool_ids()

        assert result.success is True
        assert result.return_parameters.transport_tools[0].transport_tool_id == 1
        assert result.return_parameters.transport_tools[1].labware_name == "QCG"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getTransportToolIds",
        )


class TestAddCommandsReturnTheLabwareName:
    """The add commands return what VENUS documents (docs/json_schemas_System.md): typed, and readable like a dict."""

    @pytest.mark.parametrize(
        "method,kwargs",
        [
            ("add_carrier", {"labware_definition": "TIP_CAR_480BC", "left_track": 1}),
            ("add_carrier_to_site", {"labware_definition": "X", "carrier_id": "c", "site": "1"}),
            ("add_tube_carrier", {"labware_definition": "X", "left_track": 1}),
            ("add_plate", {"labware_definition": "X", "carrier_id": "c", "site": "1"}),
            ("add_lid", {"labware_definition": "X", "carrier_id": "c", "site": "1"}),
            ("add_reservoir", {"labware_definition": "X", "carrier_id": "c", "site": "1"}),
            ("add_tip_support", {"carrier_id": "c", "site": "1"}),
            ("add_channel_liquid_waste", {}),
        ],
    )
    def test_labware_name_is_typed_and_still_readable_as_a_dict(self, config, mock_async_star_class, method, kwargs):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"labwareName": "tip_car_480bc_0001"}
            )
        )

        with StarClient(config) as client:
            result = getattr(client, method)(**kwargs)

        assert result.success is True
        assert result.return_parameters.labware_name == "tip_car_480bc_0001"
        assert result.return_parameters["labwareName"] == "tip_car_480bc_0001"  # existing scripts read it like this
        assert (
            result.return_parameters.get("labwareName") == "tip_car_480bc_0001"
            and "labwareName" in result.return_parameters
        )
        assert result.model_dump(mode="json", by_alias=True)["returnParameters"] == {
            "labwareName": "tip_car_480bc_0001"
        }

    @pytest.mark.parametrize("method,kwargs", [("add_1ml_core_grip", {}), ("add_5ml_core_grip", {}), ("add_qcg", {})])
    def test_transport_tools_return_their_name_and_id(self, config, mock_async_star_class, method, kwargs):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareName": "CoreGrip1mL", "transportID": 1},
            )
        )

        with StarClient(config) as client:
            result = getattr(client, method)(**kwargs)

        assert result.return_parameters.labware_name == "CoreGrip1mL" and result.return_parameters.transport_id == 1
        assert result.return_parameters["transportID"] == 1

    def test_remove_commands_return_what_was_removed(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"labwareRemoved": ["reservoir 1"]}
            )
        )
        with StarClient(config) as client:
            assert client.remove_labware("reservoir 1").return_parameters.labware_removed == ["reservoir 1"]
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"message": "toolId 11 was removed"}
            )
        )
        with StarClient(config) as client:
            assert client.remove_transport_tool(11).return_parameters.message == "toolId 11 was removed"
