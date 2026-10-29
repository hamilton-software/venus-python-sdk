from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus._internal._sdk_paths import REGISTRY_KEY_PATH, REGISTRY_VALUE_NAME
from hamilton_venus.setup_tools import structure

skipif_not_windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")


def test_extract_ace_fields_handles_four_tuple_shape() -> None:
    ace_sid, ace_flags, ace_mask = structure._extract_ace_fields((0, 0x3, 0xA, "sid"))
    assert ace_sid == "sid"
    assert ace_flags == 0x3
    assert ace_mask == 0xA


def test_extract_ace_fields_handles_three_tuple_shape() -> None:
    ace_sid, ace_flags, ace_mask = structure._extract_ace_fields(((0, 0x3), 0xA, "sid"))
    assert ace_sid == "sid"
    assert ace_flags == 0x3
    assert ace_mask == 0xA


def test_extract_ace_fields_raises_on_unknown_shape() -> None:
    with pytest.raises(ValueError, match="Unsupported ACE shape"):
        structure._extract_ace_fields((1, 2))


def test_install_structure_default_paths_use_env_override(monkeypatch) -> None:
    override_root = Path(r"C:\override-sdk")
    monkeypatch.setenv("HAMILTON_VENUS_SDK_ROOT", str(override_root))

    defaults = structure.default_paths()

    expected_root = Path(str(override_root)).expanduser().resolve()
    assert defaults["repo_root"] == expected_root
    assert defaults["structure"] == expected_root / "sdk_method_structure"


def test_install_structure_default_paths_prefer_cwd_discovered_sdk_root(tmp_path: Path, monkeypatch) -> None:
    sdk_root = tmp_path / "sdk-root"
    (sdk_root / "prerequisites").mkdir(parents=True)
    (sdk_root / "sdk_method_structure").mkdir(parents=True)
    nested = sdk_root / "nested" / "deeper"
    nested.mkdir(parents=True)

    monkeypatch.delenv("HAMILTON_VENUS_SDK_ROOT", raising=False)
    monkeypatch.chdir(nested)

    defaults = structure.default_paths()

    assert defaults["repo_root"] == sdk_root
    assert defaults["structure"] == sdk_root / "sdk_method_structure"


def test_copy_tree_raises_when_source_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"Source.*not found"):
        structure.copy_tree(tmp_path / "missing", tmp_path / "target")


def test_copy_tree_skips_existing_when_not_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")
    (dst / "a.txt").write_text("old", encoding="utf-8")

    copied = structure.copy_tree(src, dst, overwrite=False)

    assert copied == 0
    assert (dst / "a.txt").read_text(encoding="utf-8") == "old"


