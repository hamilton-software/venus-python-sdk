"""Unit tests for LabwareDefinition model and LabwareLayoutSpec.from_definition integration."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from hamilton_venus.models.command_types import LabwareDefinitionSingleReturnParameters
from hamilton_venus.models.labware_definition import LabwareDefinition, dump_labware_definition
from hamilton_venus.models.position import LabwareLayoutSpec


def _is_superset(dumped: object, original: object) -> bool:
    """True if ``dumped`` contains every key of ``original`` with equal values."""
    if isinstance(original, dict):
        if not isinstance(dumped, dict):
            return False
        return all(k in dumped and _is_superset(dumped[k], v) for k, v in original.items())
    if isinstance(original, list):
        if not isinstance(dumped, list) or len(dumped) != len(original):
            return False
        return all(_is_superset(d, o) for d, o in zip(dumped, original, strict=True))
    return dumped == original


PLATE_96_V1_PAYLOAD: dict = {
    "$schema": "urn:hamilton:schemas:microlab:labware:v1",
    "id": "hamilton:nun_96_fl",
    "schemaVersion": "1.0.0-alpha.1",
    "displayName": "Nunc 96 FL.rck",
    "description": "Nunc plate with 96 flat bottom wells",
    "labwareClass": "plate",
    "source": {"system": "venus", "originalId": "Nun_96_Fl"},
    "dimensions": {"x": 127.0, "y": 86.0, "z": 14.5},
    "containerGrids": {
        "default": {
            "columns": 12,
            "rows": 8,
            "columnPitch": 9.0,
            "rowPitch": 9.0,
            "iterationOrder": "column_major",
            "firstContainerCenter": {"x": 14.0, "y": 11.5, "z": 2.2},
            "namingConvention": {"rowStyle": "alpha", "columnStyle": "numeric", "format": "[row][col]"},
            "containerDefinition": {
                "openingDimensions": {"shape": "circle", "diameter": 7.0},
                "totalDepth": 11.3,
                "maxPipettingDepth": 0.0,
                "bottomWallThickness": 1.0,
                "volumeModel": {
                    "segments": [
                        {"type": "conical_frustum", "height": 11.3, "diameterBottom": 6.5, "diameterTop": 7.0}
                    ]
                },
                "liquidDetection": {"supportsLLD": True, "liquidSeekingStartHeight": 13.0},
                "customAttributes": {"hamilton:clld_mode": {"mode": 3}},
            },
            "customAttributes": {"hamilton:ix_params": {"first": 1}},
        }
    },
    "selfStack": {"height": 12.8},
    "visualModel": {"color": "#FFFFFF", "opacity": 0, "modelOrigin": "left_front_bottom"},
    "customAttributes": {"hamilton:is_user_defined": {"value": False}},
}


class TestLabwareDefinitionParsing:
    def test_parses_top_level_fields(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)

        assert defn.schema_ == "urn:hamilton:schemas:microlab:labware:v1"
        assert defn.id == "hamilton:nun_96_fl"
        assert defn.labware_class == "plate"
        assert defn.dimensions.x == 127.0
        assert defn.source.original_id == "Nun_96_Fl"
        assert defn.self_stack is not None
        assert defn.self_stack.height == 12.8

    def test_parses_container_grid(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)
        grid = defn.container_grids["default"]

        assert (grid.rows, grid.columns) == (8, 12)
        assert grid.column_pitch == 9.0
        assert grid.iteration_order == "column_major"
        assert grid.naming_convention.row_style == "alpha"
        assert grid.first_container_center.z == 2.2

    def test_parses_container_definition(self):
        grid = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD).container_grids["default"]
        container = grid.container_definition

        assert container.total_depth == 11.3
        assert container.opening_dimensions.diameter == 7.0
        assert container.liquid_detection.supports_lld is True
        assert container.volume_model.segments[0].diameter_top == 7.0
        assert container.custom_attributes["hamilton:clld_mode"] == {"mode": 3}

    def test_parses_rectangular_frustum_volume_segment(self):
        # rectangular_frustum is the one volume_model shape whose 4 wire
        # fields (widthBottom/depthBottom/widthTop/depthTop) VolumeSegment
        # didn't model at all until now -- pydantic's default extra="ignore"
        # silently dropped them, so a segment of this shape parsed with every
        # dimension missing. Regression guard for that gap.
        payload = {
            **PLATE_96_V1_PAYLOAD,
            "containerGrids": {
                "default": {
                    **PLATE_96_V1_PAYLOAD["containerGrids"]["default"],
                    "containerDefinition": {
                        **PLATE_96_V1_PAYLOAD["containerGrids"]["default"]["containerDefinition"],
                        "volumeModel": {
                            "segments": [
                                {
                                    "type": "rectangular_frustum", "height": 2.5,
                                    "widthBottom": 127.76, "depthBottom": 85.48,
                                    "widthTop": 126.76, "depthTop": 85.48,
                                }
                            ]
                        },
                    },
                }
            },
        }
        segment = (
            LabwareDefinition.model_validate(payload)
            .container_grids["default"]
            .container_definition.volume_model.segments[0]
        )

        assert segment.width_bottom == 127.76
        assert segment.depth_bottom == 85.48
        assert segment.width_top == 126.76
        assert segment.depth_top == 85.48

        dumped = dump_labware_definition(LabwareDefinition.model_validate(payload))
        dumped_segment = dumped["containerGrids"]["default"]["containerDefinition"]["volumeModel"]["segments"][0]
        assert dumped_segment["widthBottom"] == 127.76
        assert dumped_segment["depthTop"] == 85.48

    def test_optional_blocks_default_to_none(self):
        payload = json.loads(json.dumps(PLATE_96_V1_PAYLOAD))
        del payload["selfStack"]
        del payload["visualModel"]
        defn = LabwareDefinition.model_validate(payload)

        assert defn.self_stack is None
        assert defn.visual_model is None
        assert defn.tip_rack is None

    def test_round_trip_preserves_wire_shape(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)
        dumped = defn.model_dump(by_alias=True, exclude_none=True)

        assert _is_superset(dumped, PLATE_96_V1_PAYLOAD)

    def test_connected_container_groups(self):
        payload = json.loads(json.dumps(PLATE_96_V1_PAYLOAD))
        payload["connectedContainerGroups"] = {
            "connected": {"containers": ["default"], "connectionTopology": "base"}
        }
        defn = LabwareDefinition.model_validate(payload)

        assert defn.connected_container_groups["connected"].connection_topology == "base"

    def test_model_is_frozen(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)

        with pytest.raises(ValidationError):
            defn.labware_class = "reservoir"


class TestDumpLabwareDefinition:
    def test_dict_passes_through_unchanged(self):
        assert dump_labware_definition(PLATE_96_V1_PAYLOAD) is PLATE_96_V1_PAYLOAD

    def test_model_dumps_to_wire_shape(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)

        assert _is_superset(dump_labware_definition(defn), PLATE_96_V1_PAYLOAD)

    def test_dump_omits_unset_optional_blocks(self):
        payload = json.loads(json.dumps(PLATE_96_V1_PAYLOAD))
        del payload["selfStack"]
        dumped = dump_labware_definition(LabwareDefinition.model_validate(payload))

        assert "selfStack" not in dumped


class TestLabwareLayoutSpecFromModel:
    def test_typed_model_matches_raw_dict(self):
        defn = LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD)
        from_model = LabwareLayoutSpec.from_definition(defn)
        from_dict = LabwareLayoutSpec.from_definition(PLATE_96_V1_PAYLOAD)

        assert from_model == from_dict

    def test_typed_model_grid_dimensions(self):
        spec = LabwareLayoutSpec.from_definition(LabwareDefinition.model_validate(PLATE_96_V1_PAYLOAD))

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.pattern == "COLUMN_MAJOR"
        assert spec.numeric_addressing is False

    def test_from_dict_still_works(self):
        spec = LabwareLayoutSpec.from_definition(PLATE_96_V1_PAYLOAD)

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm == 9.0
        assert spec.pattern == "COLUMN_MAJOR"

    def test_from_response_wrapper_dict(self):
        wrapped = {"returnParameters": {"definition": PLATE_96_V1_PAYLOAD}}
        spec = LabwareLayoutSpec.from_definition(wrapped)

        assert spec.rows == 8
        assert spec.cols == 12


class TestLabwareDefinitionResponseAccessor:
    def test_to_labware_definition_parses_v1_payload(self):
        params = LabwareDefinitionSingleReturnParameters(labwareName="Nun_96_Fl", definition=PLATE_96_V1_PAYLOAD)

        assert isinstance(params.to_labware_definition(), LabwareDefinition)

    def test_to_labware_layout_spec_parses_v1_payload(self):
        params = LabwareDefinitionSingleReturnParameters(labwareName="Nun_96_Fl", definition=PLATE_96_V1_PAYLOAD)
        spec = params.to_labware_layout_spec()

        assert (spec.rows, spec.cols) == (8, 12)
