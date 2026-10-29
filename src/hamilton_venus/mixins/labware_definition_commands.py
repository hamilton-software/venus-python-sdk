"""Labware definition management methods for StarClient (System category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    LabwareDefinition,
    LabwareDefinitionDefinitionsResponse,
    LabwareDefinitionImportParameters,
    LabwareDefinitionParameters,
    LabwareDefinitionSingleResponse,
    LabwareDefinitionTypesResponse,
    LabwareFilterParameters,
    LabwareNameParameters,
    LabwareParamsFromIdParameters,
    LabwareType,
)
from hamilton_venus.models.labware_definition import dump_labware_definition

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class LabwareDefinitionCommandsMixin:
    """Mixin providing labware definition management commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def labware_definition_get_types(self) -> LabwareDefinitionTypesResponse:
        """Return the list of available labware type names."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.getLabwareTypes",
            )
        )
        return self._parse_response(LabwareDefinitionTypesResponse, response)

    def labware_definition_get_definitions(
        self,
        filter: list[str] | None = None,
    ) -> LabwareDefinitionDefinitionsResponse:
        """Return labware definitions, optionally filtered by name."""
        parameters = LabwareFilterParameters(filter=filter)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.getLabwareDefinitions",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(LabwareDefinitionDefinitionsResponse, response)

    def labware_definition_get_definition(self, labware_name: str) -> LabwareDefinitionSingleResponse:
        """Return the definition for the specified labware type."""
        parameters = LabwareNameParameters(labware_definition=labware_name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.getLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(LabwareDefinitionSingleResponse, response)

    def labware_definition_add_definition(
        self,
        labware_name: str,
        labware_definition: LabwareDefinition | dict[str, Any],
    ) -> CommandResponse:
        """Add a new labware definition to the system.

        VENUS takes the labware category from the definition's own ``labwareClass``.
        """
        definition_dict = dump_labware_definition(labware_definition)
        parameters = LabwareDefinitionParameters(
            labware_definition=labware_name,
            definition=definition_dict,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.addLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def labware_definition_import_definition(
        self,
        labware_path: str,
        labware_type: LabwareType,
        labware_name: str | None = None,
    ) -> CommandResponse:
        """Import a labware definition from a legacy ``.rck`` file."""
        parameters = LabwareDefinitionImportParameters(
            labware_definition=labware_name,
            labware_path=labware_path,
            labware_type=labware_type,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.importLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def labware_definition_update_definition(
        self,
        labware_name: str,
        labware_definition: LabwareDefinition | dict[str, Any],
    ) -> CommandResponse:
        """Update an existing labware definition."""
        definition_dict = dump_labware_definition(labware_definition)
        parameters = LabwareDefinitionParameters(
            labware_definition=labware_name,
            definition=definition_dict,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.updateLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def labware_definition_delete_definition(self, labware_name: str) -> CommandResponse:
        """Delete the specified labware definition from the system."""
        parameters = LabwareNameParameters(labware_definition=labware_name)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.deleteLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def labware_definition_get_params_from_id(self, labware_name: str) -> LabwareDefinitionSingleResponse:
        """Return the full labware definition for a labware instance by its name/ID."""
        parameters = LabwareParamsFromIdParameters(labware_name=labware_name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="labware.getLabwareParamsFromID",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(LabwareDefinitionSingleResponse, response)

