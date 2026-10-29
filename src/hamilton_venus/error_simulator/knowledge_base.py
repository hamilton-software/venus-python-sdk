"""In-memory view of the ``ErrorSimulator`` knowledge base.

The custom ``ErrorSimulator.mdb`` is converted to
``data/error_simulator.json`` by ``hamilton_venus.tools.generate_error_simulator_data``;
this module loads that file and exposes the same lookups the HSL performed with
SQL (``MODULE`` resolution, per-table ``FW`` / ``ERROR`` rows). The data is tiny
(~1400 rows) and read-only, so it lives entirely in memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from hamilton_venus.error_simulator.keywords import generate_keywords

_DATA_FILE = Path(__file__).parent / "data" / "error_simulator.json"


@dataclass(frozen=True)
class ModuleInfo:
    """One row of the ``MODULE`` table."""

    table: str  # canonical suffix, e.g. "1mL"
    description: str
    key1: str | None
    key2: str | None
    prefix: dict[str, str | None]  # {"STAR": "P", "VANTAGE": "P"}

    def command_prefix(self, instrument: str) -> str:
        return self.prefix.get(instrument) or ""


@dataclass(frozen=True)
class Row:
    """One ``FW`` or ``ERROR`` row of an ``<INSTR>-<MODULE>`` table."""

    code: str
    description: str
    key1: str | None
    key2: str | None
    key3: str | None
    tag1: str | None
    tag2: str | None
    main: str | None = None  # STAR error rows only

    def keys(self) -> tuple[str | None, str | None, str | None]:
        return (self.key1, self.key2, self.key3)


class KnowledgeBase:
    """Loaded ``error_simulator.json``."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.source: dict[str, str] = payload.get("source", {})
        self.modules: list[ModuleInfo] = [
            ModuleInfo(
                table=m["table"],
                description=m.get("description") or "",
                key1=m.get("key1"),
                key2=m.get("key2"),
                prefix=m.get("prefix", {}),
            )
            for m in payload["modules"]
        ]
        self._tables: dict[str, dict[str, list[Row]]] = {}
        for table_key, groups in payload["tables"].items():
            self._tables[table_key] = {
                "fw": [_row(r) for r in groups.get("fw", [])],
                "error": [_row(r) for r in groups.get("error", [])],
            }

    # -- construction ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> KnowledgeBase:
        return _load_cached(str(path or _DATA_FILE))

    # -- MODULE resolution --------------------------------------------------------

    def resolve_module(self, name: str) -> ModuleInfo:
        """Resolve a module name to its :class:`ModuleInfo`.

        Accepts the canonical suffix (``"1mL"``), a case-insensitive match on it,
        or -- like the HSL -- a free-text phrase matched against ``KEY1``/``KEY2``
        after keyword generation.
        """
        cleaned = (name or "").strip()
        for module in self.modules:
            if module.table.casefold() == cleaned.casefold():
                return module

        # "/" separates alternatives in module names ("IPG/iSWAP"); the HSL's
        # keyword generation does not split on it, so do it here.
        keywords = set(generate_keywords(cleaned.replace("/", " ")))
        hits = [
            module
            for module in self.modules
            if (module.key1 and module.key1 in keywords) or (module.key2 and module.key2 in keywords)
        ]
        if len(hits) == 1:
            return hits[0]
        from hamilton_venus.error_simulator.exceptions import NoMatchError

        valid = ", ".join(sorted(m.table for m in self.modules))
        raise NoMatchError(
            f"module {name!r} matched {len(hits)} entries; valid modules: {valid}",
            candidates=[m.table for m in self.modules],
        )

    # -- table access -----------------------------------------------------------

    def table_key(self, instrument: str, module: ModuleInfo | str) -> str:
        suffix = module.table if isinstance(module, ModuleInfo) else module
        return f"{instrument}-{suffix}"

    def firmware_rows(self, instrument: str, module: ModuleInfo | str) -> list[Row]:
        return self._tables.get(self.table_key(instrument, module), {}).get("fw", [])

    def error_rows(self, instrument: str, module: ModuleInfo | str) -> list[Row]:
        return self._tables.get(self.table_key(instrument, module), {}).get("error", [])

    def has_table(self, instrument: str, module: ModuleInfo | str) -> bool:
        return self.table_key(instrument, module) in self._tables


def _row(raw: dict[str, Any]) -> Row:
    return Row(
        code=raw.get("code") or "",
        description=raw.get("description") or "",
        key1=raw.get("key1"),
        key2=raw.get("key2"),
        key3=raw.get("key3"),
        tag1=raw.get("tag1"),
        tag2=raw.get("tag2"),
        main=raw.get("main"),
    )


@lru_cache(maxsize=4)
def _load_cached(path: str) -> KnowledgeBase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return KnowledgeBase(payload)
