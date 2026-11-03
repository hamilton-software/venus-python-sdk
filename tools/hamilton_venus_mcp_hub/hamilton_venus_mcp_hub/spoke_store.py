"""Where connected spokes are remembered across hub restarts -- separate from
HAMILTON_MCP_SPOKES (see spokes.py), which stays available for scripted/pinned
deployments and always takes precedence over a persisted entry with the same id.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

_logger = logging.getLogger("hamilton_venus_mcp_hub.spoke_store")

SPOKES_FILE_ENV = "HAMILTON_MCP_SPOKES_FILE"


def default_spokes_file() -> Path:
    """$HAMILTON_MCP_SPOKES_FILE, else a per-machine file under ProgramData -- same
    fallback convention as hamilton_venus_mcp's own scripts_store.default_scripts_dir()
    (a long-lived machine service's data, not tied to whichever user happens to double-
    click the start batch file; writable by standard Windows accounts, no elevation)."""
    configured = os.environ.get(SPOKES_FILE_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "Hamilton" / "mcp_hub" / "spokes.json"


def load(path: Path | None = None) -> list[dict[str, str]]:
    """[] if the file doesn't exist yet or is malformed -- logged, never raised, so a
    bad or hand-edited file can never block hub startup."""
    path = path or default_spokes_file()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [{"id": str(entry["id"]), "url": str(entry["url"])} for entry in raw]
    except Exception:
        _logger.exception("Could not read %s; starting with no persisted spokes.", path)
        return []


def save(spokes: list[dict[str, str]], path: Path | None = None) -> None:
    """Atomic overwrite (temp file + os.replace) so a crash mid-write never leaves a
    half-written, unparsable file behind."""
    path = path or default_spokes_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".spokes-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spokes, f, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise
