"""Tests for script_runs.consumables_ledger: idempotent run recording, usage reports, levels/
thresholds, and events -- the "track all consumables over time" store."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hamilton_venus_mcp.script_runs.consumables_ledger import ConsumablesLedger, RunRecord, UsageRow


def run(run_id, *, script="a.py", simulate=False, status="completed", started="2026-09-01T10:00:00+00:00", ended="2026-09-01T10:05:00+00:00", partial=False):
    return RunRecord(run_id=run_id, script=script, sha256="abc", started_at=started, ended_at=ended, status=status, simulate=simulate, partial=partial)


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "ledger.sqlite")
        self.addCleanup(self.ledger.close)


class RecordRunTests(LedgerTestCase):
    def test_records_run_and_usage(self):
        rows = [UsageRow(kind="tip", item_key="Tip_Rack_50ul", item_label="50uL", quantity=8, unit="tips")]
        self.assertTrue(self.ledger.record_run(run("r1"), rows))
        self.assertIsNotNone(self.ledger.get_run("r1"))
        report = self.ledger.usage_report(kind="tip")
        self.assertEqual(report[0]["total_quantity"], 8)

    def test_is_idempotent_by_run_id(self):
        rows = [UsageRow(kind="tip", item_key="X", item_label="X", quantity=8, unit="tips")]
        self.assertTrue(self.ledger.record_run(run("r1"), rows))
        self.assertFalse(self.ledger.record_run(run("r1"), rows))  # second attempt: no-op
        report = self.ledger.usage_report(kind="tip")
        self.assertEqual(report[0]["total_quantity"], 8)  # not 16

    def test_has_run(self):
        self.assertFalse(self.ledger.has_run("r1"))
        self.ledger.record_run(run("r1"), [])
        self.assertTrue(self.ledger.has_run("r1"))

    def test_levels_are_recorded_alongside_the_run(self):
        self.ledger.record_run(run("r1"), [], levels=[{"kind": "tip", "item_key": "P", "level": 40, "capacity": 96, "source": "run_end"}])
        levels = self.ledger.current_levels(kind="tip")
        self.assertEqual(levels[0]["level"], 40)
        self.assertEqual(levels[0]["capacity"], 96)

    def test_a_run_with_no_usage_is_still_recorded(self):
        self.assertTrue(self.ledger.record_run(run("r1"), []))
        self.assertEqual(self.ledger.usage_report(), [])


class SimulateFilterTests(LedgerTestCase):
    def test_simulated_usage_excluded_by_default(self):
        self.ledger.record_run(run("sim1", simulate=True), [UsageRow(kind="tip", item_key="X", item_label="X", quantity=8, unit="tips")])
        self.assertEqual(self.ledger.usage_report(kind="tip"), [])
        self.assertEqual(self.ledger.usage_report(kind="tip", simulate=True)[0]["total_quantity"], 8)

    def test_real_and_simulated_runs_stay_separate(self):
        self.ledger.record_run(run("real1", simulate=False), [UsageRow(kind="tip", item_key="X", item_label="X", quantity=5, unit="tips")])
        self.ledger.record_run(run("sim1", simulate=True), [UsageRow(kind="tip", item_key="X", item_label="X", quantity=100, unit="tips")])
        self.assertEqual(self.ledger.usage_report(kind="tip")[0]["total_quantity"], 5)


class SimulatedLevelsTests(LedgerTestCase):
    def test_simulated_run_levels_are_ignored_even_if_already_stored(self):
        lvl = lambda v: [{"kind": "tip", "item_key": "P", "level": v, "capacity": 96, "source": "run_end"}]
        self.ledger.record_run(run("real1"), [], levels=lvl(90))
        # Databases written before simulated levels were dropped at write time may hold rows like this.
        self.ledger.record_run(run("sim1", simulate=True, started="2026-09-02T10:00:00+00:00"), [], levels=lvl(10))
        (row,) = self.ledger.current_levels(kind="tip")
        self.assertEqual(row["level"], 90)

    def test_only_simulated_levels_means_no_level_at_all(self):
        self.ledger.record_run(run("sim1", simulate=True), [], levels=[{"kind": "tip", "item_key": "P", "level": 10, "capacity": 96, "source": "run_end"}])
        self.assertEqual(self.ledger.current_levels(), [])


class UsageReportGroupingTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.ledger.record_run(
            run("r1", script="a.py", started="2026-09-01T10:00:00+00:00", ended="2026-09-01T10:05:00+00:00"),
            [UsageRow(kind="tip", item_key="T50", item_label="T50", quantity=8, unit="tips")],
        )
        self.ledger.record_run(
            run("r2", script="b.py", started="2026-09-02T10:00:00+00:00", ended="2026-09-02T10:05:00+00:00"),
            [UsageRow(kind="tip", item_key="T50", item_label="T50", quantity=16, unit="tips")],
        )

    def test_group_by_item_sums_across_runs(self):
        report = self.ledger.usage_report(kind="tip", group_by="item")
        self.assertEqual(report[0]["total_quantity"], 24)

    def test_group_by_day_splits_per_day(self):
        report = self.ledger.usage_report(kind="tip", group_by="day")
        by_day = {r["day"]: r["total_quantity"] for r in report}
        self.assertEqual(by_day, {"2026-09-01": 8, "2026-09-02": 16})

    def test_group_by_run(self):
        report = self.ledger.usage_report(kind="tip", group_by="run")
        by_run = {r["run_id"]: r["total_quantity"] for r in report}
        self.assertEqual(by_run, {"r1": 8, "r2": 16})

    def test_group_by_script(self):
        report = self.ledger.usage_report(kind="tip", group_by="script")
        by_script = {r["script"]: r["total_quantity"] for r in report}
        self.assertEqual(by_script, {"a.py": 8, "b.py": 16})

    def test_period_filter(self):
        report = self.ledger.usage_report(kind="tip", start="2026-09-02T00:00:00+00:00", group_by="item")
        self.assertEqual(report[0]["total_quantity"], 16)
        report = self.ledger.usage_report(kind="tip", end="2026-09-02T00:00:00+00:00", group_by="item")
        self.assertEqual(report[0]["total_quantity"], 8)

    def test_script_filter(self):
        report = self.ledger.usage_report(kind="tip", script="a.py", group_by="item")
        self.assertEqual(report[0]["total_quantity"], 8)

    def test_bad_group_by_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.usage_report(group_by="nonsense")


class LevelsAndThresholdTests(LedgerTestCase):
    def test_latest_level_wins(self):
        self.ledger.record_level("tip", "P", 88, 96, source="run_start")
        self.ledger.record_level("tip", "P", 40, 96, source="run_end")
        levels = self.ledger.current_levels(kind="tip")
        self.assertEqual(levels[0]["level"], 40)

    def test_percent_and_low_flag_from_capacity(self):
        # Reagent (and any non-tip kind) thresholds compare against percent-of-capacity.
        self.ledger.set_config("reagent", "Trough1", low_threshold=0.10)
        self.ledger.record_level("reagent", "Trough1", 5, 96, source="run_end")
        (row,) = self.ledger.current_levels(kind="reagent")
        self.assertAlmostEqual(row["percent"], 5 / 96, places=4)
        self.assertTrue(row["low"])

    def test_not_low_above_threshold(self):
        self.ledger.set_config("reagent", "Trough1", low_threshold=0.10)
        self.ledger.record_level("reagent", "Trough1", 90, 96, source="run_end")
        (row,) = self.ledger.current_levels(kind="reagent")
        self.assertFalse(row["low"])

    def test_low_items_filters_to_only_low(self):
        self.ledger.set_config("reagent", "Low", low_threshold=0.50)
        self.ledger.set_config("reagent", "High", low_threshold=0.10)
        self.ledger.record_level("reagent", "Low", 5, 96, source="run_end")
        self.ledger.record_level("reagent", "High", 90, 96, source="run_end")
        low = self.ledger.low_items(kind="reagent")
        self.assertEqual([r["item_key"] for r in low], ["Low"])

    def test_tip_threshold_is_an_absolute_remaining_count_not_a_percent(self):
        # Unlike reagent/other kinds, a tip pool's low_threshold is an absolute remaining-tip
        # count (matches set_tip_threshold and the live in-run warning in child_bootstrap.py),
        # even when capacity is known -- a rack at 50% full should not read as "low" against a
        # threshold that means "warn once 10 tips are left".
        self.ledger.set_config("tip", "P", low_threshold=10)
        self.ledger.record_level("tip", "P", 48, 96, source="run_end")  # 50% full, well above 10 tips
        (row,) = self.ledger.current_levels(kind="tip")
        self.assertAlmostEqual(row["percent"], 0.5)
        self.assertFalse(row["low"])
        self.ledger.record_level("tip", "P", 8, 96, source="run_end")
        (row,) = self.ledger.current_levels(kind="tip")
        self.assertTrue(row["low"])

    def test_no_capacity_falls_back_to_absolute_threshold(self):
        self.ledger.set_config("tip", "P", low_threshold=10)
        self.ledger.record_level("tip", "P", 5, None, source="run_end")
        (row,) = self.ledger.current_levels(kind="tip")
        self.assertIsNone(row["percent"])
        self.assertTrue(row["low"])

    def test_config_upsert_preserves_unset_fields(self):
        self.ledger.set_config("tip", "P", label="Pool P", low_threshold=0.1)
        self.ledger.set_config("tip", "P", unit="tips")  # no label/threshold given this time
        self.ledger.record_level("tip", "P", 5, 96, source="run_end")
        (row,) = self.ledger.current_levels(kind="tip")
        self.assertEqual(row["label"], "Pool P")
        self.assertEqual(row["low_threshold"], 0.1)
        self.assertEqual(row["unit"], "tips")


class EventTests(LedgerTestCase):
    def test_add_and_list_events(self):
        self.ledger.add_event("tip", "P", "reload", amount=96, operator="Sam")
        events = self.ledger.events(kind="tip")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "reload")
        self.assertEqual(events[0]["operator"], "Sam")

    def test_events_filter_by_item(self):
        self.ledger.add_event("tip", "P1", "reload")
        self.ledger.add_event("tip", "P2", "reload")
        self.assertEqual(len(self.ledger.events(item_key="P1")), 1)

    def test_events_most_recent_first(self):
        self.ledger.add_event("tip", "P", "reload", ts="2026-09-01T00:00:00+00:00")
        self.ledger.add_event("tip", "P", "counter_reset", ts="2026-09-02T00:00:00+00:00")
        events = self.ledger.events(item_key="P")
        self.assertEqual([e["type"] for e in events], ["counter_reset", "reload"])


class ConcurrencyTests(LedgerTestCase):
    def test_reopening_the_same_file_sees_committed_data(self):
        self.ledger.record_run(run("r1"), [UsageRow(kind="tip", item_key="X", item_label="X", quantity=8, unit="tips")])
        second = ConsumablesLedger(self.ledger._path)
        try:
            self.assertTrue(second.has_run("r1"))
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()
