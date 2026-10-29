"""Unit tests for the 32-bit Python runtime installer (setup_tools.py32_runtime).

No test touches the network: fake artifacts are built in tmp_path and passed via
``artifacts=`` together with ``source_dir=``, so ``_download`` is never reached
except in the tests that exercise it directly.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from hamilton_venus.setup_tools import py32_runtime

_ORIGINAL_PTH = "python312.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"
_EXPECTED_PTH = "python312.zip\n.\n\n# Uncomment to run site.main() automatically\nimport site\nLib\\site-packages\n"


def _make_fakes(source_dir: Path) -> tuple[py32_runtime.Artifact, py32_runtime.Artifact]:
    """Write fake embed/wheel zips into *source_dir*; return artifacts with their hashes."""
    source_dir.mkdir(parents=True)
    embed_path = source_dir / "fake-embed.zip"
    wheel_path = source_dir / "fake-wheel.zip"
    with zipfile.ZipFile(embed_path, "w") as zf:
        zf.writestr("python.exe", b"MZ-fake-python")
        zf.writestr("python312._pth", _ORIGINAL_PTH)
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("pywin32.pth", b"# fake pywin32 bootstrap\n")
        zf.writestr("win32com/__init__.py", b"")
    embed = py32_runtime.Artifact(filename=embed_path.name, url="", sha256=py32_runtime._sha256(embed_path))
    wheel = py32_runtime.Artifact(filename=wheel_path.name, url="", sha256=py32_runtime._sha256(wheel_path))
    return embed, wheel


class TestInstallPy32Runtime:
    def test_successful_install(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)
        monkeypatch.setattr(py32_runtime, "verify_py32_runtime", lambda exe: (True, "ok"))

        ok, msg = py32_runtime.install_py32_runtime(target, source_dir=source, artifacts=(embed, wheel))

        assert ok is True
        assert (target / "python.exe").is_file()
        assert (target / "python312._pth").read_text() == _EXPECTED_PTH
        assert (target / "Lib" / "site-packages" / "pywin32.pth").is_file()
        assert (target / "Lib" / "site-packages" / "win32com" / "__init__.py").is_file()
        assert not (tmp_path / "py32.staging").exists()
        assert "installed" in msg

    def test_hash_mismatch_reports_filename(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        (source / embed.filename).write_bytes(b"corrupted")
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)

        ok, msg = py32_runtime.install_py32_runtime(target, source_dir=source, artifacts=(embed, wheel))

        assert ok is False
        assert embed.filename in msg
        assert not target.exists()

    def test_missing_source_file_names_expected_filename(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        (source / wheel.filename).unlink()
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)

        ok, msg = py32_runtime.install_py32_runtime(target, source_dir=source, artifacts=(embed, wheel))

        assert ok is False
        assert wheel.filename in msg
        assert not target.exists()

    def test_zip_slip_member_rejected_and_nothing_written(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        with zipfile.ZipFile(source / wheel.filename, "a") as zf:
            zf.writestr("../evil.txt", b"boom")
        wheel = py32_runtime.Artifact(
            filename=wheel.filename,
            url="",
            sha256=py32_runtime._sha256(source / wheel.filename),
        )
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)

        ok, _ = py32_runtime.install_py32_runtime(target, source_dir=source, artifacts=(embed, wheel))

        assert ok is False
        assert not target.exists()
        assert not (tmp_path / "evil.txt").exists()
        assert not (tmp_path / "py32.staging").exists()

    def test_already_installed_and_verified_skips_fetch(self, monkeypatch, tmp_path):
        target = tmp_path / "py32"
        target.mkdir()
        (target / "python.exe").write_bytes(b"old")
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)
        monkeypatch.setattr(py32_runtime, "verify_py32_runtime", lambda exe: (True, "ok"))

        ok, msg = py32_runtime.install_py32_runtime(target, source_dir=empty)

        assert ok is True
        assert "already installed" in msg
        assert (target / "python.exe").read_bytes() == b"old"

    def test_force_replaces_existing_target(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        target = tmp_path / "py32"
        target.mkdir()
        (target / "marker.txt").write_text("old marker")
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)
        monkeypatch.setattr(py32_runtime, "verify_py32_runtime", lambda exe: (True, "ok"))

        ok, _ = py32_runtime.install_py32_runtime(target, source_dir=source, force=True, artifacts=(embed, wheel))

        assert ok is True
        assert not (target / "marker.txt").exists()
        assert (target / "python.exe").is_file()

    def test_dry_run_writes_nothing(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)

        ok, msg = py32_runtime.install_py32_runtime(target, source_dir=source, dry_run=True, artifacts=(embed, wheel))

        assert ok is True
        assert "[DRY-RUN]" in msg
        assert not target.exists()
        assert not (tmp_path / "py32.staging").exists()

    def test_non_windows_is_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: False)

        ok, msg = py32_runtime.install_py32_runtime(tmp_path / "py32")

        assert ok is False
        assert "skipped" in msg

    def test_download_used_when_no_source_dir(self, monkeypatch, tmp_path):
        source = tmp_path / "source"
        embed, wheel = _make_fakes(source)
        target = tmp_path / "py32"
        monkeypatch.setattr(py32_runtime, "_is_windows", lambda: True)
        monkeypatch.setattr(py32_runtime, "verify_py32_runtime", lambda exe: (True, "ok"))
        fetched: list[str] = []

        def fake_download(artifact, dest_dir, *, timeout: float = 60) -> Path:
            fetched.append(artifact.filename)
            path = dest_dir / artifact.filename
            import shutil

            shutil.copyfile(source / artifact.filename, path)
            return path

        monkeypatch.setattr(py32_runtime, "_download", fake_download)

        ok, _ = py32_runtime.install_py32_runtime(target, artifacts=(embed, wheel))

        assert ok is True
        assert fetched == [embed.filename, wheel.filename]
        assert (target / "python.exe").is_file()


class TestDownload:
    def test_urlerror_wrapped_in_py32_install_error(self, monkeypatch, tmp_path):
        def _raise(*_a: object, **_k: object) -> None:
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)

        with pytest.raises(py32_runtime.Py32InstallError, match="--py32-from"):
            py32_runtime._download(
                py32_runtime.Artifact(filename="x.zip", url="https://example.invalid/x.zip", sha256=""),
                tmp_path,
            )


class TestVerifyPy32Runtime:
    def test_ok_when_32bit_and_rc_zero(self, monkeypatch):
        class _Result:
            returncode = 0
            stdout = "True\n"
            stderr = ""

        monkeypatch.setattr(py32_runtime.subprocess, "run", lambda *_a, **_k: _Result())

        ok, msg = py32_runtime.verify_py32_runtime(Path("C:/py32/python.exe"))

        assert ok is True
        assert "verified" in msg

    def test_failure_reports_stderr_tail(self, monkeypatch):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'win32com'\n"

        monkeypatch.setattr(py32_runtime.subprocess, "run", lambda *_a, **_k: _Result())

        ok, msg = py32_runtime.verify_py32_runtime(Path("C:/py32/python.exe"))

        assert ok is False
        assert "win32com" in msg


class TestRemovePy32Runtime:
    def test_removes_existing_dir(self, tmp_path):
        target = tmp_path / "py32"
        target.mkdir()
        (target / "python.exe").write_bytes(b"x")

        assert py32_runtime.remove_py32_runtime(target) is True
        assert not target.exists()

    def test_absent_returns_false(self, tmp_path):
        assert py32_runtime.remove_py32_runtime(tmp_path / "py32") is False

    def test_dry_run_does_not_delete(self, tmp_path):
        target = tmp_path / "py32"
        target.mkdir()
        (target / "python.exe").write_bytes(b"x")

        assert py32_runtime.remove_py32_runtime(target, dry_run=True) is True
        assert (target / "python.exe").is_file()
