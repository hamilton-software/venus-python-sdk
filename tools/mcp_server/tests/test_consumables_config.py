"""Tests for script_runs.consumables_config.ConsumablesConfigStore."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hamilton_venus_mcp.script_runs.consumables_config import ConsumablesConfigStore, reagent_key


class ConfigStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ConsumablesConfigStore(Path(self._tmp.name) / "config.json")


class KeyTests(unittest.TestCase):
    def test_pooled_reservoir_has_no_well_suffix(self):
        self.assertEqual(reagent_key("Trough1", "all"), "Trough1")
        self.assertEqual(reagent_key("Trough1", None), "Trough1")
        self.assertEqual(reagent_key("Trough1", ""), "Trough1")

    def test_per_well_key(self):
        self.assertEqual(reagent_key("Tubes", "1"), "Tubes@1")


class TipThresholdTests(ConfigStoreTestCase):
    def test_set_and_read_back(self):
        self.store.set_tip_threshold("P", 15)
        snap = self.store.snapshot()
        self.assertEqual(snap["tip_pools"]["P"]["low_threshold"], 15)

    def test_negative_threshold_rejected(self):
        with self.assertRaises(ValueError):
            self.store.set_tip_threshold("P", -1)

    def test_overwrite_replaces(self):
        self.store.set_tip_threshold("P", 10)
        self.store.set_tip_threshold("P", 20)
        self.assertEqual(self.store.snapshot()["tip_pools"]["P"]["low_threshold"], 20)

    def test_written_to_disk_and_reloadable(self):
        self.store.set_tip_threshold("P", 10)
        reopened = ConsumablesConfigStore(self.store._path)
        self.assertEqual(reopened.snapshot()["tip_pools"]["P"]["low_threshold"], 10)


class RegisterReagentTests(ConfigStoreTestCase):
    def test_register_pooled_reservoir(self):
        entry = self.store.register_reagent("Trough1", "all", label="Water", low_percent=0.2)
        self.assertEqual(entry.key, "Trough1")
        self.assertEqual(entry.label, "Water")
        self.assertEqual(entry.source, "manual")

    def test_capacity_is_optional_stored_and_kept_when_registering_again(self):
        self.assertIsNone(self.store.register_reagent("Trough1", "all").capacity_ul)
        entry = self.store.register_reagent("Trough1", "all", capacity_ul=60000.0)
        self.assertEqual(entry.capacity_ul, 60000.0)
        self.assertEqual(self.store.snapshot()["reagents"]["Trough1"]["capacity_ul"], 60000.0)
        again = self.store.register_reagent("Trough1", "all", low_percent=0.3)  # no capacity given: keep it
        self.assertEqual(again.capacity_ul, 60000.0)

    def test_bad_capacity_rejected(self):
        for bad in (0, -5.0):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.register_reagent("T", "1", capacity_ul=bad)

    def test_register_per_well(self):
        entry = self.store.register_reagent("Tubes", "1", label="Mastermix", lot="LOT-42")
        self.assertEqual(entry.key, "Tubes@1")
        self.assertEqual(entry.lot, "LOT-42")

    def test_bad_percent_rejected(self):
        for bad in (-0.1, 1.1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.register_reagent("T", "1", low_percent=bad)

    def test_default_label_is_the_key(self):
        entry = self.store.register_reagent("Trough1", "all")
        self.assertEqual(entry.label, "Trough1")

    def test_re_registering_preserves_created_at(self):
        first = self.store.register_reagent("Trough1", "all")
        second = self.store.register_reagent("Trough1", "all", label="Renamed")
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(second.label, "Renamed")

    def test_remove(self):
        self.store.register_reagent("Trough1", "all")
        self.assertTrue(self.store.remove_reagent("Trough1"))
        self.assertFalse(self.store.remove_reagent("Trough1"))
        self.assertEqual(self.store.snapshot()["reagents"], {})


class AutoDiscoveredReagentTests(ConfigStoreTestCase):
    def test_auto_discovery_inserts_once(self):
        entry = self.store.record_auto_discovered_reagent("Trough1", "Trough1", "all")
        self.assertEqual(entry.source, "auto")
        self.assertEqual(self.store.snapshot()["reagents"]["Trough1"]["source"], "auto")

    def test_auto_discovery_never_downgrades_a_manual_entry(self):
        self.store.register_reagent("Trough1", "all", label="Manually Set")
        entry = self.store.record_auto_discovered_reagent("Trough1", "Trough1", "all")
        self.assertEqual(entry.label, "Manually Set")
        self.assertEqual(entry.source, "manual")

    def test_auto_discovery_does_not_overwrite_a_second_time(self):
        self.store.record_auto_discovered_reagent("Trough1", "Trough1", "all")
        self.store.set_tip_threshold("noop", 1)  # unrelated write, just to touch the file
        again = self.store.record_auto_discovered_reagent("Trough1", "Trough1", "all")
        self.assertEqual(again.source, "auto")


class CorruptFileTests(ConfigStoreTestCase):
    def test_corrupt_file_reads_as_empty(self):
        self.store._path.parent.mkdir(parents=True, exist_ok=True)
        self.store._path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.snapshot(), {"tip_pools": {}, "reagents": {}})
        self.store.set_tip_threshold("P", 5)  # still writable afterward
        self.assertEqual(self.store.snapshot()["tip_pools"]["P"]["low_threshold"], 5)


if __name__ == "__main__":
    unittest.main()
