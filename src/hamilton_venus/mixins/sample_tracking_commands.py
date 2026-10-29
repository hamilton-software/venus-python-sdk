"""Sample tracking methods for the synchronous instrument clients (Sample Tracking category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    Position,
    TrackingBarcodeLocationsResponse,
    TrackingGetBarcodeLocationsParameters,
    TrackingGetLabwareDetailsParameters,
    TrackingLabwareBarcodes,
    TrackingLabwareDetailsResponse,
    TrackingLabwareQuery,
    TrackingLabwareVolume,
    TrackingSetBarcodesParameters,
    TrackingSetBarcodesResponse,
    TrackingSetLabwareVolumeParameters,
    TrackingWellId,
)
from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import _split_selector, normalize_positions

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
    from hamilton_venus.models.position import LabwareLayoutSpec

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

_POSITION_WELL_KEYS = ("wellId", "well")


def _is_position_entry(entry: Any) -> bool:
    """True for the position forms pipetting steps take (selector, Position, labwareId/wellId dict)."""
    if isinstance(entry, (str, Position)):
        return True
    return isinstance(entry, dict) and any(key in entry for key in _POSITION_WELL_KEYS)


class SampleTrackingCommandsMixin:
    """Mixin providing sample tracking commands (barcodes, tracked labware details and volumes)."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def get_labware_spec(self, labware_id: str) -> LabwareLayoutSpec: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def _tracking_wells(self, entry: Any, well_order: WellOrder) -> tuple[str, list[str] | None]:
        """Resolve one position entry to ``(labware_id, wells)``; ``wells`` is None for the whole labware."""
        if isinstance(entry, str):
            labware_id, expression = _split_selector(entry)
            if expression is None or expression == "all":
                return labware_id, None
            positions = normalize_positions(entry, well_order, get_spec=self.get_labware_spec)
            return labware_id, [position.well for position in positions]
        position = entry if isinstance(entry, Position) else Position.model_validate(entry)
        return position.labware, [position.well]

    def _group_tracking_positions(self, entries: list[Any], well_order: WellOrder) -> dict[str, list[str] | None]:
        """Group position entries by labware, keeping first-seen order."""
        grouped: dict[str, list[str] | None] = {}
        for entry in entries:
            labware_id, wells = self._tracking_wells(entry, well_order)
            if labware_id not in grouped:
                grouped[labware_id] = wells
                continue
            existing = grouped[labware_id]
            grouped[labware_id] = None if existing is None or wells is None else existing + wells
        return grouped

    def get_barcode_locations(self, barcodes: list[str]) -> TrackingBarcodeLocationsResponse:
        """Return where each barcode is currently tracked on the deck.

        Found barcodes are listed in ``.return_parameters.barcodes`` with their
        ``labware_id``, ``well`` (empty for a labware-level barcode) and
        ``labware_type``; the rest are listed in ``.return_parameters.not_found``.

        Call ``.to_positions()`` on the response to turn the found barcodes into
        position selectors (``"Plate_1@A1"``) that aspirate/dispense steps accept.
        """
        parameters = TrackingGetBarcodeLocationsParameters(barcodes=barcodes)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Sample Tracking",
                action_name="tracking.getBarcodeLocations",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TrackingBarcodeLocationsResponse, response)

    def get_labware_details(
        self,
        labware: str
        | Position
        | dict[str, Any]
        | TrackingLabwareQuery
        | list[str]
        | list[Position]
        | list[dict[str, Any]]
        | list[str | Position | dict[str, Any] | TrackingLabwareQuery],
        well_order: WellOrder = WellOrder.COL_ASC,
    ) -> TrackingLabwareDetailsResponse:
        """Return the current sample tracking details (barcode, volume, state, position) for labware.

        Args:
            labware: What to report on, as one entry or a list. Each entry may be:

                - a position selector as used by pipetting steps: ``"Plate_1"`` or
                  ``"Plate_1@all"`` (every well loaded in the labware),
                  ``"Plate_1@A1,B1"``, ``"Plate_1@A1:C3"``, ``"Plate_1@col:1"``, ...
                - a ``Position`` or a ``{"labwareId": ..., "wellId": ...}`` dict
                - a TrackingLabwareQuery, or a dict with ``labwareId`` and optional
                  ``wells`` (well IDs or ``{"id": "A1"}`` objects)
            well_order: Order in which selector ranges are expanded.

        A labware item that cannot be reported (not on the layout, nothing tracked
        on it yet) carries the reason in its ``message`` instead of failing the command.

        Wells are returned sorted by deck position: X ascending, then Y descending,
        then Z descending.

        Limitation: VENUS sample tracking keeps no volume for reservoirs (connected
        containers), tip racks or carriers, so well ``volume`` is ``None`` for labware
        of type ``Reservoir Rack``, ``Tip Rack`` and ``Template``. Reservoirs also
        track no well state and no well barcode, so ``labware_state`` and ``barcode``
        are ``None`` for their wells too.
        """
        entries = labware if isinstance(labware, list) else [labware]
        queries: list[TrackingLabwareQuery] = []
        from_positions: dict[str, TrackingLabwareQuery] = {}
        for entry in entries:
            if isinstance(entry, TrackingLabwareQuery):
                queries.append(entry)
            elif not _is_position_entry(entry):
                queries.append(TrackingLabwareQuery.model_validate(entry))
            else:
                # Positions on the same labware merge into one query; "whole labware" wins.
                labware_id, wells = self._tracking_wells(entry, well_order)
                query = from_positions.get(labware_id)
                if query is None:
                    well_ids = None if wells is None else [TrackingWellId(id=well) for well in wells]
                    query = TrackingLabwareQuery(labware_id=labware_id, wells=well_ids)
                    from_positions[labware_id] = query
                    queries.append(query)
                elif query.wells is None or wells is None:
                    query.wells = None
                else:
                    query.wells = query.wells + [TrackingWellId(id=well) for well in wells]
        parameters = TrackingGetLabwareDetailsParameters(labware=queries)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Sample Tracking",
                action_name="tracking.getLabwareDetails",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(TrackingLabwareDetailsResponse, response)

    def set_barcodes(
        self,
        labware: str
        | Position
        | dict[str, Any]
        | TrackingLabwareBarcodes
        | list[str]
        | list[Position]
        | list[dict[str, Any]]
        | list[str | Position | dict[str, Any] | TrackingLabwareBarcodes],
        barcodes: str | list[str] | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
    ) -> TrackingSetBarcodesResponse:
        """Assign barcodes to labware and/or to individual wells.

        Two call forms:

        - ``set_barcodes("Plate_1@A1,B1,C1", ["bc1", "bc2", "bc3"])`` -- positions as
          used by pipetting steps (selector, ``Position``, ``labwareId``/``wellId``
          dict, or a list of those) paired in order with ``barcodes``. A bare labware
          ID (``"Plate_1"``) takes one barcode, assigned to the labware itself.
        - ``set_barcodes([{...}])`` -- TrackingLabwareBarcodes entries, or dicts with
          ``labwareId`` (required), optional ``barcode`` (the labware itself) and
          optional ``wells`` (``{"id": "A1", "barcode": "..."}`` objects).

        Args:
            labware: Positions (with ``barcodes``) or explicit barcode entries.
            barcodes: Barcodes for the positions in ``labware``, in expansion order.
            well_order: Order in which selector ranges are expanded.
        """
        entries = labware if isinstance(labware, list) else [labware]
        if barcodes is None:
            normalized = [
                entry if isinstance(entry, TrackingLabwareBarcodes) else TrackingLabwareBarcodes.model_validate(entry)
                for entry in entries
            ]
        else:
            values = [barcodes] if isinstance(barcodes, str) else list(barcodes)
            resolved = [self._tracking_wells(entry, well_order) for entry in entries]
            needed = sum(1 if wells is None else len(wells) for _, wells in resolved)
            if needed != len(values):
                raise ValueError(f"labware expanded to {needed} position(s), but {len(values)} barcode(s) were given")
            by_labware: dict[str, dict[str, Any]] = {}
            remaining = iter(values)
            for labware_id, wells in resolved:
                target = by_labware.setdefault(labware_id, {"labwareId": labware_id})
                if wells is None:
                    target["barcode"] = next(remaining)
                else:
                    target.setdefault("wells", []).extend({"id": well, "barcode": next(remaining)} for well in wells)
            normalized = [TrackingLabwareBarcodes.model_validate(target) for target in by_labware.values()]
        parameters = TrackingSetBarcodesParameters(labware=normalized)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Sample Tracking",
                action_name="tracking.setBarcodes",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(TrackingSetBarcodesResponse, response)

    def set_labware_volume(
        self,
        labware: str
        | Position
        | dict[str, Any]
        | TrackingLabwareVolume
        | list[str]
        | list[Position]
        | list[dict[str, Any]]
        | list[str | Position | dict[str, Any] | TrackingLabwareVolume],
        volume: float | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
    ) -> CommandResponse:
        """Set the tracked liquid volume of labware and/or of individual wells.

        Two call forms:

        - ``set_labware_volume("Plate_1@A1:H1", 50.0)`` -- positions as used by
          pipetting steps (selector, ``Position``, ``labwareId``/``wellId`` dict, or a
          list of those), each set to ``volume``. A bare labware ID or ``@all`` sets
          every well of the labware.
        - ``set_labware_volume([{...}])`` -- TrackingLabwareVolume entries, or dicts
          with ``labwareId`` (required), optional ``volume`` (every well) and optional
          ``wells`` (``{"id": "A1", "volume": 50.0}`` objects, applied after ``volume``).

        Limitation: VENUS sample tracking keeps no volume for reservoirs (connected
        containers), tip racks or carriers; setting one succeeds but has no effect.

        Args:
            labware: Positions (with ``volume``) or explicit volume entries.
            volume: Volume in uL for the positions in ``labware``.
            well_order: Order in which selector ranges are expanded.
        """
        entries = labware if isinstance(labware, list) else [labware]
        if volume is None:
            normalized = [
                entry if isinstance(entry, TrackingLabwareVolume) else TrackingLabwareVolume.model_validate(entry)
                for entry in entries
            ]
        else:
            normalized = [
                TrackingLabwareVolume.model_validate(
                    {"labwareId": labware_id, "volume": volume}
                    if wells is None
                    else {
                        "labwareId": labware_id,
                        "wells": [{"id": well, "volume": volume} for well in wells],
                    }
                )
                for labware_id, wells in self._group_tracking_positions(entries, well_order).items()
            ]
        parameters = TrackingSetLabwareVolumeParameters(labware=normalized)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Sample Tracking",
                action_name="tracking.setLabwareVolume",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
