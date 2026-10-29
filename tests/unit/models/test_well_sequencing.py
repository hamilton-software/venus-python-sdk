"""Unit tests for well_sequencing module and spacing-aware normalize_positions."""

from __future__ import annotations

import pytest

from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import (
    LabwareLayoutSpec,
    normalize_positions,
)
from hamilton_venus.models.well_sequencing import (
    compute_interleaved_sequence,
    get_axis_spacing,
    infer_traversal_axis,
)


class TestInferTraversalAxis:
    def test_col_selector_returns_column(self):
        assert infer_traversal_axis("col:1", WellOrder.COL_ASC) == "COLUMN"

    def test_row_selector_returns_row(self):
        assert infer_traversal_axis("row:A", WellOrder.COL_ASC) == "ROW"

    def test_all_column_major_returns_column(self):
        assert infer_traversal_axis("all", WellOrder.COL_ASC, "COLUMN_MAJOR") == "COLUMN"

    def test_all_row_major_returns_row(self):
        assert infer_traversal_axis("all", WellOrder.COL_ASC, "ROW_MAJOR") == "ROW"

    def test_none_expression_with_row_order_returns_row(self):
        assert infer_traversal_axis(None, WellOrder.ROW_ASC) == "ROW"

    def test_none_expression_with_row_desc_returns_row(self):
        assert infer_traversal_axis(None, WellOrder.ROW_DESC) == "ROW"

    def test_none_expression_with_col_order_returns_column(self):
        assert infer_traversal_axis(None, WellOrder.COL_ASC) == "COLUMN"

    def test_explicit_selector_overrides_well_order(self):
        assert infer_traversal_axis("col:1", WellOrder.ROW_ASC) == "COLUMN"
        assert infer_traversal_axis("row:A", WellOrder.COL_ASC) == "ROW"


class TestGetAxisSpacing:
    def test_column_axis_returns_y_spacing(self):
        assert get_axis_spacing(9.0, 9.0, "COLUMN") == 9.0

    def test_row_axis_returns_x_spacing(self):
        assert get_axis_spacing(9.0, 4.5, "ROW") == 9.0

    def test_none_spacing_column(self):
        assert get_axis_spacing(None, None, "COLUMN") is None

    def test_none_spacing_row(self):
        assert get_axis_spacing(None, None, "ROW") is None

    def test_mixed_none_column(self):
        assert get_axis_spacing(9.0, None, "COLUMN") is None

    def test_mixed_none_row(self):
        assert get_axis_spacing(None, 9.0, "ROW") is None