def test_copy_tree_overwrites_existing_when_overwrite_true(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("new", encoding="utf-8")
    (dst / "a.txt").write_text("old", encoding="utf-8")

    copied = structure.copy_tree(src, dst, overwrite=True)

    assert copied == 1
    assert (dst / "a.txt").read_text(encoding="utf-8") == "new"


def test_copy_tree_dry_run_counts_without_writing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    copied = structure.copy_tree(src, dst, dry_run=True)

    assert copied == 1
    assert not (dst / "a.txt").exists()


def test_set_sdk_registry_path_dry_run_logs(caplog, tmp_path: Path) -> None:
    target = tmp_path / "SDK"

    with caplog.at_level(logging.INFO):
        result = structure.set_sdk_registry_path(target, dry_run=True)

    assert result is True
    assert "[DRY-RUN] Would set registry" in caplog.text
    assert REGISTRY_KEY_PATH in caplog.text


def test_structure_parse_args_accepts_target_override(tmp_path: Path) -> None:
    structure_path = tmp_path / "structure"
    target_path = tmp_path / "custom_sdk"

    args = structure.parse_args(["--structure", str(structure_path), "--target", str(target_path)])

    assert args.structure == structure_path
    assert args.target == target_path


def test_main_uses_target_override_for_copy_and_registry(monkeypatch, tmp_path: Path) -> None:
    structure_path = tmp_path / "structure"
    target_path = tmp_path / "custom_sdk"
    structure_path.mkdir()

    monkeypatch.setattr(
        structure,
        "parse_args",
        lambda _argv=None: structure.argparse.Namespace(
            structure=structure_path,
            target=target_path,
            dry_run=True,
            force=False,
            prompt=False,
            verbose=False,
        ),
    )

    copied_calls: list[Path] = []
    registry_calls: list[Path] = []

    def _copy_tree(src: Path, dst: Path, *, dry_run: bool, overwrite: bool) -> int:
        copied_calls.append(dst)
        return 0

    def _set_registry(path: Path, *, dry_run: bool) -> bool:
        registry_calls.append(path)
        return True

    monkeypatch.setattr(structure, "collect_version_errors", lambda: [])
    monkeypatch.setattr(structure, "copy_tree", _copy_tree)
    monkeypatch.setattr(structure, "set_folder_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(structure, "set_sdk_registry_path", _set_registry)

    rc = structure.main([])

    assert rc == 0
    assert copied_calls == [target_path.resolve()]
    assert registry_calls == [target_path.resolve()]


def test_main_continues_when_registry_update_fails(monkeypatch, tmp_path: Path, caplog) -> None:
    structure_path = tmp_path / "structure"
    target_path = tmp_path / "custom_sdk"
    structure_path.mkdir()

    monkeypatch.setattr(
        structure,
        "parse_args",
        lambda _argv=None: structure.argparse.Namespace(
            structure=structure_path,
            target=target_path,
            dry_run=True,
            force=False,
            prompt=False,
            verbose=False,
        ),
    )
    monkeypatch.setattr(structure, "collect_version_errors", lambda: [])
    monkeypatch.setattr(structure, "copy_tree", lambda *_args, **_kwargs: 5)
    monkeypatch.setattr(structure, "set_folder_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(structure, "set_sdk_registry_path", lambda *_args, **_kwargs: False)

    with caplog.at_level(logging.WARNING):
        rc = structure.main([])

    assert rc == 0
    assert "registry path update did not complete" in caplog.text


def test_main_returns_1_when_prompt_enabled_and_user_declines(monkeypatch, tmp_path: Path) -> None:
    structure_path = tmp_path / "structure"
    target_path = tmp_path / "custom_sdk"
    structure_path.mkdir()

    monkeypatch.setattr(
        structure,
        "parse_args",
        lambda _argv=None: structure.argparse.Namespace(
            structure=structure_path,
            target=target_path,
            dry_run=True,
            force=False,
            prompt=True,
            verbose=False,
        ),
    )
    monkeypatch.setattr(structure, "collect_version_errors", lambda: [])
    monkeypatch.setattr(structure, "confirm", lambda *_args, **_kwargs: False)

    rc = structure.main([])

    assert rc == 1


def test_set_sdk_registry_path_non_windows_returns_false(monkeypatch, caplog, tmp_path: Path) -> None:
    target = tmp_path / "SDK"
    monkeypatch.setattr(structure.sys, "platform", "linux")

    with caplog.at_level(logging.INFO):
        result = structure.set_sdk_registry_path(target)

    assert result is False
    assert "Skipping registry update on non-Windows platform" in caplog.text


@skipif_not_windows
def test_set_sdk_registry_path_sets_value_on_windows(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "SDK"
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    mock_key.__exit__.return_value = None
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.REG_SZ = 1
    mock_winreg.CreateKey.return_value = mock_key

    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    result = structure.set_sdk_registry_path(target)

    assert result is True
    mock_winreg.CreateKey.assert_called_once_with(
        mock_winreg.HKEY_LOCAL_MACHINE,
        REGISTRY_KEY_PATH,
    )
    mock_winreg.SetValueEx.assert_called_once_with(
        mock_key,
        REGISTRY_VALUE_NAME,
        0,
        mock_winreg.REG_SZ,
        str(target.resolve()),
    )


def test_set_sdk_registry_path_permission_error_returns_false(monkeypatch, caplog, tmp_path: Path) -> None:
    target = tmp_path / "SDK"
    monkeypatch.setattr(structure.sys, "platform", "win32")

    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.REG_SZ = 1
    mock_winreg.CreateKey.side_effect = PermissionError("denied")

    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    with caplog.at_level(logging.WARNING):
        result = structure.set_sdk_registry_path(target)

    assert result is False
    assert "Unable to set SDK registry path due to permissions" in caplog.text


def test_install_structure_default_target_path(monkeypatch) -> None:
    monkeypatch.setattr(structure, "get_sdk_install_path", lambda: Path(r"C:\Program Files (x86)\HAMILTON\SDK"))
    defaults = structure.default_paths()
    assert defaults["target"] == Path(r"C:\Program Files (x86)\HAMILTON\SDK")


@skipif_not_windows
def test_is_admin_returns_true_when_admin() -> None:
    with patch("hamilton_venus.setup_tools.structure.ctypes.windll.shell32.IsUserAnAdmin", return_value=1, create=True):
        assert structure._is_admin() is True


@skipif_not_windows
def test_is_admin_returns_false_when_not_admin() -> None:
    with patch("hamilton_venus.setup_tools.structure.ctypes.windll.shell32.IsUserAnAdmin", return_value=0, create=True):
        assert structure._is_admin() is False


@skipif_not_windows
def test_is_admin_returns_false_on_exception() -> None:
    with patch(
        "hamilton_venus.setup_tools.structure.ctypes.windll.shell32.IsUserAnAdmin",
        side_effect=AttributeError("No windll"),
        create=True,
    ):
        assert structure._is_admin() is False


def test_warn_if_not_admin_logs_warning_when_not_admin_on_windows(caplog) -> None:
    with (
        patch("hamilton_venus.setup_tools.structure._is_windows", return_value=True),
        patch("hamilton_venus.setup_tools.structure._is_admin", return_value=False),
        caplog.at_level(logging.WARNING),
    ):
        structure.warn_if_not_admin()
    assert "Administrator privileges are recommended" in caplog.text


def test_warn_if_not_admin_no_warning_when_admin(caplog) -> None:
    with (
        patch("hamilton_venus.setup_tools.structure._is_windows", return_value=True),
        patch("hamilton_venus.setup_tools.structure._is_admin", return_value=True),
        caplog.at_level(logging.WARNING),
    ):
        structure.warn_if_not_admin()
    assert "Administrator privileges are recommended" not in caplog.text


def test_warn_if_not_admin_no_warning_on_non_windows(caplog) -> None:
    with (
        patch("hamilton_venus.setup_tools.structure._is_windows", return_value=False),
        caplog.at_level(logging.WARNING),
    ):
        structure.warn_if_not_admin()
    assert "Administrator privileges are recommended" not in caplog.text


def _mock_venus_registry(monkeypatch, version: str | None) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    mock_key.__exit__.return_value = None
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.return_value = mock_key
    if version is None:
        mock_winreg.OpenKey.side_effect = OSError("not found")
    else:
        mock_winreg.QueryValueEx.return_value = (version, 1)
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)


def test_check_venus_version_errors_when_below_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure, "_is_windows", lambda: True)
    _mock_venus_registry(monkeypatch, "6.4.0.12345")

    error = structure.check_venus_version()

    assert error is not None
    assert "Installed VENUS version 6.4.0.12345 is older than the minimum supported version 6.5" in error


def test_check_venus_version_none_when_at_or_above_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure, "_is_windows", lambda: True)
    _mock_venus_registry(monkeypatch, "6.6.0.50481")

    assert structure.check_venus_version() is None


def test_check_venus_version_errors_when_registry_key_missing(monkeypatch) -> None:
    monkeypatch.setattr(structure, "_is_windows", lambda: True)
    _mock_venus_registry(monkeypatch, None)

    error = structure.check_venus_version()

    assert error is not None
    assert "Could not detect an installed VENUS version" in error


def test_check_venus_version_none_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(structure, "_is_windows", lambda: False)

    assert structure.check_venus_version() is None


def test_check_python_version_errors_when_below_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure.sys, "version_info", (3, 9, 7))

    error = structure.check_python_version()

    assert error is not None
    assert "Python 3.9.7" in error
    assert "requires Python 3.11" in error


