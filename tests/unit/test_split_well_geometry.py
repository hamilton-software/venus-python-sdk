"""Unit tests for split_well_geometry: how many channels fit in a large well, and where."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from hamilton_venus.models import SplitChannelType, SplitWellFit, TiltWellPosition
from hamilton_venus.split_well_geometry import (
    DEFAULT_TIP_PROFILES,
    TipClearance,
    TipProfile,
    compute_split_well_plan,
    requested_x_shift,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labware"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8-sig"))


PLATE_6 = load("Greiner_Culture_Plate_6")
PLATE_12 = load("Greiner_Culture_Plate_12")
PLATE_24 = load("Greiner_Culture_Plate_24")
SIX_WELL_MEASURED = load("SixWell_Measured_1016")
#: Tip end 2 mm above the floor, margins 1.0 / 2.0 mm: the settings checked on the instrument.
MEASURED_SETTINGS = {"tip_end_height_mm": 2.0, "wall_margin_mm": 1.0, "high_wall_margin_mm": 2.0}

ONE_ML_TIP = DEFAULT_TIP_PROFILES[SplitChannelType.ONE_ML]
ONE_ML = {"pitch_mm": 9.0, "tip": ONE_ML_TIP}
FIVE_ML = {"pitch_mm": 18.0, "tip": DEFAULT_TIP_PROFILES[SplitChannelType.FIVE_ML]}
DEEPEST = TiltWellPosition.DEEPEST_POINT


def plan(definition, *, max_channels=8, channel=ONE_ML, **kwargs):
    return compute_split_well_plan(definition, "A1", max_channels=max_channels, **channel, **kwargs)


def with_container(definition: dict, **container) -> dict:
    """A copy of *definition* with its container definition fields replaced."""
    result = copy.deepcopy(definition)
    result["containerGrids"]["default"]["containerDefinition"].update(container)
    return result


class TestSlotCount:
    @pytest.mark.parametrize(
        ("definition", "one_ml", "five_ml"),
        [(PLATE_6, 4, 2), (PLATE_12, 2, 1), (PLATE_24, 2, 1)],
        ids=["6-well", "12-well", "24-well"],
    )
    def test_flat_plates(self, definition, one_ml, five_ml):
        assert plan(definition).slot_count == one_ml
        assert plan(definition, channel=FIVE_ML).slot_count == five_ml

    def test_slots_are_centred_on_the_well_back_to_front(self):
        result = plan(PLATE_6)

        assert [s.well for s in result.slots] == ["1", "2", "3", "4"]
        assert [s.dy for s in result.slots] == [13.5, 4.5, -4.5, -13.5]
        assert all(s.dx == 0.0 and s.dz == 0.0 for s in result.slots)
        assert result.limited_by == "chord"

    def test_max_channels_caps_the_count(self):
        result = plan(PLATE_6, max_channels=3)

        assert result.slot_count == 3
        assert [s.dy for s in result.slots] == [9.0, 0.0, -9.0]
        assert result.limited_by == "max_channels"

    def test_zero_opening_diameter_falls_back_to_the_volume_model(self):
        # Greiner 12-well has openingDimensions.diameter == 0.0; its frustum is 22.2 -> 22.7 mm.
        assert PLATE_12["containerGrids"]["default"]["containerDefinition"]["openingDimensions"]["diameter"] == 0.0
        assert plan(PLATE_12).slot_count == 2

    def test_no_usable_size_raises(self):
        blank = with_container(PLATE_12, volumeModel={"segments": []})

        with pytest.raises(ValueError, match="no opening dimensions"):
            plan(blank)

    def test_a_wider_tip_fits_fewer(self):
        fat = TipProfile(end_radius_mm=4.0, radius_taper=0.0, max_radius_mm=4.0)

        assert plan(PLATE_6, channel={"pitch_mm": 9.0, "tip": fat}).slot_count == 3


class TestTiltedDeepestPoint:
    def test_requested_shift_is_the_closest_one_tip_fits(self):
        deep = requested_x_shift(PLATE_6, 10, DEEPEST)
        high = requested_x_shift(PLATE_6, 10, TiltWellPosition.HIGHEST_POINT)

        # Low wall: the tip end binds, 1.0 mm margin + 0.6 mm tip end radius from the 17.3 mm floor radius.
        assert deep == pytest.approx(17.3 - ONE_ML_TIP.radius(0) - 1.0)
        # High wall: it leans in over the tip, and keeps a 2.0 mm margin, so the tip stays nearer the centre.
        assert -deep < high < 0
        assert requested_x_shift(PLATE_6, 0, DEEPEST) == 0.0
        assert requested_x_shift(PLATE_6, 10, TiltWellPosition.CENTER) == 0.0

    def test_position_aimed_at_a_wall_is_as_close_as_each_count_fits(self):
        position = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=SplitWellFit.POSITION)
        most = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=SplitWellFit.MAX_CHANNELS)

        assert position == most
        assert position.slot_count == 3
        assert position.x_shift_applied < position.requested_x_shift

    def test_max_channels_moves_toward_the_centre_until_all_fit(self):
        result = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=SplitWellFit.MAX_CHANNELS)

        assert result.slot_count == 3
        # Outer slots at 9 mm on the 34.6 mm floor: u0 <= sqrt((17.3 - tip end radius - margin)^2 - 9^2).
        room = 17.3 - ONE_ML_TIP.radius(0) - 1.0
        assert result.x_shift_applied == pytest.approx(math.sqrt(room**2 - 9.0**2), abs=1e-3)
        shift = result.x_shift_applied - result.requested_x_shift
        theta = math.radians(10)
        first = result.slots[0]
        # Pulling back from the low wall moves the slots toward +X and up the tilted floor.
        assert first.dx == pytest.approx(-shift * math.cos(theta), abs=1e-3) and first.dx > 0
        assert first.dz == pytest.approx(-shift * math.sin(theta), abs=1e-3) and first.dz > 0

    def test_more_channels_sit_further_from_the_wall(self):
        two = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=2)
        three = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=3)

        assert (two.slot_count, three.slot_count) == (2, 3)
        assert three.x_shift_applied < two.x_shift_applied < two.requested_x_shift

    def test_a_channel_count_the_well_cannot_hold_raises(self):
        with pytest.raises(ValueError, match=r"cannot hold 4 channels.*only with the plate flat"):
            plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=4)

    def test_fit_outside_the_channels_available_raises(self):
        with pytest.raises(ValueError, match=r"outside 1..4"):
            plan(PLATE_6, max_channels=4, fit=5)

    def test_high_side_is_tighter_than_low_side(self):
        # On the high side the tilted wall leans over the tips, so they fit nearer the centre only.
        low = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=SplitWellFit.MAX_CHANNELS)
        high = plan(
            PLATE_6, tilt_degrees=10, well_position=TiltWellPosition.HIGHEST_POINT, fit=SplitWellFit.MAX_CHANNELS
        )

        assert high.slot_count == low.slot_count == 3
        assert abs(high.x_shift_applied) < abs(low.x_shift_applied)

    def test_split_aimed_at_the_centre_of_a_plate_tilted_to_its_deepest_point(self):
        result = plan(
            PLATE_6,
            tilt_degrees=10,
            well_position=TiltWellPosition.CENTER,
            parent_well_position=DEEPEST,
            fit=SplitWellFit.POSITION,
        )

        parent = requested_x_shift(PLATE_6, 10, DEEPEST)
        assert result.x_shift_applied == 0.0
        assert result.slots[0].dx == pytest.approx(parent * math.cos(math.radians(10)), abs=1e-3)

    def test_parent_x_shift_overrides_the_parent_aim(self):
        result = plan(PLATE_6, tilt_degrees=10, parent_x_shift=5.0, fit=SplitWellFit.POSITION)

        assert result.slots[0].dx == pytest.approx(5.0 * math.cos(math.radians(10)), abs=1e-3)
        assert result.slots[0].dz == pytest.approx(5.0 * math.sin(math.radians(10)), abs=1e-3)


class TestClearanceSettings:
    def test_a_raised_tip_end_comes_closer_to_the_wall(self):
        floor = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=2)
        raised = plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=2, tip_end_height_mm=3.0)

        assert raised.x_shift_applied > floor.x_shift_applied

    def test_tip_end_height_zero_is_the_default(self):
        assert plan(PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=2) == plan(
            PLATE_6, tilt_degrees=10, well_position=DEEPEST, fit=2, tip_end_height_mm=0.0
        )

    def test_margins_are_per_wall(self):
        low = requested_x_shift(PLATE_6, 10, DEEPEST, TipClearance(wall_margin_mm=1.0))
        low_wider = requested_x_shift(PLATE_6, 10, DEEPEST, TipClearance(wall_margin_mm=2.0))
        highest = TiltWellPosition.HIGHEST_POINT
        high = requested_x_shift(PLATE_6, 10, highest, TipClearance(high_wall_margin_mm=2.0))
        high_wider = requested_x_shift(PLATE_6, 10, highest, TipClearance(high_wall_margin_mm=3.0))
        # The high margin does not move the low-wall aim.
        same_low = requested_x_shift(PLATE_6, 10, DEEPEST, TipClearance(wall_margin_mm=1.0, high_wall_margin_mm=5.0))

        assert low - low_wider == pytest.approx(1.0)
        assert high_wider - high == pytest.approx(1.0)
        assert same_low == low

    def test_a_flat_plate_uses_the_low_margin_on_both_sides(self):
        assert plan(PLATE_6, high_wall_margin_mm=10.0).slot_count == plan(PLATE_6).slot_count == 4

    @pytest.mark.parametrize("name", ["tip_end_height_mm", "wall_margin_mm", "high_wall_margin_mm"])
    def test_negative_settings_are_rejected(self, name):
        with pytest.raises(ValueError, match=name):
            TipClearance(**{name: -1.0})

    def test_no_single_tip_fit_names_the_largest_angle(self):
        with pytest.raises(ValueError, match=r"a single tip does not fit .* \(it fits up to 7\.6 degrees\)"):
            requested_x_shift(PLATE_24, 10, DEEPEST, TipClearance(wall_margin_mm=5.5, high_wall_margin_mm=5.0))


class TestMeasuredSixWellPlate:
    """The 6-well plate measured on a real tilt module (36 mm straight wells, 15.8 deep), 10 degrees.

    Tip end 2 mm above the floor, margins 1.0 / 2.0 mm: the aims checked on the instrument
    (Tilt_Labware_Corrections, 2026-10-16), as lab-X offsets from the tilted well centre.
    """

    @pytest.mark.parametrize(
        ("position", "expected"),
        [(DEEPEST, [16.5, 15.9, 13.8, 9.0]), (TiltWellPosition.HIGHEST_POINT, [11.0, 10.2, 7.7, 0.6])],
        ids=["low-wall", "high-wall"],
    )
    def test_offsets_from_the_centre_for_one_to_four_tips(self, position, expected):
        cos_t = math.cos(math.radians(10))
        one = requested_x_shift(SIX_WELL_MEASURED, 10, position, TipClearance(**MEASURED_SETTINGS))
        offsets = [abs(one) * cos_t]
        for count in (2, 3, 4):
            result = plan(
                SIX_WELL_MEASURED,
                tilt_degrees=10,
                well_position=position,
                parent_well_position=TiltWellPosition.CENTER,
                fit=count,
                **MEASURED_SETTINGS,
            )
            offsets.append(abs(result.x_shift_applied) * cos_t)

        assert offsets == pytest.approx(expected, abs=0.05)


class TestRectangularWells:
    # A straight-sided rectangular well, 30 mm across the tilt and 40 mm along the hinge, 15 mm deep.
    BOX = with_container(
        PLATE_6,
        openingDimensions={"shape": "rectangle", "width": 30.0, "depth": 40.0},
        totalDepth=15.0,
        volumeModel={"segments": [{"type": "rectangular_prism", "height": 15.0, "width": 30.0, "depth": 40.0}]},
    )

    def test_the_low_wall_binds_at_the_tip_end(self):
        assert requested_x_shift(self.BOX, 10, DEEPEST) == pytest.approx(15.0 - ONE_ML_TIP.radius(0) - 1.0)

    def test_the_high_wall_binds_at_the_rim(self):
        theta = math.radians(10)
        rim_tip = ONE_ML_TIP.radius(15.0 / math.cos(theta))
        expected = 15.0 * math.tan(theta) - (15.0 - rim_tip - 2.0)

        assert requested_x_shift(self.BOX, 10, TiltWellPosition.HIGHEST_POINT) == pytest.approx(expected)

    def test_the_depth_along_the_hinge_sets_the_slot_count(self):
        # At the rim: half-span + tip radius + 1 mm <= 20 mm, so 4 slots (13.5 mm), not 5 (18 mm).
        assert plan(self.BOX).slot_count == 4


class TestShapedBottoms:
    def test_cone_bottom_raises_the_outer_slots(self):
        # 30 mm tube: 10 mm cone from a point, then a straight wall.
        tube = with_container(
            PLATE_6,
            openingDimensions={"shape": "circle", "diameter": 30.0},
            totalDepth=60.0,
            volumeModel={
                "segments": [
                    {"type": "conical_frustum", "height": 10.0, "diameterBottom": 0.0, "diameterTop": 30.0},
                    {"type": "cylinder", "height": 50.0, "diameter": 30.0},
                ]
            },
        )

        result = plan(tube)

        assert result.slot_count == 3
        outer, centre = result.slots[0], result.slots[1]
        assert centre.dz == 0.0
        assert outer.dz == pytest.approx(10.0 * 9.0 / 15.0)  # on the cone at r = 9 mm
        assert result.slots[2].dz == outer.dz

    def test_round_bottom_follows_the_sphere(self):
        well = with_container(
            PLATE_6,
            openingDimensions={"shape": "circle", "diameter": 30.0},
            totalDepth=40.0,
            volumeModel={
                "segments": [
                    {"type": "spherical_cap", "height": 5.0, "diameter": 30.0},
                    {"type": "cylinder", "height": 35.0, "diameter": 30.0},
                ]
            },
        )

        result = plan(well)

        sphere = (15.0**2 + 5.0**2) / (2 * 5.0)
        expected = sphere - math.sqrt(sphere**2 - result.slots[0].dy ** 2)
        assert result.slots[0].dz == pytest.approx(expected, abs=1e-3)

    def test_an_x_shift_on_a_cone_uses_the_radial_distance(self):
        tube = with_container(
            PLATE_6,
            openingDimensions={"shape": "circle", "diameter": 30.0},
            totalDepth=60.0,
            volumeModel={
                "segments": [
                    {"type": "conical_frustum", "height": 10.0, "diameterBottom": 0.0, "diameterTop": 30.0},
                    {"type": "cylinder", "height": 50.0, "diameter": 30.0},
                ]
            },
        )

        result = plan(tube, tilt_degrees=5, well_position=TiltWellPosition.CENTER, fit=SplitWellFit.POSITION)

        theta = math.radians(5)
        for slot in result.slots:  # u = 0, so the radial distance is the slot's Y offset
            floor = 10.0 * abs(slot.dy) / 15.0
            assert slot.dz == pytest.approx(floor * math.cos(theta), abs=1e-3)
            assert slot.dx == pytest.approx(-floor * math.sin(theta), abs=1e-3)

    def test_slight_draft_is_a_flat_bottom(self):
        # 6-well: one frustum 34.6 -> 35.5 mm is a flat bottom, so every slot keeps the parent's Z.
        assert all(s.dz == 0.0 for s in plan(PLATE_6).slots)


class TestValidation:
    def test_rejects_bad_fit(self):
        with pytest.raises(ValueError, match=r"fit must be SplitWellFit.POSITION, SplitWellFit.MAX_CHANNELS"):
            plan(PLATE_6, fit="most")
        with pytest.raises(ValueError, match="fit must be"):
            plan(PLATE_6, fit=True)

    def test_plain_strings_still_work(self):
        lower_fit = plan(PLATE_6, fit="MAX_CHANNELS".lower()).slot_count
        enum_fit = plan(PLATE_6, fit=SplitWellFit.MAX_CHANNELS).slot_count
        assert lower_fit == enum_fit

    def test_measured_tip_profiles(self):
        one, five = ONE_ML_TIP, DEFAULT_TIP_PROFILES[SplitChannelType.FIVE_ML]
        # Outside diameter 1.2 -> 5.4 mm (1 mL) and 1.8 -> 6.0 mm (5 mL) over the lowest 19.8 mm.
        assert 2 * one.end_radius_mm == pytest.approx(1.2)
        assert 2 * one.radius(19.8) == pytest.approx(5.4)
        assert 2 * five.end_radius_mm == pytest.approx(1.8)
        assert 2 * five.radius(19.8) == pytest.approx(6.0)
        with pytest.raises(ValueError):
            TipProfile.from_measurements(5.0, 1.0, 19.8, max_diameter_mm=8.0)

    def test_rejects_zero_max_channels(self):
        with pytest.raises(ValueError, match="max_channels must be at least 1"):
            plan(PLATE_6, max_channels=0)

    def test_rejects_bad_angle(self):
        with pytest.raises(ValueError, match="out of range"):
            plan(PLATE_6, tilt_degrees=16)

    def test_tip_radius_grows_with_height_up_to_the_body(self):
        tip = TipProfile(end_radius_mm=0.5, radius_taper=0.1, max_radius_mm=2.0)

        assert tip.radius(0) == 0.5
        assert tip.radius(-3) == 0.5
        assert tip.radius(10) == pytest.approx(1.5)
        assert tip.radius(100) == 2.0

    def test_fractional_and_measured_angles_are_accepted(self):
        assert plan(PLATE_6, tilt_degrees=10.8, well_position=DEEPEST, fit=2).slot_count == 2
