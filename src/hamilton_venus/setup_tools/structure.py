from __future__ import annotations

import argparse
import ctypes
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from hamilton_venus._internal._sdk_paths import REGISTRY_KEY_PATH, REGISTRY_VALUE_NAME, get_sdk_install_path
from hamilton_venus.setup_tools.root_discovery import find_sdk_root
from hamilton_venus.setup_tools.version_detection import compare_versions

logger = logging.getLogger("venus_install_structure")

USERS_SID = "S-1-5-32-545"

VENUS_RELEASE_REGISTRY_KEY = r"SOFTWARE\WOW6432Node\Phoenix\Release"
MIN_VENUS_VERSION = "6.5"
# The SDK uses enum.StrEnum (added in Python 3.11) -- an interpreter older than this
# fails with a bare ImportError deep inside a top-level `from enum import StrEnum`
# (observed live under Python 3.10) before this check ever runs, since that import
# happens as a side effect of importing this package at all. This check is still worth
# keeping as defense-in-depth for anything that doesn't hit that exact import path, but
# the installer's own find-python step (installer/shell/InstallRunner.cs) is the
# earliest point that can actually catch it -- it runs before any Python code from this
# package has executed.
#
# The floor is 3.11: the SDK uses enum.StrEnum, added in 3.11.
REQUIRED_PYTHON_VERSION = (3, 11)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_admin() -> bool:
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        return bool(windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def warn_if_not_admin() -> None:
    if not _is_windows():
        return
    if not _is_admin():
        logger.warning(
            "Administrator privileges are recommended for registry and ACL updates. "
            "Setup will continue, but some post-install behavior may require manual fixes."
        )


def _read_venus_version_from_registry() -> str | None:
    if not _is_windows():
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VENUS_RELEASE_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "")
    except OSError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def check_venus_version() -> str | None:
    """Return a blocking error message if VENUS is missing or older than the minimum, else None."""
    if not _is_windows():
        return None
    version = _read_venus_version_from_registry()
    if version is None:
        return (
            f"Could not detect an installed VENUS version (registry key HKLM\\{VENUS_RELEASE_REGISTRY_KEY} "
            f"not found). This SDK requires VENUS {MIN_VENUS_VERSION} or newer -- install/upgrade VENUS, "
            "then re-run setup."
        )
    if compare_versions(version, MIN_VENUS_VERSION) == -1:
        return (
            f"Installed VENUS version {version} is older than the minimum supported version "
            f"{MIN_VENUS_VERSION}. The SDK will not work correctly against this VENUS version -- "
            "upgrade VENUS, then re-run setup."
        )
    return None


def check_python_version() -> str | None:
    """Return a blocking error message if the running interpreter is older than the minimum, else None."""
    if sys.version_info < REQUIRED_PYTHON_VERSION:
        installed = ".".join(str(part) for part in sys.version_info[:3])
        required = ".".join(str(part) for part in REQUIRED_PYTHON_VERSION)
        return (
            f"Python {installed} is running this setup, but the SDK requires Python {required} or newer. "
            "Install a newer Python, recreate the virtual environment with it, and re-run setup."
        )
    return None


def collect_version_errors() -> list[str]:
    """Return every blocking prerequisite-version error, or an empty list if all requirements are met."""
    return [message for message in (check_python_version(), check_venus_version()) if message is not None]


def _resolve_modify_permissions(ntsecuritycon: Any) -> int:
    return int(
        ntsecuritycon.FILE_GENERIC_READ
        | ntsecuritycon.FILE_GENERIC_WRITE
        | ntsecuritycon.FILE_GENERIC_EXECUTE
        | ntsecuritycon.DELETE
    )


def _extract_ace_fields(ace: Any) -> tuple[Any, Any, Any]:
    if isinstance(ace, tuple) and len(ace) >= 4:
        return ace[3], ace[1], ace[2]
    if isinstance(ace, tuple) and len(ace) == 3:
        header, ace_mask, ace_sid = ace
        ace_flags = header[1] if isinstance(header, tuple) and len(header) >= 2 else 0
        return ace_sid, ace_flags, ace_mask
    raise ValueError(f"Unsupported ACE shape: {ace!r}")


