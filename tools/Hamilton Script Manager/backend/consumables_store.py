"""JSON-file-backed store for consumables tracking configuration: per-tip-pool
low-count thresholds, and the registry of labware positions treated as
tracked reagent reservoirs (explicitly added via the UI, or auto-discovered
by a run and persisted here so later runs recognize them immediately).

Mirrors shortcuts_store.py's pattern: no database, single-writer, rewritten
whole under a lock on every mutation. This store only holds *configuration*
(thresholds, which positions to track, labels) -- live measured state
(current tip counts, remaining reagent volume) lives only in the running
subprocess's bootstrap state and is never persisted here, since deck contents
can change between runs (see script_runner.py's docstring for how this
config is pushed into each run's bootstrap).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from backend.config import BackendConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reservoir_key(labware: str, well: str) -> str:
    return f"{labware}@{well}"


@dataclass
class TipPoolConfig:
    tip_pool: str
    low_threshold: int


@dataclass
class ReservoirConfig:
    key: str
    labware: str
    well: str
    label: str
    source: str  # "manual" | "auto"
    created_at: str


class ConsumablesStore:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        config.consumables_file.parent.mkdir(parents=True, exist_ok=True)
        if not config.consumables_file.is_file():
            self._write({"tip_pools": {}, "reservoirs": {}})

    # -- persistence ----------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._config.consumables_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"tip_pools": {}, "reservoirs": {}}
        data.setdefault("tip_pools", {})
        data.setdefault("reservoirs", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self._config.consumables_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._config.consumables_file)

    # -- queries ----------------------------------------------------------

    def list_config(self) -> dict[str, Any]:
        with self._lock:
            data = self._read()
        return {"tip_pools": data["tip_pools"], "reservoirs": data["reservoirs"]}

    # -- mutations ----------------------------------------------------------

    def set_tip_threshold(self, tip_pool: str, threshold: int) -> TipPoolConfig:
        with self._lock:
            data = self._read()
            entry = TipPoolConfig(tip_pool=tip_pool, low_threshold=threshold)
            data["tip_pools"][tip_pool] = asdict(entry)
            self._write(data)
            return entry

    def add_reservoir(self, labware: str, well: str, label: str) -> ReservoirConfig:
        with self._lock:
            data = self._read()
            key = _reservoir_key(labware, well)
            existing = data["reservoirs"].get(key)
            entry = ReservoirConfig(
                key=key,
                labware=labware,
                well=well,
                label=label or key,
                source="manual",
                created_at=existing["created_at"] if existing else _now(),
            )
            data["reservoirs"][key] = asdict(entry)
            self._write(data)
            return entry

    def record_auto_discovered_reservoir(self, key: str, labware: str, well: str) -> ReservoirConfig:
        """Persist a reservoir a run discovered on its own, so later runs
        recognize it immediately. Never downgrades an already-manual entry --
        only inserts when the key isn't known at all yet.

        `key` is the exact key the run tracked it under (script_runner.py's
        `_record_reservoir_aspirate` uses the bare labware name for a
        connected/reservoir-class labware, not `labware@well` -- it must be
        persisted under that same key, or the next run's live update and
        this store's config-seeded entry end up as two separate,
        never-converging rows in the UI instead of one."""
        with self._lock:
            data = self._read()
            if key in data["reservoirs"]:
                return ReservoirConfig(**data["reservoirs"][key])
            entry = ReservoirConfig(
                key=key, labware=labware, well=well, label=key, source="auto", created_at=_now()
            )
            data["reservoirs"][key] = asdict(entry)
            self._write(data)
            return entry
