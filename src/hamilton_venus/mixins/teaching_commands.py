"""Teaching methods for the synchronous instrument clients (Teaching category).

Single commands drive the teaching needle on the teaching channel (``teaching.1mL.*``);
:meth:`TeachingCommandsMixin.teach_well` combines them into an automated plate teach.
See :mod:`hamilton_venus.teaching` for the algorithm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    TeachingChannelResponse,
    TeachingLabwareDimensionsParameters,
    TeachingLabwareDimensionsResponse,
    TeachingMeasureXYParameters,
    TeachingMeasureXYResponse,
    TeachingMeasureZParameters,
    TeachingMeasureZResponse,
    TeachingMoveParameters,
    TeachingMoveResponse,
    TeachingNeedleStatusResponse,
    TeachingSetChannelParameters,
)
from hamilton_venus.models.enums import TeachingDirection
from hamilton_venus.teaching import (
    DEFAULT_TRAVERSE_Z,
    SECOND_WALL_SHIFT,
    TeachingError,
    TeachingPoint,
    TeachingWall,
    TeachWellResult,
    bottom_search_window,
    check_search_status,
    round_mm,
    wall_center,
    wall_label,
    wall_search_heights,
    well_widths_from_definition,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
    from hamilton_venus.models import LabwareCoordinatesResponse, LabwareDefinitionSingleResponse
    from hamilton_venus.taught_locations import LabwarePosition

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)

_CATEGORY = "Teaching"


class TeachingCommandsMixin:
    """Mixin providing teaching-needle commands and automated plate teaching."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def get_labware_coordinates(self, labware_name: str, well: str | None = None) -> LabwareCoordinatesResponse: ...

        def labware_definition_get_params_from_id(self, labware_name: str) -> LabwareDefinitionSingleResponse: ...

        def register_taught_position(
            self,
            labware: str,
            carrier: str,
            site: str | int,
            *,
            x: float,
            y: float,
            z: float,
            angle: float = 0.0,
            note: str | None = None,
        ) -> LabwarePosition: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def _send_teaching(self, action: str, parameters: dict[str, Any] | None = None) -> CommandResponse:
        response: CommandResponse = self._run(
            self._connected_instrument.venus.send_command(
                category=_CATEGORY,
                action_name=f"teaching.1mL.{action}",
                parameters=parameters or {},
            )
        )
        return response

    # --- single commands ---------------------------------------------------------

    def teaching_set_channel(self, channel: int) -> TeachingChannelResponse:
        """Set the 1 mL channel (1-based) used for teaching. Not allowed while a needle is held.

        The channel is reset to the instrument configuration's teaching channel on every connect.
        """
        parameters = TeachingSetChannelParameters(channel=channel)
        response = self._send_teaching("setTeachingChannel", parameters.model_dump(by_alias=True))
        return self._parse_response(TeachingChannelResponse, response)

    def teaching_get_channel(self) -> TeachingChannelResponse:
        """Return the 1 mL channel used for teaching (``.return_parameters.channel``)."""
        return self._parse_response(TeachingChannelResponse, self._send_teaching("getTeachingChannel"))

    def teaching_pickup_needle(self) -> TeachingChannelResponse:
        """Pick up a teaching needle with the teaching channel.

        Needs a teaching-needle rack on the deck. Returns the channel that holds the needle.
        """
        return self._parse_response(TeachingChannelResponse, self._send_teaching("pickupTeachingNeedle"))

    def teaching_eject_needle(self) -> CommandResponse:
        """Return the teaching needle to its pickup position."""
        return self._send_teaching("ejectTeachingNeedle")

    def teaching_is_needle_picked_up(self) -> TeachingNeedleStatusResponse:
        """Return whether the teaching channel holds a teaching needle (``.return_parameters.is_needle_picked_up``)."""
        return self._parse_response(TeachingNeedleStatusResponse, self._send_teaching("isNeedlePickedUp"))

    def teaching_get_labware_dimensions(
        self, labware_name: str, well: str | None = None
    ) -> TeachingLabwareDimensionsResponse:
        """Return a labware's center, bottom and height, and a well's center, bottom and depth.

        Without ``well`` the labware's first position is reported in ``.well``.
        """
        parameters = TeachingLabwareDimensionsParameters(labware_name=labware_name, well=well)
        response = self._send_teaching("getLabwareDimensions", parameters.model_dump(by_alias=True, exclude_none=True))
        return self._parse_response(TeachingLabwareDimensionsResponse, response)

    def teaching_move_channel(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        z_traverse: float | None = None,
    ) -> TeachingMoveResponse:
        """Move the teaching channel to a needle-tip position and return where it ended up.

        Omitted axes keep their current value; ``z_traverse`` (105-245 mm) defaults to the
        current Z. With no arguments nothing moves and the current position is returned.
        Needs a teaching needle.
        """
        parameters = TeachingMoveParameters(x=x, y=y, z=z, z_traverse=z_traverse)
        response = self._send_teaching("moveChannelToPosition", parameters.model_dump(by_alias=True, exclude_none=True))
        return self._parse_response(TeachingMoveResponse, response)

    def teaching_measure_z(
        self,
        z_start: float,
        z_min: float,
        *,
        z_end: float = -1.0,
        slow: bool = False,
    ) -> TeachingMeasureZResponse:
        """Search down from ``z_start`` to ``z_min`` until the needle stalls.

        ``.return_parameters.measured_z`` is the stall height and ``.status`` the result
        (``NOT_FOUND`` / ``FOUND`` / ``FOUND_EARLY``). With ``z_end`` -1 the needle returns
        to its start height after a find. Needs a teaching needle.
        """
        parameters = TeachingMeasureZParameters(z_start=z_start, z_min=z_min, z_end=z_end, use_slow_speed=slow or None)
        response = self._send_teaching("measureZHeight", parameters.model_dump(by_alias=True, exclude_none=True))
        return self._parse_response(TeachingMeasureZResponse, response)

    def teaching_measure_wall(
        self,
        direction: TeachingDirection,
        *,
        safe_height: float,
        min_search_z: float,
        well_width: float,
        step_distance: float | None = None,
    ) -> TeachingMeasureXYResponse:
        """Step toward one wall, probing Z at each step, until the needle stalls on the wall top.

        Start with the needle inside the well at its entrance height. ``safe_height`` is
        above the labware, ``min_search_z`` 2-3 mm inside the well, ``well_width`` the
        maximum travel and ``step_distance`` (0.3-2.4 mm, default 0.6) the probe step.
        ``.return_parameters.measured.wall_coordinate`` is the last X or Y where the needle
        still dropped into the well. Needs a teaching needle.
        """
        parameters = TeachingMeasureXYParameters(
            safe_height=safe_height,
            min_search_z=min_search_z,
            well_width=well_width,
            direction=direction,
            step_distance=step_distance,
        )
        response = self._send_teaching("measureXY", parameters.model_dump(by_alias=True, exclude_none=True))
        return self._parse_response(TeachingMeasureXYResponse, response)

    # --- automated teach -----------------------------------------------------------

    def teach_well(
        self,
        labware_name: str,
        well: str | None = None,
        *,
        well_width: float | tuple[float, float] | None = None,
        step_distance: float = 0.6,
        safe_clearance: float = 5.0,
        search_depth: float = 3.0,
        bottom_search_margin: float = 5.0,
        z_offset: float = 0.0,
        teach_z_only: bool = False,
        move_to_well: bool = True,
        traverse_z: float = DEFAULT_TRAVERSE_Z,
        register: bool = False,
        carrier: str | None = None,
        site: str | int | None = None,
    ) -> TeachWellResult:
        """Teach one well of a plate: find its four walls and its bottom with the teaching needle.

        Pick up a teaching needle first (:meth:`teaching_pickup_needle`). Steps:

        1. Move over the definition's well center at its entrance height
           (``move_to_well=False`` starts wherever the needle is instead; it must be
           inside the well at the entrance height).
        2. Find the +X, -X, +Y and -Y walls; the center of each axis is the mean of its
           two walls, the measured entrance height the mean of the four wall-top stalls.
        3. Search down from the measured entrance for the well bottom.
        4. Lift to ``traverse_z`` and compare with the definition.

        Args:
            labware_name: Labware ID of the plate.
            well: Well to teach (e.g. ``"A1"``); default the labware's first position.
            well_width: Well opening in mm, one value or ``(x, y)``; also the farthest a
                wall search travels. Default: from the labware definition.
            step_distance: Wall search step, 0.3-2.4 mm.
            safe_clearance: Travel height above the entrance between probes, mm.
            search_depth: How far into the well each wall probe goes, mm (2-3 mm).
            bottom_search_margin: How far below the expected bottom the Z search may go, mm.
            z_offset: Added to the measured bottom (needle/stall correction), mm.
            teach_z_only: Skip the wall searches and only find the bottom at the start X/Y.
            move_to_well: Move over the expected well first.
            traverse_z: Height for the moves to and away from the well (105-245 mm).
            register: Save the taught labware position to TaughtLocations.json
                (:meth:`register_taught_position`); needs ``carrier`` and ``site``.
            carrier, site: Where the plate sits, for ``register``.

        Raises:
            TeachingError: A wall or the bottom was not found, or the needle stalled
                early. The needle is lifted to ``traverse_z`` first.
        """
        if register and (carrier is None or site is None):
            raise ValueError("register=True needs carrier and site")
        if not self.teaching_is_needle_picked_up().return_parameters.is_needle_picked_up:
            raise TeachingError("no teaching needle is picked up; call teaching_pickup_needle() first")

        dimensions = self.teaching_get_labware_dimensions(labware_name, well).return_parameters
        target = dimensions.well
        expected = TeachingPoint(x=target.center.x, y=target.center.y, z=target.bottom_z)
        width_x, width_y = (0.0, 0.0) if teach_z_only else self._teaching_well_widths(labware_name, well_width)

        if move_to_well:
            start = self.teaching_move_channel(
                x=target.center.x, y=target.center.y, z=round_mm(target.entrance_z), z_traverse=traverse_z
            ).return_parameters
        else:
            start = self.teaching_move_channel().return_parameters

        failed = True
        try:
            walls: list[TeachingWall] = []
            if teach_z_only:
                center_x, center_y, entrance_z = start.x, start.y, start.z
            else:
                safe, min_search = wall_search_heights(start.z, safe_clearance, search_depth)

                def find(direction: TeachingDirection, width: float) -> TeachingWall:
                    wall = self._teaching_find_wall(direction, safe, min_search, width, step_distance)
                    walls.append(wall)
                    return wall

                plus_x = find(TeachingDirection.PLUS_X, width_x)
                self.teaching_move_channel(
                    x=round_mm(plus_x.coordinate - SECOND_WALL_SHIFT * width_x), y=start.y, z=safe, z_traverse=safe
                )
                minus_x = find(TeachingDirection.MINUS_X, width_x)
                center_x = wall_center(plus_x.coordinate, minus_x.coordinate)
                self.teaching_move_channel(x=center_x, y=start.y, z=safe, z_traverse=safe)
                plus_y = find(TeachingDirection.PLUS_Y, width_y)
                self.teaching_move_channel(
                    x=center_x, y=round_mm(plus_y.coordinate - SECOND_WALL_SHIFT * width_y), z=safe, z_traverse=safe
                )
                minus_y = find(TeachingDirection.MINUS_Y, width_y)
                center_y = wall_center(plus_y.coordinate, minus_y.coordinate)
                self.teaching_move_channel(x=center_x, y=center_y, z=safe, z_traverse=safe)
                entrance_z = round_mm(sum(wall.entrance_z for wall in walls) / len(walls))

            z_start, z_min = bottom_search_window(entrance_z, target.depth, bottom_search_margin)
            bottom = self.teaching_measure_z(z_start, z_min).return_parameters
            check_search_status(bottom.status.measure_status, "the well bottom")
            failed = False
        finally:
            self._teaching_lift(traverse_z, suppress_errors=failed)

        measured_bottom_z = round_mm(bottom.measured_z)
        bottom_z = round_mm(measured_bottom_z + z_offset)
        offset = TeachingPoint(
            x=round_mm(center_x - expected.x),
            y=round_mm(center_y - expected.y),
            z=round_mm(bottom_z - expected.z),
        )
        result = TeachWellResult(
            labware=labware_name,
            well=target.position_id or (well or ""),
            walls=walls,
            center=TeachingPoint(x=center_x, y=center_y, z=bottom_z),
            entrance_z=entrance_z,
            measured_bottom_z=measured_bottom_z,
            bottom_z=bottom_z,
            expected=expected,
            offset=offset,
        )
        if register and carrier is not None and site is not None:
            result.taught_position = self._teaching_register(result, carrier, site)
        return result

    # --- helpers -----------------------------------------------------------------

    def _teaching_well_widths(
        self, labware_name: str, well_width: float | tuple[float, float] | None
    ) -> tuple[float, float]:
        if isinstance(well_width, tuple):
            return well_width
        if well_width is not None:
            return well_width, well_width
        definition = self.labware_definition_get_params_from_id(labware_name).return_parameters.to_labware_definition()
        widths = well_widths_from_definition(definition)
        if widths is None:
            raise ValueError(f"{labware_name}: the labware definition has no well size; pass well_width")
        return widths

    def _teaching_find_wall(
        self,
        direction: TeachingDirection,
        safe_height: float,
        min_search_z: float,
        well_width: float,
        step_distance: float,
    ) -> TeachingWall:
        label = wall_label(direction)
        response = self.teaching_measure_wall(
            direction,
            safe_height=safe_height,
            min_search_z=min_search_z,
            well_width=well_width,
            step_distance=step_distance,
        ).return_parameters
        check_search_status(response.status.measure_status, f"the {label} wall", wall=label)
        if response.measured is None:
            raise TeachingError(f"the {label} wall search returned no measurement", wall=label)
        return TeachingWall(
            wall=label,
            coordinate=round_mm(response.measured.wall_coordinate),
            entrance_z=round_mm(response.measured.entrance_z),
        )

    def _teaching_lift(self, traverse_z: float, *, suppress_errors: bool) -> None:
        """Raise the needle straight up to ``traverse_z``; on a failed teach, never mask the original error."""
        try:
            self.teaching_move_channel(z=traverse_z)
        except Exception:
            if not suppress_errors:
                raise

    def _teaching_register(self, result: TeachWellResult, carrier: str, site: str | int) -> LabwarePosition:
        # VENUS applies a taught position as the coordinates of the labware's first
        # position (A1), not its origin: register first position + offset.
        wells = self.get_labware_coordinates(result.labware).return_parameters.wells
        if not wells:
            raise TeachingError(
                f"{result.labware}: no position coordinates returned; cannot register the taught position"
            )
        first = wells[0]
        return self.register_taught_position(
            result.labware,
            carrier,
            site,
            x=round_mm(first.x + result.offset.x),
            y=round_mm(first.y + result.offset.y),
            z=round_mm(first.z + result.offset.z),
            angle=first.angle,
            note=f"auto-teach {result.well}",
        )