def set_folder_permissions(path: Path, *, dry_run: bool = False) -> None:
    if not _is_windows():
        return

    try:
        import ntsecuritycon
        import win32security
    except ImportError:
        logger.warning(
            "Unable to set folder permissions because pywin32 is not available. "
            "On Windows this should come from `pip install .`; if needed, install with "
            "`python -m pip install pywin32`, then re-run setup, or manually configure permissions on %s",
            path,
        )
        return

    if not path.exists():
        logger.warning("Cannot set permissions: path does not exist: %s", path)
        return

    if dry_run:
        logger.info("[DRY-RUN] Would set folder permissions on: %s", path)
        return

    try:
        security_descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        existing_dacl = security_descriptor.GetSecurityDescriptorDacl()
        users_sid = win32security.ConvertStringSidToSid(USERS_SID)
        access_mask = _resolve_modify_permissions(ntsecuritycon)
        inherit_flags = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE

        users_ace_exists = False
        if existing_dacl:
            for i in range(existing_dacl.GetAceCount()):
                ace: Any = existing_dacl.GetAce(i)
                ace_sid, ace_flags, ace_mask = _extract_ace_fields(ace)
                if ace_sid == users_sid and ace_flags == inherit_flags and (ace_mask & access_mask) == access_mask:
                    users_ace_exists = True
                    break

        if users_ace_exists:
            logger.info("Folder permissions already include required Users access: %s", path)
            return

        new_dacl = win32security.ACL()
        if existing_dacl:
            for i in range(existing_dacl.GetAceCount()):
                ace = existing_dacl.GetAce(i)
                ace_sid, ace_flags, ace_mask = _extract_ace_fields(ace)
                new_dacl.AddAccessAllowedAceEx(
                    win32security.ACL_REVISION,
                    ace_flags,
                    ace_mask,
                    ace_sid,
                )

        new_dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            inherit_flags,
            access_mask,
            users_sid,
        )

        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None,
            None,
            new_dacl,
            None,
        )
        logger.info("Added Users modify-style access to: %s", path)
    except Exception as e:
        logger.warning("Failed to set folder permissions on %s: %s", path, e)


def copy_tree(src: Path, dst: Path, *, dry_run: bool = False, overwrite: bool = False) -> int:
    src = src.resolve()
    dst = dst.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    files_copied = 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dst.joinpath(rel)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            s = Path(root) / f
            t = target_dir / f
            if t.exists() and not overwrite:
                logger.debug("Skipping existing: %s", t)
                continue
            logger.info("Copying %s -> %s", s, t)
            if not dry_run:
                shutil.copy2(s, t)
            files_copied += 1
    return files_copied


def set_sdk_registry_path(path: Path, *, dry_run: bool = False) -> bool:
    value = str(path.resolve())
    if dry_run:
        logger.info(
            "[DRY-RUN] Would set registry: HKLM\\%s (default) = %s",
            REGISTRY_KEY_PATH,
            value,
        )
        return True

    if not _is_windows():
        logger.info("Skipping registry update on non-Windows platform")
        return False

    try:
        import winreg

        winreg_mod: Any = winreg
        hkey_local_machine = winreg_mod.HKEY_LOCAL_MACHINE
        reg_sz = winreg_mod.REG_SZ
        create_key = winreg_mod.CreateKey
        set_value_ex = winreg_mod.SetValueEx

        with create_key(hkey_local_machine, REGISTRY_KEY_PATH) as key:
            set_value_ex(key, REGISTRY_VALUE_NAME, 0, reg_sz, value)
        logger.info(
            "Set registry: HKLM\\%s (default) = %s",
            REGISTRY_KEY_PATH,
            value,
        )
        return True
    except PermissionError as e:
        logger.warning("Unable to set SDK registry path due to permissions: %s", e)
    except OSError as e:
        logger.warning("Unable to set SDK registry path: %s", e)
    return False


