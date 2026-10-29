from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hamilton_venus._internal._sdk_paths import REGISTRY_KEY_PATH
from hamilton_venus.setup_tools import structure, uninstall
from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteInfo, PrerequisiteManifest

skipif_not_windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")


def _make_structure(root: Path) -> Path:
    src = root / "sdk_method_structure"
    (src / "Method").mkdir(parents=True)
    (src / "Method" / "VENUS_SDK_Executor.hsl").write_text("hsl", encoding="utf-8")
    (src / "Labware").mkdir()
    (src / "Labware" / "plate.lb").write_text("lb", encoding="utf-8")
    return src


def test_remove_structure_tree_deletes_matching_files_and_prunes_dirs(tmp_path: Path) -> None:
    src = _make_structure(tmp_path)
    target = tmp_path / "installed"
    (target / "Method").mkdir(parents=True)
    (target / "Method" / "VENUS_SDK_Executor.hsl").write_text("hsl", encoding="utf-8")
    (target / "Labware").mkdir()
    (target / "Labware" / "plate.lb").write_text("lb", encoding="utf-8")
    (target / "Labware" / "user_added.lb").write_text("keep me", encoding="utf-8")

    removed = uninstall.remove_structure_tree(src, target)

    assert removed == 2
    assert not (target / "Method" / "VENUS_SDK_Executor.hsl").exists()
    assert not (target / "Method").exists()
    assert (target / "Labware" / "user_added.lb").exists()
    assert target.exists()


def test_remove_structure_tree_dry_run_makes_no_changes(tmp_path: Path) -> None:
    src = _make_structure(tmp_path)
    target = tmp_path / "installed"
    (target / "Method").mkdir(parents=True)
    (target / "Method" / "VENUS_SDK_Executor.hsl").write_text("hsl", encoding="utf-8")

    removed = uninstall.remove_structure_tree(src, target, dry_run=True)

    assert removed == 1
    assert (target / "Method" / "VENUS_SDK_Executor.hsl").exists()


def test_remove_structure_tree_returns_zero_when_target_missing(tmp_path: Path, caplog) -> None:
    src = _make_structure(tmp_path)
    target = tmp_path / "absent"

    with caplog.at_level(logging.INFO):
        removed = uninstall.remove_structure_tree(src, target)

    assert removed == 0
    assert "Nothing to remove" in caplog.text


def test_remove_structure_tree_warns_when_structure_source_missing(tmp_path: Path, caplog) -> None:
    target = tmp_path / "installed"
    target.mkdir()

    with caplog.at_level(logging.WARNING):
        removed = uninstall.remove_structure_tree(tmp_path / "missing_structure", target)

    assert removed == 0
    assert "Structure source not found" in caplog.text


def test_purge_target_tree_removes_everything_including_stale_files(tmp_path: Path) -> None:
    target = tmp_path / "installed"
    (target / "Labware" / "System" / "plate").mkdir(parents=True)
    (target / "Labware" / "System" / "plate" / "Nun_96_Fl.json").write_text("{}", encoding="utf-8")
    (target / "Labware" / "Plates").mkdir()
    (target / "Labware" / "Plates" / "stale_legacy.json").write_text("{}", encoding="utf-8")
    (target / "Method").mkdir()
    (target / "Method" / "VENUS_SDK_Executor.hsl").write_text("hsl", encoding="utf-8")
    (target / "loose.txt").write_text("loose", encoding="utf-8")

    removed = uninstall.purge_target_tree(target)

    assert removed == 3
    assert target.exists()
    assert list(target.iterdir()) == []


def test_purge_target_tree_dry_run_makes_no_changes(tmp_path: Path) -> None:
    target = tmp_path / "installed"
    (target / "Method").mkdir(parents=True)
    (target / "Method" / "VENUS_SDK_Executor.hsl").write_text("hsl", encoding="utf-8")

    removed = uninstall.purge_target_tree(target, dry_run=True)

    assert removed == 1
    assert (target / "Method" / "VENUS_SDK_Executor.hsl").exists()


def test_purge_target_tree_returns_zero_when_target_missing(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.INFO):
        removed = uninstall.purge_target_tree(tmp_path / "absent")

    assert removed == 0
    assert "Nothing to remove" in caplog.text


def test_purge_target_tree_rejects_filesystem_root(tmp_path: Path) -> None:
    root = Path(tmp_path.anchor)

    with pytest.raises(uninstall.UnsafePurgeTargetError, match="filesystem root"):
        uninstall.purge_target_tree(root)


def test_purge_target_tree_rejects_protected_directory(tmp_path: Path) -> None:
    protected = tmp_path / "Windows"
    protected.mkdir()

    with pytest.raises(uninstall.UnsafePurgeTargetError, match="protected system directory"):
        uninstall.purge_target_tree(protected)


