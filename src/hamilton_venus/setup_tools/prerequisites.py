from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hamilton_venus.setup_tools import version_detection
from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteManifest, load_manifest
from hamilton_venus.setup_tools.root_discovery import find_sdk_root

logger = logging.getLogger("venus_install_prerequisites")

# Background VENUS processes known to hold a prerequisite-installer DLL open --
# e.g. Hamilton.WebAPI.RunExecutor.exe keeps a Hamilton library DLL loaded, so an
# HSLHttp/HSLJson/Tip Management/etc. installer running while it's up fails (or
# silently no-ops) trying to overwrite that DLL. Stopped automatically, with a
# warning, before the prerequisite installers run -- see stop_blocking_processes().
BLOCKING_PROCESS_NAMES: list[str] = [
    "Hamilton.WebAPI.RunExecutor.exe",
]

# Interactive VENUS editor processes that might have a project file (e.g. an image
# referenced by a method) open that a prerequisite installer needs to overwrite.
# Unlike BLOCKING_PROCESS_NAMES, these are never auto-closed -- a person has them
# open on purpose, and force-killing one could lose unsaved work. Only warned about;
# see warn_about_editor_processes().
WARN_ONLY_PROCESS_NAMES: list[str] = [
    "HxMetEd.exe",  # Hamilton Method Editor
]

EXECUTABLE_EXTENSIONS = {".exe", ".msi"}

KNOWN_HEADLESS_EXE_FLAG_PATTERNS: dict[str, list[str]] = {
    "hamilton hsltime library installer": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
    "hamilton_hslhttp": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
    "hsljson library": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
    "hsllabwareconverter": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
    "hslliquidsconverter": ["/S"],
    "install hamilton advanced tip management library": [
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
    ],
    "install hsllabwraccess": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
}


def resolve_headless_exe_flags(exe_name: str, default_flags: list[str]) -> list[str]:
    """Return installer-specific silent flags when a known executable name pattern matches."""
    name = exe_name.lower()
    for pattern, flags in KNOWN_HEADLESS_EXE_FLAG_PATTERNS.items():
        if pattern in name:
            return flags
    return default_flags


def find_executables(prereqs_path: Path) -> list[Path]:
    """Collect prerequisite installer files from the given directory in stable name order."""
    exes = []
    for f in sorted(prereqs_path.iterdir()):
        if f.is_file() and f.suffix.lower() in EXECUTABLE_EXTENSIONS:
            exes.append(f)
    return exes


# Inno Setup (the framework behind most of these .exe prerequisites -- see
# KNOWN_HEADLESS_EXE_FLAG_PATTERNS) uses a small fixed set of wizard exit codes.
# Surfaced only to help a human read the log; never used for control flow.
_INNO_SETUP_EXIT_CODE_HINTS: dict[int, str] = {
    1: "setup failed to initialize",
    2: "cancelled before installation started",
    3: "a fatal error occurred preparing the next installation phase",
    4: "a fatal error occurred during installation",
    5: (
        "a file conflict forced an Abort/Retry/Ignore prompt during installation and it "
        "was aborted -- commonly means another program still had a file the installer "
        "needed to overwrite open"
    ),
    6: "setup was forcibly terminated by a debugger",
    7: "a pre-installation check determined setup cannot proceed",
    8: "a pre-installation check determined setup cannot proceed; a restart is needed first",
}


def _describe_exit_code(code: int) -> str:
    hint = _INNO_SETUP_EXIT_CODE_HINTS.get(code)
    return f" ({hint})" if hint else ""


