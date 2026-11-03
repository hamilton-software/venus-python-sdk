"""Durable, queryable record of consumable usage across runs, on one spoke, over time.

Nothing about a run's *live* tracking (``manager.Run.tips``/``reagents``/``labware``) survives
past that run in memory -- this is the piece that does: every finished run's consumption is
written here exactly once (keyed by ``run_id``, so retrying/re-finalizing a run can never double
count), plus explicit events (a tip rack reload, a reagent refill, a manual count correction).

Backed by ``sqlite3`` (standard library, WAL mode so live tracking writes don't block report
reads), one file per spoke at ``<scripts_dir>/.consumables/ledger.sqlite``.

A **simulated** run's usage is still recorded (useful for testing the ledger itself) but every
read defaults to ``simulate=False`` -- simulated runs must never silently inflate real inventory
numbers.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    script TEXT,
    sha256 TEXT,
    started_at TEXT,
    ended_at TEXT,
    status TEXT,
    simulate INTEGER,
    instrument_serial TEXT,
    venus_run_guid TEXT,
    partial INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_key TEXT NOT NULL,
    item_label TEXT,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_kind_item_ts ON usage(kind, item_key, ts);
CREATE INDEX IF NOT EXISTS idx_usage_run ON usage(run_id);

CREATE TABLE IF NOT EXISTS levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_key TEXT NOT NULL,
    level REAL,
    capacity REAL,
    source TEXT NOT NULL,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_levels_kind_item_ts ON levels(kind, item_key, ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_key TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL,
    operator TEXT,
    note TEXT,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_kind_item_ts ON events(kind, item_key, ts);

CREATE TABLE IF NOT EXISTS config (
    kind TEXT NOT NULL,
    item_key TEXT NOT NULL,
    label TEXT,
    low_threshold REAL,
    unit TEXT,
    PRIMARY KEY (kind, item_key)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UsageRow:
    kind: str
    item_key: str
    item_label: str | None
    quantity: float
    unit: str
    source: str | None = None
    ts: str | None = None


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    script: str
    sha256: str | None
    started_at: str | None
    ended_at: str | None
    status: str
    simulate: bool
    instrument_serial: str | None = None
    venus_run_guid: str | None = None
    partial: bool = False


class ConsumablesLedger:
    """One connection, reused under a lock -- a spoke has one run active at a time, so there is
    never real write contention; the lock just keeps sqlite3's per-connection thread rule honest
    when tools are called from different asyncio tasks/threads."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @classmethod
    def default(cls) -> "ConsumablesLedger":
        from hamilton_venus_mcp.scripts_store import default_scripts_dir

        return cls(default_scripts_dir() / ".consumables" / "ledger.sqlite")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- writing -----------------------------------------------------------------------------

    def record_run(self, run: RunRecord, usage: list[UsageRow], levels: list[dict[str, Any]] | None = None) -> bool:
        """Insert *run* and its *usage* rows. Idempotent by ``run_id`` -- a run already present
        is left untouched and this returns ``False`` (never double counts a re-finalized or
        retried run). Returns ``True`` when this call actually inserted the run.
        """
        with self._lock:
            existing = self._conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()
            if existing is not None:
                return False
            self._conn.execute(
                "INSERT INTO runs (run_id, script, sha256, started_at, ended_at, status, simulate, "
                "instrument_serial, venus_run_guid, partial, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.script,
                    run.sha256,
                    run.started_at,
                    run.ended_at,
                    run.status,
                    int(run.simulate),
                    run.instrument_serial,
                    run.venus_run_guid,
                    int(run.partial),
                    _now(),
                ),
            )
            ts = run.ended_at or run.started_at or _now()
            for row in usage:
                self._conn.execute(
                    "INSERT INTO usage (run_id, ts, kind, item_key, item_label, quantity, unit, source) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (run.run_id, row.ts or ts, row.kind, row.item_key, row.item_label, row.quantity, row.unit, row.source),
                )
            for level in levels or []:
                self._conn.execute(
                    "INSERT INTO levels (ts, kind, item_key, level, capacity, source, run_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        level.get("ts") or ts,
                        level["kind"],
                        level["item_key"],
                        level.get("level"),
                        level.get("capacity"),
                        level.get("source", "run_end"),
                        run.run_id,
                    ),
                )
            self._conn.commit()
            return True

    def add_event(
        self,
        kind: str,
        item_key: str,
        event_type: str,
        *,
        amount: float | None = None,
        operator: str | None = None,
        note: str | None = None,
        run_id: str | None = None,
        ts: str | None = None,
    ) -> int:
        """Record a reload/threshold/manual-correction event. Returns the new row's id."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO events (ts, kind, item_key, type, amount, operator, note, run_id) VALUES (?,?,?,?,?,?,?,?)",
                (ts or _now(), kind, item_key, event_type, amount, operator, note, run_id),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def record_level(
        self, kind: str, item_key: str, level: float | None, capacity: float | None = None, *, source: str, run_id: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO levels (ts, kind, item_key, level, capacity, source, run_id) VALUES (?,?,?,?,?,?,?)",
                (_now(), kind, item_key, level, capacity, source, run_id),
            )
            self._conn.commit()

    def set_config(self, kind: str, item_key: str, *, label: str | None = None, low_threshold: float | None = None, unit: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO config (kind, item_key, label, low_threshold, unit) VALUES (?,?,?,?,?) "
                "ON CONFLICT(kind, item_key) DO UPDATE SET "
                "label=COALESCE(excluded.label, config.label), "
                "low_threshold=COALESCE(excluded.low_threshold, config.low_threshold), "
                "unit=COALESCE(excluded.unit, config.unit)",
                (kind, item_key, label, low_threshold, unit),
            )
            self._conn.commit()

    # -- reading -----------------------------------------------------------------------------

    def usage_report(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        kind: str | None = None,
        item_key: str | None = None,
        script: str | None = None,
        simulate: bool = False,
        group_by: str = "item",
    ) -> list[dict[str, Any]]:
        """Total quantity per *group_by* (``"item"``, ``"day"``, ``"run"``, or ``"script"``),
        over usage rows whose run falls in ``[start, end)`` (ISO timestamps; either end
        omittable) and matches the other filters. ``simulate=False`` (default) excludes every
        run recorded with ``simulate=True`` -- pass ``True`` explicitly to include test runs.
        """
        if group_by not in ("item", "day", "run", "script"):
            raise ValueError('group_by must be one of "item", "day", "run", "script".')
        group_expr = {
            "item": "u.kind, u.item_key, u.item_label",
            "day": "substr(u.ts, 1, 10)",
            "run": "u.run_id",
            "script": "r.script",
        }[group_by]
        select_extra = {
            "item": "u.kind AS kind, u.item_key AS item_key, u.item_label AS item_label",
            "day": "substr(u.ts, 1, 10) AS day",
            "run": "u.run_id AS run_id, r.script AS script",
            "script": "r.script AS script",
        }[group_by]

        clauses = ["r.simulate = ?"]
        params: list[Any] = [int(simulate)]
        if start:
            clauses.append("u.ts >= ?")
            params.append(start)
        if end:
            clauses.append("u.ts < ?")
            params.append(end)
        if kind:
            clauses.append("u.kind = ?")
            params.append(kind)
        if item_key:
            clauses.append("u.item_key = ?")
            params.append(item_key)
        if script:
            clauses.append("r.script = ?")
            params.append(script)
        where = " AND ".join(clauses)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT {select_extra}, SUM(u.quantity) AS total_quantity, u.unit AS unit, COUNT(*) AS entries "
                f"FROM usage u JOIN runs r ON r.run_id = u.run_id "
                f"WHERE {where} GROUP BY {group_expr}, u.unit ORDER BY total_quantity DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def current_levels(self, kind: str | None = None) -> list[dict[str, Any]]:
        """The most recent recorded level for every (kind, item_key), joined with any
        configured threshold/label. One row per item, latest ``levels`` row wins."""
        # A simulated run consumes nothing, so its levels never count (older databases may hold
        # some from before they were excluded at write time).
        real_only = "(run_id IS NULL OR run_id NOT IN (SELECT run_id FROM runs WHERE simulate = 1))"
        clause = f"WHERE {real_only}" + (" AND kind = ?" if kind else "")
        params = [kind] if kind else []
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT l.kind, l.item_key, l.level, l.capacity, l.ts AS last_updated, l.source,
                       c.label, c.low_threshold, c.unit
                FROM levels l
                JOIN (
                    SELECT kind, item_key, MAX(ts) AS max_ts FROM levels {clause} GROUP BY kind, item_key
                ) latest ON latest.kind = l.kind AND latest.item_key = l.item_key AND latest.max_ts = l.ts
                LEFT JOIN config c ON c.kind = l.kind AND c.item_key = l.item_key
                WHERE (l.run_id IS NULL OR l.run_id NOT IN (SELECT run_id FROM runs WHERE simulate = 1))
                """,
                params,
            ).fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            if entry["capacity"] and entry["level"] is not None:
                entry["percent"] = max(0.0, min(1.0, entry["level"] / entry["capacity"]))
            else:
                entry["percent"] = None
            if entry["kind"] == "tip":
                # Tip thresholds are an absolute remaining-tip count (set_tip_threshold,
                # matching the live edge-triggered warning in child_bootstrap.py) -- not a
                # fraction of capacity, unlike every other kind's low_threshold.
                entry["low"] = (
                    entry["low_threshold"] is not None
                    and entry["level"] is not None
                    and entry["level"] <= entry["low_threshold"]
                )
            else:
                entry["low"] = (
                    entry["percent"] is not None
                    and entry["low_threshold"] is not None
                    and entry["percent"] <= entry["low_threshold"]
                ) or (
                    entry["percent"] is None
                    and entry["low_threshold"] is not None
                    and entry["level"] is not None
                    and entry["level"] <= entry["low_threshold"]
                )
            results.append(entry)
        return results

    def low_items(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [row for row in self.current_levels(kind) if row["low"]]

    def events(self, *, kind: str | None = None, item_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if item_key:
            clauses.append("item_key = ?")
            params.append(item_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM events {where} ORDER BY ts DESC LIMIT ?", [*params, max(1, min(limit, 1000))]
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def has_run(self, run_id: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is not None
