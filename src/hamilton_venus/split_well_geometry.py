"""Where several channels can pipette side by side inside one large well.

A 6-well, 12-well or 24-well plate (or a 50 mL tube) has room for more than one
channel per well. ``split_wells`` places a temporary rack of *n* slots inside the
well, one slot per channel, spaced by the channel pitch along Y (9 mm for 1 mL
channels, 18 mm for 5 mL). This module computes how many slots fit and where they
go, in pure Python from the labware definition; ``split_wells`` sends the result to
VENUS (``labware.addSplitWellSite``).

Frames and conventions:

* The channels line up along deck Y, so the slots differ only in Y. Slots are
  numbered from the back (highest Y): slot 1 is where channel 1 is, and its
  position in the split rack is named ``"1"``.
* ``u`` is the offset across the well along deck X **in the plate's frame**,
  positive toward the low wall of a tilted plate (deck -X for a positive angle),
  as ``TiltWellPosition.DEEPEST_POINT`` uses it. Heights ``h`` are measured up the
  well axis from its lowest point.
* Where a tip fits (the tip's shape, the tip end height above the floor, the wall
  margins, and how the tilted wall leans over the tip) comes from
  :mod:`hamilton_venus.tilt_clearance`, the same maths ``tilt_labware`` aims one
  tip with.
* On a V- or round-bottom well, a slot away from the centre lands on the sloped
  floor, so its container base is raised to the floor height at its radial
  distance ``sqrt(u**2 + y**2)``.

Slot offsets (:class:`SplitSlot`) are relative to the parent well's **current**
position in the deck layout, as VENUS reports it (``DevGetLabwarePositionEx``),
which already includes any ``tilt_labware`` offset.

The default tip profiles and margins are a starting point: calibrate them on the
instrument and pass your own when they are too tight or too loose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML, CHANNEL_PITCH_MM_5ML
from hamilton_venus.models.enums import SplitChannelType, SplitWellFit, TiltWellPosition
from hamilton_venus.models.labware_definition import LabwareDefinition
from hamilton_venus.tilt_clearance import (
    DEFAULT_HIGH_WALL_MARGIN_MM,
    DEFAULT_TIP_PROFILES,
    DEFAULT_WALL_MARGIN_MM,
    TipClearance,
    TipProfile,
    WellProfile,
    aim_offset,
    closest_aim,
    no_fit_message,
    tip_interval,
)
from hamilton_venus.tilt_geometry import MAX_MEASURED_TILT_DEG, _as_definition, validate_tilt_degrees

#: A :class:`~hamilton_venus.models.enums.SplitWellFit` or a channel count (``int``).
SplitFit = SplitWellFit | int

CHANNEL_PITCH_BY_TYPE: dict[SplitChannelType, float] = {
    SplitChannelType.ONE_ML: CHANNEL_PITCH_MM_1ML,
    SplitChannelType.FIVE_ML: CHANNEL_PITCH_MM_5ML,
}

_ROUND_DIGITS = 4


@dataclass(frozen=True)
class SplitSlot:
    """One slot: its position in the split rack (``"1"`` at the back) and its offset from the parent well.

    ``dx`` / ``dy`` / ``dz`` are deck-frame millimetres from the parent well's current
    position; ``dz`` is how far the slot's container base sits above the parent's.
    """

    slot: int
    well: str
    dx: float
    dy: float
    dz: float


@dataclass(frozen=True)
class SplitWellPlan:
    """How one well is split.

    ``requested_x_shift`` / ``x_shift_applied`` are plate-frame ``u`` offsets (see the
    module docstring). ``limited_by`` says what capped the slot count: the well
    (``"chord"``) or the channels available (``"max_channels"``).
    """

    well: str
    pitch_mm: float
    slots: tuple[SplitSlot, ...]
    requested_x_shift: float
    x_shift_applied: float
    limited_by: Literal["chord", "max_channels"]
    well_depth: float = 0.0

    @property
    def slot_count(self) -> int:
        return len(self.slots)


def normalize_channel_type(channel_type: SplitChannelType | str) -> SplitChannelType:
    """*channel_type* as a :class:`SplitChannelType` (``"1mL"`` / ``"5mL"`` also accepted, any case)."""
    for member in SplitChannelType:
        if isinstance(channel_type, str) and channel_type.lower() == member.value.lower():
            return member
    choices = ", ".join(f"SplitChannelType.{m.name}" for m in SplitChannelType)
    raise ValueError(f"channel_type must be one of {choices}, got {channel_type!r}")


def normalize_fit(fit: SplitFit | str, max_channels: int) -> SplitWellFit | int:
    """*fit* as a :class:`SplitWellFit` or a channel count in ``1..max_channels``."""
    if isinstance(fit, int) and not isinstance(fit, bool):
        if not 1 <= fit <= max_channels:
            raise ValueError(f"fit={fit} is outside 1..{max_channels} (the channels available)")
        return fit
    if isinstance(fit, str):
        for member in SplitWellFit:
            if fit.lower() == member.value:
                return member
    choices = ", ".join(f"SplitWellFit.{m.name}" for m in SplitWellFit)
    raise ValueError(f"fit must be {choices} or a channel count, got {fit!r}")




def requested_x_shift(
    definition: LabwareDefinition | dict[str, Any],
    tilt_degrees: float,
    well_position: TiltWellPosition | str,
    clearance: TipClearance | None = None,
) -> float:
    """The plate-frame ``u`` that *well_position* aims one tip at; 0 for the centre or a flat plate.

    ``DEEPEST_POINT`` / ``HIGHEST_POINT`` are as close to the low / high wall as one
    tip fits with *clearance* (default :class:`~hamilton_venus.tilt_clearance.TipClearance`).
    """
    angle = validate_tilt_degrees(tilt_degrees, maximum=MAX_MEASURED_TILT_DEG)
    profile = WellProfile(_as_definition(definition))
    return closest_aim(profile, clearance or TipClearance(), angle, well_position)


def compute_split_well_plan(
    definition: LabwareDefinition | dict[str, Any],
    well: str,
    *,
    pitch_mm: float,
    max_channels: int,
    tilt_degrees: float = 0,
    well_position: TiltWellPosition | str = TiltWellPosition.CENTER,
    parent_well_position: TiltWellPosition | str | None = None,
    parent_x_shift: float | None = None,
    fit: SplitFit = SplitWellFit.POSITION,
    tip: TipProfile = DEFAULT_TIP_PROFILES[SplitChannelType.ONE_ML],
    tip_end_height_mm: float = 0.0,
    wall_margin_mm: float = DEFAULT_WALL_MARGIN_MM,
    high_wall_margin_mm: float = DEFAULT_HIGH_WALL_MARGIN_MM,
) -> SplitWellPlan:
    """Plan the slots for one well of *definition*.

    Args:
        definition: The parent labware's definition (anything ``tilt_geometry`` accepts).
        well: The parent well, e.g. ``"A1"``; only echoed back in the plan.
        pitch_mm: Channel pitch: 9.0 for 1 mL channels, 18.0 for 5 mL.
        max_channels: Most slots to make (the channels available).
        tilt_degrees: The angle the plate really sits at (``tilt_labware``'s
            measured angle, else its commanded one; 0..15).
        well_position: Where to aim the slots across the well: the centre, or as
            close to the low (``DEEPEST_POINT``) or high (``HIGHEST_POINT``) wall as
            the slots fit. Like ``tilt_labware``, it only matters while tilted.
        parent_well_position: Where ``tilt_labware`` aimed the parent well, which is
            where VENUS reports it. Defaults to *well_position*.
        parent_x_shift: The plate-frame ``u`` ``tilt_labware`` aimed the parent well
            at, if known; otherwise computed from *parent_well_position* with this
            plan's tip and margins.
        fit: :attr:`~hamilton_venus.models.enums.SplitWellFit.POSITION` keeps the aim
            and uses as many channels as fit there; aimed at a wall, that is as
            many channels as the well holds, each count as close to the wall as it
            fits (the same as ``MAX_CHANNELS``). ``MAX_CHANNELS`` uses the most
            channels the well holds and moves toward the aim as far as they fit.
            An ``int`` asks for exactly that many channels.
        tip: Tip shape used to check that each slot fits.
        tip_end_height_mm: How far above the floor the tip ends sit (the aspirate /
            dispense fixed height). 0 is the most conservative.
        wall_margin_mm: Gap kept between the tips and the low wall (and the walls
            along the hinge).
        high_wall_margin_mm: Gap kept between the tips and the high wall, which leans
            in over them. On a flat plate both walls use ``wall_margin_mm``.

    Raises:
        ValueError: For a definition without one container grid or any usable well
            size, an angle outside 0..15, ``max_channels < 1``, an ``int`` *fit* the
            well cannot hold, or a wall aim where not even one tip fits.
    """
    if max_channels < 1:
        raise ValueError(f"max_channels must be at least 1, got {max_channels}")
    fit = normalize_fit(fit, max_channels)
    angle = validate_tilt_degrees(tilt_degrees, maximum=MAX_MEASURED_TILT_DEG)
    defn = _as_definition(definition)
    profile = WellProfile(defn)
    clearance = TipClearance(tip, tip_end_height_mm, wall_margin_mm, high_wall_margin_mm)
    position = TiltWellPosition(well_position)
    aimed_at_wall = angle > 0 and position is not TiltWellPosition.CENTER

    requested = closest_aim(profile, clearance, angle, position)
    if parent_x_shift is None:
        parent_x_shift = closest_aim(profile, clearance, angle, parent_well_position or position)

    def interval(count: int) -> tuple[float, float] | None:
        return tip_interval(profile, clearance, half_span=(count - 1) / 2.0 * pitch_mm, tilt_degrees=angle)

    if fit is SplitWellFit.POSITION and not aimed_at_wall:
        count = 1
        for candidate in range(2, max_channels + 1):
            span = interval(candidate)
            if span is None or not span[0] <= requested <= span[1]:
                break
            count = candidate
        u0 = requested
    else:
        if isinstance(fit, int):
            count = fit
        else:
            count = 1
            for candidate in range(max_channels, 1, -1):
                if interval(candidate) is not None:
                    count = candidate
                    break
        span = interval(count) if count > 1 else (-math.inf, math.inf)
        if span is None:
            reason = no_fit_message(
                profile, clearance, tips=count, half_span=(count - 1) / 2.0 * pitch_mm, tilt_degrees=angle
            )
            raise ValueError(f"{well}: the well cannot hold {count} channels at {pitch_mm:g} mm pitch: {reason}")
        u0 = min(max(requested, span[0]), span[1])

    limited_by: Literal["chord", "max_channels"] = "chord"
    if count == max_channels:
        limited_by = "max_channels"

    base_dx, base_dz = aim_offset(parent_x_shift, profile.floor_height(abs(parent_x_shift)) or 0.0, angle)
    slots: list[SplitSlot] = []
    for index in range(count):
        dy = ((count - 1) / 2.0 - index) * pitch_mm
        floor = profile.floor_height(math.hypot(u0, dy)) or 0.0
        dx, dz = aim_offset(u0, floor, angle)
        slots.append(
            SplitSlot(
                slot=index + 1,
                well=str(index + 1),
                dx=round(dx - base_dx, _ROUND_DIGITS) + 0.0,
                dy=round(dy, _ROUND_DIGITS),
                dz=round(dz - base_dz, _ROUND_DIGITS) + 0.0,
            )
        )
    return SplitWellPlan(
        well=well,
        pitch_mm=pitch_mm,
        slots=tuple(slots),
        requested_x_shift=round(requested, _ROUND_DIGITS),
        x_shift_applied=round(u0, _ROUND_DIGITS),
        limited_by=limited_by,
        well_depth=profile.depth,
    )


__all__ = [
    "CHANNEL_PITCH_BY_TYPE",
    "DEFAULT_HIGH_WALL_MARGIN_MM",
    "DEFAULT_TIP_PROFILES",
    "DEFAULT_WALL_MARGIN_MM",
    "SplitFit",
    "SplitSlot",
    "SplitWellPlan",
    "TipClearance",
    "TipProfile",
    "compute_split_well_plan",
    "normalize_channel_type",
    "normalize_fit",
    "requested_x_shift",
]