def test_check_python_version_none_when_at_or_above_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure.sys, "version_info", (3, 13, 4))

    assert structure.check_python_version() is None


def test_check_python_version_errors_just_below_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure.sys, "version_info", (3, 10, 99))

    assert structure.check_python_version() is not None


def test_check_python_version_none_exactly_at_minimum(monkeypatch) -> None:
    monkeypatch.setattr(structure.sys, "version_info", (3, 11, 0))

    assert structure.check_python_version() is None


def test_collect_version_errors_combines_python_and_venus_errors(monkeypatch) -> None:
    monkeypatch.setattr(structure, "check_python_version", lambda: "python too old")
    monkeypatch.setattr(structure, "check_venus_version", lambda: "venus too old")

    assert structure.collect_version_errors() == ["python too old", "venus too old"]


def test_collect_version_errors_empty_when_all_satisfied(monkeypatch) -> None:
    monkeypatch.setattr(structure, "check_python_version", lambda: None)
    monkeypatch.setattr(structure, "check_venus_version", lambda: None)

    assert structure.collect_version_errors() == []


def test_main_stops_with_clear_reason_when_venus_too_old(monkeypatch, tmp_path: Path, caplog) -> None:
    structure_path = tmp_path / "structure"
    structure_path.mkdir()

    monkeypatch.setattr(
        structure,
        "parse_args",
        lambda _argv=None: structure.argparse.Namespace(
            structure=structure_path,
            target=tmp_path / "sdk",
            dry_run=True,
            force=False,
            prompt=False,
            verbose=False,
        ),
    )
    monkeypatch.setattr(
        structure,
        "collect_version_errors",
        lambda: ["Installed VENUS version 6.4.0.1 is older than the minimum supported version 6.5."],
    )
    copy_calls: list[Path] = []
    monkeypatch.setattr(structure, "copy_tree", lambda *_a, **_k: copy_calls.append(_a) or 0)

    with caplog.at_level(logging.ERROR):
        rc = structure.main([])

    assert rc == 2
    assert "older than the minimum supported version 6.5" in caplog.text
    assert copy_calls == []


