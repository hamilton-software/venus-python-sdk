"""Tests for script_runs.consumables_from_summary.usage_from_summary."""

from __future__ import annotations

import unittest

from hamilton_venus_mcp.script_runs.consumables_from_summary import usage_from_summary


class UsageFromSummaryTests(unittest.TestCase):
    def test_empty_summary_is_no_usage(self):
        self.assertEqual(usage_from_summary({}), [])

    def test_tips_by_type(self):
        summary = {"tips_by_type": [{"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_50ul", "count": 40}]}
        (row,) = usage_from_summary(summary)
        self.assertEqual((row.kind, row.item_key, row.quantity, row.unit), ("tip", "Tip_Rack_50ul", 40.0, "tips"))
        self.assertEqual(row.source, "tip_rack")

    def test_multiple_tip_types(self):
        summary = {
            "tips_by_type": [
                {"kind": "tip_rack", "tip_type": "A", "count": 8},
                {"kind": "tip_box", "tip_type": "B", "count": 16},
            ]
        }
        rows = usage_from_summary(summary)
        self.assertEqual({(r.item_key, r.quantity) for r in rows}, {("A", 8.0), ("B", 16.0)})

    def test_reservoir_volumes(self):
        summary = {"reservoir_volumes": [{"labware": "Trough1", "volume_ul": 1234.5}]}
        (row,) = usage_from_summary(summary)
        self.assertEqual((row.kind, row.item_key, row.quantity, row.unit), ("reagent", "Trough1", 1234.5, "uL"))

    def test_plates_and_lids(self):
        summary = {
            "plates_by_type": [{"labware_definition": "Cos_96_Rd", "count": 2}],
            "lids_by_type": [{"labware_definition": "Cos_96_Lid", "count": 2}],
        }
        rows = usage_from_summary(summary)
        kinds = {r.kind for r in rows}
        self.assertEqual(kinds, {"plate", "lid"})
        plate = next(r for r in rows if r.kind == "plate")
        self.assertEqual((plate.item_key, plate.quantity, plate.unit), ("Cos_96_Rd", 2.0, "each"))

    def test_zero_and_missing_counts_are_dropped(self):
        summary = {
            "tips_by_type": [{"tip_type": "A", "count": 0}],
            "reservoir_volumes": [{"labware": "Trough1", "volume_ul": 0.0}],
            "plates_by_type": [{"labware_definition": "X"}],  # no "count" key at all
        }
        self.assertEqual(usage_from_summary(summary), [])

    def test_missing_fields_use_placeholders_not_crash(self):
        summary = {"tips_by_type": [{"count": 5}], "reservoir_volumes": [{"volume_ul": 10.0}]}
        rows = usage_from_summary(summary)
        self.assertEqual(rows[0].item_key, "(unknown tip type)")
        self.assertEqual(rows[1].item_key, "(unknown reservoir)")

    def test_full_summary_shape(self):
        summary = {
            "tips_by_type": [{"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_300ul", "count": 96}],
            "plates_by_type": [{"labware_definition": "Cos_96_DW_1mL", "count": 1}],
            "lids_by_type": [],
            "reservoir_volumes": [{"labware": "MastermixTubes", "volume_ul": 1920.0}],
        }
        rows = usage_from_summary(summary)
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