def configure_heater_cooler(*, dry_run: bool = False) -> bool:
    """Best-effort HeaterCooler setup: write the 32-bit-Python binding config and
    grant ``Users`` write access to the vendor driver's ProgramData log tree.

    Delegates to :func:`hamilton_venus.heater_cooler.configure_heater_cooler`.
    **Never raises** -- a missing driver, non-Windows host, or non-admin run just
    logs a warning (the SDK still works: it bridges through the bundled 32-bit
    Python, else falls back to simulation).
    """
    if dry_run:
        logger.info("[DRY-RUN] Would configure HeaterCooler (py32 binding config + ProgramData ACL)")
        return True
    if not _is_windows():
        logger.info("Skipping HeaterCooler configuration on non-Windows platform")
        return False
    try:
        from hamilton_venus.heater_cooler import (
            configure_heater_cooler as _configure,
        )
        from hamilton_venus.heater_cooler import (
            heater_cooler_com_diagnosis,
        )

        ok, message = _configure()
        (logger.info if ok else logger.warning)("HeaterCooler: %s", message)
        logger.info("HeaterCooler COM status: %s", heater_cooler_com_diagnosis())
        return ok
    except Exception as e:
        logger.warning("Could not configure HeaterCooler: %s", e)
        return False


def configure_odtc(*, dry_run: bool = False) -> bool:
    """Best-effort ODTC setup: grant ``Users`` write access to the vendor
    driver's ProgramData log tree.

    Delegates to :func:`hamilton_venus.odtc.configure_odtc`. **Never raises**
    -- a missing driver, non-Windows host, or non-admin run just logs a
    warning (the SDK still works: it bridges through the bundled 32-bit
    Python, else falls back to simulation).
    """
    if dry_run:
        logger.info("[DRY-RUN] Would configure ODTC (ProgramData ACL)")
        return True
    if not _is_windows():
        logger.info("Skipping ODTC configuration on non-Windows platform")
        return False
    try:
        from hamilton_venus.odtc import configure_odtc as _configure
        from hamilton_venus.odtc import odtc_com_diagnosis

        ok, message = _configure()
        (logger.info if ok else logger.warning)("ODTC: %s", message)
        logger.info("ODTC COM status: %s", odtc_com_diagnosis())
        return ok
    except Exception as e:
        logger.warning("Could not configure ODTC: %s", e)
        return False


def configure_inheco_tec(*, dry_run: bool = False) -> bool:
    """Best-effort InhecoTEC setup (currently a presence check only -- the
    vendor driver ships with no external config, unlike HHC/ODTC).

    Delegates to :func:`hamilton_venus.inheco_tec.configure_inheco_tec`.
    **Never raises** -- a missing driver or non-Windows host just logs a
    message (the SDK still works: it bridges through the bundled 32-bit
    Python, else falls back to simulation).
    """
    if dry_run:
        logger.info("[DRY-RUN] Would configure InhecoTEC (presence check only)")
        return True
    if not _is_windows():
        logger.info("Skipping InhecoTEC configuration on non-Windows platform")
        return False
    try:
        from hamilton_venus.inheco_tec import configure_inheco_tec as _configure
        from hamilton_venus.inheco_tec import inheco_tec_com_diagnosis

        ok, message = _configure()
        (logger.info if ok else logger.warning)("InhecoTEC: %s", message)
        logger.info("InhecoTEC COM status: %s", inheco_tec_com_diagnosis())
        return ok
    except Exception as e:
        logger.warning("Could not configure InhecoTEC: %s", e)
        return False


def configure_tilt_module(*, dry_run: bool = False) -> bool:
    """Best-effort Tilt Module check (a pywin32 presence check only -- the module is
    driven over RS-232, so there is no COM object, config file or ACL to set up).

    Delegates to :func:`hamilton_venus.tilt_module.configure_tilt_module`.
    **Never raises** -- without pywin32 the driver falls back to simulation.
    """
    if dry_run:
        logger.info("[DRY-RUN] Would check the Tilt Module serial transport (presence check only)")
        return True
    if not _is_windows():
        logger.info("Skipping Tilt Module configuration on non-Windows platform")
        return False
    try:
        from hamilton_venus.tilt_module import configure_tilt_module as _configure
        from hamilton_venus.tilt_module import tilt_module_diagnosis

        ok, message = _configure()
        (logger.info if ok else logger.warning)("%s", message)
        logger.info("Tilt Module status: %s", tilt_module_diagnosis())
        return ok
    except Exception as e:
        logger.warning("Could not check the Tilt Module: %s", e)
        return False


