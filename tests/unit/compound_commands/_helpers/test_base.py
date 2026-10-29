from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    emit_final_mix,
    resolve_plate_wells,
    resolve_selector_positions,
    slice_settings,
    validate_channels,
)
from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import LabwareLayoutSpec, Position


class TestValidateChannels:
    def test_default_channels_constant(self):
        assert DEFAULT_CHANNELS == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_valid_channels(self):
        validate_channels([1, 2, 3])

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_channels([])

    def test_too_many_raises(self):
        with pytest.raises(ValueError, match="at most 16"):
            validate_channels(list(range(1, 18)))

    def test_more_than_eight_channels_allowed(self):
        validate_channels(list(range(1, 17)))

    def test_out_of_range_zero(self):
        with pytest.raises(ValueError, match="between 1 and 16"):
            validate_channels([0])

    def test_out_of_range_seventeen(self):
        with pytest.raises(ValueError, match="between 1 and 16"):
            validate_channels([17])

    def test_duplicates_raises(self):
        with pytest.raises(ValueError, match="duplicates"):
            validate_channels([1, 1, 2])


class TestResolvePlateWells:
    @staticmethod
    def _mock_client(definition: dict) -> MagicMock:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.return_parameters.definition = definition
        mock_client.labware_get_params_from_id.return_value = mock_resp
        mock_client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition(definition)
        return mock_client

    def test_queries_deck_and_returns_positions(self):
        mock_client = self._mock_client({"rack_layout": {"rows": 4, "columns": 6}})

        positions = resolve_plate_wells(mock_client, "TestPlate")

        mock_client.get_labware_spec.assert_called_with("TestPlate")
        assert len(positions) == 24
        assert all(isinstance(p, Position) for p in positions)
        assert positions[0].labware == "TestPlate"
        assert positions[0].well == "A1"

    def test_96_well_plate(self):
        mock_client = self._mock_client({"rack_layout": {"rows": 8, "columns": 12}})
        positions = resolve_plate_wells(mock_client, "Plate96")
        assert len(positions) == 96

    def test_missing_geometry_raises(self):
        mock_client = MagicMock()
        mock_client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition({})
        with pytest.raises(ValueError, match="Could not locate rack_layout"):
            resolve_plate_wells(mock_client, "BadPlate")

    def test_missing_rows_raises(self):
        mock_client = MagicMock()
        mock_client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition(
            {"rack_layout": {"columns": 12}}
        )
        with pytest.raises((ValueError, KeyError)):
            resolve_plate_wells(mock_client, "BadPlate")


