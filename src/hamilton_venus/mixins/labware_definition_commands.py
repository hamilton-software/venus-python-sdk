"""Labware definition management methods for StarClient (System category)."""

from __future__ import annotations

from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.labware_models import convert_definition_models, model_references
from hamilton_venus.models import (
    CommandResponse,
    LabwareDefinition,
    LabwareDefinitionDefinitionsResponse,
    LabwareDefinitionImportParameters,
    LabwareDefinitionImportResponse,
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
        labware_name: str | None = None,
        *,
        convert_models: bool = True,
    ) -> LabwareDefinitionImportResponse:
        """Import a labware definition from a VENUS labware file (``.rck``, ``.tml``, ...).

        VENUS works out the labware type from the file, converts it to the SDK's JSON format,
        stores it under ``Labware\\User\\<type>`` and returns it as
        ``return_parameters.definition``.

        With *convert_models* (the default), the 3D models it refers to as VENUS ``.x`` /
        ``.hxx`` files are converted to glTF (``.gltf`` + ``.bin``) in the registered SDK
        folder's ``Labware\\Models``, and the stored definition is updated to refer to them;
        ``return_parameters.models`` says what was converted, found already, missing or failed.

        Args:
            labware_path: The labware file to import.
            labware_name: Name for the new definition; defaults to the file name. A
                definition replacing another needs a new name.
            convert_models: Convert the definition's ``.x`` / ``.hxx`` models to glTF.
        """
        if isinstance(labware_name, LabwareType):
            raise TypeError(
                "labware_definition_import_definition no longer takes a labware type: VENUS works it "
                "out from the file. Call it as (labware_path, labware_name=None)."
            )
        parameters = LabwareDefinitionImportParameters(
            labware_definition=labware_name,
            labware_path=labware_path,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="labware.importLabwareDefinition",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        result = self._parse_response(LabwareDefinitionImportResponse, response)
        name = labware_name or PureWindowsPath(labware_path).stem
        result.return_parameters.labware_name = name
        if result.success and not result.return_parameters.definition:
            # A VENUS method that doesn't send the definition back: read the stored one.
            stored = self.labware_definition_get_definition(name)
            result.return_parameters.definition = stored.return_parameters.definition
        definition = result.return_parameters.definition
        if convert_models and definition and model_references(definition):
            updated, report = convert_definition_models(definition, source_file=labware_path)
            if updated != definition:
                self.labware_definition_update_definition(name, updated)
                report.definition_updated = True
                result.return_parameters.definition = updated
            result.return_parameters.models = report
        return result

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

