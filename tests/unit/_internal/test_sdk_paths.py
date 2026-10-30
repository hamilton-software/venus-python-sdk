from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

MODULE_NAME = "hamilton_venus._internal._sdk_paths"


def _reload_sdk_paths() -> object:
    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


def test_get_sdk_install_path_defaults_when_not_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    module = _reload_sdk_paths()

    assert module.get_sdk_install_path() == module.DEFAULT_SDK_INSTALL_PATH


def test_get_sdk_install_path_uses_registry_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    mock_key.__exit__.return_value = None
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (r"C:\custom\sdk", mock_winreg.REG_SZ)
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    module = _reload_sdk_paths()

    result = module.get_sdk_install_path()

    mock_winreg.OpenKey.assert_called_once_with(
        mock_winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Phoenix\Directories\SDK",
    )
    mock_winreg.QueryValueEx.assert_called_once_with(mock_key, "")
    assert Path(r"C:\custom\sdk") == result


def test_get_sdk_install_path_falls_back_when_registry_read_fails(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.side_effect = OSError("missing")
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    module = _reload_sdk_paths()

    assert module.get_sdk_install_path() == module.DEFAULT_SDK_INSTALL_PATH


def test_get_sdk_executor_hsl_path_uses_dynamic_install_path(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    mock_key.__exit__.return_value = None
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (r"C:\dynamic\sdk", mock_winreg.REG_SZ)
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    module = _reload_sdk_paths()

    result = module.get_sdk_executor_hsl_path()

    mock_winreg.OpenKey.assert_called_once_with(
        mock_winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Phoenix\Directories\SDK",
    )
    mock_winreg.QueryValueEx.assert_called_once_with(mock_key, "")
    assert result == Path(r"C:\dynamic\sdk\Method\VENUS_SDK_Executor.hsl")


def _winreg_returning(value: object) -> MagicMock:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    mock_key.__exit__.return_value = None
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (value, mock_winreg.REG_SZ)
    return mock_winreg


def test_read_instrument_cfg_name_returns_none_when_not_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    module = _reload_sdk_paths()
    assert module.read_instrument_cfg_name() is None


def test_read_instrument_cfg_name_reads_default_value_from_registry(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = _winreg_returning("VStar.cfg")
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    module = _reload_sdk_paths()

    assert module.read_instrument_cfg_name() == "VStar.cfg"
    mock_winreg.OpenKey.assert_called_once_with(
        mock_winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Phoenix\Instruments\ML_STAR\InstCfgFile",
    )
    mock_winreg.QueryValueEx.assert_called_once_with(mock_winreg.OpenKey.return_value, "")


def test_read_instrument_cfg_name_returns_none_when_key_missing(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = object()
    mock_winreg.OpenKey.side_effect = OSError("missing")
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    module = _reload_sdk_paths()

    assert module.read_instrument_cfg_name() is None


@pytest.mark.parametrize(
    ("cfg_name", "expected"),
    [
        ("VStar.cfg", "vantage"),
        ("vstar.CFG", "vantage"),
        ("HxVantage.cfg", "vantage"),
        ("ML_STAR.cfg", "star"),
        ("STARlet.cfg", "star"),
        ("", "star"),
        (None, "star"),
    ],
)
def test_detect_instrument_type_classifies_cfg_name(monkeypatch, cfg_name, expected) -> None:
    module = _reload_sdk_paths()
    monkeypatch.setattr(module, "read_instrument_cfg_name", lambda: cfg_name)
    assert module.detect_instrument_type() == expected


@pytest.mark.parametrize(
    ("cfg_name", "expected"),
    [("VStar.cfg", "vantage"), ("ML_STAR.cfg", "star"), (None, None)],
)
def test_installed_instrument_type_is_unknown_when_the_registry_is_silent(monkeypatch, cfg_name, expected) -> None:
    """A guard must not refuse on a guess: no registry value is None, not "star"."""
    module = _reload_sdk_paths()
    monkeypatch.setattr(module, "read_instrument_cfg_name", lambda: cfg_name)
    assert module.installed_instrument_type() == expected


@pytest.fixture(autouse=True)
def _cleanup_module() -> None:
    yield
    sys.modules.pop(MODULE_NAME, None)
