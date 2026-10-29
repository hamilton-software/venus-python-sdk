"""Unit tests for LabwareLayoutSpec."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hamilton_venus.models.position import (
    LabwareLayoutSpec,
)

FULL_VENUS_RESPONSE = {
    "id": "2f865366-89cd-499d-954e-18b5be42a3c7",
    "status": "Success",
    "returnStatus": "Success",
    "returnCode": 0,
    "returnParameters": {
        "labwareName": "",
        "definition": {
            "format_version": "1.0",
            "metadata": {"description": "Nunc plate"},
            "rack_layout": {
                "rows": 8,
                "columns": 12,
                "well_spacing_x_mm": 9.0,
                "well_spacing_y_mm": 9.0,
                "indexing": {
                    "first": 1,
                    "increment": 0,
                    "index": 1,
                    "start": 0,
                    "pattern": "COLUMN_MAJOR",
                },
            },
        },
    },
}

DEFINITION_OBJECT = FULL_VENUS_RESPONSE["returnParameters"]["definition"]

RACK_LAYOUT_OBJECT = DEFINITION_OBJECT["rack_layout"]


class TestLabwareLayoutSpec:
    def test_defaults(self):
        spec = LabwareLayoutSpec()

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm is None
        assert spec.well_spacing_y_mm is None
        assert spec.pattern == "COLUMN_MAJOR"

    def test_custom_values(self):
        spec = LabwareLayoutSpec(
            rows=16,
            cols=24,
            well_spacing_x_mm=4.5,
            well_spacing_y_mm=4.5,
            pattern="ROW_MAJOR",
        )

        assert spec.rows == 16
        assert spec.cols == 24
        assert spec.well_spacing_x_mm == 4.5
        assert spec.pattern == "ROW_MAJOR"

    def test_row_labels(self):
        spec = LabwareLayoutSpec(rows=4, cols=6)

        assert spec.row_labels == ("A", "B", "C", "D")

    def test_row_labels_are_alphabetic_regardless_of_columns(self):
        # Row labels are geometric (Excel-style alphabetic) for every labware;
        # numeric labware emits numeric *well* IDs via cell_to_number, not via
        # the row labels.
        spec = LabwareLayoutSpec(rows=32, cols=1)

        assert spec.row_labels[0] == "A"
        assert spec.row_labels[25] == "Z"
        assert spec.row_labels[26] == "AA"
        assert spec.row_labels[-1] == "AF"

    def test_col_labels(self):
        spec = LabwareLayoutSpec(rows=4, cols=6)

        assert spec.col_labels == (1, 2, 3, 4, 5, 6)

    def test_rows_zero_raises(self):
        with pytest.raises(ValidationError, match="rows must be >= 1"):
            LabwareLayoutSpec(rows=0)

    def test_rows_above_26_raises_for_multi_column(self):
        # Two-letter Excel-style row labels (AA-ZZ) are supported for
        # multi-column labware up to 702 rows. Anything above raises.
        with pytest.raises(ValidationError, match="multi-column labware"):
            LabwareLayoutSpec(rows=703, cols=12)

    def test_1536_well_layout_allowed(self):
        spec = LabwareLayoutSpec(rows=32, cols=48)
        assert spec.rows == 32
        assert spec.cols == 48
        assert spec.row_labels[26] == "AA"
        assert spec.row_labels[-1] == "AF"

    def test_rows_above_26_allowed_for_single_column(self):
        spec = LabwareLayoutSpec(rows=32, cols=1)
        assert spec.rows == 32
        assert spec.cols == 1

    def test_cols_zero_raises(self):
        with pytest.raises(ValidationError, match="cols must be >= 1"):
            LabwareLayoutSpec(cols=0)

    def test_frozen(self):
        spec = LabwareLayoutSpec()
        with pytest.raises((TypeError, ValidationError)):
            spec.rows = 4  # type: ignore[misc]

    def test_numeric_addressing_defaults_false(self):
        assert LabwareLayoutSpec().numeric_addressing is False

    def test_connected_container_defaults_false(self):
        assert LabwareLayoutSpec().connected_container is False

    def test_connected_container_custom_value(self):
        assert LabwareLayoutSpec(connected_container=True).connected_container is True

    def test_well_count(self):
        assert LabwareLayoutSpec(rows=8, cols=12).well_count == 96
        assert LabwareLayoutSpec(rows=16, cols=1).well_count == 16


class TestLabwareLayoutSpecCellNumbering:
    def test_column_major_cell_to_number(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, pattern="COLUMN_MAJOR")
        # Numbering runs down each column first: A1=1, B1=2, ..., H1=8, A2=9.
        assert spec.cell_to_number(0, 1) == 1
        assert spec.cell_to_number(7, 1) == 8
        assert spec.cell_to_number(0, 2) == 9
        assert spec.cell_to_number(7, 12) == 96

    def test_row_major_cell_to_number(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, pattern="ROW_MAJOR")
        # Numbering runs across each row first: A1=1, A2=2, ..., A12=12, B1=13.
        assert spec.cell_to_number(0, 1) == 1
        assert spec.cell_to_number(0, 12) == 12
        assert spec.cell_to_number(1, 1) == 13
        assert spec.cell_to_number(7, 12) == 96

    def test_number_to_cell_is_inverse_column_major(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, pattern="COLUMN_MAJOR")
        for number in range(1, spec.well_count + 1):
            assert spec.cell_to_number(*spec.number_to_cell(number)) == number

    def test_number_to_cell_is_inverse_row_major(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, pattern="ROW_MAJOR")
        for number in range(1, spec.well_count + 1):
            assert spec.cell_to_number(*spec.number_to_cell(number)) == number

    def test_single_column_numbering_matches_row(self):
        spec = LabwareLayoutSpec(rows=16, cols=1)
        assert spec.cell_to_number(0, 1) == 1
        assert spec.cell_to_number(15, 1) == 16
        assert spec.number_to_cell(16) == (15, 1)


class TestLabwareLayoutSpecFromDefinition:
    def test_from_full_venus_response(self):
        spec = LabwareLayoutSpec.from_definition(FULL_VENUS_RESPONSE)

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm == 9.0
        assert spec.well_spacing_y_mm == 9.0
        assert spec.pattern == "COLUMN_MAJOR"

    def test_from_definition_object(self):
        spec = LabwareLayoutSpec.from_definition(DEFINITION_OBJECT)

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm == 9.0

    def test_from_rack_layout_object(self):
        spec = LabwareLayoutSpec.from_definition(RACK_LAYOUT_OBJECT)

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm == 9.0

    def test_row_major_pattern(self):
        payload = {
            "rows": 4,
            "columns": 6,
            "indexing": {"pattern": "ROW_MAJOR"},
        }
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.pattern == "ROW_MAJOR"

    def test_missing_rows_raises(self):
        with pytest.raises(ValueError, match="Could not locate rack_layout"):
            LabwareLayoutSpec.from_definition({"columns": 12})

    def test_missing_columns_raises(self):
        with pytest.raises(ValueError, match="Could not locate rack_layout"):
            LabwareLayoutSpec.from_definition({"rows": 8})

    def test_unrecognized_payload_raises(self):
        with pytest.raises(ValueError, match="Could not locate rack_layout"):
            LabwareLayoutSpec.from_definition({"foo": "bar"})

    def test_no_spacing_fields(self):
        payload = {"rows": 4, "columns": 6}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.well_spacing_x_mm is None
        assert spec.well_spacing_y_mm is None

    def test_no_indexing_defaults_to_column_major(self):
        payload = {"rows": 4, "columns": 6}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.pattern == "COLUMN_MAJOR"

    def test_index_one_is_alphanumeric(self):
        payload = {"rows": 8, "columns": 12, "indexing": {"index": 1}}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.numeric_addressing is False

    def test_index_zero_is_numeric(self):
        payload = {"rows": 8, "columns": 12, "indexing": {"index": 0}}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.numeric_addressing is True

    def test_missing_index_defaults_to_alphanumeric(self):
        payload = {"rows": 4, "columns": 6, "indexing": {"pattern": "ROW_MAJOR"}}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.numeric_addressing is False

    def test_connected_container_from_raw_dict(self):
        payload = {"rows": 8, "columns": 1, "connected_container": True}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.connected_container is True

    def test_connected_container_defaults_false_when_absent(self):
        payload = {"rows": 8, "columns": 12}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.connected_container is False

    def test_full_response_index_one_is_alphanumeric(self):
        spec = LabwareLayoutSpec.from_definition(FULL_VENUS_RESPONSE)

        assert spec.numeric_addressing is False


PLATE_96_V1_DEFINITION = {
    "$schema": "urn:hamilton:schemas:microlab:labware:v1",
    "labwareClass": "plate",
    "containerGrids": {
        "default": {
            "columns": 12,
            "rows": 8,
            "columnPitch": 9.0,
            "rowPitch": 9.0,
            "iterationOrder": "column_major",
            "namingConvention": {"rowStyle": "alpha", "columnStyle": "numeric"},
        }
    },
}


class TestLabwareLayoutSpecFromContainerGrids:
    """Parsing of ``urn:hamilton:schemas:microlab:labware:v1`` definitions."""

    def test_regular_grid(self):
        spec = LabwareLayoutSpec.from_definition(PLATE_96_V1_DEFINITION)

        assert spec.rows == 8
        assert spec.cols == 12
        assert spec.well_spacing_x_mm == 9.0
        assert spec.well_spacing_y_mm == 9.0
        assert spec.pattern == "COLUMN_MAJOR"
        assert spec.numeric_addressing is False
        assert spec.connected_container is False

    def test_wrapped_in_venus_response(self):
        wrapped = {"returnParameters": {"definition": PLATE_96_V1_DEFINITION}}
        spec = LabwareLayoutSpec.from_definition(wrapped)

        assert spec.rows == 8
        assert spec.cols == 12

    def test_row_major_iteration_order(self):
        definition = {"containerGrids": {"default": {"rows": 4, "columns": 6, "iterationOrder": "row_major"}}}
        spec = LabwareLayoutSpec.from_definition(definition)

        assert spec.pattern == "ROW_MAJOR"

    def test_numeric_row_style_is_numeric_addressing(self):
        definition = {
            "containerGrids": {
                "default": {
                    "rows": 8,
                    "columns": 12,
                    "namingConvention": {"rowStyle": "numeric", "columnStyle": "numeric"},
                }
            }
        }
        spec = LabwareLayoutSpec.from_definition(definition)

        assert spec.numeric_addressing is True

    def test_connected_container_groups(self):
        definition = {
            "containerGrids": {"default": {"rows": 8, "columns": 1}},
            "connectedContainerGroups": {"connected": {"containers": ["default"], "connectionTopology": "base"}},
        }
        spec = LabwareLayoutSpec.from_definition(definition)

        assert spec.connected_container is True

    def test_irregular_rack_flattens_multiple_grids(self):
        definition = {
            "containerGrids": {
                "group_1": {"rows": 4, "columns": 1, "columnPitch": 9.0, "rowPitch": 9.0},
                "group_2": {"rows": 4, "columns": 1, "columnPitch": 9.0, "rowPitch": 9.0},
            }
        }
        spec = LabwareLayoutSpec.from_definition(definition)

        assert spec.rows == 1
        assert spec.cols == 8
        assert spec.numeric_addressing is True
        assert spec.pattern == "ROW_MAJOR"

    def test_empty_container_grids_raises(self):
        with pytest.raises(ValueError, match="empty 'containerGrids' map"):
            LabwareLayoutSpec.from_definition({"containerGrids": {}})


    def test_zero_rows_and_cols_default_to_1x1(self):
        """Waste containers and similarly incomplete definitions with no grid
        and no irregular_wells fall back to a bare 1x1 (pre-existing behavior).
        """
        payload = {"rows": 0, "columns": 0}
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.rows == 1
        assert spec.cols == 1
        assert spec.well_count == 1

    def test_irregular_wells_used_as_well_count_when_no_grid(self):
        """Single-container labware (e.g. a multi-channel reagent trough sharing
        one physical container) has rows=cols=0 but lists its real positions
        under irregular_wells -- that list's length is the true well count.
        """
        payload = {
            "rows": 0,
            "columns": 0,
            "single_container": True,
            "irregular_wells": [{"id": str(i), "x_mm": 0.0, "y_mm": -9.0 * i} for i in range(8)],
        }
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.rows == 1
        assert spec.cols == 8
        assert spec.well_count == 8

    def test_irregular_wells_ignored_when_grid_present(self):
        """irregular_wells should only be consulted when the definition has no
        real row/column grid at all -- a normal plate's grid always wins.
        """
        payload = {
            "rows": 8,
            "columns": 12,
            "irregular_wells": [{"id": "1", "x_mm": 0.0, "y_mm": 0.0}],
        }
        spec = LabwareLayoutSpec.from_definition(payload)

        assert spec.rows == 8
        assert spec.cols == 12