def configure_media_fill(*, dry_run: bool = False) -> bool:
    """Best-effort Hamilton Media Fill Module setup: give the bundled 32-bit Python
    VENUS's .NET 4 ``<startup>`` setting for the vendor's .NET 2.0 ``HxMediaFill.dll``,
    and check its COM registration.

    Delegates to :func:`hamilton_venus.media_fill.configure_media_fill`. **Never
    raises** -- a missing driver, non-Windows host, or non-admin run just logs a
    warning (the SDK still works: it bridges through the bundled 32-bit Python,
    else falls back to simulation).
    """
    if dry_run:
        logger.info("[DRY-RUN] Would configure the Media Fill Module (32-bit Python .NET 4 setting)")
        return True
    if not _is_windows():
        logger.info("Skipping Media Fill Module configuration on non-Windows platform")
        return False
    try:
        from hamilton_venus.media_fill import configure_media_fill as _configure
        from hamilton_venus.media_fill import media_fill_com_diagnosis

        ok, message = _configure()
        (logger.info if ok else logger.warning)("Media Fill: %s", message)
        logger.info("Media Fill COM status: %s", media_fill_com_diagnosis())
        return ok
    except Exception as e:
        logger.warning("Could not configure the Media Fill Module: %s", e)
        return False

def default_paths() -> dict[str, Path]:
    repo_root = find_sdk_root()
    return {
        "repo_root": repo_root,
        "structure": repo_root / "sdk_method_structure",
        "target": get_sdk_install_path(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install VENUS SDK Folder Structure to Program Files")
    defaults = default_paths()
    p.add_argument("--structure", type=Path, default=defaults["structure"], help="Path to sdk_method_structure folder")
    p.add_argument("--target", type=Path, default=defaults["target"], help="Target SDK installation path")
    p.add_argument("--dry-run", action="store_true", help="Show what would be copied without making changes")
    p.add_argument("--force", action="store_true", help="Overwrite existing files in target")
    p.add_argument("--prompt", action="store_true", help="Require confirmation prompt")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return p.parse_args(argv)


def confirm(prompt: str, default: bool = False) -> bool:
    resp = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ")
    if not resp:
        return default
    return resp.strip().lower().startswith("y")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    version_errors = collect_version_errors()
    if version_errors:
        for message in version_errors:
            logger.error("%s", message)
        return 2

    warn_if_not_admin()

    if not args.structure.exists():
        logger.error("SDK structure folder not found: %s", args.structure)
        return 2

    target = args.target.resolve()
    logger.info("Target install path: %s", target)

    if args.prompt:
        logger.info("Structure: %s", args.structure)
        if not confirm("Proceed with installation to target?", default=False):
            logger.info("Aborted by user")
            return 1

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    set_folder_permissions(target, dry_run=args.dry_run)

    logger.info("Installing SDK structure to %s", target)
    copied = copy_tree(args.structure, target, dry_run=args.dry_run, overwrite=args.force)

    registry_updated = set_sdk_registry_path(target, dry_run=args.dry_run)
    if not registry_updated:
        logger.warning(
            "SDK files were installed, but registry path update did not complete. "
            "Runtime path discovery may use defaults until registry is fixed."
        )

    # Best-effort; must never fail the install.
    try:
        configure_heater_cooler(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("HeaterCooler configuration skipped: %s", e)
    try:
        configure_odtc(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("ODTC configuration skipped: %s", e)
    try:
        configure_inheco_tec(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("InhecoTEC configuration skipped: %s", e)
    try:
        configure_tilt_module(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("Tilt Module configuration skipped: %s", e)
    try:
        configure_media_fill(dry_run=args.dry_run)
    except Exception as e:
        logger.warning("Media Fill configuration skipped: %s", e)

    logger.info("Done. Files copied: %d", copied)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
