"""Where a vertical tip fits inside a well of a tilted plate.

Shared by ``tilt_labware`` (where one tip aims in each well) and ``split_wells``
(several tips side by side in one well). Pure Python, from the labware definition.

Frames and conventions:

* ``u`` is the offset across the well along deck X **in the plate's frame**,
  positive toward the low wall of a tilted plate (deck -X for a positive angle).
  ``u0`` is where the tip's centre line meets the well floor. Heights ``v`` are
  measured up the well axis from its lowest point.
* The channels stay vertical while the well tilts by ``theta``, so a tip whose
  centre line meets the floor at ``u0`` is at ``u0 - v * tan(theta)`` at well
  height ``v``: it moves away from the low wall going up, and toward the high
  wall, which leans in over the tip.
* The tip end sits ``tip_end_height_mm`` above the floor, measured vertically (the
  aspirate / dispense fixed height). Above the end, the tip widens as a cone
  (:class:`TipProfile`).
* A tip fits when, at every checked height, the tip's surface stays a wall margin
  inside the well: ``wall_margin_mm`` from the low wall (and the walls along the
  hinge), ``high_wall_margin_mm`` from the high wall. The high wall leans in, so
  errors in the real angle, the hinge or the teaching reach it first. Checks are
  made at the tip end, at each segment boundary above any shaped bottom, and at
  the rim; between those heights the constraint is convex, so the ends bound it.

The default tip profiles and margins were checked on a real MFX Tilt Module with a
6-well plate at 10 degrees. Calibrate them for your tips and module: pass your own
:class:`TipProfile` and margins when the defaults are too tight or too loose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from hamilton_venus.models.enums import SplitChannelType, TiltWellPosition
from hamilton_venus.models.labware_definition import LabwareDefinition, VolumeSegment

#: Default gap (mm) between a tip's surface and the low wall, and the walls along the hinge.
DEFAULT_WALL_MARGIN_MM = 1.0
#: Default gap (mm) between a tip's surface and the high wall, which leans in over the tip.
DEFAULT_HIGH_WALL_MARGIN_MM = 2.0

#: A bottom segment counts as a shaped (V or round) bottom when it is a spherical
#: cap, or a cone whose bottom radius is below this fraction of its top radius. A
#: slight draft (e.g. 6.35 -> 6.86 mm) is a flat-bottom well.
_SHAPED_CONE_RATIO = 0.75

#: Step (degrees) used to find the largest angle at which a tip still fits.
_FIT_ANGLE_STEP = 0.1


@dataclass(frozen=True)
class TipProfile:
    """Simplified tip shape: a cone from the tip end, capped at the tip body radius."""

    end_radius_mm: float
    radius_taper: float
    max_radius_mm: float

    def radius(self, height_above_end: float) -> float:
        """The tip's outside radius *height_above_end* mm above its end."""
        return min(self.end_radius_mm + self.radius_taper * max(0.0, height_above_end), self.max_radius_mm)

    @classmethod
    def from_measurements(
        cls,
        lower_diameter_mm: float,
        upper_diameter_mm: float,
        height_mm: float,
        *,
        max_diameter_mm: float,
    ) -> TipProfile:
        """A profile from a tip's outside diameter at its end and *height_mm* above it.

        The cone continues past the measured height until it reaches *max_diameter_mm*.
        """
        if height_mm <= 0 or upper_diameter_mm < lower_diameter_mm:
            raise ValueError("expected height_mm > 0 and upper_diameter_mm >= lower_diameter_mm")
        return cls(
            end_radius_mm=lower_diameter_mm / 2.0,
            radius_taper=(upper_diameter_mm - lower_diameter_mm) / 2.0 / height_mm,
            max_radius_mm=max_diameter_mm / 2.0,
        )


