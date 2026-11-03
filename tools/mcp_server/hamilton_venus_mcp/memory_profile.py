"""Opt-in memory profiling for hunting a leak in a long-running spoke.

Set HAMILTON_MCP_MEMORY_PROFILE=<seconds> (e.g. 300) before starting the spoke. Every interval a
daemon thread appends to a report file (HAMILTON_MCP_MEMORY_PROFILE_FILE, default
``hamilton_mcp_memory_profile.txt`` in the temp folder):

* the Python allocation sites that grew most since the first snapshot (tracemalloc), with their
  call stacks, and
* the object types whose count grew most since the first snapshot (gc).

Growth that shows up in neither is native memory (COM / .NET / C extensions), not Python objects.
tracemalloc slows the spoke down noticeably, so leave this unset outside leak hunts.
"""

from __future__ import annotations

import gc
import logging
import os
import tempfile
import threading
import time
import tracemalloc
from collections import Counter
from pathlib import Path

PROFILE_ENV = "HAMILTON_MCP_MEMORY_PROFILE"
PROFILE_FILE_ENV = "HAMILTON_MCP_MEMORY_PROFILE_FILE"

_FRAMES = 12
_TOP_SITES = 15
_TOP_TYPES = 20

_logger = logging.getLogger("hamilton_venus_mcp")


def _type_name(obj: object) -> str:
    # Proxies (COM, .NET) can have a type whose __module__ / __qualname__ is not a plain string.
    kind = type(obj)
    try:
        return f"{kind.__module__}.{kind.__qualname__}"
    except Exception:
        return "<unnamed type>"


def _type_counts() -> Counter[str]:
    return Counter(_type_name(obj) for obj in gc.get_objects())


def _report(path: Path, baseline: tracemalloc.Snapshot, baseline_types: Counter[str], started: float) -> None:
    gc.collect()
    snapshot = tracemalloc.take_snapshot().filter_traces((tracemalloc.Filter(False, tracemalloc.__file__),))
    current, peak = tracemalloc.get_traced_memory()
    lines = [
        "",
        f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  +{(time.monotonic() - started) / 60:.0f} min  "
        f"traced {current / 1048576:.1f} MB (peak {peak / 1048576:.1f} MB) ===",
        "-- allocation sites grown since the first snapshot --",
    ]
    for stat in snapshot.compare_to(baseline, "traceback")[:_TOP_SITES]:
        lines.append(f"{stat.size_diff / 1024:+10.1f} KiB  {stat.count_diff:+8d} blocks  ({stat.size / 1024:.1f} KiB now)")
        lines.extend(f"      {line}" for line in stat.traceback.format(limit=6))
    lines.append("-- object types grown since the first snapshot --")
    grown = Counter(_type_counts())
    grown.subtract(baseline_types)
    for name, delta in grown.most_common(_TOP_TYPES):
        if delta <= 0:
            break
        lines.append(f"{delta:+9d}  {name}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _run(interval_s: float, path: Path) -> None:
    started = time.monotonic()
    # The first snapshot is taken after one interval, so start-up allocations are not counted as growth.
    time.sleep(interval_s)
    try:
        gc.collect()
        baseline = tracemalloc.take_snapshot().filter_traces((tracemalloc.Filter(False, tracemalloc.__file__),))
        baseline_types = _type_counts()
    except Exception:
        _logger.exception("Memory profile baseline failed; profiling stopped")
        return
    while True:
        time.sleep(interval_s)
        try:
            _report(path, baseline, baseline_types, started)
        except Exception:
            _logger.exception("Memory profile report failed")


def start_if_requested() -> None:
    """Start the profiler when HAMILTON_MCP_MEMORY_PROFILE is set to a positive number of seconds."""
    raw = os.getenv(PROFILE_ENV, "").strip()
    if not raw:
        return
    try:
        interval_s = float(raw)
    except ValueError:
        _logger.warning("%s=%r is not a number of seconds; memory profiling stays off.", PROFILE_ENV, raw)
        return
    if interval_s <= 0:
        return
    path = Path(os.getenv(PROFILE_FILE_ENV) or Path(tempfile.gettempdir()) / "hamilton_mcp_memory_profile.txt")
    tracemalloc.start(_FRAMES)
    threading.Thread(target=_run, args=(interval_s, path), name="memory-profile", daemon=True).start()
    _logger.warning("Memory profiling every %g s (slows the spoke down); report: %s", interval_s, path)
