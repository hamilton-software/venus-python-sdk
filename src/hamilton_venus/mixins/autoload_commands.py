"""Autoload command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hamilton_venus.models import (
    AutoloadLoadCarrierByIdParameters,
    AutoloadLoadCarrierByTrackParameters,
    AutoloadLoadCarrierResponse,
    AutoloadMoveParameters,
    AutoloadUnloadCarrierByIdParameters,
    AutoloadUnloadCarrierByTrackParameters,
    CarrierSensorStatusResponse,
    CommandResponse,
    ScanPositions,
    TrackIdParameters,
    TrackOccupiedResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

class AutoloadCommandsMixin:
    """Mixin providing autoload control commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def autoload_move(self, track_id: int) -> CommandResponse:
        """Move the autoload shuttle to the specified deck track."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.moveTo",
                parameters=AutoloadMoveParameters(track_id=track_id).model_dump(by_alias=True),
            )
        )

    def autoload_park_left(self) -> CommandResponse:
        """Park the autoload shuttle at its left-most position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.parkLeft",
            )
        )

    def autoload_park_right(self) -> CommandResponse:
        """Park the autoload shuttle at its right-most position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.parkRight",
            )
        )

    def autoload_load_carrier_by_id(
        self,
        carrier_id: str,
        scan_positions: ScanPositions | list[int] | None = None,
    ) -> AutoloadLoadCarrierResponse:
        """Load a carrier by carrier identifier, optionally scanning positions.

        When *scan_positions* is set, the response's ``barcode_returns``
        carries one entry per barcode position of the carrier (``MlStarCarCountOfBCPos``),
        empty for positions not scanned -- see
        :class:`~hamilton_venus.models.command_types.AutoloadLoadCarrierReturnParameters`.

        A carrier that is already pushed in: on the STAR, unload it first (check
        :meth:`autoload_get_carrier_sensor_status`); on the Vantage, the load step
        unloads it itself, and an unload before the load raises a load tray error.
        """
        parameters = AutoloadLoadCarrierByIdParameters(
            carrier_id=carrier_id,
            scan_positions=scan_positions,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.loadCarrierById",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return AutoloadLoadCarrierResponse.model_validate(response.model_dump(by_alias=True))

    def autoload_load_carrier_by_track(
        self,
        track_id: int,
        scan_positions: ScanPositions | list[int] | None = None,
    ) -> AutoloadLoadCarrierResponse:
        """Load a carrier from the specified track, optionally scanning positions.

        When *scan_positions* is set, the response's ``barcode_returns``
        carries one entry per barcode position of the carrier (``MlStarCarCountOfBCPos``),
        empty for positions not scanned -- see
        :class:`~hamilton_venus.models.command_types.AutoloadLoadCarrierReturnParameters`.

        A carrier that is already pushed in: on the STAR, unload it first (check
        :meth:`autoload_get_carrier_sensor_status`); on the Vantage, the load step
        unloads it itself, and an unload before the load raises a load tray error.
        """
        parameters = AutoloadLoadCarrierByTrackParameters(
            track_id=track_id,
            scan_positions=scan_positions,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.loadCarrierByTrack",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return AutoloadLoadCarrierResponse.model_validate(response.model_dump(by_alias=True))

    def autoload_unload_carrier_by_id(self, carrier_id: str) -> CommandResponse:
        """Unload a carrier using its configured carrier identifier."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.unloadCarrierById",
                parameters=AutoloadUnloadCarrierByIdParameters(carrier_id=carrier_id).model_dump(by_alias=True),
            )
        )

    def autoload_unload_carrier_by_track(self, track_id: int) -> CommandResponse:
        """Unload a carrier from the specified deck track."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.unloadCarrierByTrack",
                parameters=AutoloadUnloadCarrierByTrackParameters(track_id=track_id).model_dump(by_alias=True),
            )
        )

    def autoload_is_track_occupied(self, track_id: int) -> TrackOccupiedResponse:
        """Return whether the specified autoload track currently holds a carrier."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.isTrackOccupied",
                parameters=TrackIdParameters(track_id=track_id).model_dump(by_alias=True),
            )
        )
        return TrackOccupiedResponse.model_validate(response.model_dump(by_alias=True))

    def autoload_get_carrier_sensor_status(self) -> CarrierSensorStatusResponse:
        """Return carrier sensor availability and occupancy status across tracks."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="autoload.getCarrierSensorStatus",
            )
        )
        return CarrierSensorStatusResponse.model_validate(response.model_dump(by_alias=True))

