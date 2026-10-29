from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hamilton_venus.setup_tools import prerequisites, py32_runtime, structure
from hamilton_venus.setup_tools.version_checker import PrerequisiteVersionChecker, warn_if_outdated
from hamilton_venus.tools import generate_catalog

logger = logging.getLogger("venus_setup")

CHECK_VERSIONS_COMMAND = "check-versions"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults = structure.default_paths()
    p = argparse.ArgumentParser(
        description=(
            "Run prerequisite installers and copy sdk method structure in one command. "
            f"Use 'setup-venus-sdk {CHECK_VERSIONS_COMMAND}' to report outdated prerequisite installs."
        )
    )
    p.add_argument(
        "--prereqs",
        type=Path,
        default=prerequisites.default_prereqs_path(),
        help="Path to prerequisites folder",
    )
    p.add_argument(
        "--structure",
        type=Path,
        default=defaults["structure"],
        help="Path to sdk_method_structure folder",
    )
    p.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Override SDK installation target path",
    )
    p.add_argument(
        "--skip-prereqs",
        action="store_true",
        help="Skip running prerequisite executables",
    )
    p.add_argument(
        "--skip-structure",
        action="store_true",
        help="Skip copying sdk_method_structure",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run/copy without making changes",
    )
    p.add_argument("--force", action="store_true", help="Overwrite existing files in target")
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Run prerequisites installer in interactive mode",
    )
    p.add_argument("--prompt", action="store_true", help="Require confirmation prompts")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    p.add_argument(
        "--skip-catalog",
        action="store_true",
        help="Skip pulling liquid classes from VENUS and generating static catalog",
    )
    p.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Skip checking installed prerequisites for outdated versions",
    )
    p.add_argument(
        "--install-py32",
        action="store_true",
        help="Download and install the private 32-bit Python + pywin32 runtime used by the "
        "Heater/Cooler, Inheco TEC and ODTC drivers on 64-bit Python",
    )
    p.add_argument(
        "--py32-from",
        type=Path,
        default=None,
        help="Install the 32-bit runtime from a folder containing the pinned files instead of "
        "downloading (offline PCs); implies --install-py32",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to the prerequisite version manifest (defaults to prerequisites/manifest.json)",
    )
    return p.parse_args(argv)


