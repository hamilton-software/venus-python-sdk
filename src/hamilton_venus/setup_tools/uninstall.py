from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hamilton_venus._internal._sdk_paths import REGISTRY_KEY_PATH
from hamilton_venus.setup_tools import py32_runtime, structure
from hamilton_venus.setup_tools.prerequisite_manifest import (
    PrerequisiteManifest,
    default_manifest_path,
    load_manifest,
)
from hamilton_venus.setup_tools.prerequisites import resolve_headless_exe_flags
from hamilton_venus.setup_tools.version_detection import UNINSTALL_REGISTRY_KEYS

logger = logging.getLogger("venus_uninstall")

DEFAULT_UNINSTALL_SILENT_FLAGS: list[str] = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]

# Directory names that must never be purged wholesale, even if --target points at one.
PROTECTED_PURGE_NAMES = frozenset(
    {
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "users",
        "system32",
        "hamilton",
    }
)


def default_paths() -> dict[str, Path]:
    """Return the same structure/target defaults used by the installer."""
    return structure.default_paths()


class UnsafePurgeTargetError(ValueError):
    """Raised when the requested purge target is a root or well-known system directory."""


def _assert_safe_purge_target(target: Path) -> None:
    """Reject purge targets that would wipe a drive root or a well-known system directory."""
    if target.parent == target:
        raise UnsafePurgeTargetError(f"Refusing to purge a filesystem root: {target}")
    if target.name.lower() in PROTECTED_PURGE_NAMES:
        raise UnsafePurgeTargetError(f"Refusing to purge a protected system directory: {target}")


def purge_target_tree(target: Path, *, dry_run: bool = False) -> int:
    """Delete every file and directory inside target, leaving target itself in place.

    Unlike :func:`remove_structure_tree`, this also clears files the current
    ``sdk_method_structure`` no longer ships, so a stale install cannot leave
    renamed or removed assets behind for the next install to pick up.
    """
    target = target.resolve()
    if not target.exists():
        logger.info("Nothing to remove: target does not exist: %s", target)
        return 0

    _assert_safe_purge_target(target)

    removed = 0
    for entry in sorted(target.iterdir()):
        logger.info("Removing %s", entry)
        if dry_run:
            removed += 1
            continue
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as e:
            logger.warning("Could not remove %s: %s", entry, e)
            continue
        removed += 1
    return removed


def remove_structure_tree(structure_src: Path, target: Path, *, dry_run: bool = False) -> int:
    """Remove files under target that mirror sdk_method_structure, then prune empty directories."""
    structure_src = structure_src.resolve()
    target = target.resolve()
    if not target.exists():
        logger.info("Nothing to remove: target does not exist: %s", target)
        return 0
    if not structure_src.exists():
        logger.warning("Structure source not found; skipping file removal: %s", structure_src)
        return 0

    removed = 0
    for root, _dirs, files in os.walk(structure_src):
        rel = Path(root).relative_to(structure_src)
        target_dir = target.joinpath(rel)
        for f in files:
            candidate = target_dir / f
            if not candidate.exists():
                continue
            logger.info("Removing %s", candidate)
            if not dry_run:
                candidate.unlink()
            removed += 1

    if not dry_run:
        _prune_empty_dirs(target)
    return removed


def _prune_empty_dirs(target: Path) -> None:
    """Remove now-empty directories under target, bottom-up, leaving target itself in place."""
    for root, dirs, files in os.walk(target, topdown=False):
        root_path = Path(root)
        if root_path == target:
            continue
        if dirs or files:
            continue
        try:
            root_path.rmdir()
            logger.debug("Removed empty directory: %s", root_path)
        except OSError as e:
            logger.debug("Could not remove directory %s: %s", root_path, e)


