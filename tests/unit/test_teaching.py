"""Unit tests for the plate-teaching arithmetic in hamilton_venus.teaching."""

from __future__ import annotations

import pytest

from hamilton_venus.models import LabwareDefinition, TeachingMeasureStatus
from hamilton_venus.models.enums import TeachingDirection
from hamilton_venus.teaching import (
    TeachingError,
    bottom_search_window,
    check_search_status,
    wall_center,
    wall_label,
    wall_search_heights,
    well_widths_from_definition,
)


def _definition(container: dict) -> LabwareDefinition:
    return LabwareDefinition.model_validate({"containerGrids": {"default": {"containerDefinition": container}}})


def test_wall_center_rounds_to_tenth():
    assert wall_center(103.83, 96.94) == 100.4
    assert wall_center(-3.0, 3.0) == 0.0


def test_wall_labels():
    assert [wall_label(direction) for direction in TeachingDirection] == ["+X", "-X", "+Y", "-Y"]


def test_wall_search_heights():
    assert wall_search_heights(150.04, 5.0, 3.0) == (155.0, 147.0)


@pytest.mark.parametrize(("clearance", "depth"), [(0.0, 3.0), (5.0, 0.0)])
def test_wall_search_heights_rejects_non_positive(clearance, depth):
    with pytest.raises(ValueError):
        wall_search_heights(150.0, clearance, depth)


def test_wall_search_heights_rejects_out_of_range():
    with pytest.raises(ValueError, match="minimum search Z"):
        wall_search_heights(101.0, 5.0, 3.0)


def test_bottom_search_window():
    assert bottom_search_window(150.0, 10.9, 5.0) == (150.0, 134.1)


def test_bottom_search_window_clamps_to_lowest_search_z():
    assert bottom_search_window(110.0, 10.0, 5.0) == (110.0, 100.0)


def test_check_search_status():
    check_search_status(TeachingMeasureStatus.FOUND, "the well bottom")
    with pytest.raises(TeachingError, match="was not found") as not_found:
        check_search_status(TeachingMeasureStatus.NOT_FOUND, "the +X wall", wall="+X")
    assert not_found.value.status == TeachingMeasureStatus.NOT_FOUND
    assert not_found.value.wall == "+X"
    with pytest.raises(TeachingError, match="unexpected Z stall") as early:
        check_search_status(TeachingMeasureStatus.FOUND_EARLY, "the well bottom")
    assert early.value.status == TeachingMeasureStatus.FOUND_EARLY


def test_well_widths_round_opening():
    definition = _definition({"openingDimensions": {"shape": "circle", "diameter": 6.9}})
    assert well_widths_from_definition(definition) == (6.9, 6.9)


def test_well_widths_rectangular_opening():
    definition = _definition({"openingDimensions": {"shape": "rectangle", "width": 8.0, "depth": 7.5}})
    assert well_widths_from_definition(definition) == (8.0, 7.5)


def test_well_widths_fall_back_to_volume_model():
    definition = _definition(
        {
            "openingDimensions": {"shape": "circle", "diameter": 0.0},
            "volumeModel": {
                "segments": [
                    {"type": "conical_frustum", "height": 5.0, "diameterBottom": 2.0, "diameterTop": 6.4},
                    {"type": "cylinder", "height": 6.0, "diameter": 6.6},
                ]
            },
        }
    )
    assert well_widths_from_definition(definition) == (6.6, 6.6)


def test_well_widths_unknown():
    assert well_widths_from_definition(LabwareDefinition()) is None
    assert well_widths_from_definition(_definition({})) is None
