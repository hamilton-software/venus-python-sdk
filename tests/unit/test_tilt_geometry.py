"""Unit tests for hamilton_venus.tilt_geometry (pure math; no VENUS)."""

from __future__ import annotations

import copy
import json
import logging
import math
from itertools import pairwise
from pathlib import Path

import pytest

from hamilton_venus.models import LabwareDefinition, TiltPivotPoint, TiltWellPosition
from hamilton_venus.tilt_clearance import TipClearance, TipProfile
from hamilton_venus.tilt_geometry import compute_tilt_well_deltas, validate_tilt_degrees, well_aim_x_shift

LABWARE_DIR = Path(__file__).resolve().parents[2] / "sdk_method_structure" / "Labware" / "System"


def load(relative: str) -> dict:
    return json.loads((LABWARE_DIR / relative).read_text(encoding="utf-8-sig"))


COS_96_FL = load("plate/Cos_96_Fl.json")  # first well x=14.0, base z=3.57, width 127.0
COS_96_PCR = load("plate/Cos_96_PCR.json")  # first well x=14.0, base z=2.5
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labware"
PLATE_6 = json.loads((FIXTURES / "Greiner_Culture_Plate_6.json").read_text(encoding="utf-8-sig"))
#: A narrow tip with small margins, so the 6 mm wells of a 96-well plate can take one when tilted.
NARROW = TipClearance(TipProfile(end_radius_mm=0.3, radius_taper=0.05, max_radius_mm=1.0), 0.0, 0.3, 0.3)


def by_well(deltas):
    return {d.well: d for d in deltas}


class TestValidateTiltDegrees:
    @pytest.mark.parametrize("value", [0, 1, 5, 10, 7.0, 0.1, 7.5])
    def test_accepts_degrees_in_range_including_fractions(self, value):
        assert validate_tilt_degrees(value) == float(value)

    @pytest.mark.parametrize("value", [-1, 11, 10.5, "5", None, True, math.nan, math.inf])
    def test_rejects_everything_else(self, value):
        with pytest.raises(ValueError):
            validate_tilt_degrees(value)

    def test_a_higher_maximum_for_measured_angles(self):
        assert validate_tilt_degrees(10.8, maximum=15) == 10.8
        with pytest.raises(ValueError, match="measured_tilt_degrees 16 out of range"):
            validate_tilt_degrees(16, maximum=15, name="measured_tilt_degrees")


class TestZeroDegrees:
    @pytest.mark.parametrize("pivot", list(TiltPivotPoint))
    @pytest.mark.parametrize("position", list(TiltWellPosition))
    def test_returns_the_plate_to_nominal(self, pivot, position):
        deltas = compute_tilt_well_deltas(COS_96_FL, 0, pivot, well_position=position)
        assert len(deltas) == 96
        assert all(d.dx == 0.0 and d.dy == 0.0 and d.dz == 3.57 for d in deltas)


class TestKnownValues:
    def test_left_edge_7_degrees(self):
        wells = by_well(compute_tilt_well_deltas(COS_96_FL, 7, TiltPivotPoint.LEFT_EDGE))
        assert wells["A1"].dx == pytest.approx(-0.5394, abs=1e-4)
        assert wells["A1"].dz == pytest.approx(5.2496, abs=1e-4)
        assert wells["H12"].dx == pytest.approx(-1.2774, abs=1e-4)
        assert wells["H12"].dz == pytest.approx(17.3146, abs=1e-4)

    def test_center_7_degrees(self):
        wells = by_well(compute_tilt_well_deltas(COS_96_FL, 7, TiltPivotPoint.CENTER))
        assert wells["A1"].dz == pytest.approx(-2.4891, abs=1e-4)  # left half drops below the rack base
        assert wells["H12"].dz == pytest.approx(9.5759, abs=1e-4)

    @pytest.mark.parametrize("angle", [1, 4, 10])
    @pytest.mark.parametrize("pivot", list(TiltPivotPoint))
    def test_matches_an_independent_rotation_about_the_pivot(self, angle, pivot):
        px = 127.0 / 2 if pivot is TiltPivotPoint.CENTER else 0.0
        t = math.radians(angle)
        for d in compute_tilt_well_deltas(COS_96_FL, angle, pivot):
            col = int(d.well[1:])
            x0, z0 = 14.0 + (col - 1) * 9.0 - px, 3.57
            x1 = x0 * math.cos(t) - z0 * math.sin(t)
            z1 = x0 * math.sin(t) + z0 * math.cos(t)
            assert d.dx == pytest.approx(x1 - x0)
            assert d.dz == pytest.approx(z1)  # rotated container base, measured from the rack base
            assert d.dy == 0.0

    def test_center_pivot_is_symmetric_about_the_middle(self):
        wells = by_well(compute_tilt_well_deltas(COS_96_FL, 6, TiltPivotPoint.CENTER))
        # columns 1 and 12 sit 49.5 mm either side of the 63.5 mm centre
        assert wells["A1"].dz - 3.57 == pytest.approx(-(wells["A12"].dz - 3.57), abs=0.1)


