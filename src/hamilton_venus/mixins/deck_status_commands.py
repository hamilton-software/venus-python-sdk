"""Deck layout query methods for StarClient (Deck Layout category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import (
    AddedCarriersResponse,
    AddedPlatesResponse,
    AddedReservoirsResponse,
    AddedTipRacksResponse,
    AvailableTracksResponse,
    CarrierSitesResponse,
    CommandResponse,
    GetTransportToolParameters,
    LabwareCoordinatesParameters,
    LabwareCoordinatesResponse,
    LabwareLocationResponse,
    LabwareOnCarrierResponse,
    LabwareParamsFromIdParameters,
    LabwarePositionsResponse,
    LayoutCarrierParameters,
    LayoutTopLabwareParameters,
    OccupiedTracksResponse,
    TopLabwareResponse,
    TrackIdParameters,
    TrackOccupiedResponse,
    TransportToolIdsResponse,
    TransportToolResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class DeckStatusCommandsMixin:
    """Mixin providing deck layout queries for layout state inspection."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def get_added_carriers(self) -> AddedCarriersResponse:
        """Return the list of carriers currently added to the deck layout."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAddedCarriers",
            )
        )
        return self._parse_response(AddedCarriersResponse, response)

    def get_added_plates(self) -> AddedPlatesResponse:
        """Return the list of plates currently added to the deck layout."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAddedPlates",
            )
        )
        return self._parse_response(AddedPlatesResponse, response)

    def get_added_tip_racks(self) -> AddedTipRacksResponse:
        """Return the list of tip racks currently added to the deck layout."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAddedTipRacks",
            )
        )
        return self._parse_response(AddedTipRacksResponse, response)

    def get_added_reservoirs(self) -> AddedReservoirsResponse:
        """Return the list of reservoirs currently added to the deck layout."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAddedReservoirs",
            )
        )
        return self._parse_response(AddedReservoirsResponse, response)

    def get_available_tracks(self) -> AvailableTracksResponse:
        """Return the list of available (unoccupied) deck tracks."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAvailableTracks",
            )
        )
        return self._parse_response(AvailableTracksResponse, response)

    def get_occupied_tracks(self) -> OccupiedTracksResponse:
        """Return the list of currently occupied deck tracks."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getOccupiedTracks",
            )
        )
        return self._parse_response(OccupiedTracksResponse, response)

    def get_available_carrier_sites(self, carrier: str) -> CarrierSitesResponse:
        """Return the available (empty) sites on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        parameters = LayoutCarrierParameters(carrier=carrier)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getAvailableCarrierSites",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(CarrierSitesResponse, response)

    def get_occupied_carrier_sites(self, carrier: str) -> CarrierSitesResponse:
        """Return the occupied sites on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        parameters = LayoutCarrierParameters(carrier=carrier)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getOccupiedCarrierSites",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(CarrierSitesResponse, response)

    def get_labware_on_carrier(self, carrier: str) -> LabwareOnCarrierResponse:
        """Return the labware items loaded on the specified carrier.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        parameters = LayoutCarrierParameters(carrier=carrier)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getLabwareOnCarrier",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(LabwareOnCarrierResponse, response)

    def get_labware_positions(self, labware_name: str) -> LabwarePositionsResponse:
        """Return the deck positions for the specified labware instance by name."""
        parameters = LabwareParamsFromIdParameters(labware_name=labware_name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getLabwarePositions",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(LabwarePositionsResponse, response)

    def get_labware_location(self, labware_name: str) -> LabwareLocationResponse:
        """Return the carrier and site location of the specified labware instance by name."""
        parameters = LabwareParamsFromIdParameters(labware_name=labware_name)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getLabwareLocation",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(LabwareLocationResponse, response)

    def get_top_labware(self, carrier_id: str, site: str) -> TopLabwareResponse:
        """Return the top labware at the specified carrier site.

        For carriers with sites (plate, reservoir, tip carriers). A sample tube carrier has no
        sites -- its tubes are part of the rack -- so this returns nothing for one; use
        ``get_labware_coordinates(carrier)`` (every tube position) or ``get_labware_spec(carrier)``.
        """
        parameters = LayoutTopLabwareParameters(carrier_id=carrier_id, site=site)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getTopLabware",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TopLabwareResponse, response)

    def is_track_occupied(self, track_id: int) -> TrackOccupiedResponse:
        """Return whether the specified deck track is occupied in the layout."""
        parameters = TrackIdParameters(track_id=track_id)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.isTrackOccupied",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TrackOccupiedResponse, response)

    def get_transport_tool(
        self,
        is_1ml: bool | None = None,
        is_qcg: bool | None = None,
        tool_id: int | None = None,
    ) -> TransportToolResponse:
        """Get a transport tool by type or ID (parameters are mutually exclusive)."""
        parameters = GetTransportToolParameters(
            is_1ml=is_1ml,
            is_qcg=is_qcg,
            tool_id=tool_id,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getTransportTool",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return TransportToolResponse.model_validate(response.model_dump(by_alias=True))

    def get_transport_tool_ids(self) -> TransportToolIdsResponse:
        """Get all transport tool IDs currently in the layout."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getTransportToolIds",
            )
        )
        return TransportToolIdsResponse.model_validate(response.model_dump(by_alias=True))

    def get_labware_coordinates(
        self,
        labware_name: str,
        well: str | None = None,
    ) -> LabwareCoordinatesResponse:
        """Return the deck coordinates of a labware item, or of one of its wells.

        With ``well``: the response's ``well`` / ``x`` / ``y`` / ``z`` / ``angle``
        are that well's coordinates.

        Without ``well``: ``origin`` holds the labware's origin and, for a rack-type
        labware (plate, tip rack, tube rack, reservoir), ``wells`` holds the
        coordinates of every position, ordered by column. A carrier has no wells
        and returns ``origin`` only. The top-level ``x`` / ``y`` / ``z`` / ``angle``
        are ``None`` in this case -- read ``origin`` instead.
        """
        parameters = LabwareCoordinatesParameters(labware_name=labware_name, well=well)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="status.getLabwareCoordinates",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(LabwareCoordinatesResponse, response)


