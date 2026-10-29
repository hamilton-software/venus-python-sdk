"""MethodFileManager — temporary method file copies for VENUS display names.

Creates short-lived copies of the executor ``.hsl`` and ``.stp`` files so that
each SDK session appears with a distinct name in the VENUS run control and
run history.  This is a stopgap until VENUS supports display-name metadata
natively and can be removed once that capability exists.
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_\- ]")


def _sanitize_display_name(name: str) -> str:
    sanitized = _SAFE_NAME_RE.sub("_", name)
    sanitized = sanitized.strip("_ ")
    return sanitized or "VENUS_SDK_Session"


def _resolve_display_name(configured_name: str) -> str:
    if configured_name:
        return _sanitize_display_name(configured_name)
    script = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else ""
    if script and script != "-c":
        return _sanitize_display_name(script)
    return "VENUS_SDK_Session"


class MethodFileManager:
    """Manages temporary copies of executor method files.

    Call :meth:`prepare` before loading the method and :meth:`cleanup` after
    unloading it.  Safe to call :meth:`cleanup` multiple times or when no files
    were created.
    """

    def __init__(self) -> None:
        self._created_files: list[Path] = []
        self._resolved_hsl_path: str | None = None

    @property
    def resolved_hsl_path(self) -> str | None:
        return self._resolved_hsl_path

    def prepare(self, executor_hsl_path: str, display_name: str) -> str:
        resolved_name = _resolve_display_name(display_name)
        source = Path(executor_hsl_path)
        if not source.is_file():
            raise FileNotFoundError(f"Executor HSL file not found: {executor_hsl_path}")

        try:
            target_hsl = source.parent / f"{resolved_name}.hsl"
            _logger.debug("Copying %s -> %s", source, target_hsl)
            shutil.copy2(source, target_hsl)
            self._created_files.append(target_hsl)

            source_stp = source.with_suffix(".stp")
            if source_stp.is_file():
                target_stp = source.parent / f"{resolved_name}.stp"
                _logger.debug("Copying %s -> %s", source_stp, target_stp)
                shutil.copy2(source_stp, target_stp)
                self._created_files.append(target_stp)
            else:
                _logger.warning(
                    "STP file not found alongside executor: %s — skipping STP copy",
                    source_stp,
                )

            self._resolved_hsl_path = str(target_hsl)
        except PermissionError:
            _logger.warning(
                "Permission denied when creating temporary method files in %s "
                "— falling back to default executor file",
                source.parent,
                exc_info=True,
            )
            self._resolved_hsl_path = executor_hsl_path
        except OSError:
            _logger.warning(
                "Could not create temporary method files (check write permissions "
                "for %s) — falling back to default executor file",
                source.parent,
                exc_info=True,
            )
            self._resolved_hsl_path = executor_hsl_path

        return self._resolved_hsl_path

    def cleanup(self) -> None:
        for path in self._created_files:
            try:
                if path.exists():
                    path.unlink()
                    _logger.debug("Removed temporary method file: %s", path)
            except PermissionError:
                _logger.warning("Permission denied removing temporary method file: %s", path, exc_info=True)
            except OSError:
                _logger.warning("Failed to remove temporary method file: %s", path, exc_info=True)
        self._created_files.clear()
        self._resolved_hsl_path = None

