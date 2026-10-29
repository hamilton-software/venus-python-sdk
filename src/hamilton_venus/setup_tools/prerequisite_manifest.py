from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hamilton_venus.setup_tools.root_discovery import find_sdk_root

MANIFEST_FILENAME = "manifest.json"
MANIFEST_PATH_ENV_VAR = "HAMILTON_VENUS_PREREQ_MANIFEST"
SUPPORTED_FORMAT_VERSIONS = frozenset({"1.0"})


class PrerequisiteInfo(BaseModel):
    """Version requirements and detection rules for a single prerequisite installer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str
    required_version: str
    installer_pattern: str = Field(
        description="Regex matched against installer filenames with one capture group for the version"
    )
    registry_name_pattern: str = Field(description="Regex matched against Windows uninstall entry DisplayName values")

    @field_validator("installer_pattern", "registry_name_pattern")
    @classmethod
    def _validate_regex(cls, value: str) -> str:
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {value!r}: {exc}") from exc
        return value

    @field_validator("installer_pattern")
    @classmethod
    def _validate_capture_group(cls, value: str) -> str:
        if re.compile(value, re.IGNORECASE).groups < 1:
            raise ValueError(f"installer_pattern {value!r} must contain a version capture group")
        return value


class PrerequisiteManifest(BaseModel):
    """Declarative list of the prerequisite versions shipped with this SDK release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: str
    prerequisites: tuple[PrerequisiteInfo, ...]

    @field_validator("format_version")
    @classmethod
    def _validate_format_version(cls, value: str) -> str:
        if value not in SUPPORTED_FORMAT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_FORMAT_VERSIONS))
            raise ValueError(f"unsupported manifest format_version {value!r} (supported: {supported})")
        return value

    @field_validator("prerequisites")
    @classmethod
    def _validate_unique_names(cls, value: tuple[PrerequisiteInfo, ...]) -> tuple[PrerequisiteInfo, ...]:
        names = [item.name for item in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate prerequisite name(s): {', '.join(duplicates)}")
        return value


def default_manifest_path() -> Path:
    """Return the manifest path, honouring the environment override when set."""
    configured = os.environ.get(MANIFEST_PATH_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return find_sdk_root() / "prerequisites" / MANIFEST_FILENAME


def load_manifest(manifest_path: Path | None = None) -> PrerequisiteManifest:
    """Load and validate the prerequisite manifest from disk."""
    path = manifest_path if manifest_path is not None else default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"Prerequisite manifest not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Prerequisite manifest {path} is not valid JSON: {exc}") from exc
    return PrerequisiteManifest.model_validate(raw)
