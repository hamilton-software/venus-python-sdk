"""Configuration command methods for StarClient (Instrument category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    ConfigurationResponse,
    ConfigurationSerialNumberResponse,
    DeckDimensionsResponse,
    DeckTracksResponse,
    WasteLocationsResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class ConfigurationCommandsMixin:
    """Mixin providing configuration commands for instrument hardware setup."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def instrument_get_configuration(self) -> ConfigurationResponse:
        """Return the typed hardware configuration reported by the instrument."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getConfiguration",
            )
        )
        return self._parse_response(ConfigurationResponse, response)

    def instrument_disable_cleanup(self) -> CommandResponse:
        """Disable end-of-run cleanup behavior in the instrument runtime."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.disableCleanup",
            )
        )

    def instrument_get_serial_number(self) -> ConfigurationSerialNumberResponse:
        """Return the typed instrument serial number response."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getSerialNumber",
            )
        )
        return self._parse_response(ConfigurationSerialNumberResponse, response)

    def instrument_get_deck_tracks(self) -> DeckTracksResponse:
        """Return typed deck track counts for the installed instrument."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getDeckTracks",
            )
        )
        return self._parse_response(DeckTracksResponse, response)

    def instrument_get_deck_dimensions(self) -> DeckDimensionsResponse:
        """Return typed deck dimension metadata in instrument coordinates."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getDeckDimensions",
            )
        )
        return self._parse_response(DeckDimensionsResponse, response)

    def instrument_get_waste_locations(self) -> WasteLocationsResponse:
        """Return typed waste-location metadata configured on the deck."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getWasteLocations",
            )
        )
        return self._parse_response(WasteLocationsResponse, response)

