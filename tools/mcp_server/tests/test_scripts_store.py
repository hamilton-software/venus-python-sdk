"""Tests for hamilton_venus_mcp.scripts_store: the controlled directory scripts run from."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hamilton_venus_mcp.scripts_store import (
    MAX_SCRIPT_BYTES,
    SCRIPTS_DIR_ENV,
    ScriptStore,
    ScriptStoreError,
    default_scripts_dir,
    sha256_of,
)


class ScriptStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "scripts"
        self.store = ScriptStore(self.root)


class NameTests(ScriptStoreTestCase):
    def test_accepts_ordinary_names(self):
        for name in ("run1.py", "Mastermix 384-well_v2.py", "a.b.py", "9lives.py"):
            with self.subTest(name=name):
                self.assertEqual(ScriptStore.validate_name(name), name)

    def test_rejects_paths_and_odd_names(self):
        bad = [
            "",
            "run.txt",
            "run",
            "../evil.py",
            "sub/evil.py",
            "sub\\evil.py",
            "C:\\evil.py",
            ".hidden.py",
            "-dash.py",
            "a..py",
            "con.py",
            "NUL.py",
            "COM1.py",
            "index.json",
            "x\x00.py",
        ]
        for name in bad:
            with self.subTest(name=name), self.assertRaises(ScriptStoreError):
                ScriptStore.validate_name(name)

    def test_rejects_non_strings(self):
        with self.assertRaises(ScriptStoreError):
            ScriptStore.validate_name(None)  # type: ignore[arg-type]

    def test_path_for_stays_inside_root(self):
        self.store.ensure()
        path = self.store.path_for("ok.py")
        self.assertEqual(path.parent, self.root.resolve())


class WriteReadTests(ScriptStoreTestCase):
    def test_write_then_read_roundtrip(self):
        self.store.write("a.py", "print('hi')\n")
        self.assertEqual(self.store.read_text("a.py"), "print('hi')\n")
        self.assertEqual(self.store.sha256("a.py"), sha256_of(b"print('hi')\n"))
        self.assertEqual(self.store.list_names(), ["a.py"])

    def test_write_creates_the_directory(self):
        self.assertFalse(self.root.exists())
        self.store.write("a.py", "x = 1\n")
        self.assertTrue(self.root.is_dir())

    def test_existing_script_needs_overwrite(self):
        self.store.write("a.py", "x = 1\n")
        with self.assertRaisesRegex(ScriptStoreError, "already exists"):
            self.store.write("a.py", "x = 2\n")
        self.assertEqual(self.store.read_text("a.py"), "x = 1\n")
        self.store.write("a.py", "x = 2\n", overwrite=True)
        self.assertEqual(self.store.read_text("a.py"), "x = 2\n")

    def test_size_limit(self):
        with self.assertRaisesRegex(ScriptStoreError, "limit"):
            self.store.write("big.py", "#" * (MAX_SCRIPT_BYTES + 1))
        self.assertFalse((self.root / "big.py").exists())

    def test_size_limit_counts_bytes_not_characters(self):
        with self.assertRaisesRegex(ScriptStoreError, "limit"):
            self.store.write("wide.py", "\u00e9" * (MAX_SCRIPT_BYTES // 2 + 1))

    def test_rejects_nul_and_non_text(self):
        with self.assertRaises(ScriptStoreError):
            self.store.write("a.py", "x = 1\x00\n")
        with self.assertRaises(ScriptStoreError):
            self.store.write("a.py", b"x = 1")  # type: ignore[arg-type]

    def test_no_temp_files_left_behind(self):
        self.store.write("a.py", "x = 1\n")
        leftovers = [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_reading_a_missing_script_fails_clearly(self):
        self.store.ensure()
        with self.assertRaisesRegex(ScriptStoreError, "No script named"):
            self.store.read_text("nope.py")

    def test_read_strips_a_utf8_bom(self):
        self.store.ensure()
        (self.root / "bom.py").write_bytes(b"\xef\xbb\xbfx = 1\n")
        self.assertEqual(self.store.read_text("bom.py"), "x = 1\n")

    def test_listing_ignores_non_script_files(self):
        self.store.write("a.py", "x = 1\n")
        (self.root / "notes.txt").write_text("hi")
        (self.root / ".runs").mkdir()
        self.assertEqual(self.store.list_names(), ["a.py"])

    def test_listing_an_absent_directory_is_empty(self):
        self.assertEqual(self.store.list(), [])


class SourceFileTests(ScriptStoreTestCase):
    def test_reads_a_py_file(self):
        src = Path(self._tmp.name) / "from_downloads.py"
        src.write_bytes(b"x = 1\n")  # bytes, so Windows newline translation cannot alter it
        name, text = self.store.read_source_file(str(src))
        self.assertEqual((name, text), ("from_downloads.py", "x = 1\n"))

    def test_refuses_anything_but_py(self):
        secret = Path(self._tmp.name) / "secrets.txt"
        secret.write_text("hunter2")
        with self.assertRaisesRegex(ScriptStoreError, r"\.py"):
            self.store.read_source_file(str(secret))

    def test_refuses_a_missing_file_and_a_directory(self):
        with self.assertRaisesRegex(ScriptStoreError, "No file"):
            self.store.read_source_file(str(Path(self._tmp.name) / "missing.py"))
        folder = Path(self._tmp.name) / "folder.py"
        folder.mkdir()
        with self.assertRaisesRegex(ScriptStoreError, "No file"):
            self.store.read_source_file(str(folder))

    def test_refuses_an_oversized_file(self):
        big = Path(self._tmp.name) / "big.py"
        big.write_bytes(b"#" * (MAX_SCRIPT_BYTES + 1))
        with self.assertRaisesRegex(ScriptStoreError, "limit"):
            self.store.read_source_file(str(big))

    def test_refuses_undecodable_text(self):
        bad = Path(self._tmp.name) / "bad.py"
        bad.write_bytes(b"\xff\xfe\x00 not utf8 \xc3\x28")
        with self.assertRaisesRegex(ScriptStoreError, "UTF-8"):
            self.store.read_source_file(str(bad))


class ValidationIndexTests(ScriptStoreTestCase):
    def _report(self, sha, ok=True, errors=(), warnings=()):
        return {"sha256": sha, "ok": ok, "errors": list(errors), "warnings": list(warnings)}

    def test_unvalidated_script_is_not_runnable(self):
        self.store.write("a.py", "x = 1\n")
        self.assertEqual(self.store.validation_status("a.py")["validated"], False)
        self.assertFalse(self.store.is_runnable("a.py"))

    def test_validated_ok_script_is_runnable(self):
        self.store.write("a.py", "x = 1\n")
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py")))
        status = self.store.validation_status("a.py")
        self.assertTrue(status["validation_ok"] and status["validation_current"])
        self.assertTrue(self.store.is_runnable("a.py"))

    def test_failed_validation_is_not_runnable(self):
        self.store.write("a.py", "x = 1\n")
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py"), ok=False, errors=[{}, {}]))
        self.assertFalse(self.store.is_runnable("a.py"))
        self.assertEqual(self.store.validation_status("a.py")["validation_error_count"], 2)

    def test_editing_a_script_after_validation_makes_it_stale(self):
        self.store.write("a.py", "x = 1\n")
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py")))
        (self.root / "a.py").write_text("x = 2\n")  # edited outside the store
        status = self.store.validation_status("a.py")
        self.assertFalse(status["validation_current"])
        self.assertFalse(self.store.is_runnable("a.py"))

    def test_overwriting_through_the_store_drops_the_validation(self):
        self.store.write("a.py", "x = 1\n")
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py")))
        self.store.write("a.py", "x = 2\n", overwrite=True)
        self.assertFalse(self.store.validation_status("a.py")["validated"])

    def test_a_corrupt_index_reads_as_empty(self):
        self.store.write("a.py", "x = 1\n")
        (self.root / "index.json").write_text("{not json")
        self.assertFalse(self.store.validation_status("a.py")["validated"])
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py")))
        self.assertTrue(self.store.is_runnable("a.py"))

    def test_listing_includes_validation_and_hash(self):
        self.store.write("a.py", "x = 1\n")
        self.store.record_validation("a.py", self._report(self.store.sha256("a.py"), warnings=[{}]))
        (entry,) = self.store.list()
        self.assertEqual(entry["name"], "a.py")
        self.assertEqual(entry["sha256"], sha256_of(b"x = 1\n"))
        self.assertTrue(entry["validation_ok"])
        self.assertEqual(entry["validation_warning_count"], 1)


class DefaultDirectoryTests(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {SCRIPTS_DIR_ENV: r"D:\somewhere\scripts"}):
            self.assertEqual(default_scripts_dir(), Path(r"D:\somewhere\scripts"))

    def test_default_sits_beside_the_sdk_src_folder(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SCRIPTS_DIR_ENV, None)
            path = default_scripts_dir()
        self.assertEqual(path.name, "mcp_scripts")


if __name__ == "__main__":
    unittest.main()
