"""The controlled directory of scripts the spoke is allowed to run.

Only scripts that live in this one directory can be run through ``run_script``. Scripts get
there through ``import_script`` (agent-supplied text, or a ``.py`` file already on the spoke),
which validates the name and size and writes the file atomically. The store also remembers the
last static validation of each script (see ``script_validator``) together with the sha256 it
was computed for, so a script edited after it was validated is no longer considered runnable
until it is validated again.

The directory defaults to ``<SDK repo root>/mcp_scripts`` and can be moved with
``HAMILTON_MCP_SCRIPTS_DIR``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR_ENV = "HAMILTON_MCP_SCRIPTS_DIR"
MAX_SCRIPT_BYTES = 512 * 1024
INDEX_FILE_NAME = "index.json"
RUNS_DIR_NAME = ".runs"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. \-]*\.py$")
# Windows device names are not usable as file names, with or without an extension.
_RESERVED_STEMS = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


class ScriptStoreError(ValueError):
    """A script name, size, or location the store refuses."""


def default_scripts_dir() -> Path:
    """``$HAMILTON_MCP_SCRIPTS_DIR``, else ``mcp_scripts`` next to the SDK's ``src`` folder,
    else a per-machine folder under ProgramData when the SDK is installed as a wheel."""
    configured = os.environ.get(SCRIPTS_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    import hamilton_venus

    package_dir = Path(hamilton_venus.__file__).resolve().parent
    if package_dir.parent.name == "src":
        return package_dir.parent.parent / "mcp_scripts"
    return Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "Hamilton" / "mcp_scripts"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScriptStore:
    """Read/write access to the scripts directory. Every path handed out is resolved and
    checked to sit directly inside the root, so a name can never reach outside it."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else default_scripts_dir()
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def runs_dir(self) -> Path:
        return self._root / RUNS_DIR_NAME

    def ensure(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    # -- names and paths ---------------------------------------------------------------

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str) or not name:
            raise ScriptStoreError("Script name must be a non-empty string.")
        if not _NAME_RE.fullmatch(name):
            raise ScriptStoreError(
                f"Invalid script name {name!r}: use letters, digits, '_', '-', '.', or spaces, "
                "start with a letter or digit, end in '.py', and give no folder."
            )
        if ".." in name or name.endswith((" .py", "..py")):
            raise ScriptStoreError(f"Invalid script name {name!r}.")
        if name[: -len(".py")].upper() in _RESERVED_STEMS:
            raise ScriptStoreError(f"Invalid script name {name!r}: reserved device name.")
        return name

    def path_for(self, name: str) -> Path:
        self.validate_name(name)
        root = self._root.resolve()
        candidate = (root / name).resolve()
        if candidate.parent != root:
            raise ScriptStoreError(f"Script name {name!r} resolves outside the scripts directory.")
        return candidate

    # -- reading -----------------------------------------------------------------------

    def exists(self, name: str) -> bool:
        return self.path_for(name).is_file()

    def read_bytes(self, name: str) -> bytes:
        path = self.path_for(name)
        if not path.is_file():
            raise ScriptStoreError(f"No script named {name!r} in the scripts directory.")
        return path.read_bytes()

    def read_text(self, name: str) -> str:
        return self.read_bytes(name).decode("utf-8-sig")

    def sha256(self, name: str) -> str:
        return sha256_of(self.read_bytes(name))

    def list_names(self) -> list[str]:
        if not self._root.is_dir():
            return []
        names = []
        for entry in sorted(self._root.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and _NAME_RE.fullmatch(entry.name):
                names.append(entry.name)
        return names

    def list(self) -> list[dict[str, Any]]:
        results = []
        for name in self.list_names():
            path = self._root / name
            stat = path.stat()
            results.append(
                {
                    "name": name,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "sha256": sha256_of(path.read_bytes()),
                    **self.validation_status(name),
                }
            )
        return results

    # -- writing -----------------------------------------------------------------------

    def write(self, name: str, content: str, *, overwrite: bool = False) -> Path:
        if not isinstance(content, str):
            raise ScriptStoreError("Script content must be text.")
        if "\x00" in content:
            raise ScriptStoreError("Script content must not contain NUL characters.")
        data = content.encode("utf-8")
        if len(data) > MAX_SCRIPT_BYTES:
            raise ScriptStoreError(f"Script is {len(data)} bytes; the limit is {MAX_SCRIPT_BYTES}.")
        with self._lock:
            self.ensure()
            path = self.path_for(name)
            if path.exists() and not overwrite:
                raise ScriptStoreError(f"A script named {name!r} already exists; pass overwrite=True to replace it.")
            self._atomic_write(path, data)
            self._drop_validation(name)
        return path

    def read_source_file(self, source_path: str) -> tuple[str, str]:
        """Read a ``.py`` file that is already on this machine, for importing into the store.
        Returns ``(default_name, text)``. Only ``.py`` files of a sane size are accepted, so
        this cannot be used to read arbitrary files."""
        path = Path(source_path)
        if path.suffix.lower() != ".py":
            raise ScriptStoreError("Only .py files can be imported.")
        if not path.is_file():
            raise ScriptStoreError(f"No file at {source_path!r} on this machine.")
        size = path.stat().st_size
        if size > MAX_SCRIPT_BYTES:
            raise ScriptStoreError(f"File is {size} bytes; the limit is {MAX_SCRIPT_BYTES}.")
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ScriptStoreError(f"File is not valid UTF-8 text: {exc}") from exc
        return path.name, text

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=".import_", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- validation index --------------------------------------------------------------

    def _index_path(self) -> Path:
        return self._root / INDEX_FILE_NAME

    def _load_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_index(self, index: dict[str, Any]) -> None:
        self.ensure()
        self._atomic_write(self._index_path(), json.dumps(index, indent=2, sort_keys=True).encode("utf-8"))

    def _drop_validation(self, name: str) -> None:
        index = self._load_index()
        if index.pop(name, None) is not None:
            self._save_index(index)

    def record_validation(self, name: str, report: dict[str, Any]) -> None:
        """Remember *report* (a ``ValidationReport.to_dict()``) as the latest validation of
        the script, keyed by the sha256 it was computed for."""
        self.validate_name(name)
        with self._lock:
            index = self._load_index()
            index[name] = {
                "sha256": report.get("sha256"),
                "ok": bool(report.get("ok")),
                "error_count": len(report.get("errors", [])),
                "warning_count": len(report.get("warnings", [])),
                "validated_at": _now(),
            }
            self._save_index(index)

    def validation_status(self, name: str) -> dict[str, Any]:
        """``validated`` (ever validated), ``validation_ok``, counts, and ``validation_current``
        (the recorded sha256 still matches the file on disk)."""
        entry = self._load_index().get(name)
        if not entry:
            return {"validated": False, "validation_ok": False, "validation_current": False}
        try:
            current = self.sha256(name) == entry.get("sha256")
        except ScriptStoreError:
            current = False
        return {
            "validated": True,
            "validation_ok": bool(entry.get("ok")),
            "validation_current": current,
            "validation_error_count": entry.get("error_count", 0),
            "validation_warning_count": entry.get("warning_count", 0),
            "validated_at": entry.get("validated_at"),
        }

    def is_runnable(self, name: str) -> bool:
        status = self.validation_status(name)
        return bool(status["validated"] and status["validation_ok"] and status["validation_current"])
