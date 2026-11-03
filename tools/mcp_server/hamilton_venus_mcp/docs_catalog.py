"""Reflection-based catalog of this SDK's own docs/ folder (markdown files), so an agent
can discover and read them through MCP instead of needing local filesystem access -- the
same problem list_sdk_commands/search_labware solve for the SDK's command/labware catalogs.

docs/ sits as a sibling of src/ at the SDK install root (see the GUI installer's
CopySdkToRoot, which lands both there together in every install, and this repo's own
editable-install dev layout matches it exactly). Located here relative to the installed
hamilton_venus package itself -- not a hardcoded path -- so this resolves correctly
regardless of where the SDK was actually installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import hamilton_venus

_DOCS_ROOT = Path(hamilton_venus.__file__).resolve().parent.parent.parent / "docs"


@dataclass(frozen=True)
class DocEntry:
    uri: str
    relative_path: str
    title: str
    path: Path


def read_doc_text(path: Path) -> str:
    """Read one docs/*.md file's text. Most of this repo's docs are plain UTF-8, but at
    least one carries a stray byte (e.g. a smart-dash typed in a Windows editor) that
    isn't valid UTF-8 -- falls back to cp1252 (a superset of Latin-1, the common case for
    that kind of byte on Windows) rather than raising or silently mangling the content
    with errors="replace".
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")


def _title_from_doc(path: Path) -> str:
    """The doc's own first non-blank line, leading markdown heading markers stripped --
    a far more useful listing title than the bare filename, and needs no separate
    front-matter convention this repo's docs don't already follow.
    """
    try:
        for line in read_doc_text(path).splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped
    except OSError:
        pass
    return path.stem


def _build_docs_catalog() -> list[DocEntry]:
    if not _DOCS_ROOT.is_dir():
        return []
    entries: list[DocEntry] = []
    for path in sorted(_DOCS_ROOT.rglob("*.md")):
        rel = path.relative_to(_DOCS_ROOT).as_posix()
        entries.append(
            DocEntry(
                # MCP's Url type percent-encodes reserved/unsafe characters (e.g.
                # spaces in a folder name) when a resource is actually registered
                # and listed -- built pre-encoded here (keeping "/" as a path separator)
                # so this uri matches the server's own canonical form exactly, rather
                # than drifting from what resources/list actually reports.
                uri=f"docs://hamilton-venus/{quote(rel, safe='/')}",
                relative_path=rel,
                title=_title_from_doc(path),
                path=path,
            )
        )
    return entries


DOCS_CATALOG: list[DocEntry] = _build_docs_catalog()
DOCS_BY_PATH: dict[str, DocEntry] = {entry.relative_path: entry for entry in DOCS_CATALOG}