def test_clear_sdk_registry_path_dry_run_returns_true(caplog) -> None:
    with caplog.at_level(logging.INFO):
        result = uninstall.clear_sdk_registry_path(dry_run=True)

    assert result is True
    assert "Would remove registry key" in caplog.text


def test_clear_sdk_registry_path_non_windows_returns_false(monkeypatch, caplog) -> None:
    monkeypatch.setattr(uninstall.sys, "platform", "linux")

    with caplog.at_level(logging.INFO):
        result = uninstall.clear_sdk_registry_path()

    assert result is False
    assert "Skipping registry cleanup" in caplog.text


@skipif_not_windows
def test_clear_sdk_registry_path_deletes_key_on_windows(monkeypatch) -> None:
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    result = uninstall.clear_sdk_registry_path()

    assert result is True
    mock_winreg.DeleteKey.assert_called_once_with(mock_winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH)


@skipif_not_windows
def test_clear_sdk_registry_path_missing_key_returns_true(monkeypatch, caplog) -> None:
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.DeleteKey.side_effect = FileNotFoundError()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    with caplog.at_level(logging.INFO):
        result = uninstall.clear_sdk_registry_path()

    assert result is True
    assert "already absent" in caplog.text


@skipif_not_windows
def test_clear_sdk_registry_path_permission_error_returns_false(monkeypatch, caplog) -> None:
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.DeleteKey.side_effect = PermissionError("denied")
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    with caplog.at_level(logging.WARNING):
        result = uninstall.clear_sdk_registry_path()

    assert result is False
    assert "due to permissions" in caplog.text


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('"C:\\Program Files\\App\\unins000.exe"', ["C:\\Program Files\\App\\unins000.exe"]),
        ('"C:\\Program Files\\App\\unins000.exe" /SILENT', ["C:\\Program Files\\App\\unins000.exe", "/SILENT"]),
        ("MsiExec.exe /X{GUID}", ["MsiExec.exe", "/X{GUID}"]),
        ("", []),
    ],
)
def test_split_uninstall_command(command: str, expected: list[str]) -> None:
    assert uninstall._split_uninstall_command(command) == expected


def _prereq(name: str) -> PrerequisiteInfo:
    return PrerequisiteInfo(
        name=name,
        display_name=name.upper(),
        required_version="1.0",
        installer_pattern=rf"^{name}_v([0-9][0-9.]*)\.exe$",
        registry_name_pattern=name,
    )


def test_find_prerequisite_uninstall_commands_matches_registry(monkeypatch) -> None:
    monkeypatch.setattr(uninstall.sys, "platform", "win32")
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(_prereq("hslhttp"),))

    result = _run_find_with_fake_registry(manifest)

    assert result["hslhttp"][0] == "hslhttp Library"
    assert result["hslhttp"][1] == '"C:\\App\\unins000.exe"'
    assert result["hslhttp"][2] == '"C:\\App\\unins000.exe" /VERYSILENT'


def _run_find_with_fake_registry(manifest: PrerequisiteManifest) -> dict[str, tuple[str, str, str | None]]:
    """Exercise find_prerequisite_uninstall_commands against a minimal fake winreg module."""

    class _RootKey:
        def __enter__(self) -> _RootKey:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeWinreg:
        HKEY_LOCAL_MACHINE = "HKLM"
        HKEY_CURRENT_USER = "HKCU"

        def OpenKey(self, hive, path):  # noqa: N802
            if isinstance(hive, _RootKey):
                if path == "hslhttp_entry":
                    return _RootKey()
                raise OSError("not found")
            if hive == "HKLM" and path == uninstall.UNINSTALL_REGISTRY_KEYS[0]:
                return _RootKey()
            raise OSError("not found")

        def EnumKey(self, root, index):  # noqa: N802
            if isinstance(root, _RootKey) and index == 0:
                return "hslhttp_entry"
            raise OSError("no more items")

        def QueryValueEx(self, subkey, name):  # noqa: N802
            values = {
                "DisplayName": "hslhttp Library",
                "UninstallString": '"C:\\App\\unins000.exe"',
                "QuietUninstallString": '"C:\\App\\unins000.exe" /VERYSILENT',
            }
            if name in values:
                return values[name], 1
            raise OSError("missing value")

    fake = FakeWinreg()

    import sys as _sys
    import types

    original = _sys.modules.get("winreg")
    module = types.ModuleType("winreg")
    for attr in ("HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"):
        setattr(module, attr, getattr(fake, attr))
    module.OpenKey = fake.OpenKey  # type: ignore[attr-defined]
    module.EnumKey = fake.EnumKey  # type: ignore[attr-defined]
    module.QueryValueEx = fake.QueryValueEx  # type: ignore[attr-defined]
    _sys.modules["winreg"] = module
    try:
        return uninstall.find_prerequisite_uninstall_commands(manifest)
    finally:
        if original is not None:
            _sys.modules["winreg"] = original
        else:
            del _sys.modules["winreg"]