def run_executables(
    executables: list[Path],
    dry_run: bool = False,
    silent: bool = False,
) -> tuple[int, list[Path]]:
    """Run prerequisite installers. Returns (how many completed with exit code 0, the
    ones that didn't -- always empty under --dry-run, since nothing actually runs).
    """
    default_exe_silent_flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]

    success_count = 0
    failed: list[Path] = []
    for exe in executables:
        logger.info("[RUN] %s", exe.name)

        suffix = exe.suffix.lower()
        if silent and suffix == ".msi":
            cmd = ["msiexec", "/i", str(exe), "/qn", "/norestart"]
        elif silent and suffix == ".exe":
            flags = resolve_headless_exe_flags(exe.name, default_exe_silent_flags)
            cmd = [str(exe), *flags]
        else:
            cmd = [str(exe)]

        if dry_run:
            logger.info("[DRY-RUN] Would run: %s", " ".join(cmd))
            success_count += 1
            continue
        try:
            result = subprocess.run(cmd, check=False, shell=False)
            if result.returncode == 0:
                logger.info("[OK]  %s finished (exit code 0)", exe.name)
                success_count += 1
            else:
                logger.warning(
                    "[WARN] %s finished with exit code %d%s",
                    exe.name,
                    result.returncode,
                    _describe_exit_code(result.returncode),
                )
                failed.append(exe)
        except Exception as e:
            logger.error("[ERROR] Failed to run %s: %s", exe.name, e)
            failed.append(exe)
    return success_count, failed


def _is_process_running(process_name: str) -> bool:
    """Best-effort check via `tasklist` (Windows only). Returns False on any failure
    (non-Windows, tasklist unavailable, unexpected error) rather than raising --
    this is a courtesy check, not something that should abort setup on its own.

    Uses `/FO CSV` rather than tasklist's default table format: the default format
    truncates the Image Name column (observed live: "Hamilton.WebAPI.RunExecutor.exe"
    -> "Hamilton.WebAPI.RunExecut"), so a plain substring check against that output
    can silently never match a long process name -- CSV never truncates it.
    """
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        row = next(csv.reader(io.StringIO(result.stdout)))
    except StopIteration:
        return False
    # A non-match prints a plain "INFO: No tasks..." line (not CSV) -- that parses as
    # a single field that will never equal process_name, so no special-casing needed.
    return bool(row) and row[0].strip().lower() == process_name.lower()


_RUN_STATE_PATH = "/api/vector/v3/execution/run-state"
_DEFAULT_VENUS_BASE_URL = "http://localhost:42400"
_VENUS_BASE_URL_ENV_VAR = "HAMILTON_VENUS_BASE_URL"  # matches hamilton_venus.config's own override

# Mirrors hamilton_venus.models.enums.RunState, duplicated here as plain ints. This
# module deliberately has no dependency on the broader `hamilton_venus` SDK package
# (models, venus_client, ...) -- it has to stay usable this early in setup, before the
# rest of the SDK is known-good -- but does depend on a few `setup_tools` siblings
# (root_discovery, prerequisite_manifest, version_detection) that cli.py already
# requires at this same stage via version_checker.
# 0 = NotInitialized (nothing loaded -- idle), 10 = Terminated (a method fully ended).
# Every other value (Running, Starting, Pausing, Paused, Aborting, ...) means VENUS is
# actively doing something.
_SAFE_RUN_STATES = frozenset({0, 10})


class VenusNotReadyError(RuntimeError):
    """VENUS isn't in a safe, reachable state to stop a blocking process.

    Distinct from a failed stop attempt (logged as a warning, non-fatal -- see
    stop_blocking_processes): this means forcing the process closed would risk
    killing an active run, or VENUS's WebAPI isn't responding normally -- and since
    later setup steps (the catalog-generation step) also need a working WebAPI, the
    whole install should stop here rather than fail more confusingly downstream.
    """


