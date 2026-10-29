"""Unit tests for the shared greedy batch planner in ``compound_commands._helpers._multi_dispense``."""

from __future__ import annotations

from hamilton_venus.compound_commands._helpers._multi_dispense import plan_dispense_batches
from hamilton_venus.models.position import Position


def _row(*pairs: tuple[str, float]) -> list[tuple[Position, float]]:
    return [(Position(labware="Plate1", well=well), vol) for well, vol in pairs]


def _labels(batches: list[list[list[tuple[Position, float]]]]) -> list[list[list[str]]]:
    return [[[pos.well for pos, _ in row] for row in batch] for batch in batches]


class TestPlanDispenseBatchesCapacityOnly:
    def test_empty_input_returns_empty(self):
        assert plan_dispense_batches([], capacity=1000.0) == []

    def test_all_rows_fit_single_batch(self):
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0))]
        batches = plan_dispense_batches(rows, capacity=1000.0)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_flushes_when_next_row_exceeds_capacity(self):
        # capacity 250 fits 2 rows of 100 (=200); a third (=300) overflows.
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0))]
        batches = plan_dispense_batches(rows, capacity=250.0)
        assert _labels(batches) == [[["A1"], ["A2"]], [["A3"]]]

    def test_exact_capacity_boundary_included(self):
        # 100 + 100 == 200 exactly; both fit, third starts a new batch.
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0))]
        batches = plan_dispense_batches(rows, capacity=200.0)
        assert _labels(batches) == [[["A1"], ["A2"]], [["A3"]]]

    def test_single_oversized_row_still_placed(self):
        rows = [_row(("A1", 5000.0))]
        batches = plan_dispense_batches(rows, capacity=1000.0)
        assert _labels(batches) == [[["A1"]]]

    def test_row_volume_uses_max_across_channels(self):
        # Variable-volume row: per-channel volume is the max (150), not the sum.
        rows = [_row(("A1", 100.0), ("B1", 150.0)), _row(("A2", 100.0), ("B2", 100.0))]
        # capacity 200 fits row1 (150) but not row1+row2 (150+100=250).
        batches = plan_dispense_batches(rows, capacity=200.0)
        assert _labels(batches) == [[["A1", "B1"]], [["A2", "B2"]]]


class TestPlanDispenseBatchesWithBudget:
    def test_budget_none_is_capacity_only(self):
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0))]
        assert plan_dispense_batches(rows, capacity=1000.0, budget=None) == plan_dispense_batches(rows, capacity=1000.0)

    def test_budget_bounds_batch_below_capacity(self):
        # capacity 1000 would fit all three, but budget 150 flushes after each row.
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0))]
        batches = plan_dispense_batches(rows, capacity=1000.0, budget=150.0)
        assert _labels(batches) == [[["A1"]], [["A2"]], [["A3"]]]

    def test_tighter_of_capacity_and_budget_wins(self):
        rows = [_row(("A1", 100.0)), _row(("A2", 100.0)), _row(("A3", 100.0)), _row(("A4", 100.0))]
        # capacity 250 -> 2 rows; budget 350 -> 3 rows; the tighter (capacity) applies.
        batches = plan_dispense_batches(rows, capacity=250.0, budget=350.0)
        assert _labels(batches) == [[["A1"], ["A2"]], [["A3"], ["A4"]]]

    def test_single_row_exceeding_budget_still_placed(self):
        rows = [_row(("A1", 500.0))]
        batches = plan_dispense_batches(rows, capacity=1000.0, budget=100.0)
        assert _labels(batches) == [[["A1"]]]