#: Profiles for 1000 uL and 5 mL CO-RE tips, measured over their lowest 19.8 mm. Above
#: that the taper is assumed to continue up to an estimated body diameter (8 / 10 mm).
#: Smaller tips on 1 mL channels (e.g. 300 uL) are narrower: pass their own profile.
DEFAULT_TIP_PROFILES: dict[SplitChannelType, TipProfile] = {
    SplitChannelType.ONE_ML: TipProfile.from_measurements(1.2, 5.4, 19.8, max_diameter_mm=8.0),
    SplitChannelType.FIVE_ML: TipProfile.from_measurements(1.8, 6.0, 19.8, max_diameter_mm=10.0),
}


@dataclass(frozen=True)
class TipClearance:
    """The tip and the room to keep around it: what decides where a tip fits in a well.

    Args:
        tip: The tip's shape.
        tip_end_height_mm: How far above the well floor the tip end sits (the
            aspirate / dispense fixed height). 0 is the most conservative.
        wall_margin_mm: Gap between the tip and the low wall (and the walls along
            the hinge).
        high_wall_margin_mm: Gap between the tip and the high wall. On a flat
            plate both walls use ``wall_margin_mm``.
    """

    tip: TipProfile = field(default_factory=lambda: DEFAULT_TIP_PROFILES[SplitChannelType.ONE_ML])
    tip_end_height_mm: float = 0.0
    wall_margin_mm: float = DEFAULT_WALL_MARGIN_MM
    high_wall_margin_mm: float = DEFAULT_HIGH_WALL_MARGIN_MM

    def __post_init__(self) -> None:
        for name in ("tip_end_height_mm", "wall_margin_mm", "high_wall_margin_mm"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a number >= 0, got {value!r}")

    def describe(self) -> str:
        return (
            f"the tip end {self.tip_end_height_mm:g} mm above the floor and wall margins "
            f"{self.wall_margin_mm:g} mm (low wall) / {self.high_wall_margin_mm:g} mm (high wall)"
        )


@dataclass(frozen=True)
class _Check:
    height: float
    half_x: float
    half_y: float


class WellProfile:
    """Radius-versus-height profile of one plate's container, from its volume model."""

    def __init__(self, definition: LabwareDefinition) -> None:
        grids = list(definition.container_grids.values())
        if len(grids) != 1:
            raise ValueError(f"fitting tips in a well needs a single rectangular container grid, found {len(grids)}")
        container = grids[0].container_definition
        opening = container.opening_dimensions
        self.rectangular = opening.shape == "rectangle"
        if self.rectangular:
            self.open_half_x = (opening.width or 0.0) / 2.0
            self.open_half_y = (opening.depth or 0.0) / 2.0
        else:
            self.open_half_x = self.open_half_y = (opening.diameter or 0.0) / 2.0

        fallback = min((r for r in (self.open_half_x, self.open_half_y) if r > 0), default=0.0)
        self.segments: list[tuple[VolumeSegment, float, float]] = []
        for segment in container.volume_model.segments:
            bottom, top = _segment_radii(segment, fallback)
            self.segments.append((segment, bottom, top))
        if not self.segments:
            if fallback <= 0:
                raise ValueError("the well has no opening dimensions or volume model to size it from")
            depth = container.total_depth
            self.segments.append((VolumeSegment(type="cylinder", height=depth), fallback, fallback))
        if all(top <= 0 for _, _, top in self.segments):
            raise ValueError("the well's opening diameter is 0 and its volume model gives no diameter either")

        self.depth = container.total_depth or sum(segment.height for segment, _, _ in self.segments)
        self.shaped_top = 0.0
        for segment, bottom, top in self.segments:
            if segment.type == "spherical_cap" or (
                segment.type in ("conical_frustum", "rectangular_frustum") and bottom < _SHAPED_CONE_RATIO * top
            ):
                self.shaped_top += segment.height
            else:
                break

    def floor_height(self, radial: float) -> float | None:
        """Height of the floor at *radial* mm from the well axis, or ``None`` outside the well."""
        z0 = 0.0
        for segment, bottom, top in self.segments:
            if radial <= bottom:
                return z0
            if radial <= top:
                if segment.type == "spherical_cap" and segment.height > 0:
                    sphere = (top**2 + segment.height**2) / (2.0 * segment.height)
                    return z0 + sphere - math.sqrt(max(0.0, sphere**2 - radial**2))
                return z0 + segment.height * (radial - bottom) / (top - bottom)
            z0 += segment.height
        return None

    def radius_at(self, height: float) -> float:
        """The well's radius (round wells) *height* mm above its lowest point."""
        z0 = 0.0
        radius = self.segments[-1][2]
        for segment, bottom, top in self.segments:
            if height <= z0 + segment.height:
                fraction = 0.0 if segment.height <= 0 else min(1.0, max(0.0, (height - z0) / segment.height))
                radius = bottom + (top - bottom) * fraction
                break
            z0 += segment.height
        if self.open_half_x > 0 and height >= self.depth:
            radius = min(radius, self.open_half_x)
        return radius

    def checks(self, from_height: float = 0.0) -> list[_Check]:
        """Heights at or above *from_height* at which a tip must fit, with the well half-widths there."""
        heights: list[tuple[float, float]] = []
        z0 = 0.0
        previous_top: float | None = None
        for segment, bottom, top in self.segments:
            radius = bottom if previous_top is None else min(previous_top, bottom)
            if z0 >= self.shaped_top and (z0 > 0 or self.shaped_top == 0) and z0 >= from_height:
                heights.append((z0, radius))
            z0 += segment.height
            previous_top = top
        assert previous_top is not None
        rim = max(z0, self.depth)
        if heights and heights[-1][0] == rim:
            heights.pop()
        heights.append((rim, previous_top))
        if self.shaped_top <= from_height < rim and all(height != from_height for height, _ in heights):
            heights.append((from_height, self.radius_at(from_height)))
        heights.sort()

        checks: list[_Check] = []
        for height, radius in heights:
            if self.rectangular:
                half_x, half_y = self.open_half_x, self.open_half_y
            else:
                half_x = half_y = radius
                if self.open_half_x > 0 and height >= self.depth:
                    half_x = half_y = min(radius, self.open_half_x)
            if half_x > 0 and half_y > 0:
                checks.append(_Check(height, half_x, half_y))
        return checks


def _segment_radii(segment: VolumeSegment, fallback: float) -> tuple[float, float]:
    """Bottom and top radius of one volume segment, falling back to the opening."""
    kind = segment.type
    if kind == "cylinder":
        radius = (segment.diameter or 0.0) / 2.0 or fallback
        return radius, radius
    if kind == "conical_frustum":
        return (segment.diameter_bottom or 0.0) / 2.0, (segment.diameter_top or 0.0) / 2.0 or fallback
    if kind == "spherical_cap":
        return 0.0, (segment.diameter or 0.0) / 2.0 or fallback
    if kind == "rectangular_prism":
        sizes = [s for s in (segment.width, segment.depth) if s]
        radius = min(sizes) / 2.0 if sizes else fallback
        return radius, radius
    if kind == "rectangular_frustum":
        bottoms = [s for s in (segment.width_bottom, segment.depth_bottom) if s is not None]
        tops = [s for s in (segment.width_top, segment.depth_top) if s]
        return (min(bottoms) / 2.0 if bottoms else 0.0), (min(tops) / 2.0 if tops else fallback)
    return fallback, fallback


def tip_interval(
    profile: WellProfile, clearance: TipClearance, *, half_span: float, tilt_degrees: float
) -> tuple[float, float] | None:
    """Range of floor offsets ``u0`` at which a row of tips out to ``±half_span`` along the hinge all fit.

    ``None`` when no ``u0`` fits. One tip is ``half_span=0``.
    """
    theta = math.radians(tilt_degrees)
    cos_t, tan_t = math.cos(theta), math.tan(theta)
    end = clearance.tip_end_height_mm
    low = clearance.wall_margin_mm
    high = clearance.high_wall_margin_mm if tilt_degrees > 0 else low
    checks = profile.checks(from_height=end * cos_t)
    lo, hi = -math.inf, math.inf
    for check in checks:
        tip_radius = clearance.tip.radius(check.height / cos_t - end)
        reaches: list[float] = []
        for margin in (low, high):
            room = check.half_x - tip_radius - margin
            if profile.rectangular:
                if half_span + tip_radius + low > check.half_y:
                    return None
                reach = room
            else:
                if room < half_span:
                    return None
                reach = math.sqrt(room**2 - half_span**2)
            if reach < 0:
                return None
            reaches.append(reach)
        drift = check.height * tan_t
        lo, hi = max(lo, drift - reaches[1]), min(hi, drift + reaches[0])
    if not checks or lo > hi:
        return None
    return lo, hi


def largest_fitting_tilt(
    profile: WellProfile, clearance: TipClearance, *, half_span: float, upto: float
) -> float | None:
    """The largest angle (0.1-degree steps, up to *upto*) at which the tips still fit, or ``None``."""
    steps = round(upto / _FIT_ANGLE_STEP)
    for step in range(steps, -1, -1):
        angle = step * _FIT_ANGLE_STEP
        if tip_interval(profile, clearance, half_span=half_span, tilt_degrees=angle) is not None:
            return round(angle, 1)
    return None


def no_fit_message(
    profile: WellProfile, clearance: TipClearance, *, tips: int, half_span: float, tilt_degrees: float
) -> str:
    """Why *tips* tips do not fit at *tilt_degrees*, and the largest angle at which they would."""
    what = "a single tip does" if tips == 1 else f"{tips} tips do"
    best = largest_fitting_tilt(profile, clearance, half_span=half_span, upto=tilt_degrees)
    if best is None:
        hint = "not even with the plate flat"
    elif best == 0:
        hint = "only with the plate flat"
    else:
        hint = f"{'it fits' if tips == 1 else 'they fit'} up to {best:g} degrees"
    return (
        f"{what} not fit in the well at {tilt_degrees:g} degrees with {clearance.describe()} ({hint}). "
        "Use a smaller angle, a narrower tip_profile, a higher tip_end_height_mm or smaller margins."
    )


def closest_aim(
    profile: WellProfile, clearance: TipClearance, tilt_degrees: float, well_position: TiltWellPosition | str
) -> float:
    """The plate-frame ``u`` one tip aims at for *well_position*; 0 for the centre or a flat plate.

    ``DEEPEST_POINT`` / ``HIGHEST_POINT`` are the closest a tip can come to the low /
    high wall with *clearance*.

    Raises:
        ValueError: If a single tip does not fit at all (the message says the
            largest angle at which it would).
    """
    position = TiltWellPosition(well_position)
    if position is TiltWellPosition.CENTER or tilt_degrees == 0:
        return 0.0
    span = tip_interval(profile, clearance, half_span=0.0, tilt_degrees=tilt_degrees)
    if span is None:
        raise ValueError(no_fit_message(profile, clearance, tips=1, half_span=0.0, tilt_degrees=tilt_degrees))
    return span[1] if position is TiltWellPosition.DEEPEST_POINT else span[0]


def aim_offset(u: float, floor_height: float, tilt_degrees: float) -> tuple[float, float]:
    """Deck-frame (dx, dz) of a floor point ``u`` from the well centre, raised *floor_height* by a shaped bottom."""
    theta = math.radians(tilt_degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return -u * cos_t - floor_height * sin_t, -u * sin_t + floor_height * cos_t


__all__ = [
    "DEFAULT_HIGH_WALL_MARGIN_MM",
    "DEFAULT_TIP_PROFILES",
    "DEFAULT_WALL_MARGIN_MM",
    "TipClearance",
    "TipProfile",
    "WellProfile",
    "aim_offset",
    "closest_aim",
    "largest_fitting_tilt",
    "no_fit_message",
    "tip_interval",
]
