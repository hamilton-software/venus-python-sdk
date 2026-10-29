"""Unit tests for the labware definition builder helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from hamilton_venus.labware_builder import (
    body_segment,
    build_labware_definition,
    build_tube_definition,
    rectangular_well,
    round_well,
    touch_off,
)
from hamilton_venus.models.labware_definition import LabwareDefinition

SCHEMA_DIR = Path(__file__).parents[2] / "docs" / "labware_schema"


def _plate(**overrides):
    arguments = {
        "height": 42.0,
        "rows": 8,
        "columns": 12,
        "first_well_center": (14.0, 11.5),
        "well": round_well(diameter=6.5, depth=40.0, bottom="round", bottom_wall_thickness=1.0),
    }
    arguments.update(overrides)
    return build_labware_definition("My_96_DW", **arguments)


DEFINITIONS = {
    "round-bottom plate": _plate(),
    "flat-bottom plate": _plate(well=round_well(diameter=6.5, depth=10.0), height=14.0, stack_height=13.0),
    "cone-bottom plate": _plate(well=round_well(diameter=6.5, depth=20.0, bottom="cone", bottom_height=5.0)),
    "plate with body segments": _plate(
        well=round_well(diameter=6.9, depth=11.3),
        height=14.4,
        body_segments=[
            body_segment(height=11.9, width=124.0, depth=82.0),
            body_segment(height=2.5, width=127.76, depth=85.48, top_width=126.76),
        ],
    ),
    "reservoir": _plate(
        labware_class="reservoir",
        rows=1,
        columns=1,
        first_well_center=(63.88, 42.74),
        well=rectangular_well(width=108.0, length=72.0, depth=38.0),
        description="Single trough",
    ),
    "tube": build_tube_definition(
        "My_96_DW",
        tube=round_well(diameter=19.5, depth=50.0, bottom_wall_thickness=1.8, max_pipetting_depth=1.0),
    ),
    "cone-bottom tube": build_tube_definition(
        "My_96_DW",
        tube=round_well(diameter=12.9, depth=51.0, bottom="cone", bottom_height=5.3),
        description="V-bottom tube",
    ),
}


@pytest.fixture(scope="module")
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in SCHEMA_DIR.glob("*.schema.json")]
    registry = referencing.Registry().with_resources(
        [(schema["$id"], referencing.Resource.from_contents(schema)) for schema in schemas]
    )
    labware_schema = next(schema for schema in schemas if schema["$id"].endswith(":labware:v1"))
    return jsonschema.Draft202012Validator(labware_schema, registry=registry)


@pytest.mark.parametrize("definition", DEFINITIONS.values(), ids=DEFINITIONS.keys())
def test_definition_is_schema_valid(validator, definition):
    assert [error.message for error in validator.iter_errors(definition)] == []


@pytest.mark.parametrize("definition", DEFINITIONS.values(), ids=DEFINITIONS.keys())
def test_definition_parses_as_typed_model(definition):
    model = LabwareDefinition.model_validate(definition)

    assert model.display_name == "My_96_DW"
    assert model.container_grids["default"].rows == definition["containerGrids"]["default"]["rows"]


def test_plate_layout():
    definition = _plate()
    grid = definition["containerGrids"]["default"]

    assert definition["id"] == "user:My_96_DW"
    assert definition["labwareClass"] == "plate"
    # The footprint defaults to what a standard carrier site requires.
    assert definition["dimensions"] == {"x": 127.0, "y": 86.0, "z": 42.0}
    assert (grid["rows"], grid["columns"], grid["rowPitch"], grid["columnPitch"]) == (8, 12, 9.0, 9.0)
    # Well opening is flush with the top of the labware by default.
    assert grid["firstContainerCenter"] == {"x": 14.0, "y": 11.5, "z": 2.0}
    assert grid["iterationOrder"] == "row_major"
    assert definition["selfStack"] == {"height": 0.0}


def test_reservoir_defaults_to_column_major():
    grid = DEFINITIONS["reservoir"]["containerGrids"]["default"]

    assert grid["iterationOrder"] == "column_major"


def test_hamilton_custom_attributes_default_from_labware_height():
    definition = _plate()
    grid = definition["containerGrids"]["default"]
    well = grid["containerDefinition"]

    assert definition["customAttributes"] == {"hamilton:is_user_defined": {"value": True}}
    assert grid["customAttributes"] == {"hamilton:ix_params": {"first": 1, "startingCorner": "back_left"}}
    assert well["liquidDetection"] == {"supportsLLD": True, "liquidSeekingStartHeight": 47.0}
    assert well["customAttributes"]["hamilton:clearance"] == {"clearanceMm": 47.0}
    assert well["customAttributes"]["hamilton:touch_off"]["enabled"] is False
    assert "hamilton:clld_mode" not in well["customAttributes"]


def test_hamilton_custom_attributes_explicit_values():
    well = round_well(
        diameter=6.5,
        depth=40.0,
        clld_mode=1,
        clearance=50.0,
        liquid_seeking_start_height=45.0,
        touch_off=touch_off(2.9, 32.0),
    )
    built = _plate(well=well)["containerGrids"]["default"]["containerDefinition"]

    assert built["liquidDetection"]["liquidSeekingStartHeight"] == 45.0
    assert built["customAttributes"] == {
        "hamilton:clld_mode": {"mode": 1},
        "hamilton:clearance": {"clearanceMm": 50.0},
        "hamilton:touch_off": {
            "enabled": True,
            "frontMm": 2.9,
            "backMm": 2.9,
            "leftMm": 2.9,
            "rightMm": 2.9,
            "baseMm": 0.0,
            "heightMm": 32.0,
        },
    }
    # The caller's well is not modified when the labware-level defaults are filled in.
    assert "hamilton:clearance" not in round_well(diameter=6.5, depth=40.0)["customAttributes"]


def test_no_liquid_seeking_height_without_lld():
    well = _plate(well=round_well(diameter=6.5, depth=40.0, supports_lld=False))["containerGrids"]["default"]

    assert well["containerDefinition"]["liquidDetection"] == {"supportsLLD": False}


def test_well_floor_height_override():
    grid = _plate(well_floor_height=0.6)["containerGrids"]["default"]

    assert grid["firstContainerCenter"]["z"] == 0.6


def test_round_well_segments_add_up_to_depth():
    well = round_well(diameter=6.5, depth=40.0, bottom="round")
    segments = well["volumeModel"]["segments"]

    assert [segment["type"] for segment in segments] == ["spherical_cap", "cylinder"]
    assert math.isclose(sum(segment["height"] for segment in segments), 40.0)
    assert segments[0]["height"] == 3.25


def test_flat_well_is_a_single_cylinder():
    well = round_well(diameter=6.5, depth=10.0)

    assert well["volumeModel"]["segments"] == [{"type": "cylinder", "height": 10.0, "diameter": 6.5}]
    assert well["liquidDetection"] == {"supportsLLD": True}
    assert well["bottomWallThickness"] == 1.0
    assert well["maxPipettingDepth"] == 0.0


@pytest.mark.parametrize(
    "arguments",
    [
        {"bottom": "cone"},
        {"bottom": "flat", "bottom_height": 2.0},
        {"bottom": "round", "bottom_height": 5.0},
        {"bottom": "cone", "bottom_height": 50.0},
        {"bottom": "square"},
    ],
)
def test_round_well_rejects_bad_bottom(arguments):
    with pytest.raises(ValueError):
        round_well(diameter=6.5, depth=40.0, **arguments)


def test_build_rejects_well_deeper_than_labware():
    with pytest.raises(ValueError):
        _plate(height=30.0)


def test_build_rejects_empty_grid():
    with pytest.raises(ValueError):
        _plate(rows=0)


def test_tube_layout():
    definition = DEFINITIONS["tube"]
    grid = definition["containerGrids"]["default"]

    assert definition["labwareClass"] == "tube"
    assert definition["material"] == "polypropylene"
    assert definition["dimensions"] == {"x": 19.5, "y": 19.5, "z": 50.0}
    assert (grid["rows"], grid["columns"], grid["rowPitch"], grid["columnPitch"]) == (1, 1, 19.5, 19.5)
    assert grid["firstContainerCenter"] == {"x": 9.75, "y": 9.75, "z": 1.8}
    assert definition["alignmentFeatures"] == [{"name": "tube_20", "offset": {"z": 49.0}}]
    assert definition["customAttributes"] == {"hamilton:is_user_defined": {"value": True}}
    assert "selfStack" not in definition


def test_tube_clearance_and_liquid_seeking_default_above_the_tube():
    tube = DEFINITIONS["tube"]["containerGrids"]["default"]["containerDefinition"]

    assert tube["liquidDetection"] == {"supportsLLD": True, "liquidSeekingStartHeight": 55.0}
    assert tube["customAttributes"]["hamilton:clearance"] == {"clearanceMm": 55.0}
    assert tube["customAttributes"]["hamilton:touch_off"]["enabled"] is False


def test_liquid_seeking_follows_explicit_clearance():
    plate = _plate(well=round_well(diameter=6.5, depth=40.0, clearance=50.0))
    tube = build_tube_definition("Vial", tube=round_well(diameter=19.5, depth=50.0, clearance=65.0))

    for definition, expected in ((plate, 50.0), (tube, 65.0)):
        well = definition["containerGrids"]["default"]["containerDefinition"]
        assert well["liquidDetection"]["liquidSeekingStartHeight"] == expected


def test_explicit_liquid_seeking_leaves_clearance_default():
    well = _plate(well=round_well(diameter=6.5, depth=40.0, liquid_seeking_start_height=41.0))
    well = well["containerGrids"]["default"]["containerDefinition"]

    assert well["liquidDetection"]["liquidSeekingStartHeight"] == 41.0
    assert well["customAttributes"]["hamilton:clearance"] == {"clearanceMm": 47.0}


def test_tube_keeps_explicit_clearance_and_liquid_seeking():
    definition = build_tube_definition(
        "Vial",
        tube=round_well(diameter=19.5, depth=50.0, clearance=65.0, liquid_seeking_start_height=60.0),
    )
    tube = definition["containerGrids"]["default"]["containerDefinition"]

    assert tube["liquidDetection"]["liquidSeekingStartHeight"] == 60.0
    assert tube["customAttributes"]["hamilton:clearance"] == {"clearanceMm": 65.0}


@pytest.mark.parametrize(
    ("diameter", "feature"),
    [(9.8, "tube_10"), (10.8, "tube_11"), (13.3, "tube_13"), (14.5, "tube_15")],
)
def test_tube_alignment_feature_follows_diameter(diameter, feature):
    definition = build_tube_definition("Tube", tube=round_well(diameter=diameter, depth=50.0))

    assert definition["alignmentFeatures"][0]["name"] == feature


def test_tube_rejects_rectangular_opening():
    with pytest.raises(ValueError):
        build_tube_definition("Tube", tube=rectangular_well(width=10.0, length=10.0, depth=50.0))


def test_footprint_can_be_overridden():
    definition = _plate(width=109.0, depth=152.0)

    assert definition["dimensions"] == {"x": 109.0, "y": 152.0, "z": 42.0}


def test_no_body_shape_by_default():
    definition = _plate()

    assert "collisionShapes" not in definition
    assert "hamilton:body_segments" not in definition["customAttributes"]


def test_body_segments_keep_the_footprint_and_describe_the_shell():
    definition = DEFINITIONS["plate with body segments"]

    assert definition["dimensions"] == {"x": 127.0, "y": 86.0, "z": 14.4}
    assert definition["customAttributes"]["hamilton:body_segments"] == {
        "measuredFrom": "top",
        "segmentsX": [
            {"lowerWidthMm": 124.0, "heightMm": 11.9, "upperWidthMm": 124.0},
            {"lowerWidthMm": 127.76, "heightMm": 2.5, "upperWidthMm": 126.76},
        ],
        "segmentsY": [
            {"lowerWidthMm": 82.0, "heightMm": 11.9, "upperWidthMm": 82.0},
            {"lowerWidthMm": 85.48, "heightMm": 2.5, "upperWidthMm": 85.48},
        ],
    }
    # Same shapes as the shipped Ham_96_FluorMeasure_Black definition.
    assert definition["collisionShapes"] == {
        "body_0": {
            "shape": {"type": "rectangular_prism", "height": 11.9, "width": 124.0, "depth": 82.0},
            "origin": {"x": 63.5, "y": 43.0, "z": 2.5},
        },
        "body_1": {
            "shape": {
                "type": "rectangular_frustum",
                "height": 2.5,
                "widthBottom": 127.76,
                "depthBottom": 85.48,
                "widthTop": 126.76,
                "depthTop": 85.48,
            },
            "origin": {"x": 63.5, "y": 43.0, "z": 0.0},
        },
    }


def test_body_segments_taller_than_labware_are_rejected():
    with pytest.raises(ValueError):
        _plate(body_segments=[body_segment(height=50.0, width=124.0, depth=82.0)])
