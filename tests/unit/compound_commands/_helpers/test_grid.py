"""Unit tests for the pure serial-dilution grid helpers (``_grid``).

Covers row exclusion/normalisation (ints + letters), pass partitioning (§3.7),
column sequence resolution with excluded columns skipped without consuming a
step (Q-COL2), range/capacity errors, and volume validation (positivity;
factor >= 1).
"""

from __future__ import annotations

import pytest

from hamilton_venus.compound_commands._helpers._grid import (
    DilutionGrid,
    _normalize_exclude_rows,
    _partition_rows_into_passes,
    _resolve_dilution_grid,
    _validate_volumes,
)
from hamilton_venus.models.position import LabwareLayoutSpec


def _spec(rows: int = 8, cols: int = 12, numeric_addressing: bool = False) -> LabwareLayoutSpec:
    return LabwareLayoutSpec(rows=rows, cols=cols, numeric_addressing=numeric_addressing)


class TestNormalizeExcludeRows:
    def test_none_and_empty(self):
        assert _normalize_exclude_rows(None, _spec()) == set()
        assert _normalize_exclude_rows([], _spec()) == set()

    def test_one_based_ints(self):
        assert _normalize_exclude_rows([1, 3, 8], _spec()) == {0, 2, 7}

    def test_letters(self):
        assert _normalize_exclude_rows(["A", "C", "H"], _spec()) == {0, 2, 7}

    def test_mixed_ints_and_letters(self):
        assert _normalize_exclude_rows([1, "C", 8], _spec()) == {0, 2, 7}

    def test_lowercase_letters(self):
        assert _normalize_exclude_rows(["a", "h"], _spec()) == {0, 7}

    def test_out_of_range_int_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            _normalize_exclude_rows([9], _spec(rows=8))

    def test_out_of_range_letter_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            _normalize_exclude_rows(["I"], _spec(rows=8))

    def test_letter_on_numeric_addressed_labware_raises(self):
        with pytest.raises(ValueError, match="numeric-addressed labware"):
            _normalize_exclude_rows(["A"], _spec(rows=8, cols=1, numeric_addressing=True))

    def test_single_column_carrier_accepts_ints(self):
        assert _normalize_exclude_rows([1, 2], _spec(rows=8, cols=1, numeric_addressing=True)) == {0, 1}

    def test_bool_rejected(self):
        with pytest.raises(ValueError, match="int or row letter"):
            _normalize_exclude_rows([True], _spec())

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError, match="int or row letter"):
            _normalize_exclude_rows([1.5], _spec())  # type: ignore[list-item]


class TestPartitionRowsIntoPasses:
    def test_single_pass_when_rows_fit(self):
        assert _partition_rows_into_passes([0, 1, 2, 3], [1, 2, 3, 4]) == [[0, 1, 2, 3]]

    def test_multi_pass_384_on_8_channels(self):
        active = list(range(16))
        channels = list(range(1, 9))
        assert _partition_rows_into_passes(active, channels) == [
            list(range(0, 8)),
            list(range(8, 16)),
        ]

    def test_ragged_last_pass(self):
        assert _partition_rows_into_passes([0, 1, 2, 3, 4], [1, 2]) == [[0, 1], [2, 3], [4]]

    def test_empty_channels_raises(self):
        with pytest.raises(ValueError, match="channels must not be empty"):
            _partition_rows_into_passes([0, 1], [])

    def test_empty_active_rows(self):
        assert _partition_rows_into_passes([], [1, 2]) == []


