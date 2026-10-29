from __future__ import annotations

from pathlib import Path

import pytest

from hamilton_venus.setup_tools import version_detection
from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteInfo, PrerequisiteManifest
from hamilton_venus.setup_tools.version_detection import VersionSource

HSLHTTP = PrerequisiteInfo(
    name="hslhttp",
    display_name="Hamilton HSLHttp Library",
    required_version="2.9",
    installer_pattern=r"^Hamilton_HSLHttp_v([0-9][0-9.]*)\.exe$",
    registry_name_pattern="HSLHttp",
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.1", (1, 1)),
        ("v2.9", (2, 9)),
        ("3.1.0", (3, 1, 0)),
        (" 4.5 ", (4, 5)),
        ("1.8.0-beta", (1, 8, 0)),
        ("unknown", None),
        ("", None),
    ],
)
def test_parse_version(raw: str, expected: tuple[int, ...] | None) -> None:
    assert version_detection.parse_version(raw) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("2.9", "2.9", 0),
        ("2.9", "2.9.0", 0),
        ("2.8", "2.9", -1),
        ("3.0", "2.9", 1),
        ("1.10", "1.9", 1),
        ("bad", "2.9", None),
    ],
)
def test_compare_versions(left: str, right: str, expected: int | None) -> None:
    assert version_detection.compare_versions(left, right) == expected


def test_detect_version_from_installers_picks_newest_match(tmp_path: Path) -> None:
    (tmp_path / "Hamilton_HSLHttp_v2.8.exe").touch()
    (tmp_path / "Hamilton_HSLHttp_v2.10.exe").touch()
    (tmp_path / "unrelated.exe").touch()

    found = version_detection.detect_version_from_installers(HSLHTTP, tmp_path)

    assert found is not None
    assert found.version == "2.10"
    assert found.source is VersionSource.INSTALLER_FILENAME
    assert found.location == str(tmp_path / "Hamilton_HSLHttp_v2.10.exe")


def test_detect_version_from_installers_returns_none_without_match(tmp_path: Path) -> None:
    (tmp_path / "SomethingElse.exe").touch()

    assert version_detection.detect_version_from_installers(HSLHTTP, tmp_path) is None


def test_detect_version_from_installers_returns_none_for_missing_directory(tmp_path: Path) -> None:
    assert version_detection.detect_version_from_installers(HSLHTTP, tmp_path / "absent") is None


def test_detect_version_from_registry_matches_display_name() -> None:
    entries = [
        ("Some Other Program", "1.0", r"HKLM\...\Other"),
        ("Hamilton HSLHttp Library", "2.8", r"HKLM\...\HSLHttp"),
    ]

    found = version_detection.detect_version_from_registry(HSLHTTP, entries)

    assert found is not None
    assert found.version == "2.8"
    assert found.source is VersionSource.REGISTRY
    assert found.location == r"HKLM\...\HSLHttp"


def test_detect_version_from_registry_returns_none_without_match() -> None:
    entries = [("Some Other Program", "1.0", r"HKLM\...\Other")]

    assert version_detection.detect_version_from_registry(HSLHTTP, entries) is None


def test_detect_installed_version_reports_not_found_when_absent() -> None:
    installed = version_detection.detect_installed_version(HSLHTTP, [])

    assert installed.version is None
    assert installed.source is VersionSource.NOT_FOUND


def test_detect_installed_version_reports_registry_entry_without_version() -> None:
    entries = [("Hamilton HSLHttp Library", "", r"HKLM\...\HSLHttp")]

    installed = version_detection.detect_installed_version(HSLHTTP, entries)

    assert installed.version is None
    assert installed.source is VersionSource.REGISTRY


def test_detect_all_installed_versions_covers_every_manifest_entry(monkeypatch) -> None:
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(HSLHTTP,))
    monkeypatch.setattr(
        version_detection,
        "iter_uninstall_entries",
        lambda: [("Hamilton HSLHttp Library", "2.9", r"HKLM\...\HSLHttp")],
    )

    detected = version_detection.detect_all_installed_versions(manifest)

    assert set(detected) == {"hslhttp"}
    assert detected["hslhttp"].version == "2.9"


def test_detect_all_bundled_versions_skips_unmatched_entries(tmp_path: Path) -> None:
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(HSLHTTP,))

    assert version_detection.detect_all_bundled_versions(manifest, tmp_path) == {}

    (tmp_path / "Hamilton_HSLHttp_v2.9.exe").touch()
    bundled = version_detection.detect_all_bundled_versions(manifest, tmp_path)

    assert bundled["hslhttp"].version == "2.9"


def test_iter_uninstall_entries_is_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(version_detection.sys, "platform", "linux")

    assert version_detection.iter_uninstall_entries() == []