class TestComputeInterleavedSequence:
    ROW_LABELS_8 = ("A", "B", "C", "D", "E", "F", "G", "H")
    ROW_LABELS_16 = tuple(chr(ord("A") + i) for i in range(16))

    def test_no_interleaving_when_pitch_matches_spacing(self):
        wells = ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
        result = compute_interleaved_sequence(wells, 9.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == wells

    def test_skip_factor_2_column_traversal(self):
        wells = ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == ["A1", "C1", "E1", "G1", "B1", "D1", "F1", "H1"]

    def test_skip_factor_2_multi_column(self):
        wells = [
            "A1",
            "B1",
            "C1",
            "D1",
            "E1",
            "F1",
            "G1",
            "H1",
            "A2",
            "B2",
            "C2",
            "D2",
            "E2",
            "F2",
            "G2",
            "H2",
        ]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == [
            "A1",
            "C1",
            "E1",
            "G1",
            "B1",
            "D1",
            "F1",
            "H1",
            "A2",
            "C2",
            "E2",
            "G2",
            "B2",
            "D2",
            "F2",
            "H2",
        ]

    def test_skip_factor_2_row_traversal(self):
        wells = ["A1", "A2", "A3", "A4", "A5", "A6"]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "ROW", self.ROW_LABELS_8)

        assert result == ["A1", "A3", "A5", "A2", "A4", "A6"]

    def test_skip_factor_2_row_traversal_multi_row(self):
        wells = ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4"]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "ROW", self.ROW_LABELS_8)

        assert result == ["A1", "A3", "A2", "A4", "B1", "B3", "B2", "B4"]

    def test_384_plate_skip_factor_2_column(self):
        wells = [f"{chr(65 + r)}1" for r in range(16)]
        result = compute_interleaved_sequence(wells, 9.0, 4.5, "COLUMN", self.ROW_LABELS_16)

        even_rows = [wells[i] for i in range(0, 16, 2)]
        odd_rows = [wells[i] for i in range(1, 16, 2)]
        assert result == even_rows + odd_rows

    def test_numeric_wells_skip_factor_2(self):
        wells = ["1", "2", "3", "4", "5", "6", "7", "8"]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == ["1", "3", "5", "7", "2", "4", "6", "8"]

    def test_numeric_wells_no_interleaving(self):
        wells = ["1", "2", "3", "4"]
        result = compute_interleaved_sequence(wells, 9.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == wells

    def test_returns_copy_when_no_interleaving(self):
        wells = ["A1", "B1"]
        result = compute_interleaved_sequence(wells, 9.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == wells
        assert result is not wells

    def test_zero_spacing_returns_unchanged(self):
        wells = ["A1", "B1", "C1"]
        result = compute_interleaved_sequence(wells, 9.0, 0.0, "COLUMN", self.ROW_LABELS_8)

        assert result == wells

    def test_zero_pitch_returns_unchanged(self):
        wells = ["A1", "B1", "C1"]
        result = compute_interleaved_sequence(wells, 0.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == wells

    def test_partial_column_already_spaced(self):
        wells = ["A1", "C1", "E1", "G1"]
        result = compute_interleaved_sequence(wells, 18.0, 9.0, "COLUMN", self.ROW_LABELS_8)

        assert result == ["A1", "C1", "E1", "G1"]

    def test_row_traversal_invalid_well_raises(self):
        with pytest.raises(ValueError, match="cannot parse plate well"):
            compute_interleaved_sequence(["A1", "bad"], 18.0, 9.0, "ROW", self.ROW_LABELS_8)

    def test_spec_provides_geometry(self):
        spec = LabwareLayoutSpec(rows=4, cols=6)
        result = normalize_positions("Plate@all", get_spec=lambda _lid: spec)
        assert len(result) == 24
        assert result[0].well == "A1"

    def test_well_order_row_asc(self):
        spec = LabwareLayoutSpec(rows=2, cols=3)
        result = normalize_positions("Plate@all", well_order=WellOrder.ROW_ASC, get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["A1", "A2", "A3", "B1", "B2", "B3"]

    def test_384_geometry_col_selector(self):
        spec = LabwareLayoutSpec(rows=16, cols=24, well_spacing_x_mm=4.5, well_spacing_y_mm=4.5)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec)
        assert len(result) == 16

    def test_interleaving_applied_with_pitch_and_spacing(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, well_spacing_x_mm=9.0, well_spacing_y_mm=9.0)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec, channel_pitch_mm=18.0)
        wells = [p.well for p in result]
        assert wells == ["A1", "C1", "E1", "G1", "B1", "D1", "F1", "H1"]

    def test_no_interleaving_when_pitch_matches(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, well_spacing_x_mm=9.0, well_spacing_y_mm=9.0)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec, channel_pitch_mm=9.0)
        wells = [p.well for p in result]
        assert wells == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_no_interleaving_without_pitch(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, well_spacing_x_mm=9.0, well_spacing_y_mm=9.0)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec)
        wells = [p.well for p in result]
        assert wells == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_no_interleaving_without_spacing(self):
        spec = LabwareLayoutSpec(rows=8, cols=12)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec, channel_pitch_mm=18.0)
        wells = [p.well for p in result]
        assert wells == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_row_traversal_uses_x_spacing(self):
        spec = LabwareLayoutSpec(rows=8, cols=6, well_spacing_x_mm=9.0, well_spacing_y_mm=9.0)
        result = normalize_positions("Plate@row:A", get_spec=lambda _lid: spec, channel_pitch_mm=18.0)
        wells = [p.well for p in result]
        assert wells == ["A1", "A3", "A5", "A2", "A4", "A6"]

    def test_channel_count_applied_after_interleaving(self):
        spec = LabwareLayoutSpec(rows=8, cols=12, well_spacing_x_mm=9.0, well_spacing_y_mm=9.0)
        result = normalize_positions(
            "Plate@col:1",
            channel_count=4,
            get_spec=lambda _lid: spec,
            channel_pitch_mm=18.0,
        )
        wells = [p.well for p in result]
        assert wells == ["A1", "C1", "E1", "G1"]

    def test_384_plate_interleaving(self):
        spec = LabwareLayoutSpec(rows=16, cols=24, well_spacing_x_mm=4.5, well_spacing_y_mm=4.5)
        result = normalize_positions("Plate@col:1", get_spec=lambda _lid: spec, channel_pitch_mm=9.0)
        wells = [p.well for p in result]
        even = [chr(65 + i) + "1" for i in range(0, 16, 2)]
        odd = [chr(65 + i) + "1" for i in range(1, 16, 2)]
        assert wells == even + odd


