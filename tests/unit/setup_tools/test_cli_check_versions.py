from __future__ import annotations

import json
from pathlib import Path

import pytest

from hamilton_venus.setup_tools import cli

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


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return ["--prereqs", str(tmp_path), "--manifest", str(_write_manifest(tmp_path)), *extra]


def test_check_versions_returns_zero_when_up_to_date(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.9")

    exit_code = cli.check_versions_main(_args(tmp_path))

    assert exit_code == 0
    assert "[OK]" in capsys.readouterr().out


def test_check_versions_reports_outdated_but_exits_zero_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.8")

    exit_code = cli.check_versions_main(_args(tmp_path))

    assert exit_code == 0
    assert "[OUTDATED]" in capsys.readouterr().out


def test_check_versions_fails_when_fail_if_outdated_set(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.8")

    exit_code = cli.check_versions_main(_args(tmp_path, "--fail-if-outdated"))

    capsys.readouterr()
    assert exit_code == 1


def test_check_versions_passes_when_fail_if_outdated_set_and_current(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.9")

    exit_code = cli.check_versions_main(_args(tmp_path, "--fail-if-outdated"))

    capsys.readouterr()
    assert exit_code == 0


def test_check_versions_json_output(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.8")

    exit_code = cli.check_versions_main(_args(tmp_path, "--json"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["any_outdated"] is True


def test_check_versions_check_manifest_reports_drift(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.9")

    cli.check_versions_main(_args(tmp_path, "--check-manifest"))

    assert "no bundled installer matches" in capsys.readouterr().out


def test_check_versions_missing_manifest_returns_two(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.9")

    exit_code = cli.check_versions_main(["--prereqs", str(tmp_path), "--manifest", str(tmp_path / "absent.json")])

    capsys.readouterr()
    assert exit_code == 2


def test_check_versions_invalid_manifest_returns_two(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.9")
    broken = tmp_path / "manifest.json"
    broken.write_text("{oops", encoding="utf-8")

    exit_code = cli.check_versions_main(["--prereqs", str(tmp_path), "--manifest", str(broken)])

    capsys.readouterr()
    assert exit_code == 2


def test_main_dispatches_check_versions_subcommand(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_registry(monkeypatch, "2.8")

    exit_code = cli.main([cli.CHECK_VERSIONS_COMMAND, *_args(tmp_path, "--fail-if-outdated")])

    capsys.readouterr()
    assert exit_code == 1


def test_main_warns_about_outdated_prerequisites_before_setup(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    manifest_path = _write_manifest(tmp_path)
    warned: list[tuple[Path, Path | None]] = []

    monkeypatch.setattr(cli, "warn_if_outdated", lambda prereqs, manifest: warned.append((prereqs, manifest)))
    monkeypatch.setattr(cli.prerequisites, "main", lambda argv: 0)
    monkeypatch.setattr(cli.structure, "main", lambda argv: 0)

    exit_code = cli.main(
        [
            "--prereqs",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--dry-run",
            "--skip-catalog",
        ]
    )

    assert exit_code == 0
    assert warned == [(tmp_path, manifest_path)]


def test_main_skips_version_check_when_requested(tmp_path: Path, monkeypatch) -> None:
    _patch_registry(monkeypatch, "2.8")
    warned: list[object] = []

    monkeypatch.setattr(cli, "warn_if_outdated", lambda prereqs, manifest: warned.append(prereqs))
    monkeypatch.setattr(cli.prerequisites, "main", lambda argv: 0)
    monkeypatch.setattr(cli.structure, "main", lambda argv: 0)

    exit_code = cli.main(["--prereqs", str(tmp_path), "--dry-run", "--skip-catalog", "--skip-version-check"])

    assert exit_code == 0
    assert warned == []


@pytest.mark.parametrize("flag", ["--json", "--verbose"])
def test_check_versions_arg_parsing(tmp_path: Path, flag: str) -> None:
    args = cli.parse_check_versions_args(["--prereqs", str(tmp_path), flag])

    assert args.prereqs == tmp_path
