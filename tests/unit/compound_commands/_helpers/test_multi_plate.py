from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hamilton_venus.compound_commands._helpers._multi_plate import (
    chunk_positions_per_plate,
    extract_labware_id,
    normalize_selector_list,
    resolve_multi_selector,
    split_positions_by_plate,
)
from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import LabwareLayoutSpec, Position


def _mock_client(rows: int = 8, columns: int = 12) -> MagicMock:
    mock_client = MagicMock()
    definition = {"rack_layout": {"rows": rows, "columns": columns}}
    mock_resp = MagicMock()
    mock_resp.return_parameters.definition = definition
    mock_client.labware_get_params_from_id.return_value = mock_resp
    mock_client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition(definition)
    return mock_client


def _p(labware: str, well: str) -> Position:
    return Position(labware=labware, well=well)


class TestResolveMultiSelector:
    def test_string_input_matches_resolve_selector_positions(self):
        client = _mock_client()
        result = resolve_multi_selector(client, "Plate@col:1")
        assert [p.well for p in result] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
        assert all(p.labware == "Plate" for p in result)

    def test_list_input_concatenates_in_order(self):
        client = _mock_client()
        result = resolve_multi_selector(client, ["A@col:1", "B@col:1"])
        assert [p.labware for p in result[:8]] == ["A"] * 8
        assert [p.labware for p in result[8:]] == ["B"] * 8
        assert [p.well for p in result[:8]] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
        assert [p.well for p in result[8:]] == [p.well for p in result[:8]]

    def test_single_element_list_equivalent_to_string(self):
        client_a = _mock_client()
        client_b = _mock_client()
        as_str = resolve_multi_selector(client_a, "Plate@col:1")
        as_list = resolve_multi_selector(client_b, ["Plate@col:1"])
        assert [(p.labware, p.well) for p in as_str] == [(p.labware, p.well) for p in as_list]

    def test_well_order_applies_per_plate(self):
        client = _mock_client()
        result = resolve_multi_selector(client, ["A@all", "B@all"], well_order=WellOrder.ROW_ASC)
        # First 12 should be A row A; positions 96..107 should be B row A
        assert [p.well for p in result[:12]] == [f"A{i}" for i in range(1, 13)]
        assert [p.well for p in result[96:108]] == [f"A{i}" for i in range(1, 13)]
        assert result[0].labware == "A"
        assert result[96].labware == "B"

    def test_registered_spec_avoids_deck_query(self):
        client = MagicMock()
        spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 8, "columns": 12}})
        client.get_labware_spec.side_effect = lambda _lid: spec
        result = resolve_multi_selector(client, "Plate@A1:A3")
        client.labware_get_params_from_id.assert_not_called()
        assert [p.well for p in result] == ["A1", "A2", "A3"]

    def test_empty_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="at least one entry"):
            resolve_multi_selector(client, [])

    def test_non_string_entry_raises(self):
        client = _mock_client()
        with pytest.raises(TypeError, match="must be str or Position"):
            resolve_multi_selector(client, ["A@A1", 5])  # type: ignore[list-item]

    def test_empty_string_entry_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="non-empty"):
            resolve_multi_selector(client, ["A@A1", ""])

    def test_non_list_non_string_raises(self):
        client = _mock_client()
        with pytest.raises(TypeError, match="must be a str, Position, or list"):
            resolve_multi_selector(client, 42)  # type: ignore[arg-type]

    def test_position_input_returned_as_is(self):
        client = _mock_client()
        result = resolve_multi_selector(client, _p("Plate", "A1"))
        assert [(p.labware, p.well) for p in result] == [("Plate", "A1")]

    def test_position_list_input_concatenates(self):
        client = _mock_client()
        result = resolve_multi_selector(client, [_p("A", "A1"), _p("B", "A1")])
        assert [(p.labware, p.well) for p in result] == [("A", "A1"), ("B", "A1")]

    def test_mixed_str_and_position_list_input(self):
        client = _mock_client()
        result = resolve_multi_selector(client, ["A@col:1", _p("B", "A1")])
        assert len(result) == 9  # 8 wells from "A@col:1" + 1 Position
        assert result[-1].labware == "B"


