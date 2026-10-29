from __future__ import annotations

import json

from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteInfo, PrerequisiteManifest
from hamilton_venus.setup_tools.version_detection import InstalledVersion, VersionSource
from hamilton_venus.setup_tools.version_report import (
    VersionStatus,
    format_report_as_json,
    format_report_as_text,
    generate_version_report,
)


def _prereq(name: str, required: str) -> PrerequisiteInfo:
    return PrerequisiteInfo(
        name=name,
        display_name=name.upper(),
        required_version=required,
        installer_pattern=rf"^{name}_v([0-9][0-9.]*)\.exe$",
        registry_name_pattern=name,
    )


MANIFEST = PrerequisiteManifest(
    format_version="1.0",
    prerequisites=(
        _prereq("current", "2.9"),
        _prereq("stale", "2.9"),
        _prereq("ahead", "2.9"),
        _prereq("absent", "2.9"),
        _prereq("unparsable", "2.9"),
    ),
)


def _registry(name: str, version: str | None) -> InstalledVersion:
    return InstalledVersion(name=name, version=version, source=VersionSource.REGISTRY, location=f"HKLM\\{name}")


INSTALLED = {
    "current": _registry("current", "2.9"),
    "stale": _registry("stale", "2.8"),
    "ahead": _registry("ahead", "3.0"),
    "unparsable": _registry("unparsable", "RTM"),
}


def test_generate_version_report_assigns_expected_statuses() -> None:
    report = generate_version_report(MANIFEST, INSTALLED)
    statuses = {result.name: result.status for result in report.results}

    assert statuses == {
        "current": VersionStatus.UP_TO_DATE,
        "stale": VersionStatus.OUTDATED,
        "ahead": VersionStatus.NEWER_THAN_REQUIRED,
        "absent": VersionStatus.NOT_INSTALLED,
        "unparsable": VersionStatus.UNKNOWN,
    }


def test_report_exposes_outdated_and_missing_entries() -> None:
    report = generate_version_report(MANIFEST, INSTALLED)

    assert report.any_outdated is True
    assert [result.name for result in report.outdated] == ["stale"]
    assert [result.name for result in report.missing] == ["absent"]


def test_report_is_not_outdated_when_everything_matches() -> None:
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(_prereq("current", "2.9"),))

    report = generate_version_report(manifest, {"current": _registry("current", "2.9")})

    assert report.any_outdated is False
    assert report.summary.startswith("1 up to date, 0 outdated")


def test_registry_entry_without_version_is_unknown_not_missing() -> None:
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(_prereq("current", "2.9"),))

    report = generate_version_report(manifest, {"current": _registry("current", None)})

    assert report.results[0].status is VersionStatus.UNKNOWN


def test_summary_counts_every_status() -> None:
    report = generate_version_report(MANIFEST, INSTALLED)

    assert report.summary == ("1 up to date, 1 outdated, 1 newer than required, 1 not installed, 1 unknown")


def test_format_report_as_text_is_ascii_and_lists_all_entries() -> None:
    text = format_report_as_text(generate_version_report(MANIFEST, INSTALLED))

    text.encode("ascii")
    for prereq in MANIFEST.prerequisites:
        assert prereq.display_name in text
    assert "[OUTDATED]" in text
    assert "Summary:" in text


def test_format_report_as_text_verbose_includes_detection_details() -> None:
    report = generate_version_report(MANIFEST, INSTALLED)

    text = format_report_as_text(report, verbose=True)

    assert "source: registry" in text
    assert "location: HKLM\\current" in text


def test_format_report_as_text_handles_empty_manifest() -> None:
    empty = PrerequisiteManifest(format_version="1.0", prerequisites=())

    assert "No prerequisites" in format_report_as_text(generate_version_report(empty, {}))


def test_format_report_as_json_round_trips() -> None:
    report = generate_version_report(MANIFEST, INSTALLED)

    payload = json.loads(format_report_as_json(report))

    assert payload["any_outdated"] is True
    assert len(payload["results"]) == len(MANIFEST.prerequisites)
    stale = next(item for item in payload["results"] if item["name"] == "stale")
    assert stale["status"] == "outdated"
    assert stale["installed_version"] == "2.8"
    assert stale["required_version"] == "2.9"
