from __future__ import annotations

import logging
from pathlib import Path

from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteManifest, load_manifest
from hamilton_venus.setup_tools.version_detection import (
    InstalledVersion,
    detect_all_bundled_versions,
    detect_all_installed_versions,
)
from hamilton_venus.setup_tools.version_report import (
    VersionReport,
    format_report_as_json,
    format_report_as_text,
    generate_version_report,
)

logger = logging.getLogger("venus_prereq_versions")


class PrerequisiteVersionChecker:
    """Compare the prerequisites installed on this machine against the shipped manifest."""

    def __init__(self, prereqs_path: Path, manifest_path: Path | None = None) -> None:
        self.prereqs_path = prereqs_path
        self.manifest_path = manifest_path
        self._manifest: PrerequisiteManifest | None = None
        self._report: VersionReport | None = None

    @property
    def manifest(self) -> PrerequisiteManifest:
        """Return the prerequisite manifest, loading it on first access."""
        if self._manifest is None:
            self._manifest = load_manifest(self.manifest_path)
        return self._manifest

    def installed_versions(self) -> dict[str, InstalledVersion]:
        """Return the versions detected on this machine, keyed by prerequisite name."""
        return detect_all_installed_versions(self.manifest)

    def bundled_versions(self) -> dict[str, InstalledVersion]:
        """Return the versions of the installers bundled in the prerequisites folder."""
        return detect_all_bundled_versions(self.manifest, self.prereqs_path)

    def check(self, refresh: bool = False) -> VersionReport:
        """Build the version report, reusing the previous result unless ``refresh`` is set."""
        if self._report is None or refresh:
            self._report = generate_version_report(self.manifest, self.installed_versions())
        return self._report

    def outdated_messages(self) -> list[str]:
        """Return one human-readable line per outdated prerequisite."""
        return [f"{result.display_name}: {result.message}" for result in self.check().outdated]

    def as_text(self, verbose: bool = False) -> str:
        """Return the report rendered as a console table."""
        return format_report_as_text(self.check(), verbose=verbose)

    def as_json(self) -> str:
        """Return the report rendered as JSON."""
        return format_report_as_json(self.check())

    def manifest_drift(self) -> list[str]:
        """Return warnings where the manifest disagrees with the bundled installer filenames."""
        bundled = self.bundled_versions()
        warnings: list[str] = []
        for prereq in self.manifest.prerequisites:
            found = bundled.get(prereq.name)
            if found is None:
                warnings.append(f"{prereq.display_name}: no bundled installer matches the manifest pattern")
            elif found.version != prereq.required_version:
                warnings.append(
                    f"{prereq.display_name}: manifest requires {prereq.required_version} "
                    f"but bundled installer is {found.version}"
                )
        return warnings


def warn_if_outdated(prereqs_path: Path, manifest_path: Path | None = None) -> VersionReport | None:
    """Log a warning for each outdated prerequisite; return the report, or None if unavailable."""
    try:
        checker = PrerequisiteVersionChecker(prereqs_path, manifest_path)
        report = checker.check()
    except (FileNotFoundError, ValueError) as exc:
        logger.debug("Skipping prerequisite version check: %s", exc)
        return None

    if report.any_outdated:
        logger.warning("Outdated prerequisite install(s) detected:")
        for message in checker.outdated_messages():
            logger.warning("  - %s", message)
    return report
