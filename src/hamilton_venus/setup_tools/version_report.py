from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteManifest
from hamilton_venus.setup_tools.version_detection import (
    InstalledVersion,
    VersionSource,
    compare_versions,
)


class VersionStatus(StrEnum):
    """Outcome of comparing an installed prerequisite against the required version."""

    UP_TO_DATE = "up_to_date"
    OUTDATED = "outdated"
    NEWER_THAN_REQUIRED = "newer_than_required"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


STATUS_LABELS: dict[VersionStatus, str] = {
    VersionStatus.UP_TO_DATE: "[OK]",
    VersionStatus.OUTDATED: "[OUTDATED]",
    VersionStatus.NEWER_THAN_REQUIRED: "[NEWER]",
    VersionStatus.NOT_INSTALLED: "[MISSING]",
    VersionStatus.UNKNOWN: "[UNKNOWN]",
}


@dataclass(frozen=True)
class VersionCheckResult:
    """Comparison of one prerequisite's installed version against the required version."""

    name: str
    display_name: str
    required_version: str
    installed_version: str | None
    status: VersionStatus
    source: VersionSource
    location: str | None
    message: str

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON-serialisable representation of this result."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "required_version": self.required_version,
            "installed_version": self.installed_version,
            "status": self.status.value,
            "source": self.source.value,
            "location": self.location,
            "message": self.message,
        }


@dataclass(frozen=True)
class VersionReport:
    """Aggregate view of every prerequisite version comparison."""

    results: tuple[VersionCheckResult, ...]

    def by_status(self, status: VersionStatus) -> tuple[VersionCheckResult, ...]:
        """Return the results matching the given status."""
        return tuple(result for result in self.results if result.status is status)

    @property
    def outdated(self) -> tuple[VersionCheckResult, ...]:
        """Return the results whose installed version is older than required."""
        return self.by_status(VersionStatus.OUTDATED)

    @property
    def missing(self) -> tuple[VersionCheckResult, ...]:
        """Return the results for prerequisites that are not installed."""
        return self.by_status(VersionStatus.NOT_INSTALLED)

    @property
    def any_outdated(self) -> bool:
        """Return True when at least one prerequisite is outdated."""
        return bool(self.outdated)

    @property
    def summary(self) -> str:
        """Return a one-line count of prerequisites per status."""
        counts = {status: len(self.by_status(status)) for status in VersionStatus}
        return (
            f"{counts[VersionStatus.UP_TO_DATE]} up to date, "
            f"{counts[VersionStatus.OUTDATED]} outdated, "
            f"{counts[VersionStatus.NEWER_THAN_REQUIRED]} newer than required, "
            f"{counts[VersionStatus.NOT_INSTALLED]} not installed, "
            f"{counts[VersionStatus.UNKNOWN]} unknown"
        )


def _evaluate(required: str, installed: InstalledVersion) -> tuple[VersionStatus, str]:
    """Determine the status and user-facing message for a single prerequisite."""
    if installed.version is None:
        if installed.source is VersionSource.REGISTRY:
            return (
                VersionStatus.UNKNOWN,
                f"installed but no version recorded; requires {required}",
            )
        return VersionStatus.NOT_INSTALLED, f"not installed; requires {required}"

    comparison = compare_versions(installed.version, required)
    if comparison is None:
        return (
            VersionStatus.UNKNOWN,
            f"installed version {installed.version!r} could not be compared against {required}",
        )
    if comparison < 0:
        return (
            VersionStatus.OUTDATED,
            f"installed {installed.version}, update to {required}",
        )
    if comparison > 0:
        return (
            VersionStatus.NEWER_THAN_REQUIRED,
            f"installed {installed.version} is newer than the bundled {required}",
        )
    return VersionStatus.UP_TO_DATE, f"installed {installed.version}"


def generate_version_report(
    manifest: PrerequisiteManifest,
    installed_versions: dict[str, InstalledVersion],
) -> VersionReport:
    """Compare each manifest entry against the detected installed versions."""
    results: list[VersionCheckResult] = []
    for prereq in manifest.prerequisites:
        installed = installed_versions.get(
            prereq.name,
            InstalledVersion(name=prereq.name, version=None, source=VersionSource.NOT_FOUND),
        )
        status, message = _evaluate(prereq.required_version, installed)
        results.append(
            VersionCheckResult(
                name=prereq.name,
                display_name=prereq.display_name,
                required_version=prereq.required_version,
                installed_version=installed.version,
                status=status,
                source=installed.source,
                location=installed.location,
                message=message,
            )
        )
    return VersionReport(results=tuple(results))


def format_report_as_text(report: VersionReport, verbose: bool = False) -> str:
    """Render the report as an aligned, ASCII-only table for console output."""
    if not report.results:
        return "No prerequisites are declared in the manifest."

    label_width = max(len(STATUS_LABELS[result.status]) for result in report.results)
    name_width = max(len(result.display_name) for result in report.results)

    lines = ["Prerequisite version status:"]
    for result in report.results:
        label = STATUS_LABELS[result.status].ljust(label_width)
        lines.append(f"  {label}  {result.display_name.ljust(name_width)}  {result.message}")
        if verbose:
            lines.append(f"{' ' * (label_width + 4)}source: {result.source.value}")
            if result.location:
                lines.append(f"{' ' * (label_width + 4)}location: {result.location}")

    lines.append("")
    lines.append(f"Summary: {report.summary}")
    if report.any_outdated:
        lines.append("Re-run 'setup-venus-sdk --skip-structure --skip-catalog' to install the bundled versions.")
    return "\n".join(lines)


def format_report_as_json(report: VersionReport) -> str:
    """Render the report as JSON for scripting and CI consumption."""
    payload = {
        "summary": report.summary,
        "any_outdated": report.any_outdated,
        "results": [result.as_dict() for result in report.results],
    }
    return json.dumps(payload, indent=2)