class TestAllWithPattern:
    def test_all_column_major_default(self):
        spec = LabwareLayoutSpec(rows=2, cols=3, pattern="COLUMN_MAJOR")
        result = normalize_positions("Plate@all", get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["A1", "B1", "A2", "B2", "A3", "B3"]

    def test_all_row_major_alphanumeric_plate_stays_column_first(self):
        # Alphanumeric IDs ("A1") don't depend on the pattern, and row-wise
        # order would group wells along X, which 9 mm channels can't spread
        # across -- so the default well order is kept.
        spec = LabwareLayoutSpec(rows=2, cols=3, pattern="ROW_MAJOR")
        result = normalize_positions("Plate@all", get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["A1", "B1", "A2", "B2", "A3", "B3"]

    def test_all_row_major_numeric_labware_follows_pattern(self):
        spec = LabwareLayoutSpec(rows=2, cols=3, pattern="ROW_MAJOR", numeric_addressing=True)
        result = normalize_positions("Rack@all", get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["1", "2", "3", "4", "5", "6"]

    def test_all_row_major_384_plate_groups_channels_down_a_column(self):
        spec = LabwareLayoutSpec(rows=16, cols=24, well_spacing_x_mm=4.5, well_spacing_y_mm=4.5, pattern="ROW_MAJOR")
        result = normalize_positions("Plate384@all", get_spec=lambda _lid: spec, channel_pitch_mm=9.0)
        assert [p.well for p in result[:16]] == [
            "A1", "C1", "E1", "G1", "I1", "K1", "M1", "O1",
            "B1", "D1", "F1", "H1", "J1", "L1", "N1", "P1",
        ]

    def test_all_row_major_with_explicit_col_order_overrides(self):
        spec = LabwareLayoutSpec(rows=2, cols=3, pattern="ROW_MAJOR")
        result = normalize_positions("Plate@all", well_order=WellOrder.COL_DESC, get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["B3", "A3", "B2", "A2", "B1", "A1"]

    def test_all_without_spec_uses_column_major(self):
        spec = LabwareLayoutSpec(rows=2, cols=3)
        result = normalize_positions("Plate@all", get_spec=lambda _lid: spec)
        assert [p.well for p in result] == ["A1", "B1", "A2", "B2", "A3", "B3"]


class TestBackwardCompatibility:
    def test_no_spec_no_pitch_unchanged(self):
        result = normalize_positions("Plate@col:1")
        wells = [p.well for p in result]
        assert wells == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_dict_input_unaffected(self):
        result = normalize_positions({"labwareId": "Plate", "wellId": "A1"})
        assert len(result) == 1
        assert result[0].well == "A1"

    def test_position_input_unaffected(self):
        from hamilton_venus.models.position import Position

        pos = Position(labware="Plate", well="A1")
        result = normalize_positions(pos)
        assert len(result) == 1
        assert result[0] is pos
