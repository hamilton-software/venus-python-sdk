from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteInfo, PrerequisiteManifest

logger = logging.getLogger("venus_prereq_versions")

UNINSTALL_REGISTRY_KEYS: tuple[str, ...] = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)


class VersionSource(StrEnum):
    """Where a detected version number came from."""

    REGISTRY = "registry"
    INSTALLER_FILENAME = "installer_filename"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class InstalledVersion:
    """A version detected for a single prerequisite."""

    name: str
    version: str | None
    source: VersionSource
    location: str | None = None


def parse_version(version: str) -> tuple[int, ...] | None:
    """Convert a dotted version string into a comparable tuple of integers."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", version, re.IGNORECASE)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(left: str, right: str) -> int | None:
    """Return -1/0/1 comparing two version strings, or None when either cannot be parsed."""
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    if left_parts is None or right_parts is None:
        return None
    length = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (length - len(left_parts))
    padded_right = right_parts + (0,) * (length - len(right_parts))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def detect_version_from_installers(prereq: PrerequisiteInfo, prereqs_path: Path) -> InstalledVersion | None:
    """Return the version of the newest bundled installer matching the prerequisite pattern."""
    if not prereqs_path.is_dir():
        return None

    pattern = re.compile(prereq.installer_pattern, re.IGNORECASE)
    best: tuple[tuple[int, ...], str, Path] | None = None
    for candidate in sorted(prereqs_path.iterdir()):
        if not candidate.is_file():
            continue
        match = pattern.match(candidate.name)
        if match is None:
            continue
        version = match.group(1)
        parsed = parse_version(version)
        if parsed is None:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, version, candidate)

    if best is None:
        return None
    return InstalledVersion(
        name=prereq.name,
        version=best[1],
        source=VersionSource.INSTALLER_FILENAME,
        location=str(best[2]),
    )


def iter_uninstall_entries() -> list[tuple[str, str, str]]:
    """Return (display_name, display_version, registry_key) for programs installed on Windows."""
    if sys.platform != "win32":
        logger.debug("Registry version detection is only available on Windows")
        return []

    import winreg

    entries: list[tuple[str, str, str]] = []
    for hive, hive_name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        for base_key in UNINSTALL_REGISTRY_KEYS:
            try:
                root = winreg.OpenKey(hive, base_key)
            except OSError:
                continue
            with root:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            try:
                                display_version, _ = winreg.QueryValueEx(subkey, "DisplayVersion")
                            except OSError:
                                display_version = ""
                    except OSError:
                        continue
                    if isinstance(display_name, str) and display_name:
                        entries.append(
                            (
                                display_name,
                                display_version if isinstance(display_version, str) else "",
                                f"{hive_name}\\{base_key}\\{subkey_name}",
                            )
                        )
    return entries


def detect_version_from_registry(
    prereq: PrerequisiteInfo,
    entries: list[tuple[str, str, str]] | None = None,
) -> InstalledVersion | None:
    """Return the installed version recorded in the Windows uninstall registry, if present."""
    uninstall_entries = iter_uninstall_entries() if entries is None else entries
    pattern = re.compile(prereq.registry_name_pattern, re.IGNORECASE)

    for display_name, display_version, registry_key in uninstall_entries:
        if pattern.search(display_name) is None:
            continue
        return InstalledVersion(
            name=prereq.name,
            version=display_version or None,
            source=VersionSource.REGISTRY,
            location=registry_key,
        )
    return None


def detect_installed_version(
    prereq: PrerequisiteInfo,
    entries: list[tuple[str, str, str]] | None = None,
) -> InstalledVersion:
    """Detect the version of a prerequisite installed on this machine.

    Only the Windows uninstall registry reflects what is actually installed. Bundled
    installer filenames describe what ships with the SDK and are read separately by
    :func:`detect_version_from_installers`.
    """
    detected = detect_version_from_registry(prereq, entries)
    if detected is not None:
        return detected
    return InstalledVersion(name=prereq.name, version=None, source=VersionSource.NOT_FOUND)


def detect_all_installed_versions(manifest: PrerequisiteManifest) -> dict[str, InstalledVersion]:
    """Detect installed versions for every prerequisite declared in the manifest."""
    entries = iter_uninstall_entries()
    return {prereq.name: detect_installed_version(prereq, entries) for prereq in manifest.prerequisites}


def detect_all_bundled_versions(
    manifest: PrerequisiteManifest,
    prereqs_path: Path,
) -> dict[str, InstalledVersion]:
    """Detect the versions of the installers bundled in the prerequisites folder."""
    bundled: dict[str, InstalledVersion] = {}
    for prereq in manifest.prerequisites:
        found = detect_version_from_installers(prereq, prereqs_path)
        if found is not None:
            bundled[prereq.name] = found
    return bundled
