from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from hamilton_venus.mixins.labware_commands import LabwareCommandsMixin
from hamilton_venus.models import CommandResponse


class _LabwareClient(LabwareCommandsMixin):
    def __init__(self, response: CommandResponse):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(return_value=response)

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)


def test_labware_get_types():
    client = _LabwareClient(
        CommandResponse(return_status="Success", return_code=0, return_parameters={"labwareTypes": ["TypeA"]})
    )

    result = client.labware_get_types()

    assert result.success is True
    assert result.return_parameters.labware_types == ["TypeA"]
    client._star.venus.send_command.assert_awaited_once_with(category="System", action_name="labware.getLabwareTypes")


def test_labware_get_definitions_without_filter():
    client = _LabwareClient(
        CommandResponse(return_status="Success", return_code=0, return_parameters={"labware": {"Tips": ["ST_L"]}})
    )

    result = client.labware_get_definitions()

    assert result.success is True
    assert result.return_parameters.labware["Tips"] == ["ST_L"]
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.getLabwareDefinitions",
        parameters={},
    )


def test_labware_get_definitions_with_filter():
    client = _LabwareClient(
        CommandResponse(return_status="Success", return_code=0, return_parameters={"labware": {"Plates": ["P1"]}})
    )

    result = client.labware_get_definitions(filter=["P1"])

    assert result.success is True
    assert result.return_parameters.labware["Plates"] == ["P1"]
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.getLabwareDefinitions",
        parameters={"filter": ["P1"]},
    )


def test_labware_get_definition():
    client = _LabwareClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"labwareName": "P1", "definition": {"name": "P1"}},
        )
    )

    result = client.labware_get_definition("P1")

    assert result.success is True
    assert result.return_parameters.labware_name == "P1"
    assert result.return_parameters.definition == {"name": "P1"}
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.getLabwareDefinition",
        parameters={"labwareDefinition": "P1"},
    )


def test_labware_add_definition_with_dict():
    client = _LabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.labware_add_definition("Custom", {"rows": 8, "columns": 12})

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.addLabwareDefinition",
        parameters={
            "labwareDefinition": "Custom",
            "definition": {"rows": 8, "columns": 12},
        },
    )


def test_labware_add_definition_requires_both_parameters():
    """Both labware_name and labware_definition are required, with no defaults."""
    client = _LabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    signature = inspect.signature(client.labware_add_definition)
    required = [
        name
        for name, param in signature.parameters.items()
        if param.default is inspect.Parameter.empty
        and param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    assert required == ["labware_name", "labware_definition"]

    with pytest.raises(TypeError):
        client.labware_add_definition()
    with pytest.raises(TypeError):
        client.labware_add_definition("CUSTOM_PLATE_001")
    with pytest.raises(TypeError):
        client.labware_add_definition(labware_definition={"rows": 8})


def test_labware_update_definition_with_dict():
    client = _LabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.labware_update_definition("Custom", {"rows": 16, "columns": 24})

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.updateLabwareDefinition",
        parameters={
            "labwareDefinition": "Custom",
            "definition": {"rows": 16, "columns": 24},
        },
    )


def test_labware_delete_definition():
    client = _LabwareClient(CommandResponse(return_status="Success", return_code=0, return_parameters={}))

    result = client.labware_delete_definition("Custom")

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="System",
        action_name="labware.deleteLabwareDefinition",
        parameters={"labwareDefinition": "Custom"},
    )


def test_labware_get_params_from_id():
    client = _LabwareClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"labwareName": "Plate1", "definition": {"name": "P1"}},
        )
    )

    result = client.labware_get_params_from_id("Plate1")

    assert result.success is True
    assert result.return_parameters.labware_name == "Plate1"
    assert result.return_parameters.definition == {"name": "P1"}
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="labware.getLabwareParamsFromID",
        parameters={"labwareName": "Plate1"},
    )
