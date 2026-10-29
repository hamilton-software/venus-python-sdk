"""Unit tests for hamilton_venus.tilt_calibration (pure math; no VENUS)."""

from __future__ import annotations

import math

import pytest

from hamilton_venus.tilt_calibration import fit_hinge_at_angle, fit_tilt_hinge

PLATE = {"plate_left_edge_x": 418.9, "plate_base_z": 199.65}


def rotate_about(point, hinge, degrees):
    t = math.radians(degrees)
    dx, dz = point[0] - hinge[0], point[1] - hinge[1]
    return hinge[0] + math.cos(t) * dx - math.sin(t) * dz, hinge[1] + math.sin(t) * dx + math.cos(t) * dz


class TestFitTiltHinge:
    def test_recovers_an_exact_rotation(self):
        flat = {"B1": (424.7, 203.0), "B3": (504.9, 203.0), "A2": (464.8, 203.0)}
        hinge = (420.0, 194.0)
        tilted = {name: rotate_about(p, hinge, 10.6) for name, p in flat.items()}

        fit = fit_tilt_hinge(flat, tilted, commanded_degrees=10, **PLATE)

        assert fit.best.angle_degrees == pytest.approx(10.6)
        assert (fit.best.hinge_x, fit.best.hinge_z) == pytest.approx(hinge, abs=1e-6)
        assert fit.best.rms_mm == pytest.approx(0.0, abs=1e-6)
        assert fit.best.pivot_x_offset_mm == pytest.approx(418.9 - 420.0)
        assert fit.best.pivot_z_offset_mm == pytest.approx(199.65 - 194.0)
        assert fit.span_change_mm == pytest.approx(0.0, abs=1e-9)
        assert fit.flat_span_mm == pytest.approx(464.8 - 424.7)  # first to last point: B1 to A2

    def test_the_tilt_module_readings_of_2026_10_16(self):
        # Left wall meeting the floor, row B, columns 1 and 3, flat and commanded to 10 degrees.
        flat = {"B1": (424.7, 203.0), "B3": (504.9, 203.0)}
        tilted = {"B1": (423.0, 203.4), "B3": (502.1, 218.5)}

        fit = fit_tilt_hinge(flat, tilted, commanded_degrees=10, **PLATE)

        assert fit.best.angle_degrees == pytest.approx(10.8, abs=0.05)
        assert fit.best.rms_mm == pytest.approx(0.12, abs=0.01)
        assert (fit.at_commanded.pivot_x_offset_mm, fit.at_commanded.pivot_z_offset_mm) == pytest.approx(
            (0.7, 5.5), abs=0.05
        )
        assert fit.at_commanded.rms_mm == pytest.approx(0.42, abs=0.01)
        assert fit.tilt_labware_kwargs() == {
            "pivot_x_offset_mm": round(fit.best.pivot_x_offset_mm, 2),
            "pivot_z_offset_mm": round(fit.best.pivot_z_offset_mm, 2),
            "measured_tilt_degrees": 10.81,
        }
        assert "measured_tilt_degrees" not in fit.tilt_labware_kwargs(use_measured_angle=False)

    def test_rejects_bad_readings(self):
        one = {"B1": (424.7, 203.0)}
        two = {"B1": (424.7, 203.0), "B3": (504.9, 203.0)}
        with pytest.raises(ValueError, match="at least two"):
            fit_tilt_hinge(one, one, commanded_degrees=10, **PLATE)
        with pytest.raises(ValueError, match="same points"):
            fit_tilt_hinge(two, one, commanded_degrees=10, **PLATE)
        with pytest.raises(ValueError, match="above 0"):
            fit_tilt_hinge(two, two, commanded_degrees=0, **PLATE)
        with pytest.raises(ValueError, match="non-zero angle"):
            fit_hinge_at_angle(two, two, 0, **PLATE)
