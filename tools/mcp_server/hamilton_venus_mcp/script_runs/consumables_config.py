"""Per-spoke configuration for consumables tracking: tip pool low-count thresholds and the
registry of labware positions tracked as reagent sources (a low-percent threshold, and an
optional human-readable label/lot).

Mirrors ``python_script_manager_app/backend/consumables_store.py``'s pattern (single JSON file,
single writer, rewritten whole under a lock on every mutation) but only holds *configuration*.
Measured state (current tip counts, remaining reagent volume) lives only in a run's own tracking
(``manager.Run``) and the consumables ledger (``consumables_ledger``) -- never here, since deck
contents can change between runs.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOW_TIP_THRESHOLD = 10
DEFAULT_LOW_PERCENT = 0.10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reagent_key(labware: str, well: str | None) -> str:
    """Same convention the run's live tracking uses: a pooled reservoir is keyed by its bare
    labware id, anything tracked per well by ``labware@well``.

    Not case-normalized: *labware* is used exactly as given. VENUS stores every labware id on
    the deck layout lower-cased regardless of the case it was added with, and the live
    tracking's own key comes from a script's own positions-selector string (whatever case that
    happened to use), not an echo from VENUS -- so this only matches a key built elsewhere if
    both call sites pass the same casing. Pass the same casing here as the script's own
    ``positions=`` selector to have a manually configured threshold actually match the
    auto-discovered/tracked key at run time.
    """
    return labware if not well or well == "all" else f"{labware}@{well}"


@dataclass
class TipPoolThreshold:
    tip_pool: str
    low_threshold: int


@dataclass
class ReagentConfig:
    key: str
    labware: str
    well: str
    label: str
    low_percent: float
    lot: str | None
    source: str  # "manual" | "auto"
    created_at: str
    # Full-container volume to report percent-full against, when the labware's own geometry is not
    # what the user means (a "60 mL" trough whose geometry works out to ~80 mL). None = use the geometry.
    capacity_ul: float | None = None


class ConsumablesConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> "ConsumablesConfigStore":
        from hamilton_venus_mcp.scripts_store import default_scripts_dir

        return cls(default_scripts_dir() / ".consumables" / "config.json")

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"tip_pools": {}, "reagents": {}}
        if not isinstance(data, dict):
            return {"tip_pools": {}, "reagents": {}}
        data.setdefault("tip_pools", {})
        data.setdefault("reagents", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)

    def snapshot(self) -> dict[str, Any]:
        """Everything a run's child process needs, in one call."""
        with self._lock:
            return self._read()

    def set_tip_threshold(self, tip_pool: str, low_threshold: int) -> TipPoolThreshold:
        if low_threshold < 0:
            raise ValueError("low_threshold must not be negative.")
        with self._lock:
            data = self._read()
            entry = TipPoolThreshold(tip_pool=tip_pool, low_threshold=low_threshold)
            data["tip_pools"][tip_pool] = asdict(entry)
            self._write(data)
            return entry

    def register_reagent(
        self,
        labware: str,
        well: str,
        label: str = "",
        low_percent: float = DEFAULT_LOW_PERCENT,
        lot: str | None = None,
        capacity_ul: float | None = None,
    ) -> ReagentConfig:
        if not 0.0 <= low_percent <= 1.0:
            raise ValueError("low_percent must be between 0.0 and 1.0.")
        if capacity_ul is not None and not capacity_ul > 0:
            raise ValueError("capacity_ul must be greater than 0.")
        with self._lock:
            data = self._read()
            key = reagent_key(labware, well)
            existing = data["reagents"].get(key)
            entry = ReagentConfig(
                key=key,
                labware=labware,
                well=well or "all",
                label=label or key,
                low_percent=low_percent,
                lot=lot,
                source="manual",
                created_at=existing["created_at"] if existing else _now(),
                # Registering again without a capacity keeps the one set earlier.
                capacity_ul=capacity_ul if capacity_ul is not None else (existing or {}).get("capacity_ul"),
            )
            data["reagents"][key] = asdict(entry)
            self._write(data)
            return entry

    def record_auto_discovered_reagent(self, key: str, labware: str, well: str) -> ReagentConfig:
        """Persist a reagent source a run discovered on its own (a reservoir-class labware, or
        any tracked well), so later runs recognize it immediately and can still be given a
        threshold. Never downgrades an already-manual entry -- only inserts when unknown."""
        with self._lock:
            data = self._read()
            if key in data["reagents"]:
                return ReagentConfig(**data["reagents"][key])
            entry = ReagentConfig(
                key=key,
                labware=labware,
                well=well or "all",
                label=key,
                low_percent=DEFAULT_LOW_PERCENT,
                lot=None,
                source="auto",
                created_at=_now(),
            )
            data["reagents"][key] = asdict(entry)
            self._write(data)
            return entry

    def remove_reagent(self, key: str) -> bool:
        with self._lock:
            data = self._read()
            if key not in data["reagents"]:
                return False
            del data["reagents"][key]
            self._write(data)
            return True