class TestExtractLabwareId:
    def test_str_selector_with_expression(self):
        assert extract_labware_id("Plate1@col:1") == "Plate1"

    def test_str_selector_bare(self):
        assert extract_labware_id("Plate1") == "Plate1"

    def test_position_returns_labware_field(self):
        assert extract_labware_id(_p("Plate1", "A1")) == "Plate1"


class TestNormalizeSelectorList:
    def test_wraps_single_string(self):
        assert normalize_selector_list("Plate1@A1") == ["Plate1@A1"]

    def test_wraps_single_position(self):
        pos = _p("Plate1", "A1")
        assert normalize_selector_list(pos) == [pos]

    def test_passes_through_list(self):
        assert normalize_selector_list(["A", "B"]) == ["A", "B"]


class TestSplitPositionsByPlate:
    def test_empty_input(self):
        assert split_positions_by_plate([]) == []

    def test_single_plate(self):
        positions = [Position(labware="A", well=w) for w in ["A1", "B1", "C1"]]
        groups = split_positions_by_plate(positions)
        assert len(groups) == 1
        assert groups[0][0] == "A"
        assert [p.well for p in groups[0][1]] == ["A1", "B1", "C1"]

    def test_two_plates_contiguous(self):
        positions = [_p("A", "A1"), _p("A", "B1"), _p("B", "A1")]
        groups = split_positions_by_plate(positions)
        assert [g[0] for g in groups] == ["A", "B"]
        assert [p.well for p in groups[0][1]] == ["A1", "B1"]
        assert [p.well for p in groups[1][1]] == ["A1"]

    def test_repeated_plate_non_contiguous(self):
        positions = [
            _p("A", "A1"),
            _p("B", "A1"),
            _p("A", "B1"),
        ]
        groups = split_positions_by_plate(positions)
        assert [g[0] for g in groups] == ["A", "B", "A"]
        assert len(groups[0][1]) == 1
        assert len(groups[2][1]) == 1


class TestChunkPositionsPerPlate:
    def test_empty_input_yields_nothing(self):
        assert list(chunk_positions_per_plate([], 8)) == []

    def test_chunk_within_single_plate(self):
        positions = [_p("A", f"A{i}") for i in range(1, 11)]
        chunks = list(chunk_positions_per_plate(positions, 4))
        assert [len(c) for c in chunks] == [4, 4, 2]
        assert all(p.labware == "A" for c in chunks for p in c)

    def test_chunk_breaks_at_plate_boundary(self):
        positions = [
            _p("A", "A1"),
            _p("A", "B1"),
            _p("A", "C1"),
            _p("B", "A1"),
            _p("B", "B1"),
            _p("B", "C1"),
        ]
        chunks = list(chunk_positions_per_plate(positions, 4))
        assert [len(c) for c in chunks] == [3, 3]
        assert chunks[0][0].labware == "A"
        assert chunks[1][0].labware == "B"

    def test_chunk_exact_multiple_at_boundary(self):
        positions = [_p("A", f"A{i}") for i in range(1, 5)] + [_p("B", f"A{i}") for i in range(1, 5)]
        chunks = list(chunk_positions_per_plate(positions, 4))
        assert [len(c) for c in chunks] == [4, 4]

    def test_chunk_size_one(self):
        positions = [_p("A", "A1"), _p("A", "B1"), _p("B", "A1")]
        chunks = list(chunk_positions_per_plate(positions, 1))
        assert [len(c) for c in chunks] == [1, 1, 1]

    def test_chunk_size_zero_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be >= 1"):
            list(chunk_positions_per_plate([_p("A", "A1")], 0))
