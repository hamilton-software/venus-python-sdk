"""Tests for hamilton_venus_mcp.docs_catalog's reflection-based index of docs/*.md.

Mirrors labware_catalog.py's pattern: read the live docs/ folder rather than a
hand-maintained list, so a new file added under docs/ is picked up automatically on the
next server start with no code change here.
"""

from __future__ import annotations

import unittest

import hamilton_venus_mcp.server as srv
from hamilton_venus_mcp.docs_catalog import DOCS_BY_PATH, DOCS_CATALOG, DocEntry, read_doc_text


class DocsCatalogBuildTests(unittest.TestCase):
    def test_catalog_is_nonempty(self):
        self.assertGreater(len(DOCS_CATALOG), 0)

    def test_every_entry_is_a_doc_entry(self):
        for entry in DOCS_CATALOG:
            self.assertIsInstance(entry, DocEntry)

    def test_known_doc_present_with_expected_fields(self):
        entry = DOCS_BY_PATH.get("authentication.md")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.uri, "docs://hamilton-venus/authentication.md")
        self.assertTrue(entry.path.is_file())

    def test_nested_doc_uses_a_posix_style_relative_path(self):
        # examples/*.md exercises the rglob("*.md") + relative_path.as_posix() path, not
        # just the flat top-level docs/*.md case.
        nested = [p for p in DOCS_BY_PATH if "/" in p]
        self.assertTrue(nested, "expected at least one doc under a docs/ subdirectory")
        for rel in nested:
            self.assertNotIn("\\", rel, msg=f"{rel!r} should use forward slashes even on Windows")

    def test_every_entry_s_file_actually_exists_and_is_readable(self):
        for entry in DOCS_CATALOG:
            with self.subTest(doc=entry.relative_path):
                self.assertTrue(entry.path.is_file())
                self.assertGreater(len(read_doc_text(entry.path)), 0)

    def test_titles_are_pulled_from_each_doc_s_own_heading_not_the_filename(self):
        entry = DOCS_BY_PATH.get("authentication.md")
        self.assertIsNotNone(entry)
        self.assertNotEqual(entry.title, "authentication.md")
        self.assertNotIn("#", entry.title)

    def test_no_duplicate_uris(self):
        uris = [entry.uri for entry in DOCS_CATALOG]
        self.assertEqual(len(uris), len(set(uris)))

    def test_by_path_index_matches_the_catalog(self):
        self.assertEqual(len(DOCS_BY_PATH), len(DOCS_CATALOG))
        for entry in DOCS_CATALOG:
            self.assertIs(DOCS_BY_PATH[entry.relative_path], entry)


class ReadDocTextEncodingTests(unittest.TestCase):
    def test_falls_back_to_cp1252_for_a_non_utf8_byte(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.md"
            # 0x97 is cp1252's em dash -- not valid standalone UTF-8.
            path.write_bytes(b"# Title\n\nSome text \x97 with a smart dash.\n")
            text = read_doc_text(path)
            self.assertIn("Title", text)
            self.assertIn("—", text)  # cp1252 0x97 decodes to U+2014 EM DASH


class ListReadSdkDocsToolTests(unittest.TestCase):
    """list_sdk_docs/read_sdk_doc are server.py tools -- thin wrappers over DOCS_CATALOG,
    exercised the same way an MCP client's tool-call dispatch would (see
    test_server_instrument_selection.py's module docstring for why this call style works).
    """

    def test_list_sdk_docs_returns_every_catalog_entry_with_no_filter(self):
        results = srv.list_sdk_docs()
        self.assertEqual(len(results), len(DOCS_CATALOG))
        self.assertEqual({r["relative_path"] for r in results}, set(DOCS_BY_PATH))

    def test_list_sdk_docs_search_filters_case_insensitively_on_path_or_title(self):
        results = srv.list_sdk_docs(search="AUTHENTICATION")
        self.assertTrue(any(r["relative_path"] == "authentication.md" for r in results))

    def test_read_sdk_doc_returns_the_full_file_text(self):
        entry = DOCS_BY_PATH["authentication.md"]
        text = srv.read_sdk_doc("authentication.md")
        self.assertEqual(text, read_doc_text(entry.path))

    def test_read_sdk_doc_rejects_an_unknown_path(self):
        with self.assertRaises(ValueError):
            srv.read_sdk_doc("does-not-exist.md")


class DocResourceRegistrationTests(unittest.IsolatedAsyncioTestCase):
    """Every DOCS_CATALOG entry got a real, working @mcp.resource -- not just a catalog
    entry with nothing wired up to serve it.
    """

    async def test_every_catalog_entry_is_registered_as_a_readable_resource(self):
        registered = {str(r.uri) for r in await srv.mcp.list_resources()}
        for entry in DOCS_CATALOG:
            with self.subTest(doc=entry.relative_path):
                self.assertIn(entry.uri, registered)

    async def test_reading_a_doc_resource_returns_its_file_content(self):
        entry = DOCS_BY_PATH["authentication.md"]
        result = await srv.mcp.read_resource(entry.uri)
        contents = list(result)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].content, read_doc_text(entry.path))


if __name__ == "__main__":
    unittest.main()
