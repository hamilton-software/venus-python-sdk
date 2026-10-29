"""Per-well offsets for a plate tilted about a hinge parallel to the deck Y axis.

VENUS models every rack as planar, so a plate sitting on a tilt module needs each
well's X and container base Z adjusted before it can be pipetted. This module
computes those adjustments in pure Python from the labware definition; the
``tilt_labware`` command sends them to VENUS (``labware.tiltLabware``), which
applies them to the wells of the existing labware item.

The rotation is ``HSLLabwrAccess::TiltLabware``'s, with two differences:

* It always starts from the definition's **nominal** well positions instead of the
  rack's current (possibly already tilted) ones, so calls never compound and 0
  degrees restores the plate.
* ``DEEPEST_POINT`` / ``HIGHEST_POINT`` aim one tip as close to the low / high wall
  as it fits (:mod:`hamilton_venus.tilt_clearance`), instead of a fixed 85 % of the
  well radius. A fixed fraction leaves room on the low wall however close you want
  to be, and on the high wall ignores that the wall leans over the tip: at 10
  degrees a tip aimed there hits the rim of a 6-well plate.

Conventions:

* Angles are degrees, positive counter-clockwise as seen from the front of the
  instrument, so a positive angle raises the right side. The tilt module is
  commanded in ``0..10``; the angle the plate really sits at may differ a little
  (measure it, see :mod:`hamilton_venus.tilt_calibration`) and may be up to 15.
* The pivot sits on the labware base (Z = 0), at the left edge
  (:attr:`~hamilton_venus.models.enums.TiltPivotPoint.LEFT_EDGE`) or the middle of
  the footprint (:attr:`~hamilton_venus.models.enums.TiltPivotPoint.CENTER`).
  ``pivot_x_offset_mm`` / ``pivot_z_offset_mm`` move it to a measured hinge, with
  the HSL sign convention: positive toward negative deck X / Z.
* ``dx`` is the displacement from the well's nominal X. ``dz`` is the well's
  container base offset above the rack base, i.e. it includes the definition's
  ``firstContainerCenter.z`` (at 0 degrees ``dx == 0`` and ``dz`` equals it).
  ``dy`` is always 0: the hinge is parallel to Y.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from hamilton_venus.models.enums import TiltPivotPoint, TiltWellPosition
from hamilton_venus.models.labware_definition import LabwareDefinition
from hamilton_venus.models.position import LabwareLayoutSpec, _extract_labware_v1_definition
from hamilton_venus.tilt_clearance import TipClearance, TipProfile, WellProfile, aim_offset, closest_aim, tip_interval

logger = logging.getLogger(__name__)

#: Tilt range in degrees the MFX Tilt Module can be commanded to.
MIN_TILT_DEG = 0
MAX_TILT_DEG = 10
#: Largest measured plate angle accepted (a module commanded to 10 may really sit a little higher).
MAX_MEASURED_TILT_DEG = 15

#: Only plates can be tilted; reservoirs, tip racks, tubes and tube racks cannot.
TILTABLE_LABWARE_CLASSES = frozenset({"plate"})


@dataclass(frozen=True)
class TiltWellDelta:
    """The offsets for one well; see the module docstring for what each axis means."""

    well: str
    dx: float
    dy: float
    dz: float


@dataclass(frozen=True)
class TiltSettings:
    """How ``tilt_labware`` last tilted a plate; ``split_wells`` and rebuilds reuse it.

    ``tilt_degrees`` is the angle sent to VENUS (as commanded); ``angle_degrees`` is
    the angle the offsets were computed for (``measured_tilt_degrees``, else the
    commanded one). ``aim_x_shift`` is the plate-frame ``u`` each well was aimed at.
    ``tip_profile`` is the profile passed to ``tilt_labware`` (``None``: the default).
    """

    tilt_degrees: float
    angle_degrees: float
    well_position: TiltWellPosition
    aim_x_shift: float = 0.0
    clearance: TipClearance = field(default_factory=TipClearance)
    tip_profile: TipProfile | None = None


def validate_tilt_degrees(tilt_degrees: float, *, maximum: float = MAX_TILT_DEG, name: str = "tilt_degrees") -> float:
    """Return *tilt_degrees* as a float in ``0..maximum``, else raise :class:`ValueError`."""
    if isinstance(tilt_degrees, bool) or not isinstance(tilt_degrees, (int, float)) or not math.isfinite(tilt_degrees):
        raise ValueError(f"{name} must be a number, got {tilt_degrees!r}")
    if not MIN_TILT_DEG <= tilt_degrees <= maximum:
        raise ValueError(f"{name} {tilt_degrees:g} out of range [{MIN_TILT_DEG}..{maximum:g}]")
    return float(tilt_degrees)


def _as_definition(definition: LabwareDefinition | dict[str, Any]) -> LabwareDefinition:
    if isinstance(definition, LabwareDefinition):
        return definition
    payload = _extract_labware_v1_definition(definition) if isinstance(definition, dict) else None
    if payload is None:
        raise ValueError("expected a labware:v1 definition (with 'containerGrids') to compute tilt offsets")
    return LabwareDefinition.model_validate(payload)


def well_aim_x_shift(
    definition: LabwareDefinition | dict[str, Any],
    tilt_degrees: float,
    well_position: TiltWellPosition | str,
    clearance: TipClearance | None = None,
) -> float:
    """The plate-frame ``u`` one tip aims at for *well_position*; 0 for the centre or a flat plate.

    ``DEEPEST_POINT`` / ``HIGHEST_POINT`` are as close to the low / high wall as one
    tip fits with *clearance* (default :class:`TipClearance`).

    Raises:
        ValueError: If a single tip does not fit in the well at this angle.
    """
    angle = validate_tilt_degrees(tilt_degrees, maximum=MAX_MEASURED_TILT_DEG)
    position = TiltWellPosition(well_position)
    if position is TiltWellPosition.CENTER or angle == 0:
        return 0.0
    profile = WellProfile(_as_definition(definition))
    return closest_aim(profile, clearance or TipClearance(), angle, position)


def compute_tilt_well_deltas(
    definition: LabwareDefinition | dict[str, Any],
    tilt_degrees: float,
    pivot_point: TiltPivotPoint | str = TiltPivotPoint.LEFT_EDGE,
    *,
    pivot_x_offset_mm: float = 0.0,
    pivot_z_offset_mm: float = 0.0,
    well_position: TiltWellPosition | str = TiltWellPosition.CENTER,
    clearance: TipClearance | None = None,
) -> list[TiltWellDelta]:
    """Offsets for every well of a plate tilted by *tilt_degrees* about *pivot_point*.

    *definition* is a :class:`LabwareDefinition` or any payload
    :meth:`LabwareLayoutSpec.from_definition` accepts (e.g. a
    ``labware_get_params_from_id`` response dumped by alias). Wells are returned
    column by column (A1, B1, ..., H12). *tilt_degrees* is the angle the plate really
    sits at (``0..15``).

    *well_position* aims each well at its centre, or as close to its low wall
    (``DEEPEST_POINT``) or high wall (``HIGHEST_POINT``) as one tip fits with
    *clearance* (the tip, the tip end height and the wall margins; default
    :class:`~hamilton_venus.tilt_clearance.TipClearance`). On a V- or round-bottom
    well the aim is raised onto the sloped floor. It has no effect at 0 degrees.
    A centre aim where the tip would come closer than the margins to a wall is
    logged as a warning.

    Raises :class:`ValueError` for an angle outside ``0..15``, a non-plate labware
    class, a definition without exactly one container grid, or a ``DEEPEST_POINT`` /
    ``HIGHEST_POINT`` aim where no single tip fits (the message gives the largest
    angle at which it would).
    """
    angle = validate_tilt_degrees(tilt_degrees, maximum=MAX_MEASURED_TILT_DEG)
    pivot = TiltPivotPoint(pivot_point)
    position = TiltWellPosition(well_position)
    defn = _as_definition(definition)

    if defn.labware_class not in TILTABLE_LABWARE_CLASSES:
        raise ValueError(
            f"only plates can be tilted; {defn.display_name or defn.id or 'labware'!s} "
            f"is labwareClass {defn.labware_class!r}"
        )
    grids = list(defn.container_grids.values())
    if len(grids) != 1:
        raise ValueError(f"tilting needs a single rectangular container grid, found {len(grids)}")
    grid = grids[0]
    spec = LabwareLayoutSpec.from_definition(defn)

    pivot_x = defn.dimensions.x / 2.0 if pivot is TiltPivotPoint.CENTER else 0.0
    px = pivot_x - pivot_x_offset_mm
    pz = -pivot_z_offset_mm
    base_z = grid.first_container_center.z

    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    aim_dx = aim_dz = 0.0
    if angle > 0:
        clearance = clearance or TipClearance()
        profile = WellProfile(defn)
        if position is TiltWellPosition.CENTER:
            _warn_if_centre_is_tight(profile, clearance, angle, defn)
        else:
            u = closest_aim(profile, clearance, angle, position)
            aim_dx, aim_dz = aim_offset(u, profile.floor_height(abs(u)) or 0.0, angle)

    deltas: list[TiltWellDelta] = []
    for col in range(1, spec.cols + 1):
        cx = grid.first_container_center.x + (col - 1) * grid.column_pitch - px
        cz = base_z - pz
        dx = cx * cos_t - cz * sin_t - cx + aim_dx
        dz = cx * sin_t + cz * cos_t - cz + aim_dz + base_z
        for row_index in range(spec.rows):
            deltas.append(TiltWellDelta(spec.emit_well(row_index, col), dx, 0.0, dz))
    return deltas


def _warn_if_centre_is_tight(
    profile: WellProfile, clearance: TipClearance, angle: float, defn: LabwareDefinition
) -> None:
    span = tip_interval(profile, clearance, half_span=0.0, tilt_degrees=angle)
    if span is not None and span[0] <= 0.0 <= span[1]:
        return
    name = defn.display_name or defn.id or "the plate"
    if span is None:
        detail = "no single tip fits in its wells"
    else:
        detail = "a tip at the well centre comes closer than the margins to a wall"
    logger.warning("%s tilted to %g degrees: %s with %s", name, angle, detail, clearance.describe())


__all__ = [
    "MAX_MEASURED_TILT_DEG",
    "MAX_TILT_DEG",
    "MIN_TILT_DEG",
    "TILTABLE_LABWARE_CLASSES",
    "TiltSettings",
    "TiltWellDelta",
    "compute_tilt_well_deltas",
    "validate_tilt_degrees",
    "well_aim_x_shift",
]