def test_find_prerequisite_uninstall_commands_non_windows_returns_empty(monkeypatch) -> None:
    manifest = PrerequisiteManifest(format_version="1.0", prerequisites=(_prereq("hslhttp"),))
    monkeypatch.setattr(uninstall.sys, "platform", "linux")

    assert uninstall.find_prerequisite_uninstall_commands(manifest) == {}


def test_run_prerequisite_uninstalls_dry_run(tmp_path: Path, caplog) -> None:
    commands = {"hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None)}

    with caplog.at_level(logging.INFO):
        success = uninstall.run_prerequisite_uninstalls(commands, dry_run=True)

    assert success == 1
    assert "DRY-RUN" in caplog.text


def test_run_prerequisite_uninstalls_prefers_quiet_string_when_silent(monkeypatch) -> None:
    commands = {"hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', '"C:\\App\\unins000.exe" /VERYSILENT')}
    captured: list[list[str]] = []

    def fake_run(cmd, check, shell):
        captured.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)

    success = uninstall.run_prerequisite_uninstalls(commands, silent=True)

    assert success == 1
    assert captured == [["C:\\App\\unins000.exe", "/VERYSILENT"]]


def test_run_prerequisite_uninstalls_appends_default_flags_without_quiet_string(monkeypatch) -> None:
    commands = {"hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None)}
    captured: list[list[str]] = []

    def fake_run(cmd, check, shell):
        captured.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)

    success = uninstall.run_prerequisite_uninstalls(commands, silent=True)

    assert success == 1
    assert captured == [["C:\\App\\unins000.exe", *uninstall.DEFAULT_UNINSTALL_SILENT_FLAGS]]


def test_run_prerequisite_uninstalls_uses_msi_silent_flags_for_msiexec(monkeypatch) -> None:
    commands = {"hslextensions": ("HSL Extensions", "MsiExec.exe /X{GUID}", None)}
    captured: list[list[str]] = []

    def fake_run(cmd, check, shell):
        captured.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)

    success = uninstall.run_prerequisite_uninstalls(commands, silent=True)

    assert success == 1
    assert captured == [["MsiExec.exe", "/X{GUID}", "/qn", "/norestart"]]


def test_run_prerequisite_uninstalls_reports_nonzero_exit_as_warning(monkeypatch, caplog) -> None:
    commands = {"hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None)}
    monkeypatch.setattr(uninstall.subprocess, "run", lambda *_a, **_k: MagicMock(returncode=3))

    with caplog.at_level(logging.WARNING):
        success = uninstall.run_prerequisite_uninstalls(commands)

    assert success == 0
    assert "finished with exit code 3" in caplog.text


def test_run_prerequisite_uninstalls_handles_exception(monkeypatch, caplog) -> None:
    commands = {"hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None)}

    def fake_run(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)

    with caplog.at_level(logging.ERROR):
        success = uninstall.run_prerequisite_uninstalls(commands)

    assert success == 0
    assert "Failed to uninstall" in caplog.text


def test_run_prerequisite_uninstalls_pauses_between_interactive_uninstalls(monkeypatch) -> None:
    commands = {
        "hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None),
        "other": ("Other Tool", '"C:\\App2\\unins000.exe"', None),
    }
    waited_for: list[str] = []

    monkeypatch.setattr(uninstall.subprocess, "run", lambda *_a, **_k: MagicMock(returncode=0))
    monkeypatch.setattr(uninstall, "_wait_for_interactive_uninstaller", waited_for.append)

    success = uninstall.run_prerequisite_uninstalls(commands, silent=False)

    assert success == 2
    assert waited_for == ["HSLHttp Library"]


def test_run_prerequisite_uninstalls_no_pause_when_silent(monkeypatch) -> None:
    commands = {
        "hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None),
        "other": ("Other Tool", '"C:\\App2\\unins000.exe"', None),
    }
    waited_for: list[str] = []

    monkeypatch.setattr(uninstall.subprocess, "run", lambda *_a, **_k: MagicMock(returncode=0))
    monkeypatch.setattr(uninstall, "_wait_for_interactive_uninstaller", waited_for.append)

    success = uninstall.run_prerequisite_uninstalls(commands, silent=True)

    assert success == 2
    assert waited_for == []


def test_run_prerequisite_uninstalls_no_pause_on_dry_run(monkeypatch) -> None:
    commands = {
        "hslhttp": ("HSLHttp Library", '"C:\\App\\unins000.exe"', None),
        "other": ("Other Tool", '"C:\\App2\\unins000.exe"', None),
    }
    waited_for: list[str] = []

    monkeypatch.setattr(uninstall, "_wait_for_interactive_uninstaller", waited_for.append)

    success = uninstall.run_prerequisite_uninstalls(commands, dry_run=True)

    assert success == 2
    assert waited_for == []


def _base_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "structure": Path("C:/sdk/sdk_method_structure"),
        "target": Path("C:/sdk/target"),
        "structure_only": False,
        "dry_run": True,
        "keep_registry": True,
        "keep_prereqs": False,
        "keep_py32": False,
        "manifest": None,
        "headless": False,
        "prompt": False,
        "verbose": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_main_purges_target_and_removes_registry_by_default(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args(keep_registry=False))
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: calls.append("purged") or 3)
    monkeypatch.setattr(uninstall, "remove_structure_tree", lambda *_a, **_k: calls.append("removed") or 3)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: calls.append("registry") or True)

    rc = uninstall.main([])

    assert rc == 0
    assert calls == ["purged", "registry"]


