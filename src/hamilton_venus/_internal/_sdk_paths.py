from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

DEFAULT_SDK_INSTALL_PATH = Path(r"C:\Program Files (x86)\HAMILTON\SDK")
REGISTRY_KEY_PATH = r"SOFTWARE\WOW6432Node\Phoenix\Directories\SDK"
REGISTRY_VALUE_NAME = ""

# The VENUS instrument-config file name lives at the ``(Default)`` value of this
# key -- ``VStar.cfg`` on a Vantage install, ``ML_STAR.cfg`` on a STAR install. A
# single VENUS install is one instrument or the other, never both.
INSTRUMENT_CFG_REGISTRY_KEY_PATH = r"SOFTWARE\WOW6432Node\Phoenix\Instruments\ML_STAR\InstCfgFile"


def _sdk_path(*parts: str) -> Path:
    if sys.platform == "win32":
        return Path(str(PureWindowsPath(*parts)))
    return Path(*parts)


def _read_sdk_install_path_from_registry() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
    except (ImportError, OSError, ValueError):
        return None
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def get_sdk_install_path() -> Path:
    return _read_sdk_install_path_from_registry() or DEFAULT_SDK_INSTALL_PATH


def read_instrument_cfg_name() -> str | None:
    """The ``(Default)`` value of
    ``HKLM\\SOFTWARE\\WOW6432Node\\Phoenix\\Instruments\\ML_STAR\\InstCfgFile`` --
    the VENUS instrument-config file name for this machine (e.g. ``"VStar.cfg"``
    on a Vantage install, ``"ML_STAR.cfg"`` on a STAR install). ``None`` when the
    key is missing or unreadable (non-Windows, or no VENUS installed).
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, INSTRUMENT_CFG_REGISTRY_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
    except (ImportError, OSError, ValueError):
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def detect_instrument_type() -> str:
    """``"vantage"`` or ``"star"`` for the VENUS instrument installed on this
    machine.

    Classified from the ``InstCfgFile`` registry value: ``VStar.cfg`` (or any
    Vantage-flavoured name) -> ``"vantage"``; everything else, including a
    missing or unreadable key, -> ``"star"``.
    """
    name = (read_instrument_cfg_name() or "").lower()
    if name.startswith("vstar") or "vantage" in name:
        return "vantage"
    return "star"


def installed_instrument_type() -> str | None:
    """``"vantage"`` or ``"star"`` for the installed VENUS, like :func:`detect_instrument_type`,
    but ``None`` when the registry doesn't say (no VENUS, non-Windows, or the key is
    unreadable) instead of assuming STAR -- for callers that refuse a mismatch and must not
    refuse on a guess."""
    name = read_instrument_cfg_name()
    if name is None:
        return None
    return detect_instrument_type()


def get_sdk_executor_hsl_path() -> Path:
    return _sdk_path(str(get_sdk_install_path()), "Method", "VENUS_SDK_Executor.hsl")


def get_sdk_active_layout_path() -> Path:
    return _sdk_path(str(get_sdk_install_path()), "Active Layout")


def get_sdk_labware_path() -> Path:
    return _sdk_path(str(get_sdk_install_path()), "Labware")


def get_sdk_liquid_class_path() -> Path:
    return _sdk_path(str(get_sdk_install_path()), "Liquid Class")