def clear_sdk_registry_path(*, dry_run: bool = False) -> bool:
    """Remove the HKLM registry key that points runtime path discovery at the SDK install."""
    if dry_run:
        logger.info("[DRY-RUN] Would remove registry key: HKLM\\%s", REGISTRY_KEY_PATH)
        return True

    if sys.platform != "win32":
        logger.info("Skipping registry cleanup on non-Windows platform")
        return False

    try:
        import winreg

        winreg_mod: Any = winreg
        winreg_mod.DeleteKey(winreg_mod.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH)
        logger.info("Removed registry key: HKLM\\%s", REGISTRY_KEY_PATH)
        return True
    except FileNotFoundError:
        logger.info("Registry key already absent: HKLM\\%s", REGISTRY_KEY_PATH)
        return True
    except PermissionError as e:
        logger.warning("Unable to remove SDK registry key due to permissions: %s", e)
    except OSError as e:
        logger.warning("Unable to remove SDK registry key: %s", e)
    return False


def _split_uninstall_command(command: str) -> list[str]:
    """Split a registry UninstallString into an executable and its arguments."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end != -1:
            exe = command[1:end]
            rest = command[end + 1 :].strip()
            return [exe, *rest.split()] if rest else [exe]
    return command.split()


def _is_msiexec_command(cmd: list[str]) -> bool:
    """Return True when command targets Windows Installer (msiexec)."""
    if not cmd:
        return False
    exe_name = Path(cmd[0]).name.lower()
    return exe_name in {"msiexec", "msiexec.exe"}


def find_prerequisite_uninstall_commands(manifest: PrerequisiteManifest) -> dict[str, tuple[str, str, str | None]]:
    """Match manifest prerequisites to registry uninstall entries.

    Returns a mapping of prerequisite name to (display_name, uninstall_string, quiet_uninstall_string).
    """
    if sys.platform != "win32":
        return {}

    import winreg

    found: dict[str, tuple[str, str, str | None]] = {}
    patterns = {
        prereq.name: re.compile(prereq.registry_name_pattern, re.IGNORECASE) for prereq in manifest.prerequisites
    }

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
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
                                uninstall_string, _ = winreg.QueryValueEx(subkey, "UninstallString")
                            except OSError:
                                continue
                            try:
                                quiet_uninstall_string, _ = winreg.QueryValueEx(subkey, "QuietUninstallString")
                            except OSError:
                                quiet_uninstall_string = None
                    except OSError:
                        continue
                    if not isinstance(display_name, str):
                        continue
                    for name, pattern in patterns.items():
                        if name in found:
                            continue
                        if pattern.search(display_name):
                            found[name] = (display_name, uninstall_string, quiet_uninstall_string)
    return found


def run_prerequisite_uninstalls(
    commands: dict[str, tuple[str, str, str | None]],
    *,
    dry_run: bool = False,
    silent: bool = False,
) -> int:
    """Run each matched prerequisite uninstaller and return how many completed successfully."""
    success_count = 0
    entries = list(commands.items())
    for index, (name, (display_name, uninstall_string, quiet_uninstall_string)) in enumerate(entries):
        chosen = quiet_uninstall_string if silent and quiet_uninstall_string else uninstall_string
        cmd = _split_uninstall_command(chosen)
        if not cmd:
            logger.warning("[SKIP] %s (%s): empty uninstall command", display_name, name)
            continue

        if silent and chosen is uninstall_string:
            if _is_msiexec_command(cmd):
                if not any(arg.lower() in {"/qn", "/quiet"} for arg in cmd[1:]):
                    cmd.append("/qn")
                if not any(arg.lower() == "/norestart" for arg in cmd[1:]):
                    cmd.append("/norestart")
            else:
                flags = resolve_headless_exe_flags(Path(cmd[0]).name, DEFAULT_UNINSTALL_SILENT_FLAGS)
                cmd = [*cmd, *flags]

        logger.info("[RUN] %s: %s", display_name, " ".join(cmd))
        if dry_run:
            logger.info("[DRY-RUN] Would run: %s", " ".join(cmd))
            success_count += 1
            continue
        try:
            result = subprocess.run(cmd, check=False, shell=False)
            if result.returncode == 0:
                logger.info("[OK]  %s finished (exit code 0)", display_name)
                success_count += 1
            else:
                logger.warning("[WARN] %s finished with exit code %d", display_name, result.returncode)
        except Exception as e:
            logger.error("[ERROR] Failed to uninstall %s: %s", display_name, e)

        if not silent and index < len(entries) - 1:
            _wait_for_interactive_uninstaller(display_name)
    return success_count


def _wait_for_interactive_uninstaller(display_name: str) -> None:
    """Pause until the user confirms an interactive uninstaller window has been closed.

    Many uninstallers (e.g. Inno Setup's unins000.exe) relaunch a copy of themselves and
    exit immediately, so subprocess.run() returns before the visible window is closed. Without
    this pause, the next uninstaller launches right away and its window stacks on top of the
    still-open one. Pausing here keeps the windows sequential instead of overlapping.
    """
    input(f"Close the '{display_name}' uninstaller window, then press Enter to continue...")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults = default_paths()
    p = argparse.ArgumentParser(description="Uninstall the VENUS SDK folder structure and related registration")
    p.add_argument(
        "--structure",
        type=Path,
        default=defaults["structure"],
        help="Path to sdk_method_structure folder (used to identify installed files)",
    )
    p.add_argument("--target", type=Path, default=defaults["target"], help="Installed SDK path to clean up")
    p.add_argument(
        "--structure-only",
        action="store_true",
        help="Only remove files shipped by sdk_method_structure instead of clearing the whole SDK path",
    )
    p.add_argument("--dry-run", action="store_true", help="Show what would be removed without making changes")
    p.add_argument("--keep-registry", action="store_true", help="Do not remove the SDK registry key")
    p.add_argument(
        "--keep-prereqs",
        action="store_true",
        help="Do not uninstall prerequisite executables listed in the manifest",
    )
    p.add_argument(
        "--keep-py32",
        action="store_true",
        help="Do not remove the 32-bit COM runtime installed by --install-py32",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to the prerequisite manifest",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run prerequisite uninstallers silently",
    )
    p.add_argument("--prompt", action="store_true", help="Require confirmation prompt")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return p.parse_args(argv)


def confirm(prompt: str, default: bool = False) -> bool:
    resp = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ")
    if not resp:
        return default
    return resp.strip().lower().startswith("y")


def main(argv: list[str] | None = None) -> int:
    """Run the uninstall workflow: remove SDK structure files, registry key, and default prereqs."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    structure.warn_if_not_admin()

    target = args.target.resolve()
    logger.info("Target SDK install path: %s", target)

    if args.prompt:
        logger.info("Plan:")
        if args.structure_only:
            logger.info("  1) Remove SDK structure files from: %s", target)
        else:
            logger.info("  1) Remove ALL files and folders from: %s", target)
        if not args.keep_registry:
            logger.info("  2) Remove SDK registry key: HKLM\\%s", REGISTRY_KEY_PATH)
        if not args.keep_prereqs:
            logger.info("  3) Uninstall prerequisite executables listed in the manifest")
        if not args.keep_py32:
            logger.info("  4) Remove the 32-bit COM runtime: %s", py32_runtime.default_install_dir())
        if not confirm("Proceed with uninstall?", default=False):
            logger.info("Aborted by user")
            return 1

    if args.structure_only:
        removed = remove_structure_tree(args.structure, target, dry_run=args.dry_run)
        logger.info("Removed %d file(s) from %s", removed, target)
    else:
        try:
            removed = purge_target_tree(target, dry_run=args.dry_run)
        except UnsafePurgeTargetError as e:
            logger.error("%s", e)
            return 1
        logger.info("Removed %d item(s) from %s", removed, target)

    if not args.keep_registry:
        clear_sdk_registry_path(dry_run=args.dry_run)

    if not args.keep_py32:
        py32_runtime.remove_py32_runtime(dry_run=args.dry_run)

    if not args.keep_prereqs:
        manifest_path = args.manifest if args.manifest is not None else default_manifest_path()
        try:
            manifest = load_manifest(manifest_path)
        except (FileNotFoundError, ValueError) as e:
            logger.warning("Skipping prerequisite uninstall: %s", e)
        else:
            commands = find_prerequisite_uninstall_commands(manifest)
            if not commands:
                logger.info("No installed prerequisites matched the manifest; nothing to uninstall.")
            else:
                success = run_prerequisite_uninstalls(commands, dry_run=args.dry_run, silent=args.headless)
                logger.info("Prerequisites uninstalled: %d/%d", success, len(commands))

    logger.info("Uninstall complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