def test_main_removes_structure_only_when_flag_set(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        uninstall, "parse_args", lambda _argv=None: _base_args(keep_registry=False, structure_only=True)
    )
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: calls.append("purged") or 3)
    monkeypatch.setattr(uninstall, "remove_structure_tree", lambda *_a, **_k: calls.append("removed") or 3)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: calls.append("registry") or True)

    rc = uninstall.main([])

    assert rc == 0
    assert calls == ["removed", "registry"]


def test_main_returns_error_when_purge_target_unsafe(monkeypatch, caplog) -> None:
    def _raise(*_a: object, **_k: object) -> int:
        raise uninstall.UnsafePurgeTargetError("Refusing to purge a filesystem root: C:/")

    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args())
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", _raise)

    with caplog.at_level(logging.ERROR):
        rc = uninstall.main([])

    assert rc == 1
    assert "Refusing to purge" in caplog.text


def test_main_keeps_registry_when_flag_set(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args(keep_registry=True))
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: calls.append("registry") or True)

    rc = uninstall.main([])

    assert rc == 0
    assert calls == []


def test_main_keeps_prereqs_when_flag_set(monkeypatch) -> None:
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args(keep_prereqs=True))
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: True)

    rc = uninstall.main([])

    assert rc == 0


def test_main_removes_py32_runtime_by_default(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args())
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: True)
    monkeypatch.setattr(uninstall.py32_runtime, "remove_py32_runtime", lambda **_k: calls.append("py32") or True)

    rc = uninstall.main([])

    assert rc == 0
    assert calls == ["py32"]


def test_main_keeps_py32_runtime_when_flag_set(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args(keep_py32=True))
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: True)
    monkeypatch.setattr(uninstall.py32_runtime, "remove_py32_runtime", lambda **_k: calls.append("py32") or True)

    rc = uninstall.main([])

    assert rc == 0
    assert calls == []


def test_main_purges_prereqs_by_default(monkeypatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        '{"format_version": "1.0", "prerequisites": []}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        uninstall,
        "parse_args",
        lambda _argv=None: _base_args(keep_prereqs=False, manifest=manifest_path),
    )
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: True)
    monkeypatch.setattr(uninstall, "find_prerequisite_uninstall_commands", lambda _manifest: {})

    rc = uninstall.main([])

    assert rc == 0


def test_main_skips_prereq_purge_when_manifest_missing(monkeypatch, tmp_path: Path, caplog) -> None:
    monkeypatch.setattr(
        uninstall,
        "parse_args",
        lambda _argv=None: _base_args(keep_prereqs=False, manifest=tmp_path / "absent.json"),
    )
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "purge_target_tree", lambda *_a, **_k: 0)
    monkeypatch.setattr(uninstall, "clear_sdk_registry_path", lambda **_k: True)

    with caplog.at_level(logging.WARNING):
        rc = uninstall.main([])

    assert rc == 0
    assert "Skipping prerequisite uninstall" in caplog.text


def test_main_aborts_when_prompt_declined(monkeypatch) -> None:
    monkeypatch.setattr(uninstall, "parse_args", lambda _argv=None: _base_args(prompt=True))
    monkeypatch.setattr(structure, "warn_if_not_admin", lambda: None)
    monkeypatch.setattr(uninstall, "confirm", lambda *_a, **_k: False)

    rc = uninstall.main([])

    assert rc == 1


def test_default_paths_matches_structure_defaults(monkeypatch) -> None:
    sentinel = {"structure": Path("A"), "target": Path("B"), "repo_root": Path("C")}
    monkeypatch.setattr(structure, "default_paths", lambda: sentinel)

    assert uninstall.default_paths() == sentinel
