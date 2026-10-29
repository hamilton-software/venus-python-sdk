"""Unit tests for hamilton_venus._method_file_manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hamilton_venus._internal._method_file_manager import (
    MethodFileManager,
    _resolve_display_name,
    _sanitize_display_name,
)


class TestSanitizeDisplayName:
    def test_passthrough_simple_name(self):
        assert _sanitize_display_name("MyAssay") == "MyAssay"

    def test_replaces_special_characters(self):
        assert _sanitize_display_name("my/assay:v2") == "my_assay_v2"

    def test_strips_leading_trailing_underscores(self):
        assert _sanitize_display_name("__hello__") == "hello"

    def test_empty_string_returns_fallback(self):
        assert _sanitize_display_name("") == "VENUS_SDK_Session"

    def test_all_special_chars_returns_fallback(self):
        assert _sanitize_display_name("///") == "VENUS_SDK_Session"

    def test_preserves_spaces_hyphens_underscores(self):
        assert _sanitize_display_name("My Assay-Name_v1") == "My Assay-Name_v1"


class TestResolveDisplayName:
    def test_configured_name_used(self):
        assert _resolve_display_name("CustomName") == "CustomName"

    def test_configured_name_sanitized(self):
        assert _resolve_display_name("bad/name") == "bad_name"

    def test_falls_back_to_script_name(self):
        with patch("hamilton_venus._internal._method_file_manager.sys") as mock_sys:
            mock_sys.argv = ["/path/to/my_script.py"]
            assert _resolve_display_name("") == "my_script"

    def test_falls_back_to_session_when_no_argv(self):
        with patch("hamilton_venus._internal._method_file_manager.sys") as mock_sys:
            mock_sys.argv = []
            assert _resolve_display_name("") == "VENUS_SDK_Session"

    def test_falls_back_to_session_for_dash_c(self):
        with patch("hamilton_venus._internal._method_file_manager.sys") as mock_sys:
            mock_sys.argv = ["-c"]
            assert _resolve_display_name("") == "VENUS_SDK_Session"

    def test_sanitizes_script_name(self):
        with patch("hamilton_venus._internal._method_file_manager.sys") as mock_sys:
            mock_sys.argv = ["/path/to/weird:script.py"]
            assert _resolve_display_name("") == "weird_script"


class TestMethodFileManagerPrepare:
    def test_copies_hsl_and_stp(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        stp = tmp_path / "VENUS_SDK_Executor.stp"
        hsl.write_text("hsl content")
        stp.write_text("stp content")

        mgr = MethodFileManager()
        result = mgr.prepare(str(hsl), "MyAssay")

        expected_hsl = tmp_path / "MyAssay.hsl"
        expected_stp = tmp_path / "MyAssay.stp"
        assert result == str(expected_hsl)
        assert expected_hsl.read_text() == "hsl content"
        assert expected_stp.read_text() == "stp content"

    def test_copies_hsl_without_stp(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        result = mgr.prepare(str(hsl), "MyAssay")

        expected_hsl = tmp_path / "MyAssay.hsl"
        assert result == str(expected_hsl)
        assert expected_hsl.read_text() == "hsl content"
        assert not (tmp_path / "MyAssay.stp").exists()

    def test_raises_when_hsl_missing(self, tmp_path: Path):
        mgr = MethodFileManager()
        with pytest.raises(FileNotFoundError, match="Executor HSL file not found"):
            mgr.prepare(str(tmp_path / "missing.hsl"), "MyAssay")

    def test_uses_script_name_when_display_name_empty(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        with patch("hamilton_venus._internal._method_file_manager.sys") as mock_sys:
            mock_sys.argv = ["/path/to/run_assay.py"]
            result = mgr.prepare(str(hsl), "")

        assert result == str(tmp_path / "run_assay.hsl")

    def test_resolved_hsl_path_property(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        assert mgr.resolved_hsl_path is None
        mgr.prepare(str(hsl), "Test")
        assert mgr.resolved_hsl_path == str(tmp_path / "Test.hsl")

    def test_falls_back_to_original_on_permission_error(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        with patch(
            "hamilton_venus._internal._method_file_manager.shutil.copy2",
            side_effect=PermissionError("access denied"),
        ):
            result = mgr.prepare(str(hsl), "MyAssay")

        assert result == str(hsl)
        assert mgr.resolved_hsl_path == str(hsl)
        assert len(mgr._created_files) == 0


class TestMethodFileManagerCleanup:
    def test_removes_created_files(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        stp = tmp_path / "VENUS_SDK_Executor.stp"
        hsl.write_text("hsl content")
        stp.write_text("stp content")

        mgr = MethodFileManager()
        mgr.prepare(str(hsl), "MyAssay")
        assert (tmp_path / "MyAssay.hsl").exists()
        assert (tmp_path / "MyAssay.stp").exists()

        mgr.cleanup()
        assert not (tmp_path / "MyAssay.hsl").exists()
        assert not (tmp_path / "MyAssay.stp").exists()
        assert mgr.resolved_hsl_path is None

    def test_cleanup_idempotent(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        mgr.prepare(str(hsl), "MyAssay")
        mgr.cleanup()
        mgr.cleanup()

    def test_cleanup_when_files_already_deleted(self, tmp_path: Path):
        hsl = tmp_path / "VENUS_SDK_Executor.hsl"
        hsl.write_text("hsl content")

        mgr = MethodFileManager()
        mgr.prepare(str(hsl), "MyAssay")
        (tmp_path / "MyAssay.hsl").unlink()
        mgr.cleanup()

    def test_cleanup_noop_when_nothing_prepared(self):
        mgr = MethodFileManager()
        mgr.cleanup()
