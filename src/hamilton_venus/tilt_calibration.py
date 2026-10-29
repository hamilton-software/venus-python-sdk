"""Calibrate a tilt module: its real plate angle and hinge, from probe readings.

A tilt module commanded to 10 degrees may hold the plate at a slightly different
angle (10.8 on one module tested), and its hinge is a pin under the plate, not the
plate's lower-left corner that ``tilt_labware`` assumes by default. Both move every
well: a hinge 6 mm below the plate shifts the wells about 2 mm in X at 10 degrees.

How to measure (VENUS "Move Probe - Key Control", or any probe on the channels):

1. With the module **flat**, read deck X and Z at two points far apart along X,
   e.g. where the left wall of a well meets its floor in the leftmost and the
   rightmost column of one row.
2. Tilt the module to the angle you will command, and read the same two points.
3. Pass the readings to :func:`fit_tilt_hinge` with the plate's left edge X and base
   Z when flat (from the deck layout), and use the result in ``tilt_labware``:
   ``star.tilt_labware(plate, 10, **fit.tilt_labware_kwargs())``.

A rigid plate keeps the distance between the two points: if the flat and tilted
spans differ by more than the reading noise (about 0.5 mm), re-take the readings
(or check the plate sits firmly on the module) before trusting the fit. The flat
span is also a check on the plate's labware definition: it should equal the column
pitch times the number of columns between the points. With only two points, the
angle and the hinge X trade off against each other a little: the fit also reports
the hinge for exactly the commanded angle.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hamilton_venus.tilt_geometry import MAX_MEASURED_TILT_DEG, MAX_TILT_DEG, validate_tilt_degrees

#: X / Z deck coordinates (mm) of one probed point.
Point = tuple[float, float]

_ANGLE_STEP_DEG = 0.01


@dataclass(frozen=True)
class HingeFit:
    """The hinge that best turns the flat readings into the tilted ones at one angle."""

    angle_degrees: float
    hinge_x: float
    hinge_z: float
    pivot_x_offset_mm: float
    pivot_z_offset_mm: float
    rms_mm: float


@dataclass(frozen=True)
class TiltCalibration:
    """A tilt module's calibration from probe readings (see :func:`fit_tilt_hinge`).

    ``best`` is the best-fit angle and its hinge; ``at_commanded`` the hinge fitted
    for exactly the commanded angle. ``flat_span_mm`` is the distance between the
    first and last probed point when flat (compare it with the labware definition's
    pitch); ``span_change_mm`` is how much it changed when tilted (a rigid plate
    keeps it, so a large change means a bad reading).
    Pivot offsets are relative to the plate's left edge and base
    (``TiltPivotPoint.LEFT_EDGE``): positive X toward -X, positive Z below the base.
    """

    commanded_degrees: float
    best: HingeFit
    at_commanded: HingeFit
    flat_span_mm: float
    span_change_mm: float

    def tilt_labware_kwargs(self, *, use_measured_angle: bool = True) -> dict[str, Any]:
        """Keyword arguments for ``tilt_labware``: the hinge, and the measured angle if *use_measured_angle*."""
        fit = self.best if use_measured_angle else self.at_commanded
        kwargs: dict[str, Any] = {
            "pivot_x_offset_mm": round(fit.pivot_x_offset_mm, 2),
            "pivot_z_offset_mm": round(fit.pivot_z_offset_mm, 2),
        }
        if use_measured_angle:
            kwargs["measured_tilt_degrees"] = round(fit.angle_degrees, 2)
        return kwargs


def _rotate(point: Point, cos_t: float, sin_t: float) -> Point:
    return cos_t * point[0] - sin_t * point[1], sin_t * point[0] + cos_t * point[1]


def fit_hinge_at_angle(
    flat: Mapping[str, Point],
    tilted: Mapping[str, Point],
    angle_degrees: float,
    *,
    plate_left_edge_x: float,
    plate_base_z: float,
) -> HingeFit:
    """The least-squares hinge for a rotation of *angle_degrees* from *flat* to *tilted*.

    Rotating each flat point about hinge ``h`` gives ``R p + (I - R) h``; the best
    ``h`` solves ``(I - R) h = mean(t - R p)`` exactly.
    """
    keys = _paired_keys(flat, tilted)
    theta = math.radians(angle_degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    if abs(sin_t) < 1e-9:
        raise ValueError("the hinge can only be fitted for a non-zero angle")
    bx = sum(tilted[k][0] - _rotate(flat[k], cos_t, sin_t)[0] for k in keys) / len(keys)
    bz = sum(tilted[k][1] - _rotate(flat[k], cos_t, sin_t)[1] for k in keys) / len(keys)
    # (I - R) = [[1 - c, s], [-s, 1 - c]]; its inverse is its transpose / det.
    a, s = 1.0 - cos_t, sin_t
    det = a * a + s * s
    hx = (a * bx - s * bz) / det
    hz = (s * bx + a * bz) / det
    residuals: list[float] = []
    for k in keys:
        rx, rz = _rotate((flat[k][0] - hx, flat[k][1] - hz), cos_t, sin_t)
        residuals += [hx + rx - tilted[k][0], hz + rz - tilted[k][1]]
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    return HingeFit(
        angle_degrees=angle_degrees,
        hinge_x=hx,
        hinge_z=hz,
        pivot_x_offset_mm=plate_left_edge_x - hx,
        pivot_z_offset_mm=plate_base_z - hz,
        rms_mm=rms,
    )


def fit_tilt_hinge(
    flat: Mapping[str, Point],
    tilted: Mapping[str, Point],
    *,
    commanded_degrees: float,
    plate_left_edge_x: float,
    plate_base_z: float,
    search_degrees: float = 3.0,
) -> TiltCalibration:
    """Fit a tilt module's real angle and hinge from probe readings.

    Args:
        flat: Deck ``(X, Z)`` of two or more points with the module flat, by name.
        tilted: The same points with the module at *commanded_degrees*.
        commanded_degrees: The angle the module was commanded to (``0 < angle <= 10``).
        plate_left_edge_x: The plate's left edge deck X when flat.
        plate_base_z: The plate's base deck Z when flat.
        search_degrees: How far either side of the commanded angle to look for the
            best-fit angle.

    Raises:
        ValueError: For fewer than two points, points missing from one set, or a
            commanded angle of 0.
    """
    commanded = validate_tilt_degrees(commanded_degrees, maximum=MAX_TILT_DEG, name="commanded_degrees")
    if commanded == 0:
        raise ValueError("commanded_degrees must be above 0 to fit a hinge")
    keys = _paired_keys(flat, tilted)
    place = {"plate_left_edge_x": plate_left_edge_x, "plate_base_z": plate_base_z}
    low = max(_ANGLE_STEP_DEG, commanded - search_degrees)
    high = min(MAX_MEASURED_TILT_DEG, commanded + search_degrees)
    steps = round((high - low) / _ANGLE_STEP_DEG)
    best = min(
        (fit_hinge_at_angle(flat, tilted, round(low + i * _ANGLE_STEP_DEG, 2), **place) for i in range(steps + 1)),
        key=lambda fit: fit.rms_mm,
    )
    first, last = keys[0], keys[-1]
    flat_span = math.dist(flat[first], flat[last])
    span_change = math.dist(tilted[first], tilted[last]) - flat_span
    return TiltCalibration(
        commanded_degrees=commanded,
        best=best,
        at_commanded=fit_hinge_at_angle(flat, tilted, commanded, **place),
        flat_span_mm=flat_span,
        span_change_mm=span_change,
    )


def _paired_keys(flat: Mapping[str, Point], tilted: Mapping[str, Point]) -> list[str]:
    if set(flat) != set(tilted):
        raise ValueError(f"flat and tilted readings must name the same points, got {sorted(flat)} and {sorted(tilted)}")
    if len(flat) < 2:
        raise ValueError("at least two probed points are needed")
    return list(flat)


__all__ = ["HingeFit", "Point", "TiltCalibration", "fit_hinge_at_angle", "fit_tilt_hinge"]
