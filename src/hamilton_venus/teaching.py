"""Automated plate teaching with the teaching needle and the 1 mL channel Z-stall sensor.

The ``teaching.1mL.*`` commands do single moves and searches on the instrument; this
module holds the arithmetic that turns those measurements into a taught well position.
It ports the plate flow of the VENUS Deck Teaching Method (``_TeachPlate``):

1. The needle starts over the well at its entrance height (the top of the well).
2. ``measureXY`` finds the +X wall, then from ``+X wall - 0.75 * width`` the -X wall.
   The X center is their mean. The +Y / -Y walls are found the same way along the
   X center, giving the Y center. Each wall search also reports the Z where the needle
   stalled on the wall top; the measured entrance height is the mean of the four.
3. ``measureZHeight`` searches down from the measured entrance to ``depth +
   bottom_search_margin`` below it; the stall height is the well bottom.
4. The offset is the taught well minus the labware definition's well (X, Y, bottom Z).

Each wall coordinate is the last needle position that dropped into the well, so the
needle radius cancels when the two walls of an axis are averaged.

All coordinates are needle-tip coordinates in mm; values are rounded to 0.1 mm the way
the Deck Teaching Method rounds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from hamilton_venus.exceptions import VenusError
from hamilton_venus.models.enums import TeachingDirection, TeachingMeasureStatus
from hamilton_venus.taught_locations import LabwarePosition

if TYPE_CHECKING:
    from hamilton_venus.models.labware_definition import LabwareDefinition

__all__ = [
    "DEFAULT_TRAVERSE_Z",
    "SECOND_WALL_SHIFT",
    "TeachWellResult",
    "TeachingError",
    "TeachingPoint",
    "TeachingWall",
    "bottom_search_window",
    "check_search_status",
    "round_mm",
    "wall_center",
    "wall_label",
    "wall_search_heights",
    "well_widths_from_definition",
]

DEFAULT_TRAVERSE_Z = 245.0
"""Traverse height used to move to and away from the well (the highest ``moveChannelToPosition`` Z)."""

SECOND_WALL_SHIFT = 0.75
"""After the first wall of an axis, the second search starts this fraction of the well width back from it."""

SEARCH_Z_MIN = 100.0
SEARCH_Z_MAX = 334.0
WELL_WIDTH_MIN = 2.0
WELL_WIDTH_MAX = 100.0

_WALL_LABELS = {
    TeachingDirection.PLUS_X: "+X",
    TeachingDirection.MINUS_X: "-X",
    TeachingDirection.PLUS_Y: "+Y",
    TeachingDirection.MINUS_Y: "-Y",
}


class TeachingError(VenusError):
    """Raised when a teaching search does not find what it is looking for.

    ``status`` is the search result (``NOT_FOUND`` or ``FOUND_EARLY``) and ``wall`` the
    wall being searched (``"+X"``, ...), or ``None`` for the Z bottom search.
    """

    def __init__(
        self,
        message: str,
        *,
        status: TeachingMeasureStatus | None = None,
        wall: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.wall = wall


class TeachingPoint(BaseModel):
    x: float
    y: float
    z: float


class TeachingWall(BaseModel):
    """One measured wall: ``coordinate`` on its axis and the ``entrance_z`` the needle stalled at."""

    wall: str
    coordinate: float
    entrance_z: float


class TeachWellResult(BaseModel):
    """Outcome of :meth:`teach_well`.

    ``center`` / ``bottom_z`` are the taught well; ``expected`` is the labware
    definition's well (X, Y center and bottom Z); ``offset`` is taught minus expected.
    ``bottom_z`` includes ``z_offset``; ``measured_bottom_z`` is the raw stall height.
    ``walls`` is empty for a Z-only teach. ``taught_position`` is the record written to
    TaughtLocations.json when ``register=True``.
    """

    labware: str
    well: str
    walls: list[TeachingWall] = Field(default_factory=list)
    center: TeachingPoint
    entrance_z: float
    measured_bottom_z: float
    bottom_z: float
    expected: TeachingPoint
    offset: TeachingPoint
    taught_position: LabwarePosition | None = None


def round_mm(value: float) -> float:
    """Round to 0.1 mm."""
    return round(value, 1)


def wall_label(direction: TeachingDirection) -> str:
    return _WALL_LABELS[TeachingDirection(direction)]


def wall_center(first_wall: float, second_wall: float) -> float:
    """Center between two opposite walls of an axis."""
    return round_mm((first_wall + second_wall) / 2.0)


def _check_search_z(name: str, value: float) -> float:
    if not SEARCH_Z_MIN <= value <= SEARCH_Z_MAX:
        raise ValueError(f"{name} {value:.1f} mm is outside the search range {SEARCH_Z_MIN:.0f}-{SEARCH_Z_MAX:.0f} mm")
    return value


def wall_search_heights(entrance_z: float, safe_clearance: float, search_depth: float) -> tuple[float, float]:
    """Return ``(safe_height, min_search_z)`` for wall searches from a well entrance.

    ``safe_height`` (above the labware) is where the needle travels between probes;
    ``min_search_z`` (inside the well) is how deep each probe goes: a stall above it is
    the wall top, reaching it means the needle is still inside the well.
    """
    if safe_clearance <= 0:
        raise ValueError("safe_clearance must be greater than 0")
    if search_depth <= 0:
        raise ValueError("search_depth must be greater than 0")
    safe_height = _check_search_z("safe height", round_mm(entrance_z + safe_clearance))
    min_search_z = _check_search_z("minimum search Z", round_mm(entrance_z - search_depth))
    return safe_height, min_search_z


def bottom_search_window(entrance_z: float, depth: float, margin: float) -> tuple[float, float]:
    """Return ``(z_start, z_min)`` for the well-bottom search.

    The search starts at the entrance and may go ``margin`` below the expected bottom
    (``entrance_z - depth``), clamped to the lowest searchable Z.
    """
    if margin < 0:
        raise ValueError("bottom_search_margin must not be negative")
    z_start = _check_search_z("bottom search start", round_mm(entrance_z))
    z_min = max(round_mm(entrance_z - depth - margin), SEARCH_Z_MIN)
    return z_start, z_min


def check_search_status(status: TeachingMeasureStatus, what: str, *, wall: str | None = None) -> None:
    """Raise :class:`TeachingError` unless a search ``status`` is ``FOUND``."""
    status = TeachingMeasureStatus(status)
    if status == TeachingMeasureStatus.FOUND:
        return
    if status == TeachingMeasureStatus.NOT_FOUND:
        message = f"{what} was not found"
    else:
        message = (
            f"unexpected Z stall while searching for {what}: something is higher than expected "
            "(labware taller or offset, or an obstacle); check the labware and reteach"
        )
    raise TeachingError(message, status=status, wall=wall)


def well_widths_from_definition(definition: LabwareDefinition) -> tuple[float, float] | None:
    """Return the well opening ``(width in X, width in Y)`` from a labware definition.

    Uses the first container grid's opening: ``diameter`` for a round well,
    ``width`` / ``depth`` for a rectangular one, else the widest volume-model diameter.
    ``None`` when the definition gives no usable size.
    """
    grids = list(definition.container_grids.values())
    if not grids:
        return None
    container = grids[0].container_definition
    opening = container.opening_dimensions
    if opening.shape == "rectangle" and opening.width and opening.depth:
        return opening.width, opening.depth
    if opening.diameter:
        return opening.diameter, opening.diameter
    diameters = [
        value
        for segment in container.volume_model.segments
        for value in (segment.diameter, segment.diameter_top, segment.diameter_bottom)
        if value
    ]
    if diameters:
        widest = max(diameters)
        return widest, widest
    return None
