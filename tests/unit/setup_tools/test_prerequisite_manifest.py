from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hamilton_venus.setup_tools import prerequisite_manifest


def _manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
    payload.update(overrides)
    return payload


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_parses_entries(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json", _manifest_payload())

    manifest = prerequisite_manifest.load_manifest(manifest_path)

    assert manifest.format_version == "1.0"
    assert len(manifest.prerequisites) == 1
    assert manifest.prerequisites[0].name == "hslhttp"
    assert manifest.prerequisites[0].required_version == "2.9"


def test_load_manifest_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        prerequisite_manifest.load_manifest(tmp_path / "absent.json")


def test_load_manifest_raises_for_invalid_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        prerequisite_manifest.load_manifest(manifest_path)


def test_load_manifest_rejects_unsupported_format_version(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json", _manifest_payload(format_version="9.9"))

    with pytest.raises(ValidationError, match="unsupported manifest format_version"):
        prerequisite_manifest.load_manifest(manifest_path)


def test_load_manifest_rejects_duplicate_names(tmp_path: Path) -> None:
    payload = _manifest_payload()
    entries = list(payload["prerequisites"])  # type: ignore[call-overload]
    payload["prerequisites"] = [*entries, dict(entries[0])]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError, match="duplicate prerequisite name"):
        prerequisite_manifest.load_manifest(manifest_path)


def test_load_manifest_rejects_installer_pattern_without_capture_group(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["prerequisites"][0]["installer_pattern"] = r"^Hamilton_HSLHttp\.exe$"  # type: ignore[index]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError, match="must contain a version capture group"):
        prerequisite_manifest.load_manifest(manifest_path)


def test_load_manifest_rejects_invalid_regex(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["prerequisites"][0]["registry_name_pattern"] = "HSL(Http"  # type: ignore[index]
    manifest_path = _write_manifest(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError, match="invalid regular expression"):
        prerequisite_manifest.load_manifest(manifest_path)


def test_default_manifest_path_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "custom-manifest.json"
    monkeypatch.setenv(prerequisite_manifest.MANIFEST_PATH_ENV_VAR, str(override))

    assert prerequisite_manifest.default_manifest_path() == override.expanduser().resolve()


def test_default_manifest_path_falls_back_to_sdk_root(tmp_path: Path, monkeypatch) -> None:
    sdk_root = tmp_path / "sdk-root"
    (sdk_root / "prerequisites").mkdir(parents=True)
    (sdk_root / "sdk_method_structure").mkdir(parents=True)
    monkeypatch.delenv(prerequisite_manifest.MANIFEST_PATH_ENV_VAR, raising=False)
    monkeypatch.setenv("HAMILTON_VENUS_SDK_ROOT", str(sdk_root))

    expected = Path(str(sdk_root)).expanduser().resolve() / "prerequisites" / "manifest.json"
    assert prerequisite_manifest.default_manifest_path() == expected