class TestResolveSelectorPositions:
    @staticmethod
    def _mock_client(rows: int = 8, columns: int = 12) -> MagicMock:
        mock_client = MagicMock()
        definition = {"rack_layout": {"rows": rows, "columns": columns}}
        mock_resp = MagicMock()
        mock_resp.return_parameters.definition = definition
        mock_client.labware_get_params_from_id.return_value = mock_resp
        mock_client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition(definition)
        return mock_client

    def test_bare_labware_expands_to_all(self):
        mock_client = self._mock_client(rows=4, columns=6)
        positions = resolve_selector_positions(mock_client, "Plate")
        mock_client.get_labware_spec.assert_called_with("Plate")
        assert len(positions) == 24
        assert all(isinstance(p, Position) for p in positions)
        assert positions[0].labware == "Plate"

    def test_all_selector(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@all")
        assert len(positions) == 96

    def test_single_well(self):
        mock_client = self._mock_client()
        positions = resolve_selector_positions(mock_client, "Plate@A1")
        assert len(positions) == 1
        assert positions[0].well == "A1"

    def test_explicit_wells(self):
        mock_client = self._mock_client()
        positions = resolve_selector_positions(mock_client, "Plate@wells:A1,B1,C1")
        assert [p.well for p in positions] == ["A1", "B1", "C1"]

    def test_range_selector(self):
        mock_client = self._mock_client()
        positions = resolve_selector_positions(mock_client, "Plate@A1:C1")
        assert [p.well for p in positions] == ["A1", "B1", "C1"]

    def test_row_selector(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@row:A")
        assert len(positions) == 12
        assert all(p.well.startswith("A") for p in positions)

    def test_col_selector(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@col:1")
        assert len(positions) == 8
        assert [p.well for p in positions] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]

    def test_uses_registered_spec_without_querying_client(self):
        mock_client = MagicMock()
        spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 8, "columns": 12}})
        mock_client.get_labware_spec.side_effect = lambda _lid: spec
        positions = resolve_selector_positions(mock_client, "Plate@A1:A3")
        mock_client.labware_get_params_from_id.assert_not_called()
        assert [p.well for p in positions] == ["A1", "A2", "A3"]

    def test_well_order_col_asc_default_all(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@all", well_order=WellOrder.COL_ASC)
        assert len(positions) == 96
        assert [p.well for p in positions[:9]] == [
            "A1",
            "B1",
            "C1",
            "D1",
            "E1",
            "F1",
            "G1",
            "H1",
            "A2",
        ]

    def test_well_order_col_desc_all(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@all", well_order=WellOrder.COL_DESC)
        assert len(positions) == 96
        assert positions[0].well == "H12"
        assert positions[-1].well == "A1"

    def test_well_order_row_asc_all(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@all", well_order=WellOrder.ROW_ASC)
        assert len(positions) == 96
        assert [p.well for p in positions[:13]] == [
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
            "B1",
        ]

    def test_well_order_row_desc_all(self):
        mock_client = self._mock_client(rows=8, columns=12)
        positions = resolve_selector_positions(mock_client, "Plate@all", well_order=WellOrder.ROW_DESC)
        assert len(positions) == 96
        assert positions[0].well == "H12"
        assert positions[-1].well == "A1"

    def test_well_order_none_uses_selector_default(self):
        mock_client = self._mock_client(rows=8, columns=12)
        default_positions = resolve_selector_positions(mock_client, "Plate@all")
        none_positions = resolve_selector_positions(mock_client, "Plate@all", well_order=None)
        assert [p.well for p in default_positions] == [p.well for p in none_positions]


class TestSliceSettings:
    def test_none_returns_none(self):
        assert slice_settings(None, 4) is None

    def test_non_model_passes_through(self):
        assert slice_settings("scalar", 4) == "scalar"

    def test_slices_list_fields(self):
        class FakeSettings(BaseModel):
            values: list[int] = [1, 2, 3, 4, 5, 6, 7, 8]
            scalar: int = 42

        settings = FakeSettings()
        result = slice_settings(settings, 3)
        assert result.values == [1, 2, 3]
        assert result.scalar == 42

    def test_no_slice_needed(self):
        class FakeSettings(BaseModel):
            values: list[int] = [1, 2, 3]
            scalar: int = 42

        settings = FakeSettings()
        result = slice_settings(settings, 3)
        assert result is settings

    def test_shorter_list_passes_through(self):
        class FakeSettings(BaseModel):
            values: list[int] = [1, 2]

        settings = FakeSettings()
        result = slice_settings(settings, 4)
        assert result is settings


class TestEmitFinalMix:
    def _client(self):
        client = MagicMock()
        client.dispense.return_value = "resp"
        return client

    def test_single_position_broadcasts_across_channels(self):
        client = self._client()
        pos = Position(labware="Plate1", well="A1")
        result = emit_final_mix(client, pos, [1, 2, 3], None)
        assert result == "resp"
        kwargs = client.dispense.call_args.kwargs
        assert kwargs["channels"] == [1, 2, 3]
        assert kwargs["positions"] == [pos, pos, pos]
        assert kwargs["volumes"] == 0.0

    def test_position_list_used_per_channel(self):
        client = self._client()
        positions = [Position(labware="Plate1", well=w) for w in ("A2", "B2", "C2")]
        emit_final_mix(client, positions, [1, 2, 3], None)
        kwargs = client.dispense.call_args.kwargs
        assert kwargs["positions"] == positions

    def test_position_list_length_mismatch_raises(self):
        client = self._client()
        positions = [Position(labware="Plate1", well=w) for w in ("A2", "B2")]
        with pytest.raises(ValueError, match="counts must match"):
            emit_final_mix(client, positions, [1, 2, 3], None)
        client.dispense.assert_not_called()