class TestResolveDilutionGrid:
    def test_basic_grid(self):
        grid = _resolve_dilution_grid(
            _spec(rows=8, cols=12),
            start_column=1,
            num_dilutions=5,
            exclude_columns=None,
            exclude_rows=None,
            channels=list(range(1, 9)),
        )
        assert isinstance(grid, DilutionGrid)
        assert grid.passes == [list(range(8))]
        assert grid.column_sequence == [1, 2, 3, 4, 5, 6]
        assert grid.sample_column == 1
        assert grid.dilution_columns == [2, 3, 4, 5, 6]
        assert grid.num_dilutions == 5

    def test_excluded_columns_do_not_consume_a_step(self):
        # Excluding column 3 means the sequence walks past it: 1 (sample), then
        # 2, 4, 5 as the three dilution columns.
        grid = _resolve_dilution_grid(
            _spec(rows=8, cols=12),
            start_column=1,
            num_dilutions=3,
            exclude_columns=[3],
            exclude_rows=None,
            channels=list(range(1, 9)),
        )
        assert grid.column_sequence == [1, 2, 4, 5]

    def test_excluded_rows_removed(self):
        grid = _resolve_dilution_grid(
            _spec(rows=8, cols=12),
            start_column=1,
            num_dilutions=2,
            exclude_columns=None,
            exclude_rows=["B", 4],
            channels=list(range(1, 9)),
        )
        # Rows B (index 1) and 4 (index 3) removed.
        assert grid.passes == [[0, 2, 4, 5, 6, 7]]

    def test_multi_pass_grid(self):
        grid = _resolve_dilution_grid(
            _spec(rows=16, cols=24),
            start_column=1,
            num_dilutions=4,
            exclude_columns=None,
            exclude_rows=None,
            channels=list(range(1, 9)),
        )
        assert grid.passes == [list(range(0, 8)), list(range(8, 16))]
        assert grid.column_sequence == [1, 2, 3, 4, 5]

    def test_start_column_offset(self):
        grid = _resolve_dilution_grid(
            _spec(rows=8, cols=12),
            start_column=7,
            num_dilutions=5,
            exclude_columns=None,
            exclude_rows=None,
            channels=list(range(1, 9)),
        )
        assert grid.column_sequence == [7, 8, 9, 10, 11, 12]

    def test_num_dilutions_below_one_raises(self):
        with pytest.raises(ValueError, match="num_dilutions must be >= 1"):
            _resolve_dilution_grid(
                _spec(),
                start_column=1,
                num_dilutions=0,
                exclude_columns=None,
                exclude_rows=None,
                channels=list(range(1, 9)),
            )

    def test_all_rows_excluded_raises(self):
        with pytest.raises(ValueError, match="All plate rows are excluded"):
            _resolve_dilution_grid(
                _spec(rows=3, cols=12),
                start_column=1,
                num_dilutions=2,
                exclude_columns=None,
                exclude_rows=[1, 2, 3],
                channels=list(range(1, 9)),
            )

    def test_not_enough_columns_raises(self):
        with pytest.raises(ValueError, match="Not enough non-excluded columns"):
            _resolve_dilution_grid(
                _spec(rows=8, cols=12),
                start_column=10,
                num_dilutions=5,
                exclude_columns=None,
                exclude_rows=None,
                channels=list(range(1, 9)),
            )

    def test_not_enough_columns_after_exclusions_raises(self):
        with pytest.raises(ValueError, match="Not enough non-excluded columns"):
            _resolve_dilution_grid(
                _spec(rows=8, cols=12),
                start_column=1,
                num_dilutions=11,
                exclude_columns=[5],
                exclude_rows=None,
                channels=list(range(1, 9)),
            )

    def test_start_column_out_of_range_raises(self):
        with pytest.raises(ValueError, match="start_column 13 is out of range"):
            _resolve_dilution_grid(
                _spec(rows=8, cols=12),
                start_column=13,
                num_dilutions=1,
                exclude_columns=None,
                exclude_rows=None,
                channels=list(range(1, 9)),
            )

    def test_exclude_column_out_of_range_raises(self):
        with pytest.raises(ValueError, match="exclude_columns entry 13 is out of range"):
            _resolve_dilution_grid(
                _spec(rows=8, cols=12),
                start_column=1,
                num_dilutions=1,
                exclude_columns=[13],
                exclude_rows=None,
                channels=list(range(1, 9)),
            )

    def test_start_column_excluded_raises(self):
        with pytest.raises(ValueError, match="start_column 2 is listed in exclude_columns"):
            _resolve_dilution_grid(
                _spec(rows=8, cols=12),
                start_column=2,
                num_dilutions=1,
                exclude_columns=[2],
                exclude_rows=None,
                channels=list(range(1, 9)),
            )


class TestValidateVolumes:
    def test_valid_by_volume(self):
        _validate_volumes(transfer_volume=50.0, diluent_volume=150.0)

    def test_valid_by_factor(self):
        _validate_volumes(transfer_volume=50.0, dilution_factor=10.0)

    def test_factor_of_one_allowed(self):
        _validate_volumes(transfer_volume=50.0, dilution_factor=1.0)

    def test_zero_diluent_allowed(self):
        # Zero diluent skips the diluent phase; not an error.
        _validate_volumes(transfer_volume=50.0, diluent_volume=0.0)

    def test_non_positive_transfer_raises(self):
        with pytest.raises(ValueError, match="transfer_volume must be > 0"):
            _validate_volumes(transfer_volume=0.0)

    def test_negative_diluent_raises(self):
        with pytest.raises(ValueError, match="diluent_volume must be >= 0"):
            _validate_volumes(transfer_volume=50.0, diluent_volume=-1.0)

    def test_factor_below_one_raises(self):
        with pytest.raises(ValueError, match="dilution_factor must be >= 1"):
            _validate_volumes(transfer_volume=50.0, dilution_factor=0.5)

    def test_factor_to_diluent_volume_math(self):
        # The by-factor command computes diluent_volume = transfer * (factor - 1).
        # Validate that the derived volume is accepted by _validate_volumes.
        transfer_volume = 20.0
        dilution_factor = 10.0
        diluent_volume = transfer_volume * (dilution_factor - 1)
        assert diluent_volume == 180.0
        _validate_volumes(
            transfer_volume=transfer_volume,
            diluent_volume=diluent_volume,
            dilution_factor=dilution_factor,
        )