def test_main_stops_with_clear_reason_when_python_too_old(monkeypatch, tmp_path: Path, caplog) -> None:
    structure_path = tmp_path / "structure"
    structure_path.mkdir()

    monkeypatch.setattr(
        structure,
        "parse_args",
        lambda _argv=None: structure.argparse.Namespace(
            structure=structure_path,
            target=tmp_path / "sdk",
            dry_run=True,
            force=False,
            prompt=False,
            verbose=False,
        ),
    )
    monkeypatch.setattr(
        structure,
        "collect_version_errors",
        lambda: ["Python 3.8.10 is running this setup, but the SDK requires Python 3.11 or newer."],
    )

    with caplog.at_level(logging.ERROR):
        rc = structure.main([])

    assert rc == 2
    assert "requires Python 3.11 or newer" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_skips_when_pywin32_not_available(caplog, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()

    def mock_import_error(*args, **kwargs):
        raise ImportError("No module named 'win32security'")

    monkeypatch.setitem(sys.modules, "ntsecuritycon", None)
    monkeypatch.setitem(sys.modules, "win32security", None)
    with (
        patch("builtins.__import__", side_effect=mock_import_error),
        caplog.at_level(logging.WARNING),
    ):
        structure.set_folder_permissions(target)
    assert "python -m pip install pywin32" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_warns_when_path_missing(caplog, tmp_path: Path, monkeypatch) -> None:
    missing_path = tmp_path / "missing"
    mock_win32security = MagicMock()
    mock_ntsecuritycon = MagicMock()

    monkeypatch.setitem(sys.modules, "win32security", mock_win32security)
    monkeypatch.setitem(sys.modules, "ntsecuritycon", mock_ntsecuritycon)
    with caplog.at_level(logging.WARNING):
        structure.set_folder_permissions(missing_path)
    assert "does not exist" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_dry_run_logs_info(caplog, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()

    mock_win32security = MagicMock()
    mock_ntsecuritycon = MagicMock()

    monkeypatch.setitem(sys.modules, "win32security", mock_win32security)
    monkeypatch.setitem(sys.modules, "ntsecuritycon", mock_ntsecuritycon)
    with caplog.at_level(logging.INFO):
        structure.set_folder_permissions(target, dry_run=True)
    assert "[DRY-RUN]" in caplog.text
    assert "Would set folder permissions" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_sets_acl_successfully(tmp_path: Path, caplog, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()

    mock_win32security = MagicMock()
    mock_ntsecuritycon = MagicMock()
    mock_dacl = MagicMock()
    mock_new_dacl = MagicMock()
    mock_security_descriptor = MagicMock()
    mock_security_descriptor.GetSecurityDescriptorDacl.return_value = mock_dacl
    mock_win32security.GetNamedSecurityInfo.return_value = mock_security_descriptor
    mock_win32security.ConvertStringSidToSid.return_value = b"user_sid"
    mock_win32security.ACL.return_value = mock_new_dacl
    mock_dacl.GetAceCount.return_value = 0
    mock_ntsecuritycon.FILE_GENERIC_READ = 1
    mock_ntsecuritycon.FILE_GENERIC_WRITE = 2
    mock_ntsecuritycon.FILE_GENERIC_EXECUTE = 4
    mock_ntsecuritycon.DELETE = 8

    monkeypatch.setitem(sys.modules, "win32security", mock_win32security)
    monkeypatch.setitem(sys.modules, "ntsecuritycon", mock_ntsecuritycon)
    with caplog.at_level(logging.INFO):
        structure.set_folder_permissions(target)

    mock_win32security.GetNamedSecurityInfo.assert_called_once()
    mock_win32security.ConvertStringSidToSid.assert_called_once_with(structure.USERS_SID)
    mock_new_dacl.AddAccessAllowedAceEx.assert_called_once()
    mock_win32security.SetNamedSecurityInfo.assert_called_once()
    assert "Added Users modify-style access" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_skips_when_access_already_present(tmp_path: Path, caplog, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()

    mock_win32security = MagicMock()
    mock_ntsecuritycon = MagicMock()
    mock_dacl = MagicMock()
    mock_security_descriptor = MagicMock()
    mock_security_descriptor.GetSecurityDescriptorDacl.return_value = mock_dacl
    mock_win32security.GetNamedSecurityInfo.return_value = mock_security_descriptor
    mock_users_sid = b"user_sid"
    mock_win32security.ConvertStringSidToSid.return_value = mock_users_sid
    mock_dacl.GetAceCount.return_value = 1
    mock_win32security.CONTAINER_INHERIT_ACE = 0x2
    mock_win32security.OBJECT_INHERIT_ACE = 0x1
    mock_ntsecuritycon.FILE_GENERIC_READ = 1
    mock_ntsecuritycon.FILE_GENERIC_WRITE = 2
    mock_ntsecuritycon.FILE_GENERIC_EXECUTE = 4
    mock_ntsecuritycon.DELETE = 8
    existing_mask = 1 | 2 | 4 | 8
    mock_dacl.GetAce.return_value = ((0, 0x3), existing_mask, mock_users_sid)

    monkeypatch.setitem(sys.modules, "win32security", mock_win32security)
    monkeypatch.setitem(sys.modules, "ntsecuritycon", mock_ntsecuritycon)
    with caplog.at_level(logging.INFO):
        structure.set_folder_permissions(target)

    mock_win32security.SetNamedSecurityInfo.assert_not_called()
    assert "already include required Users access" in caplog.text


@skipif_not_windows
def test_set_folder_permissions_handles_exception(tmp_path: Path, caplog, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()

    mock_win32security = MagicMock()
    mock_ntsecuritycon = MagicMock()
    mock_security_descriptor = MagicMock()
    mock_win32security.GetNamedSecurityInfo.return_value = mock_security_descriptor
    mock_win32security.ConvertStringSidToSid.side_effect = Exception("ACL error")

    monkeypatch.setitem(sys.modules, "win32security", mock_win32security)
    monkeypatch.setitem(sys.modules, "ntsecuritycon", mock_ntsecuritycon)
    with caplog.at_level(logging.WARNING):
        structure.set_folder_permissions(target)
    assert "Failed to set folder permissions" in caplog.text