class TestPlateShape:
    def test_wells_are_ordered_by_column_and_share_offsets_within_a_column(self):
        deltas = compute_tilt_well_deltas(COS_96_FL, 6)
        assert [d.well for d in deltas[:9]] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1", "A2"]
        for col in range(12):
            column = deltas[col * 8 : col * 8 + 8]
            assert len({(d.dx, d.dz) for d in column}) == 1

    def test_rise_grows_with_column(self):
        z = [d.dz for d in compute_tilt_well_deltas(COS_96_FL, 10)[::8]]
        assert all(b > a for a, b in pairwise(z))

    def test_accepts_typed_definition_and_response_shapes(self):
        expected = compute_tilt_well_deltas(COS_96_FL, 5)
        assert compute_tilt_well_deltas(LabwareDefinition.model_validate(COS_96_FL), 5) == expected
        assert compute_tilt_well_deltas({"returnParameters": {"definition": COS_96_FL}}, 5) == expected

    def test_384_well_plate(self):
        deltas = compute_tilt_well_deltas(load("plate/Cos_384_PCR.json"), 5)
        assert len(deltas) == 384
        assert deltas[0].well == "A1" and deltas[-1].well == "P24"


class TestPivotOptions:
    def test_deepest_point_shifts_toward_the_low_wall(self):
        center = compute_tilt_well_deltas(PLATE_6, 10)[0]
        deep = compute_tilt_well_deltas(PLATE_6, 10, well_position=TiltWellPosition.DEEPEST_POINT)[0]
        u = well_aim_x_shift(PLATE_6, 10, TiltWellPosition.DEEPEST_POINT)
        assert u > 0
        assert center.dx - deep.dx == pytest.approx(u * math.cos(math.radians(10)))
        assert center.dz - deep.dz == pytest.approx(u * math.sin(math.radians(10)))

    def test_the_aim_is_as_close_to_the_wall_as_one_tip_fits(self):
        # Greiner 6-well: 34.6 mm floor; 1000 uL tip end radius 0.6 mm; 1.0 mm low-wall margin.
        assert well_aim_x_shift(PLATE_6, 10, TiltWellPosition.DEEPEST_POINT) == pytest.approx(17.3 - 0.6 - 1.0)

    def test_highest_point_stays_further_from_its_leaning_wall(self):
        center = compute_tilt_well_deltas(PLATE_6, 10)[0]
        deep = compute_tilt_well_deltas(PLATE_6, 10, well_position="DeepestPoint")[0]
        high = compute_tilt_well_deltas(PLATE_6, 10, well_position=TiltWellPosition.HIGHEST_POINT)[0]
        assert high.dx - center.dx < center.dx - deep.dx
        assert high.dz > center.dz > deep.dz

    def test_clearance_moves_the_aim(self):
        default = well_aim_x_shift(PLATE_6, 10, TiltWellPosition.HIGHEST_POINT)
        wider = well_aim_x_shift(PLATE_6, 10, TiltWellPosition.HIGHEST_POINT, TipClearance(high_wall_margin_mm=3.0))
        raised = well_aim_x_shift(PLATE_6, 10, TiltWellPosition.HIGHEST_POINT, TipClearance(tip_end_height_mm=3.0))
        assert wider == pytest.approx(default + 1.0)
        assert raised < default  # a raised tip end is narrower at the rim, so it can come closer

    def test_measured_angle_is_used_as_given(self):
        deltas = by_well(compute_tilt_well_deltas(COS_96_FL, 10.8))
        t = math.radians(10.8)
        x0, z0 = 14.0, 3.57
        assert deltas["A1"].dz == pytest.approx(x0 * math.sin(t) + z0 * math.cos(t))

    def test_a_shaped_bottom_raises_the_aim_onto_its_floor(self):
        cone = copy.deepcopy(PLATE_6)
        cone["containerGrids"]["default"]["containerDefinition"].update(
            openingDimensions={"shape": "circle", "diameter": 30.0},
            totalDepth=40.0,
            volumeModel={
                "segments": [
                    {"type": "conical_frustum", "height": 10.0, "diameterBottom": 0.0, "diameterTop": 30.0},
                    {"type": "cylinder", "height": 30.0, "diameter": 30.0},
                ]
            },
        )
        t = math.radians(5)
        center = compute_tilt_well_deltas(cone, 5)[0]
        deep = compute_tilt_well_deltas(cone, 5, well_position=TiltWellPosition.DEEPEST_POINT)[0]
        u = well_aim_x_shift(cone, 5, TiltWellPosition.DEEPEST_POINT)
        floor = 10.0 * u / 15.0
        assert deep.dx - center.dx == pytest.approx(-u * math.cos(t) - floor * math.sin(t))
        assert deep.dz - center.dz == pytest.approx(-u * math.sin(t) + floor * math.cos(t))

    def test_no_room_for_a_tip_at_the_deepest_point_raises(self):
        with pytest.raises(ValueError, match="a single tip does not fit"):
            compute_tilt_well_deltas(COS_96_PCR, 10, well_position=TiltWellPosition.DEEPEST_POINT)

    def test_a_narrow_tip_fits_where_the_default_does_not(self):
        deep = compute_tilt_well_deltas(COS_96_PCR, 10, well_position=TiltWellPosition.DEEPEST_POINT, clearance=NARROW)
        assert len(deep) == 96

    def test_a_tight_centre_aim_is_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="hamilton_venus.tilt_geometry"):
            compute_tilt_well_deltas(COS_96_PCR, 10)
        assert "no single tip fits" in caplog.text

    def test_a_comfortable_centre_aim_is_quiet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="hamilton_venus.tilt_geometry"):
            compute_tilt_well_deltas(PLATE_6, 10)
        assert caplog.text == ""

    def test_pivot_offsets_match_venus_tilt_labware(self):
        """First call from a flat plate matches what HSLLabwrAccess::TiltLabware produced in VENUS.

        Captured 2026-10-13 from VENUS 6.6.0.2616 (simulation): TiltLabware(angle 7, x offset 4.0,
        z offset 3.0) on Cos_96_PCR. Values are (XCoord - nominal XCoord, ContainerBaseOffset).
        """
        venus = {
            "H7": (328.2930 - 329.5, 11.23360),
            "C10": (355.0918 - 356.5, 14.52407),
            "B12": (372.9576 - 374.5, 16.71772),
        }
        wells = by_well(compute_tilt_well_deltas(COS_96_PCR, 7, pivot_x_offset_mm=4.0, pivot_z_offset_mm=3.0))
        for well, (dx, dz) in venus.items():
            assert wells[well].dx == pytest.approx(dx, abs=2e-4)
            assert wells[well].dz == pytest.approx(dz, abs=2e-5)


class TestRejects:
    @pytest.mark.parametrize(
        "relative",
        ["reservoir/Ham_DW_Rgt.json", "tip_rack/Tip_Rack_300uL.json", "tube_rack/SMP_CAR_24_17x75.json"],
    )
    def test_non_plate_labware(self, relative):
        with pytest.raises(ValueError, match="only plates"):
            compute_tilt_well_deltas(load(relative), 5)

    def test_irregular_plate(self):
        with pytest.raises(ValueError, match="single rectangular container grid"):
            compute_tilt_well_deltas(load("plate/Cos_96_ProtCryst.json"), 5)

    def test_out_of_range_angle(self):
        with pytest.raises(ValueError):
            compute_tilt_well_deltas(COS_96_FL, 16)
