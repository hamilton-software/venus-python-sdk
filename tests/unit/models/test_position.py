"""Unit tests for position DSL parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import LabwareLayoutSpec, normalize_positions


class TestNormalizePositions:
    def test_bare_labware_is_equivalent_to_all(self):
        bare = normalize_positions("Trough_1")
        explicit_all = normalize_positions("Trough_1@all")

        assert [position.to_dict() for position in bare] == [position.to_dict() for position in explicit_all]
        assert len(bare) == 96

    def test_bare_labware_uses_channel_count_when_provided(self):
        result = normalize_positions("Trough_1", channel_count=3)

        assert [position.to_dict() for position in result] == [
            {"labwareId": "Trough_1", "wellId": "A1"},
            {"labwareId": "Trough_1", "wellId": "B1"},
            {"labwareId": "Trough_1", "wellId": "C1"},
        ]

    def test_single_well_repeats_across_channels(self):
        result = normalize_positions("Trough_1@A1", channel_count=8)

        assert [position.to_dict() for position in result] == [{"labwareId": "Trough_1", "wellId": "A1"}] * 8

    def test_single_well_in_list_repeats_across_channels(self):
        result = normalize_positions(["Trough_1@A1"], channel_count=8)

        assert [position.to_dict() for position in result] == [{"labwareId": "Trough_1", "wellId": "A1"}] * 8

    def test_plate_all_uses_default_column_major_order(self):
        result = normalize_positions("Plate_1@all")

        assert len(result) == 96
        assert [position.well for position in result[:8]] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
        assert result[-1].well == "H12"

    def test_plate_all_can_use_row_major_order(self):
        result = normalize_positions("Plate_1@all", well_order=WellOrder.ROW_ASC)

        assert [position.well for position in result[:12]] == [
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "A9",
            "A10",
            "A11",
            "A12",
        ]

    def test_col_selector_expands_plate_column(self):
        result = normalize_positions("Plate_1@col:1")

        assert [position.well for position in result] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_row_selector_expands_plate_row(self):
        result = normalize_positions("Plate_1@row:A")

        assert [position.well for position in result] == [
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "A9",
            "A10",
            "A11",
            "A12",
        ]

    def test_wells_selector_expands_numeric_positions(self):
        # A numeric tube carrier (numeric_addressing) emits numeric well IDs.
        carrier = LabwareLayoutSpec(rows=8, cols=1, numeric_addressing=True)
        result = normalize_positions("TubeCarrier_1@wells:1,3,5", get_spec=lambda _lid, _s=carrier: _s)

        assert [position.to_dict() for position in result] == [
            {"labwareId": "TubeCarrier_1", "wellId": "1"},
            {"labwareId": "TubeCarrier_1", "wellId": "3"},
            {"labwareId": "TubeCarrier_1", "wellId": "5"},
        ]

    @pytest.mark.parametrize("keyword", ["all", "All", "ALL"])
    def test_all_keyword_is_case_insensitive(self, keyword):
        carrier = LabwareLayoutSpec(rows=12, cols=1, numeric_addressing=True)
        result = normalize_positions(f"Tubes@{keyword}", get_spec=lambda _lid, _s=carrier: _s)

        assert [position.well for position in result] == [str(n) for n in range(1, 13)]

    @pytest.mark.parametrize("selector", ["Plate@col:2", "Plate@COL:2", "Plate@Col:2"])
    def test_col_keyword_is_case_insensitive(self, selector):
        result = normalize_positions(selector)

        assert [position.well for position in result] == ["A2", "B2", "C2", "D2", "E2", "F2", "G2", "H2"]

    @pytest.mark.parametrize("selector", ["Plate@row:B", "Plate@ROW:b", "Plate@Row:B"])
    def test_row_keyword_is_case_insensitive(self, selector):
        result = normalize_positions(selector)

        assert [position.well for position in result] == [f"B{col}" for col in range(1, 13)]

    @pytest.mark.parametrize("selector", ["Tubes@wells:1,3", "Tubes@Wells:1,3", "Tubes@WELLS:1,3"])
    def test_wells_keyword_is_case_insensitive(self, selector):
        carrier = LabwareLayoutSpec(rows=8, cols=1, numeric_addressing=True)
        result = normalize_positions(selector, get_spec=lambda _lid, _s=carrier: _s)

        assert [position.well for position in result] == ["1", "3"]

    def test_uppercase_all_still_drives_axis_inference(self):
        # "@ALL" must reach the interleaving logic as "all", not as an unknown expression.
        plate_384 = LabwareLayoutSpec(rows=16, cols=24, well_spacing_x_mm=4.5, well_spacing_y_mm=4.5)
        lower = normalize_positions("P@all", get_spec=lambda _lid: plate_384, channel_pitch_mm=9.0)
        upper = normalize_positions("P@ALL", get_spec=lambda _lid: plate_384, channel_pitch_mm=9.0)

        assert [p.well for p in upper] == [p.well for p in lower]

    def test_unknown_keyword_like_expression_still_rejected(self):
        with pytest.raises(ValueError, match="invalid well selector"):
            normalize_positions("Plate@everything")

    def test_range_selector_expands_inclusive_plate_range(self):
        result = normalize_positions("Plate_1@A1:G1")

        assert [position.well for position in result] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1"]

    def test_list_of_selectors_concatenates_expanded_positions(self):
        result = normalize_positions(["Plate_A@A1:C1", "Plate_B@A12,C12,D12,G12,H12"])

        assert [position.to_dict() for position in result] == [
            {"labwareId": "Plate_A", "wellId": "A1"},
            {"labwareId": "Plate_A", "wellId": "B1"},
            {"labwareId": "Plate_A", "wellId": "C1"},
            {"labwareId": "Plate_B", "wellId": "A12"},
            {"labwareId": "Plate_B", "wellId": "C12"},
            {"labwareId": "Plate_B", "wellId": "D12"},
            {"labwareId": "Plate_B", "wellId": "G12"},
            {"labwareId": "Plate_B", "wellId": "H12"},
        ]

    def test_dict_input_normalizes_to_position_model(self):
        result = normalize_positions({"labwareId": "Plate_1", "wellId": "A1"})

        assert [position.to_dict() for position in result] == [{"labwareId": "Plate_1", "wellId": "A1"}]

    def test_channel_count_mismatch_raises(self):
        with pytest.raises(ValueError, match="expanded to 2 entries"):
            normalize_positions(["Plate_1@A1:B1"], channel_count=3)

    def test_total_wells_caps_result(self):
        full = normalize_positions("Plate_1@all")
        result = normalize_positions("Plate_1@all", total_wells=17)

        assert len(result) == 17
        assert [p.to_dict() for p in result] == [p.to_dict() for p in full[:17]]

    def test_total_wells_exceeding_available_returns_all_no_error(self):
        result = normalize_positions("Plate_1@A1:C1", total_wells=10)

        assert len(result) == 3
        assert [p.well for p in result] == ["A1", "B1", "C1"]

    def test_total_wells_composes_with_channel_count(self):
        result = normalize_positions("Trough_1@A1", channel_count=8, total_wells=3)

        assert [position.to_dict() for position in result] == [{"labwareId": "Trough_1", "wellId": "A1"}] * 3


class TestLabwareLayoutSpec:
    def test_all_with_384_well_plate(self):
        geometry = LabwareLayoutSpec(rows=16, cols=24)
        result = normalize_positions("Plate_1@all", get_spec=lambda _lid, _s=geometry: _s)

        assert len(result) == 384
        assert result[0].well == "A1"
        assert result[-1].well == "P24"

    def test_col_selector_uses_custom_row_count(self):
        geometry = LabwareLayoutSpec(rows=4, cols=6)
        result = normalize_positions("Plate_1@col:1", get_spec=lambda _lid, _s=geometry: _s)

        assert [position.well for position in result] == ["A1", "B1", "C1", "D1"]

    def test_row_selector_uses_custom_col_count(self):
        geometry = LabwareLayoutSpec(rows=4, cols=6)
        result = normalize_positions("Plate_1@row:A", get_spec=lambda _lid, _s=geometry: _s)

        assert [position.well for position in result] == ["A1", "A2", "A3", "A4", "A5", "A6"]

    def test_all_with_small_geometry(self):
        geometry = LabwareLayoutSpec(rows=2, cols=3)
        result = normalize_positions("Plate_1@all", get_spec=lambda _lid, _s=geometry: _s)

        assert len(result) == 6
        assert [position.well for position in result] == ["A1", "B1", "A2", "B2", "A3", "B3"]

    def test_row_range_uses_custom_geometry(self):
        geometry = LabwareLayoutSpec(rows=16, cols=24)
        result = normalize_positions("Plate_1@row:N:P", get_spec=lambda _lid, _s=geometry: _s)

        assert [position.well for position in result[:3]] == ["N1", "O1", "P1"]
        assert len(result) == 3 * 24

    def test_invalid_row_for_geometry_raises(self):
        geometry = LabwareLayoutSpec(rows=4, cols=6)
        with pytest.raises(ValueError, match="invalid row selector"):
            normalize_positions("Plate_1@row:E", get_spec=lambda _lid, _s=geometry: _s)

    def test_range_with_custom_geometry(self):
        geometry = LabwareLayoutSpec(rows=16, cols=24)
        result = normalize_positions("Plate_1@A1:B2", get_spec=lambda _lid, _s=geometry: _s)

        assert [position.well for position in result] == ["A1", "B1", "A2", "B2"]


class TestSixteenThirtySixWellPlateAddressing:
    """1536-well plates use 32 rows (A-Z, then AA-AF) and 48 columns.

    Rows beyond Z follow the Excel-style convention (AA=27, AB=28, ..., AF=32).
    """

    _PLATE_1536 = LabwareLayoutSpec(rows=32, cols=48)

    def test_row_aa_resolves_to_row_27(self):
        result = normalize_positions("Plate@AA1", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        assert result[0].well == "AA1"

    def test_row_ac_column_2_resolves(self):
        # The example from the issue: row 29, column 2 == AC2.
        result = normalize_positions("Plate@AC2", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        assert result[0].well == "AC2"

    def test_row_af_column_48_resolves(self):
        # Last well of a 1536-well plate.
        result = normalize_positions("Plate@AF48", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        assert result[0].well == "AF48"

    def test_row_ag_out_of_bounds_raises(self):
        with pytest.raises(ValueError, match="invalid well"):
            normalize_positions("Plate@AG1", get_spec=lambda _lid, _s=self: _s._PLATE_1536)

    def test_range_spans_letter_boundary(self):
        # Range from Z to AB in a single column spans rows 26..28.
        result = normalize_positions("Plate@Z1:AB1", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        assert [p.well for p in result] == ["Z1", "AA1", "AB1"]

    def test_all_wells_includes_two_letter_rows(self):
        result = normalize_positions("Plate@all", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        assert len(result) == 32 * 48
        # First column: A1..Z1, AA1..AF1
        assert result[0].well == "A1"
        assert result[25].well == "Z1"
        assert result[26].well == "AA1"
        assert result[31].well == "AF1"

    def test_row_selector_with_two_letter_row(self):
        result = normalize_positions("Plate@row:AA,AC", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        wells = [p.well for p in result]
        assert wells[:2] == ["AA1", "AC1"]
        assert len(wells) == 2 * 48

    def test_row_range_across_letter_boundary(self):
        result = normalize_positions("Plate@row:Y:AB", get_spec=lambda _lid, _s=self: _s._PLATE_1536)
        # Rows Y, Z, AA, AB across 48 columns; first 4 wells in column 1.
        assert [p.well for p in result[:4]] == ["Y1", "Z1", "AA1", "AB1"]

    def test_default_geometry_is_96_well(self):
        result = normalize_positions("Plate_1@all")

        assert len(result) == 96


class TestLabwareLayoutSpecValidation:
    def test_rows_zero_raises(self):
        with pytest.raises(ValueError, match="rows must be >= 1"):
            LabwareLayoutSpec(rows=0)

    def test_rows_negative_raises(self):
        with pytest.raises(ValueError, match="rows must be >= 1"):
            LabwareLayoutSpec(rows=-1)

    def test_rows_above_702_raises_for_multi_column(self):
        with pytest.raises(ValidationError, match="multi-column labware"):
            LabwareLayoutSpec(rows=703, cols=12)

    def test_rows_27_allowed_for_multi_column(self):
        # 1536-well plates use 32 rows (A-AF); two-letter Excel-style row
        # labels (AA-ZZ) are supported up to 702 rows.
        spec = LabwareLayoutSpec(rows=27, cols=12)
        assert spec.row_labels[26] == "AA"

    def test_1536_well_plate_layout(self):
        spec = LabwareLayoutSpec(rows=32, cols=48)
        assert spec.rows == 32
        assert spec.cols == 48
        assert spec.row_labels[-1] == "AF"

    def test_rows_above_26_allowed_for_single_column(self):
        g32 = LabwareLayoutSpec(rows=32, cols=1)
        assert g32.rows == 32

    def test_cols_zero_raises(self):
        with pytest.raises(ValueError, match="cols must be >= 1"):
            LabwareLayoutSpec(cols=0)

    def test_cols_negative_raises(self):
        with pytest.raises(ValueError, match="cols must be >= 1"):
            LabwareLayoutSpec(cols=-1)

    def test_valid_boundary_rows(self):
        g1 = LabwareLayoutSpec(rows=1, cols=1)
        assert g1.rows == 1
        g26 = LabwareLayoutSpec(rows=26, cols=1)
        assert g26.rows == 26
        g32 = LabwareLayoutSpec(rows=32, cols=1)
        assert g32.rows == 32

    def test_frozen_raises_on_mutation(self):
        g = LabwareLayoutSpec()
        with pytest.raises((TypeError, ValidationError)):
            g.rows = 4


class TestColumnBoundsChecking:
    def test_col_selector_out_of_bounds_raises(self):
        geometry = LabwareLayoutSpec(rows=8, cols=12)
        with pytest.raises(ValueError, match="invalid column selector"):
            normalize_positions("Plate_1@col:25", get_spec=lambda _lid, _s=geometry: _s)

    def test_col_selector_boundary_valid(self):
        geometry = LabwareLayoutSpec(rows=8, cols=12)
        result = normalize_positions("Plate_1@col:12", get_spec=lambda _lid, _s=geometry: _s)
        assert result[0].well == "A12"

    def test_col_selector_on_384_well(self):
        geometry = LabwareLayoutSpec(rows=16, cols=24)
        result = normalize_positions("Plate_1@col:24", get_spec=lambda _lid, _s=geometry: _s)
        assert len(result) == 16
        assert result[0].well == "A24"

    def test_col_selector_above_384_raises(self):
        geometry = LabwareLayoutSpec(rows=16, cols=24)
        with pytest.raises(ValueError, match="invalid column selector"):
            normalize_positions("Plate_1@col:25", get_spec=lambda _lid, _s=geometry: _s)

    def test_well_column_out_of_bounds_raises(self):
        geometry = LabwareLayoutSpec(rows=8, cols=12)
        with pytest.raises(ValueError, match="invalid column in well selector"):
            normalize_positions("Plate_1@A25", get_spec=lambda _lid, _s=geometry: _s)

    def test_range_column_out_of_bounds_raises(self):
        geometry = LabwareLayoutSpec(rows=8, cols=12)
        with pytest.raises(ValueError, match="invalid column in well selector"):
            normalize_positions("Plate_1@A1:A15", get_spec=lambda _lid, _s=geometry: _s)

    def test_col_range_out_of_bounds_raises(self):
        geometry = LabwareLayoutSpec(rows=8, cols=12)
        with pytest.raises(ValueError, match="invalid column selector"):
            normalize_positions("Plate_1@col:10:15", get_spec=lambda _lid, _s=geometry: _s)


class TestSingleColumnNumericAddressing:
    """Single-column numeric labware (troughs, tube/sample carriers).

    These labware advertise ``indexing.index == 0`` and are addressed by
    numeric position (``"1"``, ``"2"``, ...).  Alphanumeric input (``"A1"``)
    is accepted and translated to the numeric form via the labware's
    ``pattern``; the emitted ``Position.well`` is always numeric.
    """

    _TROUGH = LabwareLayoutSpec(rows=8, cols=1, numeric_addressing=True)
    _TALL_CARRIER = LabwareLayoutSpec(rows=32, cols=1, numeric_addressing=True)

    def test_numeric_form_is_canonical(self):
        result = normalize_positions("Trough@1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert result[0].well == "1"

    def test_alpha_input_translates_to_numeric(self):
        result = normalize_positions("Trough@A1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert result[0].well == "1"

    def test_b1_translates_to_two(self):
        result = normalize_positions("Trough@B1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert result[0].well == "2"

    def test_h1_translates_to_eight(self):
        result = normalize_positions("Trough@H1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert result[0].well == "8"

    def test_alpha_column_out_of_range_raises(self):
        # A single-column carrier has no column 2, so "A2" is a clear error
        # rather than being silently reinterpreted.
        with pytest.raises(ValueError, match="invalid column in well selector"):
            normalize_positions("Trough@A2", get_spec=lambda _lid, _s=self: _s._TROUGH)

    def test_plate_style_out_of_bounds_raises(self):
        with pytest.raises(ValueError, match="invalid well selector"):
            normalize_positions("Trough@I1", get_spec=lambda _lid, _s=self: _s._TROUGH)

    def test_numeric_out_of_bounds_raises(self):
        with pytest.raises(ValueError, match="invalid well selector"):
            normalize_positions("Trough@9", get_spec=lambda _lid, _s=self: _s._TROUGH)

    def test_wells_prefix_with_plate_style_translates(self):
        result = normalize_positions("Trough@wells:A1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert result[0].well == "1"

    def test_multi_letter_alpha_alias_on_tall_carrier(self):
        # Position 27 on a 32-row carrier is addressable both as the numeric
        # "27" and the Excel-style alphabetic alias "AA1"; both canonicalize
        # to the numeric "27".
        r_alpha = normalize_positions("Carrier@AA1", get_spec=lambda _lid, _s=self: _s._TALL_CARRIER)
        r_num = normalize_positions("Carrier@27", get_spec=lambda _lid, _s=self: _s._TALL_CARRIER)
        assert r_alpha[0].well == "27"
        assert r_num[0].well == "27"

    def test_alpha_range_translates_to_numeric(self):
        result = normalize_positions("Trough@A1:C1", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert [p.well for p in result] == ["1", "2", "3"]

    def test_numeric_range_emits_numeric_wells(self):
        result = normalize_positions("Trough@1:3", get_spec=lambda _lid, _s=self: _s._TROUGH)
        assert [p.well for p in result] == ["1", "2", "3"]

    def test_alpha_range_spans_letter_boundary(self):
        # A1:AC1 on a 32-row carrier spans rows 1..29 -> numeric wells 1..29.
        result = normalize_positions("Carrier@A1:AC1", get_spec=lambda _lid, _s=self: _s._TALL_CARRIER)
        wells = [p.well for p in result]
        assert wells[0] == "1"
        assert wells[25] == "26"
        assert wells[26] == "27"
        assert wells[-1] == "29"


class TestNumericMultiColumnAddressing:
    """Numeric labware that spans a full grid (tip racks, reservoir grids).

    ``indexing.index == 0`` combined with multiple columns numbers the wells
    1..N following the definition's ``pattern``.
    """

    _COLUMN_MAJOR = LabwareLayoutSpec(rows=8, cols=12, numeric_addressing=True, pattern="COLUMN_MAJOR")
    _ROW_MAJOR = LabwareLayoutSpec(rows=8, cols=12, numeric_addressing=True, pattern="ROW_MAJOR")

    def test_all_column_major_numbers_down_columns(self):
        result = normalize_positions("Rack@all", get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        wells = [p.well for p in result]
        assert len(wells) == 96
        assert wells[:8] == ["1", "2", "3", "4", "5", "6", "7", "8"]
        assert wells[-1] == "96"

    def test_all_row_major_numbers_across_rows(self):
        result = normalize_positions("Rack@all", get_spec=lambda _lid, _s=self: _s._ROW_MAJOR)
        wells = [p.well for p in result]
        assert len(wells) == 96
        # Row-major: well 1 is A1, well 2 is A2, ... well 13 is B1.
        assert wells[:3] == ["1", "2", "3"]
        assert wells[-1] == "96"

    def test_col_selector_emits_numeric_wells(self):
        # Column 2 in a column-major 8x12 rack is wells 9..16.
        result = normalize_positions("Rack@col:2", get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        assert [p.well for p in result] == ["9", "10", "11", "12", "13", "14", "15", "16"]

    def test_row_selector_emits_numeric_wells(self):
        # Row A (row_index 0) in a column-major 8x12 rack maps to wells 1, 9, 17, ...
        result = normalize_positions("Rack@row:A", get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        assert [p.well for p in result] == [str(1 + 8 * c) for c in range(12)]

    def test_alpha_well_translates_to_number(self):
        # B2 in a column-major 8x12 rack is well number 10.
        result = normalize_positions("Rack@B2", get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        assert result[0].well == "10"

    def test_bare_labware_numeric_addressing_expands_to_all(self):
        result = normalize_positions("Rack", channel_count=2, get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        assert [p.well for p in result] == ["1", "2"]

    def test_single_numeric_well_repeats_across_channels(self):
        result = normalize_positions("Rack@1", channel_count=2, get_spec=lambda _lid, _s=self: _s._COLUMN_MAJOR)
        assert [p.well for p in result] == ["1", "1"]
