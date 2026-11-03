"""Unit tests for spoke_store.py: the JSON persistence layer that lets add_spoke/
remove_spoke survive a hub restart (see spokes.py's SpokeGroup._save)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamilton_venus_mcp_hub import spoke_store


class DefaultSpokesFileTests(unittest.TestCase):
    def test_honors_the_env_var_override(self):
        with patch.dict(os.environ, {spoke_store.SPOKES_FILE_ENV: r"C:\custom\path\spokes.json"}):
            self.assertEqual(spoke_store.default_spokes_file(), Path(r"C:\custom\path\spokes.json"))

    def test_falls_back_to_programdata(self):
        with patch.dict(os.environ, {spoke_store.SPOKES_FILE_ENV: "", "PROGRAMDATA": r"C:\ProgramData"}):
            self.assertEqual(
                spoke_store.default_spokes_file(), Path(r"C:\ProgramData") / "Hamilton" / "mcp_hub" / "spokes.json"
            )


class LoadTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(spoke_store.load(Path(tmp) / "nonexistent.json"), [])

    def test_malformed_json_returns_empty_list_not_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spokes.json"
            path.write_text("{ this is not valid json", encoding="utf-8")
            self.assertEqual(spoke_store.load(path), [])

    def test_wrong_shape_returns_empty_list_not_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spokes.json"
            path.write_text('{"not": "a list"}', encoding="utf-8")
            self.assertEqual(spoke_store.load(path), [])


class SaveLoadRoundTripTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "spokes.json"
            spokes = [{"id": "star1", "url": "http://192.168.1.10:8000/mcp"}, {"id": "star2", "url": "http://192.168.1.11:8000/mcp"}]
            spoke_store.save(spokes, path)
            self.assertEqual(spoke_store.load(path), spokes)

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "c" / "spokes.json"
            spoke_store.save([], path)
            self.assertTrue(path.is_file())

    def test_save_overwrites_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spokes.json"
            spoke_store.save([{"id": "a", "url": "http://a"}], path)
            spoke_store.save([{"id": "b", "url": "http://b"}], path)
            self.assertEqual(spoke_store.load(path), [{"id": "b", "url": "http://b"}])

    def test_save_is_atomic_no_leftover_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spokes.json"
            spoke_store.save([{"id": "a", "url": "http://a"}], path)
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_saved_file_is_pretty_printed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spokes.json"
            spoke_store.save([{"id": "a", "url": "http://a"}], path)
            raw = path.read_text(encoding="utf-8")
            self.assertEqual(json.loads(raw), [{"id": "a", "url": "http://a"}])
            self.assertIn("\n", raw)  # indent=2 -- not a single minified line


if __name__ == "__main__":
    unittest.main()