def parse_check_versions_args(argv: list[str]) -> argparse.Namespace:
    """Parse arguments for the standalone 'check-versions' subcommand."""
    p = argparse.ArgumentParser(
        prog=f"setup-venus-sdk {CHECK_VERSIONS_COMMAND}",
        description="Report installed prerequisite versions and flag outdated installs",
    )
    p.add_argument(
        "--prereqs",
        type=Path,
        default=prerequisites.default_prereqs_path(),
        help="Path to prerequisites folder",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to the prerequisite version manifest (defaults to prerequisites/manifest.json)",
    )
    p.add_argument("--json", action="store_true", help="Emit the report as JSON")
    p.add_argument(
        "--fail-if-outdated",
        action="store_true",
        help="Exit with code 1 when any prerequisite is outdated",
    )
    p.add_argument(
        "--check-manifest",
        action="store_true",
        help="Also report where the manifest disagrees with the bundled installer filenames",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Include detection details")
    return p.parse_args(argv)


def check_versions_main(argv: list[str]) -> int:
    """Run the 'check-versions' subcommand and return its exit code."""
    args = parse_check_versions_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    checker = PrerequisiteVersionChecker(args.prereqs, args.manifest)
    try:
        report = checker.check()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ValueError as exc:
        logger.error("Invalid prerequisite manifest: %s", exc)
        return 2

    if args.json:
        print(checker.as_json())
    else:
        print(checker.as_text(verbose=args.verbose))
        if args.check_manifest:
            drift = checker.manifest_drift()
            if drift:
                print("\nManifest/installer mismatches:")
                for warning in drift:
                    print(f"  - {warning}")
            else:
                print("\nManifest matches the bundled installers.")

    if args.fail_if_outdated and report.any_outdated:
        return 1
    return 0


def confirm(prompt: str, default: bool = False) -> bool:
    resp = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ")
    if not resp:
        return default
    return resp.strip().lower().startswith("y")


def _build_prereq_args(args: argparse.Namespace) -> list[str]:
    """Translate combined CLI options into arguments for the prerequisites step."""
    cmd_args: list[str] = ["--prereqs", str(args.prereqs)]
    if args.dry_run:
        cmd_args.append("--dry-run")
    if args.verbose:
        cmd_args.append("--verbose")
    if not args.interactive:
        cmd_args.append("--headless")
    return cmd_args


def _build_setup_args(args: argparse.Namespace) -> list[str]:
    """Translate combined CLI options into arguments for the structure step."""
    cmd_args: list[str] = [
        "--structure",
        str(args.structure),
    ]
    if args.target is not None:
        cmd_args.extend(["--target", str(args.target)])
    if args.dry_run:
        cmd_args.append("--dry-run")
    if args.force:
        cmd_args.append("--force")
    if args.verbose:
        cmd_args.append("--verbose")
    return cmd_args


def main(argv: list[str] | None = None) -> int:
    """Run the combined setup flow for prerequisites and SDK structure installation."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == CHECK_VERSIONS_COMMAND:
        return check_versions_main(argv[1:])

    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    run_prereqs = not args.skip_prereqs
    run_structure = not args.skip_structure
    run_catalog = not args.skip_catalog
    run_py32 = args.install_py32 or args.py32_from is not None

    if not run_prereqs and not run_structure and not run_py32:
        logger.error("Nothing to do. Remove one of --skip-prereqs/--skip-structure, or add --install-py32.")
        return 2

    if args.prompt:
        logger.info("Plan:")
        if run_prereqs:
            logger.info("  1) Run prerequisites from: %s", args.prereqs)
        if run_py32:
            logger.info("  2) Install the 32-bit COM runtime under: %s", py32_runtime.default_install_dir())
            if args.py32_from is not None:
                logger.info("     Source folder override: %s", args.py32_from)
        if run_structure:
            logger.info("  3) Install SDK structure from: %s", args.structure)
            if args.target is not None:
                logger.info("     Target install path override: %s", args.target)
        if run_catalog:
            logger.info("  4) Pull liquid classes from VENUS and generate static catalog")
        if not confirm("Proceed with combined setup?", default=False):
            logger.info("Aborted by user")
            return 1

    if not args.skip_version_check:
        warn_if_outdated(args.prereqs, args.manifest)

    if run_prereqs:
        logger.info(
            "If any prerequisite installer asks to restart your PC, select No/Restart Later until setup finishes."
        )
        logger.info("Starting prerequisites step...")
        prereq_exit = prerequisites.main(_build_prereq_args(args))
        if prereq_exit != 0:
            logger.error("Prerequisites step failed with exit code %d", prereq_exit)
            return prereq_exit

    if run_py32:
        logger.info("Starting 32-bit COM runtime installation step...")
        ok, message = py32_runtime.install_py32_runtime(
            source_dir=args.py32_from, force=args.force, dry_run=args.dry_run
        )
        (logger.info if ok else logger.error)("32-bit COM runtime: %s", message)
        if not ok:
            return 1

    if run_structure:
        logger.info("Starting SDK structure installation step...")
        setup_exit = structure.main(_build_setup_args(args))
        if setup_exit != 0:
            logger.error("SDK structure installation failed with exit code %d", setup_exit)
            return setup_exit

    if run_catalog:
        if args.dry_run:
            logger.info("[DRY-RUN] Would pull liquid classes from VENUS and generate static catalog")
        else:
            logger.info("Starting liquid class catalog generation...")
            catalog_args = []
            if args.verbose:
                catalog_args.append("--debug")
            catalog_exit = generate_catalog.main(catalog_args)
            if catalog_exit != 0:
                logger.error("Catalog generation failed with exit code %d", catalog_exit)
                return catalog_exit

    logger.info("Setup completed successfully.")
    if run_prereqs:
        logger.info("Restart your PC now to finalize installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
