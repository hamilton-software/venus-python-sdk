"""Liquid Class command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.models import (
    CommandResponse,
    GetLiquidClassParameters,
    GetLiquidClassResponse,
    LiquidClassDefinition,
    LiquidClassesParameters,
    LiquidClassesResponse,
    LiquidClassNamesParameters,
    LiquidDevicesResponse,
    LiquidNamesResponse,
    TipTypesResponse,
    UpdateLiquidClassParameters,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class LiquidClassCommandsMixin:
    """Mixin providing Liquid Class commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def pull_liquid_classes(self, names: list[str]) -> CommandResponse:
        """Pull liquid class definitions from the instrument database."""
        parameters = LiquidClassNamesParameters(names=names)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.pullLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def push_liquid_classes(self, names: list[str]) -> CommandResponse:
        """Push liquid class definitions to the instrument database.

        Not needed before pipetting: custom liquid classes a command uses are pushed
        automatically the first time a session uses them and whenever their JSON
        changes. Use this to load a set up front in one call.
        """
        parameters = LiquidClassNamesParameters(names=names)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.pushLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        self._connected_instrument.liquid_class_sync.record_pushed(names)
        return response

    def get_liquid_devices(self) -> LiquidDevicesResponse:
        """Get the list of available liquid handling devices."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidDevices",
            )
        )
        return LiquidDevicesResponse.model_validate(response.model_dump(by_alias=True))

    def get_liquid_names(self) -> LiquidNamesResponse:
        """Get the list of available liquid class names."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidNames",
            )
        )
        return LiquidNamesResponse.model_validate(response.model_dump(by_alias=True))

    def get_liquid_classes(
        self,
        *,
        tip_type: int = -1,
        device: int = -1,
        dispense_mode: int = -1,
        is_original: int = -1,
        has_tadm_enabled: int = -1,
    ) -> LiquidClassesResponse:
        """Get liquid class names filtered by tip, device, dispense mode, and metadata flags."""
        parameters = LiquidClassesParameters(
            tip_type=tip_type,
            device=device,
            dispense_mode=dispense_mode,
            is_original=is_original,
            has_tadm_enabled=has_tadm_enabled,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidClasses",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return LiquidClassesResponse.model_validate(response.model_dump(by_alias=True))

    def get_tip_types(self) -> TipTypesResponse:
        """Get the list of available tip types."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getTipTypes",
            )
        )
        return TipTypesResponse.model_validate(response.model_dump(by_alias=True))

    def get_liquid_class(self, name: str) -> GetLiquidClassResponse:
        """Get the full definition of a single liquid class by name."""
        parameters = GetLiquidClassParameters(name=name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.getLiquidClass",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return GetLiquidClassResponse.model_validate(response.model_dump(by_alias=True))

    def update_liquid_class(self, definition: LiquidClassDefinition) -> CommandResponse:
        """Update an existing liquid class definition on the instrument."""
        parameters = UpdateLiquidClassParameters(definition=definition)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="liquidClass.updateLiquidClass",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

