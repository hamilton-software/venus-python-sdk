"""Tests for hamilton_venus_mcp.labware_catalog's reflection-based labware-type index.

Covers the scenario that motivated it: an agent with no local SDK access (e.g. behind
hamilton_venus_mcp_hub) had no way to look up labware type names/ids short of reading
hamilton_venus/catalog/labware.py directly -- this mirrors catalog.py's list_sdk_commands
pattern (read the live SDK install, never a hand-maintained list) for the labware catalog.
"""

from __future__ import annotations

import unittest

from hamilton_venus.catalog import LABWARE
from hamilton_venus_mcp.labware_catalog import LABWARE_CATALOG, LabwareEntry


class LabwareCatalogBuildTests(unittest.TestCase):
    def test_catalog_is_nonempty(self):
        self.assertGreater(len(LABWARE_CATALOG), 0)

    def test_every_entry_is_a_labware_entry(self):
        for entry in LABWARE_CATALOG:
            self.assertIsInstance(entry, LabwareEntry)

    def test_known_carrier_entry_present_with_expected_fields(self):
        matches = [e for e in LABWARE_CATALOG if e.name == "TIP_CAR_480BC"]
        self.assertEqual(len(matches), 1)
        entry = matches[0]
        self.assertEqual(entry.category, "CARRIER")
        self.assertEqual(entry.labware_id, "TIP_CAR_480BC")
        self.assertEqual(entry.access_path, "LABWARE.CARRIER.TIP_CAR_480BC")

    def test_every_labware_id_resolves_through_the_sdk_s_own_lookup(self):
        # Cross-check against LABWARE's own case-insensitive lookup (_CatalogNamespace)
        # rather than re-deriving expectations by hand -- this catalog should never
        # disagree with the SDK it reflects over.
        for entry in LABWARE_CATALOG:
            with self.subTest(name=entry.name):
                self.assertEqual(LABWARE[entry.labware_id], entry.labware_id)

    def test_categories_match_labware_s_own_top_level_namespaces(self):
        categories = {entry.category for entry in LABWARE_CATALOG}
        expected = {
            attr for attr in vars(type(LABWARE)) if attr.isupper() and not attr.startswith("_")
        }
        self.assertEqual(categories, expected)

    def test_no_duplicate_access_paths(self):
        access_paths = [entry.access_path for entry in LABWARE_CATALOG]
        self.assertEqual(len(access_paths), len(set(access_paths)))


class LabwareCatalogToolBehaviorTests(unittest.TestCase):
    """Mirrors list_sdk_commands/list_sdk_categories's filtering semantics, exercised
    directly against LABWARE_CATALOG the way server.py's search_labware/
    list_labware_categories tools filter it."""

    def test_category_filter_is_case_insensitive(self):
        lower = [e for e in LABWARE_CATALOG if e.category.lower() == "carrier"]
        self.assertTrue(lower)
        for entry in lower:
            self.assertEqual(entry.category, "CARRIER")

    def test_search_matches_name_or_labware_id_case_insensitively(self):
        hits = [e for e in LABWARE_CATALOG if "tip_car_480bc" in f"{e.name} {e.labware_id}".lower()]
        self.assertTrue(any(e.name == "TIP_CAR_480BC" for e in hits))


if __name__ == "__main__":
    unittest.main()