def _get_run_state(base_url: str, timeout: float = 5.0) -> int:
    """Raw ``GET .../execution/run-state`` -- VENUS's current RunState as an int.

    Raises VenusNotReadyError on any connection failure, non-2xx response
    (explicitly including HTTP 400), or an unparseable payload.
    """
    url = base_url.rstrip("/") + _RUN_STATE_PATH
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise VenusNotReadyError(
            f"VENUS WebAPI at {url} returned HTTP {exc.code} -- the service is not responding normally"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VenusNotReadyError(f"Could not reach the VENUS WebAPI at {url}: {exc}") from exc

    try:
        return int(json.loads(body))
    except (ValueError, TypeError) as exc:
        raise VenusNotReadyError(
            f"VENUS WebAPI at {url} returned an unexpected run-state payload: {body!r}"
        ) from exc


def ensure_venus_safe_to_stop(base_url: str | None = None) -> None:
    """Raise VenusNotReadyError unless VENUS is reachable and reports an idle/terminated
    run-state. Called right before a blocking process actually gets stopped.
    """
    resolved_base_url = base_url or os.environ.get(_VENUS_BASE_URL_ENV_VAR, _DEFAULT_VENUS_BASE_URL)
    state = _get_run_state(resolved_base_url)
    if state not in _SAFE_RUN_STATES:
        raise VenusNotReadyError(f"VENUS run-state is {state} (not idle/terminated) -- a method may be active")


def stop_blocking_processes(
    process_names: list[str] | None = None, *, dry_run: bool = False, venus_base_url: str | None = None
) -> list[str]:
    """Check VENUS's run-state, then warn about and stop any running process that
    would block a prerequisite installer from overwriting a DLL it still has open
    (see BLOCKING_PROCESS_NAMES).

    The run-state check (ensure_venus_safe_to_stop) runs unconditionally, up front --
    deliberately *not* only when a name in BLOCKING_PROCESS_NAMES is found running.
    Process existence isn't a reliable proxy for "is a method active": a run can be
    genuinely active (or paused) in VENUS's run control without
    Hamilton.WebAPI.RunExecutor.exe necessarily being alive under that exact name at
    the instant we happen to check (observed live: a method stayed in VENUS's
    "Running" state throughout an install where tasklist never once showed the
    executor process). Gating the safety check behind process detection would let an
    active run get silently overrun -- by the prerequisite installers directly, and
    by generate-catalog's own stale-method cleanup later in the same setup run (which
    aborts/unloads whatever is currently loaded before loading its own method).

    If VENUS isn't idle/terminated and reachable, this raises VenusNotReadyError,
    which the caller should treat as fatal (abort the whole install), not just skip
    this one process: forcing VENUS closed mid-run risks corrupting it, and later
    setup steps need a working WebAPI anyway.

    Once that check passes, stopping itself is best-effort: a process that can't be
    stopped (e.g. access denied) is logged as a warning, not a hard failure -- the
    prerequisite installer itself will surface the real error if the lock is still
    held. Returns the names found running (whether or not the stop actually succeeded;
    under --dry-run, nothing is actually stopped, but the safety check still runs).
    """
    names = BLOCKING_PROCESS_NAMES if process_names is None else process_names
    logger.info("Checking VENUS's run-state before touching background processes: %s", names)
    ensure_venus_safe_to_stop(venus_base_url)
    logger.info("VENUS is idle -- safe to continue.")

    running: list[str] = []
    for name in names:
        if not _is_process_running(name):
            logger.info("%s is not running -- nothing to stop.", name)
            continue
        running.append(name)
        logger.warning(
            "%s is running and may be holding a DLL open that a prerequisite installer "
            "needs to overwrite -- stopping it before continuing.",
            name,
        )
        if dry_run:
            logger.info("[DRY-RUN] Would stop: %s", name)
            continue
        try:
            result = subprocess.run(
                ["taskkill", "/IM", name, "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                logger.info("Stopped %s.", name)
            else:
                logger.warning(
                    "Could not stop %s (taskkill exit code %d): %s",
                    name,
                    result.returncode,
                    (result.stderr or result.stdout).strip(),
                )
        except OSError as exc:
            logger.warning("Could not stop %s: %s", name, exc)
    return running


def warn_about_editor_processes(process_names: list[str] | None = None) -> list[str]:
    """Warn about (but never stop) interactive VENUS editor processes -- see
    WARN_ONLY_PROCESS_NAMES -- that could be holding a project file open that a
    prerequisite installer needs to overwrite. Returns the names found running.
    """
    names = WARN_ONLY_PROCESS_NAMES if process_names is None else process_names
    running: list[str] = []
    for name in names:
        if _is_process_running(name):
            running.append(name)
            logger.warning(
                "%s is open. If it has a project file open (an image, a method, ...), "
                "a prerequisite installer may fail to overwrite that file while it's "
                "in use. Save your work, close %s yourself, then re-run setup.",
                name,
                name,
            )
    return running


def _uninstall_msi(path: Path) -> bool:
    """Uninstall an MSI package via its own file -- msiexec resolves the product to
    remove directly from the package, so this needs no registry lookup or guessing.
    """
    try:
        result = subprocess.run(
            ["msiexec", "/x", str(path), "/qn", "/norestart"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        logger.warning("Could not run msiexec to uninstall %s: %s", path.name, exc)
        return False
    if result.returncode == 0:
        logger.info("Uninstalled %s.", path.name)
        return True
    logger.warning(
        "msiexec /x for %s exited %d: %s",
        path.name,
        result.returncode,
        (result.stderr or result.stdout).strip(),
    )
    return False


# An installer filename and its registered "Programs and Features" DisplayName rarely
# match exactly -- e.g. "Hamilton HSLTime Library Installer v1.1.exe" vs. "HSLTime
# Library" -- so both are reduced to their meaningful tokens before comparing.
_UNINSTALL_NAME_NOISE_WORDS = {"setup", "installer", "install", "for", "the", "v"}


def _normalize_product_name(name: str) -> str:
    # Strip a real installer-file extension if present -- deliberately not
    # Path(name).stem, which treats ANY trailing ".word" as an extension and would
    # wrongly truncate a dotted registry DisplayName like "Hamilton.HSLExtensions"
    # down to just "Hamilton" (observed live).
    for ext in (".exe", ".msi"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    tokens = re.split(r"[^A-Za-z0-9]+", name)
    kept = []
    for tok in tokens:
        if not tok:
            continue
        low = tok.lower()
        if low in _UNINSTALL_NAME_NOISE_WORDS or re.fullmatch(r"v?\d+", low):
            continue
        kept.append(low)
    return " ".join(kept)


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity between two space-separated token strings. Deliberately
    word-level rather than character-level (e.g. difflib's SequenceMatcher): a
    character-level ratio is easily fooled by shared common words -- observed live,
    "hsljson library" (from "HSLJson Library v4.6 Installer.exe") scored close enough
    against the unrelated "hamilton venus libraries" (shared "librar-") to beat the
    confidence margin against the real match, "hamilton hsljson library version".
    Token overlap doesn't share any tokens between those two ("library" != "libraries")
    and cleanly separates them instead.
    """
    set_a, set_b = set(a.split()), set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _read_uninstall_command(registry_key: str) -> str | None:
    """Read the uninstall command string (QuietUninstallString, falling back to
    UninstallString) for a registry_key path as returned by
    version_detection.iter_uninstall_entries(), e.g.
    "HKLM\\SOFTWARE\\...\\Uninstall\\{GUID}". Windows-only.
    """
    import winreg

    winreg_mod: Any = winreg
    hive_name, _sep, subkey_path = registry_key.partition("\\")
    hive = {"HKLM": winreg_mod.HKEY_LOCAL_MACHINE, "HKCU": winreg_mod.HKEY_CURRENT_USER}.get(hive_name)
    if hive is None:
        return None
    try:
        with winreg_mod.OpenKey(hive, subkey_path) as entry:
            try:
                command, _ = winreg_mod.QueryValueEx(entry, "QuietUninstallString")
            except OSError:
                command, _ = winreg_mod.QueryValueEx(entry, "UninstallString")
    except OSError:
        return None
    return command if isinstance(command, str) else None


_prereq_manifest_cache: PrerequisiteManifest | None = None
_prereq_manifest_load_attempted = False


def _load_manifest_quietly() -> PrerequisiteManifest | None:
    """Load prerequisites/manifest.json (see prerequisite_manifest.py), caching the
    result (including a failed load) for the life of the process. Never raises: a
    missing or invalid manifest just means uninstall lookups fall back to the fuzzy
    matcher, same as if this module had no manifest support at all.
    """
    global _prereq_manifest_cache, _prereq_manifest_load_attempted
    if _prereq_manifest_load_attempted:
        return _prereq_manifest_cache
    _prereq_manifest_load_attempted = True
    try:
        _prereq_manifest_cache = load_manifest()
    except (FileNotFoundError, ValueError) as exc:
        logger.debug("No usable prerequisite manifest for uninstall lookups: %s", exc)
        _prereq_manifest_cache = None
    return _prereq_manifest_cache


def _find_manifest_uninstall_command(installer_name: str) -> list[str] | None:
    """Match installer_name against the SDK's own prerequisite manifest
    (prerequisites/manifest.json) -- an exact, authoritative installer-filename ->
    registry-DisplayName-pattern mapping already used for version checking (see
    version_checker.py) -- so an installer covered by it needs no fuzzy guessing at
    all. Returns None (not an error) when the manifest is unavailable, doesn't cover
    this installer, or the matched prerequisite isn't currently registered as
    installed (nothing to uninstall).
    """
    manifest = _load_manifest_quietly()
    if manifest is None:
        return None
    prereq = next(
        (p for p in manifest.prerequisites if re.match(p.installer_pattern, installer_name, re.IGNORECASE)),
        None,
    )
    if prereq is None:
        return None

    pattern = re.compile(prereq.registry_name_pattern, re.IGNORECASE)
    match = next((entry for entry in version_detection.iter_uninstall_entries() if pattern.search(entry[0])), None)
    if match is None:
        logger.info(
            "%s is a known prerequisite (%s) but isn't currently registered as installed -- nothing to uninstall.",
            installer_name,
            prereq.display_name,
        )
        return None

    display_name, _display_version, registry_key = match
    command = _read_uninstall_command(registry_key)
    if command is None:
        logger.warning("Found %s in the registry but could not read its uninstall command.", display_name)
        return None
    logger.info("Matched %s to %s via the prerequisite manifest.", installer_name, display_name)
    try:
        argv = shlex.split(command, posix=False)
    except ValueError:
        return None
    return [tok.strip('"') for tok in argv if tok.strip('"')]


_UNINSTALL_MATCH_THRESHOLD = 0.5
_UNINSTALL_MATCH_MARGIN = 0.15  # best match must lead the runner-up by at least this much


def _find_fuzzy_uninstall_command(installer_name: str) -> list[str] | None:
    """Fallback for an installer the prerequisite manifest doesn't cover: best-effort
    match of its filename to a registered uninstaller in the Windows "Programs and
    Features" registry by word-level (token) overlap. Deliberately conservative: only
    returns a command when exactly one entry is a clear, confident best match -- an
    ambiguous or weak match returns None rather than guessing, since running the wrong
    uninstaller would remove unrelated software.
    """
    target = _normalize_product_name(installer_name)
    if not target:
        return None

    scored: list[tuple[float, float, str, str]] = []
    for display_name, _display_version, registry_key in version_detection.iter_uninstall_entries():
        candidate = _normalize_product_name(display_name)
        if not candidate:
            continue
        overlap = _token_overlap(target, candidate)
        tiebreak = difflib.SequenceMatcher(None, target, candidate).ratio()
        scored.append((overlap, tiebreak, display_name, registry_key))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_overlap, _best_tiebreak, best_name, best_registry_key = scored[0]
    runner_up_overlap = scored[1][0] if len(scored) > 1 else 0.0
    if best_overlap < _UNINSTALL_MATCH_THRESHOLD or (best_overlap - runner_up_overlap) < _UNINSTALL_MATCH_MARGIN:
        logger.info(
            "No confident uninstall-registry match for %s (best guess %r at %.2f, runner-up %.2f) "
            "-- skipping the uninstall step.",
            installer_name,
            best_name,
            best_overlap,
            runner_up_overlap,
        )
        return None

    command = _read_uninstall_command(best_registry_key)
    if command is None:
        logger.warning("Found %s in the registry but could not read its uninstall command.", best_name)
        return None
    logger.info(
        "Matched %s to registered uninstaller %r (token overlap %.2f).", installer_name, best_name, best_overlap
    )
    try:
        argv = shlex.split(command, posix=False)
    except ValueError:
        return None
    return [tok.strip('"') for tok in argv if tok.strip('"')]


def _find_registry_uninstall_command(installer_name: str) -> list[str] | None:
    """Find the registered Windows uninstaller for a prerequisite installer filename.
    Prefers the authoritative manifest match (_find_manifest_uninstall_command) and
    only falls back to fuzzy token-overlap matching (_find_fuzzy_uninstall_command)
    for an installer the manifest doesn't cover.
    """
    if sys.platform != "win32":
        return None
    return _find_manifest_uninstall_command(installer_name) or _find_fuzzy_uninstall_command(installer_name)


def _uninstall_exe(exe: Path) -> bool:
    """Best-effort uninstall of an Inno-Setup-style .exe prerequisite via its
    registered uninstaller (see _find_registry_uninstall_command). Returns False --
    without raising -- when no confident match is found or the uninstall itself
    fails; the caller falls back to retrying the plain install anyway.
    """
    command = _find_registry_uninstall_command(exe.name)
    if command is None:
        return False
    if not any(flag.upper().startswith(("/VERYSILENT", "/SILENT")) for flag in command):
        command = [*command, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        logger.warning("Could not run the uninstaller for %s: %s", exe.name, exc)
        return False
    if result.returncode == 0:
        logger.info("Uninstalled %s.", exe.name)
        return True
    logger.warning(
        "Uninstaller for %s exited %d: %s",
        exe.name,
        result.returncode,
        (result.stderr or result.stdout).strip(),
    )
    return False


def retry_failed_executables(failed: list[Path], *, silent: bool = True) -> tuple[int, list[Path]]:
    """Retry each installer that failed on the first pass, exactly once: uninstall the
    current (partial/failed) install first -- via msiexec for .msi packages (always
    unambiguous, see _uninstall_msi), or via a confidently-matched registered
    uninstaller for .exe packages (see _uninstall_exe) -- then reinstall from the
    prerequisites folder.

    A failed or skipped uninstall step doesn't stop the retry: the reinstall is
    attempted either way, since re-running the installer can still succeed on its own
    (e.g. the original failure was a transient file lock that's since cleared).
    Returns (how many now succeeded, the ones still failing after the retry).
    """
    still_failed: list[Path] = []
    retried_success = 0
    for exe in failed:
        logger.info("Retrying %s: uninstalling the current install first.", exe.name)
        uninstalled = _uninstall_msi(exe) if exe.suffix.lower() == ".msi" else _uninstall_exe(exe)
        if not uninstalled:
            logger.warning("Could not uninstall the current %s -- reinstalling over it anyway.", exe.name)
        ok_count, _ = run_executables([exe], dry_run=False, silent=silent)
        if ok_count:
            retried_success += 1
        else:
            still_failed.append(exe)
    return retried_success, still_failed


def default_prereqs_path() -> Path:
    """Return the repository default path for prerequisite installers."""
    return find_sdk_root() / "prerequisites"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run prerequisite executables for VENUS SDK")
    p.add_argument("--prereqs", type=Path, default=default_prereqs_path(), help="Path to preRequisites folder")
    p.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    p.add_argument("--headless", action="store_true", help="Run installers in silent/headless mode")
    p.add_argument("--prompt", action="store_true", help="Require confirmation prompt")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return p.parse_args(argv)


def confirm(prompt: str, default: bool = False) -> bool:
    resp = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ")
    if not resp:
        return default
    return resp.strip().lower().startswith("y")


def main(argv: list[str] | None = None) -> int:
    """Execute the prerequisites installer CLI workflow."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    if not args.prereqs.exists():
        logger.error("preRequisites folder not found: %s", args.prereqs)
        return 2

    executables = find_executables(args.prereqs)
    if not executables:
        logger.warning("No executables found in: %s", args.prereqs)
        return 0

    logger.info("Found %d executable(s):", len(executables))
    for exe in executables:
        logger.info("  - %s", exe.name)

    if args.prompt and not confirm("Proceed with running all prerequisites?", default=False):
        logger.info("Aborted by user.")
        return 1

    warn_about_editor_processes()

    try:
        stop_blocking_processes(dry_run=args.dry_run)
    except VenusNotReadyError as exc:
        logger.error(
            "%s -- aborting setup rather than risk stopping VENUS while it's busy. "
            "Close out whatever VENUS is doing (or wait for it to go idle) and re-run.",
            exc,
        )
        return 3

    success, failed = run_executables(executables, dry_run=args.dry_run, silent=args.headless)

    if failed and not args.dry_run:
        logger.warning(
            "%d/%d prerequisite installer(s) did not finish cleanly -- retrying once "
            "(uninstall, then reinstall): %s",
            len(failed),
            len(executables),
            [exe.name for exe in failed],
        )
        retried_success, failed = retry_failed_executables(failed, silent=args.headless)
        success += retried_success

    logger.info("Done. %d/%d ran successfully.", success, len(executables))

    if failed:
        logger.error(
            "%d/%d prerequisite installer(s) still failed after the retry -- aborting setup: %s. "
            "Install these manually from %s and re-run.",
            len(failed),
            len(executables),
            [exe.name for exe in failed],
            args.prereqs,
        )
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
