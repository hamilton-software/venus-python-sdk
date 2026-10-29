"""Unit tests for the shared ``_transfer_plan`` helpers.

Tests CSV parsing/grouping primitives used by ``add_reagent`` and other
compound commands: :class:`TransferRow`, :class:`DestGroup`,
:class:`SourceGroup`, :class:`SourceWellGroup`,
:func:`_validate_required_csv_field`, :func:`_parse_transfer_csv`,
:func:`_group_csv_rows`, :func:`_group_by_source_well`,
:func:`_plan_source_runs`, and the plate-grouped column-major reordering
helpers (:func:`_well_grid_index`, :func:`_plate_grouped_column_major_key`,
:func:`_sort_plate_grouped_column_major`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hamilton_venus.compound_commands._helpers._transfer_plan import (
    DestGroup,
    SourceGroup,
    SourceWellGroup,
    TransferRow,
    _group_by_source_well,
    _group_csv_rows,
    _parse_transfer_csv,
    _plan_source_runs,
    _plate_grouped_column_major_key,
    _sort_plate_grouped_column_major,
    _validate_required_csv_field,
    _well_grid_index,
    validate_labware_on_deck,
)
from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.models.position import LabwareLayoutSpec


def _write_csv(tmp_path: Path, content: str, name: str = "transfer.csv") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestPlanSourceRuns:
    def test_plan_source_runs_empty(self):
        assert _plan_source_runs([]) == []

    def test_plan_source_runs_single_source(self):
        rows = [
            TransferRow("S1", "A1", "D1", "A1", 50.0),
            TransferRow("S1", "A1", "D1", "B1", 50.0),
        ]
        runs = _plan_source_runs(rows)
        assert len(runs) == 1
        assert runs[0] == rows

    def test_plan_source_runs_aba_pattern(self):
        rows = [
            TransferRow("S1", "A1", "D1", "A1", 50.0),
            TransferRow("S2", "A1", "D2", "A1", 60.0),
            TransferRow("S1", "A1", "D1", "B1", 50.0),
        ]
        runs = _plan_source_runs(rows)
        assert len(runs) == 3
        assert runs[0] == [rows[0]]
        assert runs[1] == [rows[1]]
        assert runs[2] == [rows[2]]

    def test_plan_source_runs_contiguous_same_source(self):
        rows = [
            TransferRow("S1", "A1", "D1", "A1", 50.0),
            TransferRow("S1", "A1", "D1", "B1", 50.0),
            TransferRow("S2", "A1", "D2", "A1", 60.0),
            TransferRow("S2", "A1", "D2", "B1", 60.0),
        ]
        runs = _plan_source_runs(rows)
        assert len(runs) == 2
        assert len(runs[0]) == 2
        assert len(runs[1]) == 2


class TestValidateRequiredCsvField:
    """Tests for _validate_required_csv_field helper."""

    def test_validates_non_empty_string(self):
        result = _validate_required_csv_field("value", "field_name", Path("test.csv"), 10)
        assert result == "value"

    def test_strips_whitespace(self):
        result = _validate_required_csv_field("  value  ", "field_name", Path("test.csv"), 10)
        assert result == "value"

    def test_raises_on_none(self):
        with pytest.raises(ValueError, match="missing required field 'test_field'"):
            _validate_required_csv_field(None, "test_field", Path("test.csv"), 5)

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="missing required field 'test_field'"):
            _validate_required_csv_field("", "test_field", Path("test.csv"), 5)

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValueError, match="missing required field 'test_field'"):
            _validate_required_csv_field("   ", "test_field", Path("test.csv"), 5)

    def test_error_includes_csv_path_and_line_number(self):
        csv_path = Path("transfers.csv")
        with pytest.raises(ValueError, match=r"transfers\.csv.*line 42"):
            _validate_required_csv_field(None, "field", csv_path, 42)


class TestParseTransferCsv:
    def test_full_csv(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume\nSrc1,A1,Dst1,B1,50.0\nSrc1,A2,Dst1,B2,75.5\n",
        )
        rows = _parse_transfer_csv(path)
        assert rows == [
            TransferRow("Src1", "A1", "Dst1", "B1", 50.0, line_no=2),
            TransferRow("Src1", "A2", "Dst1", "B2", 75.5, line_no=3),
        ]

    def test_defaults_fill_missing_columns(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_well,dest_well\nA1,B1\nA2,B2\n",
        )
        rows = _parse_transfer_csv(
            path,
            default_source_labware="Src",
            default_dest_labware="Dst",
            default_volume=25.0,
        )
        assert [r.source_labware for r in rows] == ["Src", "Src"]
        assert [r.dest_labware for r in rows] == ["Dst", "Dst"]
        assert [r.volume for r in rows] == [25.0, 25.0]

    def test_defaults_fill_empty_cells(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume\n,A1,,B1,\nSrc2,A2,Dst2,B2,30\n",
        )
        rows = _parse_transfer_csv(
            path,
            default_source_labware="Src",
            default_dest_labware="Dst",
            default_volume=10.0,
        )
        assert rows[0] == TransferRow("Src", "A1", "Dst", "B1", 10.0, line_no=2)
        assert rows[1] == TransferRow("Src2", "A2", "Dst2", "B2", 30.0, line_no=3)

    def test_extra_columns_ignored(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume,notes\nSrc,A1,Dst,B1,5,hello\n",
        )
        rows = _parse_transfer_csv(path)
        assert rows == [TransferRow("Src", "A1", "Dst", "B1", 5.0, line_no=2)]

    def test_header_case_insensitive_and_whitespace(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            " Source_Labware , source_well ,DEST_LABWARE,dest_well,VOLUME\nSrc,A1,Dst,B1,5\n",
        )
        rows = _parse_transfer_csv(path)
        assert rows == [TransferRow("Src", "A1", "Dst", "B1", 5.0, line_no=2)]

    def test_missing_well_no_default_raises(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,dest_labware,volume\nSrc,Dst,5\n",
        )
        with pytest.raises(ValueError, match=r"missing required field"):
            _parse_transfer_csv(path)

    def test_missing_volume_no_default_raises(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well\nSrc,A1,Dst,B1\n",
        )
        with pytest.raises(ValueError, match=r"missing required field.*volume"):
            _parse_transfer_csv(path)

    def test_invalid_volume_raises(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume\nSrc,A1,Dst,B1,not-a-number\n",
        )
        with pytest.raises(ValueError, match=r"invalid volume"):
            _parse_transfer_csv(path)

    def test_empty_file_raises(self, tmp_path: Path):
        path = _write_csv(tmp_path, "")
        with pytest.raises(ValueError, match=r"empty"):
            _parse_transfer_csv(path)

    def test_header_only_raises(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume\n",
        )
        with pytest.raises(ValueError, match=r"no data rows"):
            _parse_transfer_csv(path)

    def test_utf8_bom_handled(self, tmp_path: Path):
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfsource_labware,source_well,dest_labware,dest_well,volume\nSrc,A1,Dst,B1,5\n")
        rows = _parse_transfer_csv(path)
        assert rows == [TransferRow("Src", "A1", "Dst", "B1", 5.0, line_no=2)]

    @pytest.mark.parametrize(
        "field, csv_content",
        [
            (
                "source_labware",
                "source_labware,source_well,dest_labware,dest_well,volume\n   ,A1,Dst,B1,5\n",
            ),
            (
                "source_well",
                "source_labware,source_well,dest_labware,dest_well,volume\nSrc,   ,Dst,B1,5\n",
            ),
            (
                "dest_labware",
                "source_labware,source_well,dest_labware,dest_well,volume\nSrc,A1,   ,B1,5\n",
            ),
            (
                "dest_well",
                "source_labware,source_well,dest_labware,dest_well,volume\nSrc,A1,Dst,   ,5\n",
            ),
        ],
    )
    def test_whitespace_only_cell_raises(self, tmp_path: Path, field: str, csv_content: str):
        path = _write_csv(tmp_path, csv_content)
        with pytest.raises(ValueError, match=rf"missing required field '{field}'"):
            _parse_transfer_csv(path)

    @pytest.mark.parametrize(
        "csv_content, kwargs, field",
        [
            (
                "source_well,dest_labware,dest_well,volume\nA1,Dst,B1,5\n",
                {"default_source_labware": "   "},
                "source_labware",
            ),
            (
                "source_labware,source_well,dest_well,volume\nSrc,A1,B1,5\n",
                {"default_dest_labware": "   "},
                "dest_labware",
            ),
        ],
    )
    def test_whitespace_only_default_raises(self, tmp_path: Path, csv_content: str, kwargs: dict[str, Any], field: str):
        path = _write_csv(tmp_path, csv_content)
        with pytest.raises(ValueError, match=rf"missing required field '{field}'"):
            _parse_transfer_csv(path, **kwargs)

    def test_whitespace_padded_cell_values_are_trimmed(self, tmp_path: Path):
        path = _write_csv(
            tmp_path,
            "source_labware,source_well,dest_labware,dest_well,volume\n Src1 , A1 , Dst1 , B1 ,5\n",
        )
        rows = _parse_transfer_csv(path)
        assert rows == [TransferRow("Src1", "A1", "Dst1", "B1", 5.0, line_no=2)]


class TestGroupCsvRows:
    def test_single_source_single_dest(self):
        rows = [
            TransferRow("Src", "A1", "Dst", "B1", 5.0),
            TransferRow("Src", "A2", "Dst", "B2", 5.0),
        ]
        groups = _group_csv_rows(rows)
        assert groups == [
            SourceGroup(
                source_labware="Src",
                dest_groups=[DestGroup(dest_labware="Dst", rows=rows)],
            )
        ]

    def test_multiple_dests_same_source(self):
        r1 = TransferRow("Src", "A1", "DstA", "B1", 5.0)
        r2 = TransferRow("Src", "A2", "DstB", "B1", 5.0)
        r3 = TransferRow("Src", "A3", "DstA", "B2", 5.0)
        groups = _group_csv_rows([r1, r2, r3])
        assert len(groups) == 1
        assert groups[0].source_labware == "Src"
        dest_labwares = [d.dest_labware for d in groups[0].dest_groups]
        assert dest_labwares == ["DstA", "DstB"]
        assert groups[0].dest_groups[0].rows == [r1, r3]
        assert groups[0].dest_groups[1].rows == [r2]

    def test_multiple_sources_preserves_first_appearance_order(self):
        r1 = TransferRow("SrcB", "A1", "Dst", "B1", 5.0)
        r2 = TransferRow("SrcA", "A1", "Dst", "B2", 5.0)
        r3 = TransferRow("SrcB", "A2", "Dst", "B3", 5.0)
        groups = _group_csv_rows([r1, r2, r3])
        assert [g.source_labware for g in groups] == ["SrcB", "SrcA"]
        assert groups[0].dest_groups[0].rows == [r1, r3]
        assert groups[1].dest_groups[0].rows == [r2]

    def test_empty_rows_returns_empty(self):
        assert _group_csv_rows([]) == []

    def test_row_order_within_dest_group_preserved(self):
        rows = [TransferRow("Src", f"A{i}", "Dst", f"B{i}", 5.0) for i in range(1, 6)]
        groups = _group_csv_rows(rows)
        assert groups[0].dest_groups[0].rows == rows


class TestGroupBySourceWell:
    def test_empty_rows_returns_empty(self):
        assert _group_by_source_well([]) == []

    def test_single_source_well(self):
        rows = [
            TransferRow("Src", "A1", "Dst", "B1", 5.0),
            TransferRow("Src", "A1", "Dst", "C1", 5.0),
        ]
        groups = _group_by_source_well(rows)
        assert groups == [SourceWellGroup(source_labware="Src", source_well="A1", rows=rows)]

    def test_every_row_has_a_unique_source_well(self):
        rows = [
            TransferRow("Src", "A1", "Dst", "B1", 5.0),
            TransferRow("Src", "A2", "Dst", "B2", 5.0),
            TransferRow("Src", "A3", "Dst", "B3", 5.0),
        ]
        groups = _group_by_source_well(rows)
        assert [g.source_well for g in groups] == ["A1", "A2", "A3"]
        assert all(len(g.rows) == 1 for g in groups)

    def test_groups_preserve_first_appearance_order(self):
        r1 = TransferRow("Src", "B1", "Dst", "A1", 5.0)
        r2 = TransferRow("Src", "A1", "Dst", "A2", 5.0)
        r3 = TransferRow("Src", "B1", "Dst", "A3", 5.0)
        groups = _group_by_source_well([r1, r2, r3])
        assert [g.source_well for g in groups] == ["B1", "A1"]
        assert groups[0].rows == [r1, r3]
        assert groups[1].rows == [r2]

    def test_merges_non_consecutive_same_source_well(self):
        # W1 -> W2 -> W1 merges the two W1 rows into one group, unlike
        # _plan_source_runs which would emit three separate runs.
        r1 = TransferRow("Src", "A1", "Dst", "A1", 5.0)
        r2 = TransferRow("Src", "A2", "Dst", "A2", 5.0)
        r3 = TransferRow("Src", "A1", "Dst", "A3", 5.0)
        groups = _group_by_source_well([r1, r2, r3])
        assert groups == [
            SourceWellGroup("Src", "A1", [r1, r3]),
            SourceWellGroup("Src", "A2", [r2]),
        ]

    def test_same_well_id_different_labware_are_distinct_groups(self):
        r1 = TransferRow("SrcA", "A1", "Dst", "A1", 5.0)
        r2 = TransferRow("SrcB", "A1", "Dst", "A2", 5.0)
        groups = _group_by_source_well([r1, r2])
        assert [(g.source_labware, g.source_well) for g in groups] == [("SrcA", "A1"), ("SrcB", "A1")]

    def test_within_group_row_order_preserved(self):
        rows = [TransferRow("Src", "A1", "Dst", f"B{i}", float(i)) for i in range(1, 6)]
        groups = _group_by_source_well(rows)
        assert len(groups) == 1
        assert groups[0].rows == rows


_SPEC_96 = LabwareLayoutSpec(rows=8, cols=12)


class TestWellGridIndex:
    def test_plate_wells_return_column_then_row(self):
        assert _well_grid_index("A1", _SPEC_96) == (1, 0)
        assert _well_grid_index("B1", _SPEC_96) == (1, 1)
        assert _well_grid_index("A2", _SPEC_96) == (2, 0)
        assert _well_grid_index("H12", _SPEC_96) == (12, 7)

    def test_is_case_insensitive(self):
        assert _well_grid_index("a1", _SPEC_96) == _well_grid_index("A1", _SPEC_96)

    def test_single_column_carrier_numeric_wells(self):
        spec = LabwareLayoutSpec(rows=24, cols=1)
        assert _well_grid_index("1", spec) == (1, 0)
        assert _well_grid_index("5", spec) == (1, 4)

    def test_sorting_on_index_is_column_major(self):
        wells = ["A2", "B1", "A1", "C1"]
        ordered = sorted(wells, key=lambda w: _well_grid_index(w, _SPEC_96))
        assert ordered == ["A1", "B1", "C1", "A2"]

    def test_invalid_well_raises(self):
        with pytest.raises(ValueError):
            _well_grid_index("Z99", _SPEC_96)


class TestPlateGroupedColumnMajor:
    def test_key_is_rank_based_six_tuple(self):
        spec_cache = {"S": _SPEC_96, "D": _SPEC_96}
        row = TransferRow("S", "B2", "D", "C3", 5.0)
        key = _plate_grouped_column_major_key(row, spec_cache, {"S": 0}, {"D": 0})
        # B2 -> (col 2, row 1); C3 -> (col 3, row 2); both plates rank 0.
        assert key == (0, 2, 1, 0, 3, 2)

    def test_source_tier_reordered_column_major(self):
        spec_cache = {"S": _SPEC_96, "D": _SPEC_96}
        rows = [
            TransferRow("S", "A2", "D", "A1", 5.0),
            TransferRow("S", "B1", "D", "A1", 5.0),
            TransferRow("S", "A1", "D", "A1", 5.0),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [r.source_well for r in ordered] == ["A1", "B1", "A2"]

    def test_dest_tier_reordered_column_major_within_source_well(self):
        spec_cache = {"S": _SPEC_96, "D": _SPEC_96}
        rows = [
            TransferRow("S", "A1", "D", "A2", 5.0),
            TransferRow("S", "A1", "D", "B1", 5.0),
            TransferRow("S", "A1", "D", "A1", 5.0),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [r.dest_well for r in ordered] == ["A1", "B1", "A2"]

    def test_source_plate_first_appearance_rank_not_lexicographic(self):
        # PlateB is referenced first; rank ordering must keep it ahead of
        # PlateA (lexicographic ordering would invert this).
        spec_cache = {"PlateB": _SPEC_96, "PlateA": _SPEC_96, "D": _SPEC_96}
        rows = [
            TransferRow("PlateB", "A1", "D", "A1", 5.0),
            TransferRow("PlateA", "A1", "D", "A1", 5.0),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [r.source_labware for r in ordered] == ["PlateB", "PlateA"]

    def test_dest_plate_first_appearance_rank_not_lexicographic(self):
        spec_cache = {"S": _SPEC_96, "DestZ": _SPEC_96, "DestA": _SPEC_96}
        rows = [
            TransferRow("S", "A1", "DestZ", "A1", 5.0),
            TransferRow("S", "A1", "DestA", "A1", 5.0),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [r.dest_labware for r in ordered] == ["DestZ", "DestA"]

    def test_ties_preserve_original_order(self):
        spec_cache = {"S": _SPEC_96, "D": _SPEC_96}
        rows = [
            TransferRow("S", "A1", "D", "A1", 1.0, line_no=2),
            TransferRow("S", "A1", "D", "A1", 2.0, line_no=3),
            TransferRow("S", "A1", "D", "A1", 3.0, line_no=4),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [r.volume for r in ordered] == [1.0, 2.0, 3.0]

    def test_full_multi_plate_ordering(self):
        spec_cache = {"S1": _SPEC_96, "S2": _SPEC_96, "D1": _SPEC_96}
        rows = [
            TransferRow("S2", "A1", "D1", "A1", 5.0),
            TransferRow("S1", "B1", "D1", "A1", 5.0),
            TransferRow("S2", "A1", "D1", "B1", 5.0),
            TransferRow("S1", "A1", "D1", "A1", 5.0),
        ]
        ordered = _sort_plate_grouped_column_major(rows, spec_cache)
        assert [(r.source_labware, r.source_well, r.dest_well) for r in ordered] == [
            ("S2", "A1", "A1"),
            ("S2", "A1", "B1"),
            ("S1", "A1", "A1"),
            ("S1", "B1", "A1"),
        ]

    def test_does_not_mutate_input(self):
        spec_cache = {"S": _SPEC_96, "D": _SPEC_96}
        rows = [
            TransferRow("S", "A2", "D", "A1", 5.0),
            TransferRow("S", "A1", "D", "A1", 5.0),
        ]
        snapshot = list(rows)
        _sort_plate_grouped_column_major(rows, spec_cache)
        assert rows == snapshot


# ---------------------------------------------------------------------------
# validate_labware_on_deck
# ---------------------------------------------------------------------------


def _make_labware_client(present: set[str]) -> MagicMock:
    """Build a mock StarClient whose labware_get_params_from_id succeeds only for *present*."""
    client = MagicMock()

    def _side_effect(labware_id: str) -> MagicMock:
        if labware_id in present:
            resp = MagicMock()
            resp.return_parameters = MagicMock()
            return resp
        fail_resp = MagicMock(
            action_name="labware.getLabwareParamsFromID",
            return_status="Failure",
            return_code=1,
            return_parameters={},
        )
        raise VenusCommandFailedError(fail_resp)

    client.labware_get_params_from_id.side_effect = _side_effect
    return client


class TestValidateLabwareOnDeck:
    def test_returns_dict_for_present_labware(self):
        client = _make_labware_client({"PlateA", "PlateB"})
        result = validate_labware_on_deck(client, ["PlateA", "PlateB"])
        assert set(result.keys()) == {"PlateA", "PlateB"}

    def test_deduplicates_ids(self):
        client = _make_labware_client({"PlateA"})
        validate_labware_on_deck(client, ["PlateA", "PlateA", "PlateA"])
        assert client.labware_get_params_from_id.call_count == 1

    def test_preserves_first_occurrence_order(self):
        client = _make_labware_client({"X", "Y", "Z"})
        result = validate_labware_on_deck(client, ["Y", "X", "Y", "Z", "X"])
        assert list(result.keys()) == ["Y", "X", "Z"]

    def test_raises_for_missing_labware(self):
        client = _make_labware_client({"PlateA"})
        with pytest.raises(ValueError, match="PlateB"):
            validate_labware_on_deck(client, ["PlateA", "PlateB"])

    def test_accumulates_all_missing_in_one_error(self):
        client = _make_labware_client({"Good"})
        with pytest.raises(ValueError) as exc:
            validate_labware_on_deck(client, ["Good", "Bad1", "Bad2", "Bad3"])
        msg = str(exc.value)
        assert "Bad1" in msg
        assert "Bad2" in msg
        assert "Bad3" in msg
        assert "Good" not in msg or "are referenced" in msg

    def test_error_message_includes_row_origin_line_numbers(self):
        client = _make_labware_client(set())
        with pytest.raises(ValueError) as exc:
            validate_labware_on_deck(
                client,
                ["BadA", "BadB"],
                row_origin={"BadA": 7, "BadB": 12},
            )
        msg = str(exc.value)
        assert "line 7" in msg
        assert "line 12" in msg

    def test_omits_line_numbers_when_row_origin_not_provided(self):
        client = _make_labware_client(set())
        with pytest.raises(ValueError) as exc:
            validate_labware_on_deck(client, ["BadX"])
        assert "line" not in str(exc.value)

    def test_empty_iterable_returns_empty_dict(self):
        client = _make_labware_client(set())
        result = validate_labware_on_deck(client, [])
        assert result == {}
        client.labware_get_params_from_id.assert_not_called()

    def test_does_not_raise_for_id_present_in_row_origin_but_resolvable(self):
        client = _make_labware_client({"PlateA"})
        validate_labware_on_deck(client, ["PlateA"], row_origin={"PlateA": 2})

    def test_partial_failure_still_lists_all_missing(self):
        client = _make_labware_client({"PlateA", "PlateC"})
        with pytest.raises(ValueError) as exc:
            validate_labware_on_deck(client, ["PlateA", "PlateB", "PlateC", "PlateD"])
        msg = str(exc.value)
        assert "PlateB" in msg
        assert "PlateD" in msg
