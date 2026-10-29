from __future__ import annotations

import json
import logging
from pathlib import Path

from hamilton_venus.setup_tools import version_checker
from hamilton_venus.setup_tools.version_checker import PrerequisiteVersionChecker, warn_if_outdated

MANIFEST_JSON = {
    "format_version": "1.0",
    "prerequisites": [
        {
            "name": "hslhttp",
            "display_name": "Hamilton HSLHttp Library",
            "required_version": "2.9",
            "installer_pattern": r"^Hamilton_HSLHttp_v([0-9][0-9.]*)\.exe$",
            "registry_name_pattern": "HSLHttp",
        }
    ],
}


def _write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST_JSON), encoding="utf-8")
    return manifest_path


def _patch_registry(monkeypatch, version: str | None) -> None:
    entries = [] if version is None else [("Hamilton HSLHttp Library", version, r"HKLM\HSLHttp")]
    monkeypatch.setattr(
        "hamilton_venus.setup_tools.version_detection.iter_uninstall_entries",
        lambda: entries,
    )


def test_checker_reports_outdated_install(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    report = checker.check()

    assert report.any_outdated is True
    assert checker.outdated_messages() == ["Hamilton HSLHttp Library: installed 2.8, update to 2.9"]


def test_checker_reports_up_to_date_install(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.9")
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    assert checker.check().any_outdated is False
    assert checker.outdated_messages() == []


def test_checker_caches_report_until_refresh(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    first = checker.check()
    assert checker.check() is first

    _patch_registry(monkeypatch, "2.9")
    refreshed = checker.check(refresh=True)

    assert refreshed is not first
    assert refreshed.any_outdated is False


def test_checker_json_output_is_valid(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    payload = json.loads(checker.as_json())

    assert payload["any_outdated"] is True
    assert payload["results"][0]["name"] == "hslhttp"


def test_manifest_drift_flags_missing_installer(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.9")
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    assert checker.manifest_drift() == ["Hamilton HSLHttp Library: no bundled installer matches the manifest pattern"]


def test_manifest_drift_flags_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.9")
    (tmp_path / "Hamilton_HSLHttp_v3.0.exe").touch()
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    assert checker.manifest_drift() == ["Hamilton HSLHttp Library: manifest requires 2.9 but bundled installer is 3.0"]


def test_manifest_drift_is_empty_when_aligned(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.9")
    (tmp_path / "Hamilton_HSLHttp_v2.9.exe").touch()
    checker = PrerequisiteVersionChecker(tmp_path, _write_manifest(tmp_path))

    assert checker.manifest_drift() == []


def test_warn_if_outdated_logs_each_outdated_prerequisite(tmp_path: Path, monkeypatch, caplog) -> None:
    _patch_registry(monkeypatch, "2.8")
    manifest_path = _write_manifest(tmp_path)

    with caplog.at_level(logging.WARNING, logger="venus_prereq_versions"):
        report = warn_if_outdated(tmp_path, manifest_path)

    assert report is not None and report.any_outdated
    assert "Hamilton HSLHttp Library: installed 2.8, update to 2.9" in caplog.text


def test_warn_if_outdated_returns_none_without_manifest(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")

    assert warn_if_outdated(tmp_path, tmp_path / "absent.json") is None


def test_warn_if_outdated_returns_none_for_invalid_manifest(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    broken = tmp_path / "manifest.json"
    broken.write_text("{oops", encoding="utf-8")

    assert warn_if_outdated(tmp_path, broken) is None


def test_shipped_manifest_matches_bundled_installers() -> None:
    sdk_root = Path(version_checker.__file__).resolve().parents[3]
    prereqs_path = sdk_root / "prerequisites"
    manifest_path = prereqs_path / "manifest.json"
    if not manifest_path.exists():
        return

    checker = PrerequisiteVersionChecker(prereqs_path, manifest_path)

    assert checker.manifest_drift() == []
