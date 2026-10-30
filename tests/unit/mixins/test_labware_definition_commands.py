"""Unit tests for LabwareDefinitionCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.models.enums import LabwareType
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


class TestLabwareDefinitionCommands:
    def test_labware_get_types(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareTypes": ["type1", "type2"]},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_get_types()

        assert result.success is True
        assert result.return_parameters.labware_types == ["type1", "type2"]

    def test_labware_get_definitions(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "labware": {
                        "Carriers": ["MFX_CAR_2HHSF30MTP", "PLT_CAR_L5MD"],
                        "Plates": ["Nun_96_Fl_HB", "Nun_384_Fl"],
                    }
                },
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_get_definitions()

        assert result.success is True
        assert result.return_parameters.labware["Carriers"][0] == "MFX_CAR_2HHSF30MTP"

    def test_labware_get_definitions_with_filter(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labware": {"Tips": ["ST_L", "ST_L_Wide"]}},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_get_definitions(filter=["ST_L"])

        assert result.success is True
        assert result.return_parameters.labware["Tips"][0] == "ST_L"

    def test_labware_get_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareDefinition": {}},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_get_definition(labware_name="ST_L")

        assert result.success is True

    def test_labware_add_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_add_definition(
                labware_name="CustomPlate",
                labware_definition={"rows": 8, "columns": 12},
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="labware.addLabwareDefinition",
            parameters={
                "labwareDefinition": "CustomPlate",
                "definition": {"rows": 8, "columns": 12},
            },
        )

    def test_labware_import_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": '"MyImportedPlate" added', "definition": {"labwareClass": "plate"}},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_import_definition(
                labware_path=r"C:\Labware\MyRack.rck",
                labware_name="MyImportedPlate",
            )

        assert result.success is True
        assert result.return_parameters.definition == {"labwareClass": "plate"}
        assert result.return_parameters.labware_name == "MyImportedPlate"
        assert result.return_parameters.models is None  # no .x / .hxx models to convert
        # VENUS works out the labware type from the file: no labwareType is sent any more.
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="labware.importLabwareDefinition",
            parameters={
                "labwareDefinition": "MyImportedPlate",
                "labwarePath": r"C:\Labware\MyRack.rck",
            },
        )

    def test_labware_import_definition_reads_back_a_definition_venus_did_not_send(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(side_effect=[
            CommandResponse(return_status="Success", return_code=0, return_parameters={"message": "added"}),
            CommandResponse(return_status="Success", return_code=0,
                            return_parameters={"definition": {"labwareClass": "reservoir"}}),
        ])

        with StarClient(config) as client:
            result = client.labware_definition_import_definition(r"C:\Labware\Trough.rck")

        assert result.return_parameters.definition == {"labwareClass": "reservoir"}
        read_back = star.venus.send_command.await_args_list[1].kwargs
        assert read_back["action_name"] == "labware.getLabwareDefinition"
        assert read_back["parameters"] == {"labwareDefinition": "Trough"}

    def test_labware_import_definition_refuses_the_old_labware_type(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(TypeError, match="no longer takes a labware type"):
            client.labware_definition_import_definition(r"C:\Labware\MyRack.rck", LabwareType.PLATE)

    def test_labware_import_definition_converts_models(self, config, mock_async_star_class, tmp_path, monkeypatch):
        from hamilton_venus.mixins import labware_definition_commands as module
        from hamilton_venus.models import ModelConversionReport

        star = mock_async_star_class.return_value
        imported = {"customAttributes": {"hamilton:container_visual": {"modelRef": "rack.hxx"}}}
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0,
                                         return_parameters={"message": "added", "definition": imported})
        )
        converted = {"customAttributes": {"hamilton:container_visual": {"modelRef": "rack.gltf"}}}
        monkeypatch.setattr(module, "convert_definition_models",
                            lambda definition, source_file: (converted, ModelConversionReport(converted=["rack.hxx"])))

        with StarClient(config) as client:
            result = client.labware_definition_import_definition(r"C:\Labware\MyRack.rck")

        assert result.return_parameters.definition == converted
        assert result.return_parameters.models.converted == ["rack.hxx"]
        assert result.return_parameters.models.definition_updated is True
        update = star.venus.send_command.await_args_list[-1].kwargs
        assert update["action_name"] == "labware.updateLabwareDefinition"
        assert update["parameters"]["labwareDefinition"] == "MyRack"  # the file name when none is given

    def test_labware_update_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_update_definition(
                labware_name="CustomPlate",
                labware_definition={"rows": 8, "columns": 12},
            )

        assert result.success is True

    def test_labware_delete_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.labware_definition_delete_definition(labware_name="CustomPlate")

        assert result.success is True

    def test_labware_get_params_from_id(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareDefinition": {"rows": 8, "columns": 12}},
            )
        )

        with StarClient(config) as client:
            result = client.labware_get_params_from_id(labware_name="Plate1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="labware.getLabwareParamsFromID",
            parameters={"labwareName": "Plate1"},
        )
