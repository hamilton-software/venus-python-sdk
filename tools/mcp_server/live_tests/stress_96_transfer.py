"""Stress test for the MCP spoke's memory: build a deck, do a 96-well plate-to-plate transfer,
tear the deck down, and repeat for hours.

One cycle:
  add tip + plate carriers -> add tip rack -> reset tip counter -> add 2 plates ->
  MPH96 tip pickup / aspirate / dispense / tip eject -> remove all labware.

The session starts on a blank deck and stays open across cycles (a new session is started
every --cycles-per-session cycles, 0 = never, to also exercise start/close). After every cycle
the spoke process's working set / private bytes are appended to a CSV, so a leak shows up as
a line that keeps climbing. The summary at the end (and on Ctrl-C) gives the growth per cycle.

Usage (spoke already running with HAMILTON_MCP_TRANSPORT=streamable-http):
    python stress_96_transfer.py --hours 4
    python stress_96_transfer.py --cycles 500 --cycles-per-session 50 --url http://127.0.0.1:8001/mcp
    python stress_96_transfer.py --start-local --hours 8      # starts a spoke on port 8000 first

Simulation only unless --live is given. Refuses to start if VENUS is running a method, because
starting a session aborts it.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# orchestrator_client is stdlib-only; import it straight from the repo if it isn't installed.
_CLIENT_SRC = Path(__file__).resolve().parents[2] / "orchestrator_client"
if _CLIENT_SRC.is_dir():
    sys.path.insert(0, str(_CLIENT_SRC))

from orchestrator_client import Instrument, InstrumentType, OrchestratorCallError  # noqa: E402

VENUS_RUN_STATE_URL = "http://localhost:42400/api/vector/v3/execution/run-state"

# VENUS-side processes whose private bytes are logged next to the spoke's, to tell a leak in the
# spoke from one on the VENUS side (the RunExecutor is where the method runs).
VENUS_PROCESSES = {
    "runexecutor": "Hamilton.WebAPI.RunExecutor",
    "webapihost": "Hamilton.WebAPI.Host",
    "desktop": "Hamilton.VENUS",
}

TIP_CARRIER_ID = "StressTipCarrier"
PLATE_CARRIER_ID = "StressPlateCarrier"
TIP_RACK_ID = "StressTips"
SOURCE_ID = "StressSource"
DEST_ID = "StressDest"
TIP_POOL = "StressTips300"

TIP_CARRIER = "TIP_CAR_480BC"
PLATE_CARRIER = "PLT_CAR_L5_DWP"
TIP_RACK = "Tip_Rack_300uL"
PLATE = "BioRad_HSP_96FullSkirt"
LIQUID_CLASS = "StandardVolume_96COREHead_Water_DispenseSurface_Empty"
VOLUME_UL = 100.0

# Labware ids VENUS creates for the carrier sites are removed in this order: children first.
REMOVE_ORDER = [SOURCE_ID, DEST_ID, TIP_RACK_ID, PLATE_CARRIER_ID, TIP_CARRIER_ID]


def venus_run_state() -> int | None:
    try:
        with urllib.request.urlopen(VENUS_RUN_STATE_URL, timeout=5) as response:
            return int(response.read().decode().strip())
    except Exception:
        return None


def listening_pid(port: int) -> int | None:
    """PID listening on *port* on this PC (None if remote or not found)."""
    command = f"(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out) if out else None
    except Exception:
        return None


def process_memory_mb(pid: int) -> tuple[float, float] | None:
    """(working set, private bytes) in MB for *pid*."""
    command = f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p) {{ '{{0}},{{1}}' -f $p.WorkingSet64, $p.PrivateMemorySize64 }}"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=20).stdout.strip()
        working, private = out.split(",")
        return int(working) / 1048576, int(private) / 1048576
    except Exception:
        return None


def venus_memory_mb() -> dict[str, float]:
    """Summed private bytes in MB per VENUS process name in VENUS_PROCESSES (missing: not running)."""
    names = ",".join(f"'{name}'" for name in VENUS_PROCESSES.values())
    command = f"Get-Process -Name {names} -ErrorAction SilentlyContinue | ForEach-Object {{ '{{0}},{{1}}' -f $_.ProcessName, $_.PrivateMemorySize64 }}"
    totals: dict[str, float] = {}
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            name, _, size = line.strip().partition(",")
            totals[name] = totals.get(name, 0.0) + int(size) / 1048576
    except Exception:
        return {}
    return {key: totals[name] for key, name in VENUS_PROCESSES.items() if name in totals}


# .NET counters of the RunExecutor (where HSL methods run, and where the HSLJson / HSLHttp
# assemblies are exposed to HSL as COM objects). CCWs are the COM-callable wrappers .NET keeps
# for managed objects handed to COM: objects HSL creates and never releases keep theirs, so a
# CCW count that only climbs is an HSLJson / HSLHttp object leak. Values are (counter path, scale).
DOTNET_COUNTERS = {
    "dotnet_heap_mb": (r"\.NET CLR Memory(Hamilton.WebAPI.RunExecutor*)\# Bytes in all Heaps", 1048576),
    "ccws": (r"\.NET CLR Interop(Hamilton.WebAPI.RunExecutor*)\# of CCWs", 1),
    "gc_handles": (r"\.NET CLR Memory(Hamilton.WebAPI.RunExecutor*)\# GC Handles", 1),
    "gen2_collections": (r"\.NET CLR Memory(Hamilton.WebAPI.RunExecutor*)\# Gen 2 Collections", 1),
}


def dotnet_counters() -> dict[str, float]:
    """The RunExecutor's DOTNET_COUNTERS values (missing when it isn't running or has no counters)."""
    paths = ",".join(f"'{path}'" for path, _ in DOTNET_COUNTERS.values())
    command = (
        f"Get-Counter -Counter {paths} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples | "
        "ForEach-Object { '{0}|{1}' -f $_.Path, $_.CookedValue }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return {}
    values: dict[str, float] = {}
    for line in out.splitlines():
        path, _, value = line.strip().partition("|")
        for key, (counter, scale) in DOTNET_COUNTERS.items():
            if path.rsplit("\\", 1)[1] == counter.rsplit("\\", 1)[1].lower():
                values[key] = values.get(key, 0.0) + float(value) / scale
    return values


class MeteredInstrument(Instrument):
    """Instrument that reads the RunExecutor's CCW count after every command and keeps the change
    per command name, so the commands that leave COM objects behind stand out (--per-step). Each
    read takes about a second, and events VENUS delivers late are counted against the next command."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.ccw_deltas: dict[str, list[float]] = {}
        self._last_ccws: float | None = None

    def call(self, name: str, /, **kwargs: object) -> object:
        if self._last_ccws is None:
            self._last_ccws = dotnet_counters().get("ccws")
        result = super().call(name, **kwargs)
        ccws = dotnet_counters().get("ccws")
        if ccws is not None and self._last_ccws is not None:
            self.ccw_deltas.setdefault(name, []).append(ccws - self._last_ccws)
        self._last_ccws = ccws
        return result


def print_ccw_deltas(instrument: MeteredInstrument, cycles: int) -> None:
    print("\nCCWs left behind, per call and per cycle (all calls of a command added up):")
    per_cycle = {name: sum(deltas) / cycles for name, deltas in instrument.ccw_deltas.items()}
    for name, deltas in sorted(instrument.ccw_deltas.items(), key=lambda item: -per_cycle[item[0]]):
        print(f"  {name:32s} {statistics.fmean(deltas):7.1f} per call  {per_cycle[name]:7.1f} per cycle  (min {min(deltas):.0f}, max {max(deltas):.0f}, {len(deltas)} calls)")
    print(f"  {'total per cycle':32s} {'':16s}{sum(per_cycle.values()):7.1f}")


def run_probe(instrument: Instrument, commands: list[str], calls: int, *, simulate: bool, instrument_type: InstrumentType) -> int:
    """Call each argument-less command *calls* times on an empty deck, reading the CCW count every
    tenth of the way, to see whether a command that does no deck work still leaves objects behind."""
    if dotnet_counters().get("ccws") is None:
        print("The RunExecutor's CCW counter can't be read -- is VENUS running?")
        return 2
    instrument.start(simulate=simulate, instrument_type=instrument_type, initialize=True, session_name="stress-probe")
    try:
        for name in commands:
            step = max(calls // 10, 1)
            readings = [(0, dotnet_counters()["ccws"])]
            for done in range(1, calls + 1):
                instrument.call(name)
                if done % step == 0 or done == calls:
                    readings.append((done, dotnet_counters()["ccws"]))
            slope = statistics.linear_regression([r[0] for r in readings], [r[1] for r in readings]).slope
            total = readings[-1][1] - readings[0][1]
            print(f"{name:34s} {slope:7.2f} CCWs per call   ({total:+.0f} over {calls} calls)")
    finally:
        instrument.finish()
    return 0


def build_deck(instrument: Instrument) -> None:
    instrument.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id=TIP_CARRIER_ID)
    instrument.add_carrier(labware_definition=PLATE_CARRIER, left_track=8, labware_id=PLATE_CARRIER_ID)
    instrument.add_tip_rack(labware_definition=TIP_RACK, carrier_id=TIP_CARRIER_ID, site="1", tip_pool=TIP_POOL, labware_id=TIP_RACK_ID)
    instrument.tip_pool_reset_tip_counter(tip_pool=TIP_POOL)
    instrument.add_plate(labware_definition=PLATE, carrier_id=PLATE_CARRIER_ID, site="1", plate_id=SOURCE_ID)
    instrument.add_plate(labware_definition=PLATE, carrier_id=PLATE_CARRIER_ID, site="2", plate_id=DEST_ID)


def transfer_96(instrument: Instrument) -> None:
    instrument.tip_pick_up_mph96(tip_pool=TIP_POOL)
    try:
        instrument.aspirate_mph96(
            labware_id=SOURCE_ID,
            volume=VOLUME_UL,
            liquid_class=LIQUID_CLASS,
            settings={"fixed_height": 1.0, "liquid_following": False},
        )
        instrument.dispense_mph96(
            labware_id=DEST_ID,
            volume=VOLUME_UL,
            settings={"dispense_mode": 8, "fixed_height": 3.0, "liquid_following": False},  # 8 = FROM_LIQUID_CLASS
        )
    finally:
        instrument.tip_eject_mph96(eject_mode="waste")


def remove_deck(instrument: Instrument, *, ignore_errors: bool) -> None:
    for name in REMOVE_ORDER:
        try:
            instrument.remove_labware(labware_name=name)
        except OrchestratorCallError:
            if not ignore_errors:
                raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp", help="the spoke's MCP endpoint (direct mode)")
    parser.add_argument("--start-local", action="store_true", help="start a spoke on this PC (port from --url) if none is running")
    parser.add_argument("--instrument", choices=["STAR", "Vantage"], default="STAR")
    parser.add_argument("--live", action="store_true", help="drive real hardware instead of the simulator")
    parser.add_argument("--hours", type=float, default=None, help="stop after this many hours")
    parser.add_argument("--cycles", type=int, default=None, help="stop after this many cycles")
    parser.add_argument("--cycles-per-session", type=int, default=0, help="restart the session every N cycles (0: one session for the whole run)")
    parser.add_argument("--max-consecutive-failures", type=int, default=5)
    parser.add_argument("--csv", default=None, help="memory log (default: stress_96_transfer_<timestamp>.csv in the current directory)")
    parser.add_argument("--pid", type=int, default=None, help="process to watch (default: whatever listens on the URL's port)")
    parser.add_argument("--skip-idle-check", action="store_true")
    parser.add_argument("--probe", nargs="+", metavar="COMMAND", help="instead of the stress cycle, call each of these argument-less commands --calls times and report the CCWs left behind per call (e.g. tip_pool_get_tip_counters get_status_mph96)")
    parser.add_argument("--calls", type=int, default=200, help="calls per --probe command")
    parser.add_argument("--per-step", action="store_true", help="read the CCW count around every command and report which commands leak (slow: ~1 s per command; use with --cycles 10)")
    args = parser.parse_args()

    if not args.skip_idle_check:
        state = venus_run_state()
        if state not in (0, None) and not args.live:
            print(f"VENUS run-state is {state} (not idle) -- a running method would be aborted. Close it first, or pass --skip-idle-check.")
            return 2

    port = urlparse(args.url).port or 8000
    if args.start_local:
        instrument = Instrument.local(port)
    else:
        instrument = (MeteredInstrument if args.per_step else Instrument)(args.url, None, call_timeout_s=120.0)

    pid = args.pid or (listening_pid(port) if urlparse(args.url).hostname in ("127.0.0.1", "localhost") else None)
    print(f"Watching spoke pid {pid}" if pid else "No local spoke pid found -- memory will not be logged (use --pid)")

    csv_path = Path(args.csv or f"stress_96_transfer_{datetime.now():%Y%m%d_%H%M%S}.csv")
    deadline = time.monotonic() + args.hours * 3600 if args.hours else None
    instrument_type = InstrumentType.STAR if args.instrument == "STAR" else InstrumentType.VANTAGE

    if args.probe:
        return run_probe(instrument, args.probe, args.calls, simulate=not args.live, instrument_type=instrument_type)

    cycle = 0
    failures = 0
    total_failures = 0
    samples: list[tuple[int, float, float]] = []
    session_open = False
    started = time.monotonic()

    def open_session() -> None:
        nonlocal session_open
        info = instrument.start(simulate=not args.live, instrument_type=instrument_type, initialize=True, session_name="stress-96-transfer")
        session_open = True
        print(f"  session {info.get('session_id')} (connection {info.get('connection_id')})")

    def close_session() -> None:
        nonlocal session_open
        if session_open:
            try:
                instrument.finish()
            except OrchestratorCallError as exc:
                print(f"  close_session failed: {exc}")
            session_open = False

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cycle", "elapsed_s", "cycle_s", "working_set_mb", "private_mb", "failures", *(f"venus_{key}_private_mb" for key in VENUS_PROCESSES), *DOTNET_COUNTERS])
        try:
            while True:
                if args.cycles is not None and cycle >= args.cycles:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                cycle += 1
                cycle_started = time.monotonic()
                try:
                    if not session_open or (args.cycles_per_session and cycle > 1 and (cycle - 1) % args.cycles_per_session == 0):
                        close_session()
                        open_session()
                    build_deck(instrument)
                    transfer_96(instrument)
                    remove_deck(instrument, ignore_errors=False)
                    failures = 0
                except OrchestratorCallError as exc:
                    failures += 1
                    total_failures += 1
                    print(f"cycle {cycle} FAILED: {exc}")
                    try:
                        remove_deck(instrument, ignore_errors=True)
                    except Exception:
                        close_session()
                    if failures >= args.max_consecutive_failures:
                        print(f"{failures} failures in a row -- stopping.")
                        break

                memory = process_memory_mb(pid) if pid else None
                venus = venus_memory_mb()
                dotnet = dotnet_counters()
                cycle_s = time.monotonic() - cycle_started
                elapsed = time.monotonic() - started
                if memory:
                    samples.append((cycle, *memory))
                writer.writerow([cycle, f"{elapsed:.0f}", f"{cycle_s:.1f}", f"{memory[0]:.1f}" if memory else "", f"{memory[1]:.1f}" if memory else "", total_failures, *(f"{venus[key]:.1f}" if key in venus else "" for key in VENUS_PROCESSES), *(f"{dotnet[key]:.1f}" if key in dotnet else "" for key in DOTNET_COUNTERS)])
                handle.flush()
                print(
                    f"cycle {cycle:5d}  {cycle_s:5.1f}s  elapsed {elapsed / 3600:5.2f}h  "
                    + (f"working set {memory[0]:8.1f} MB  private {memory[1]:8.1f} MB" if memory else "memory n/a")
                    + "".join(f"  {key} {venus[key]:7.1f} MB" for key in VENUS_PROCESSES if key in venus)
                    + (f"  CCWs {dotnet['ccws']:9.0f}  .NET heap {dotnet['dotnet_heap_mb']:6.1f} MB" if "ccws" in dotnet and "dotnet_heap_mb" in dotnet else "")
                )
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            close_session()

    if isinstance(instrument, MeteredInstrument):
        print_ccw_deltas(instrument, cycle)

    print(f"\n{cycle} cycles, {total_failures} failed, {(time.monotonic() - started) / 3600:.2f} h. Log: {csv_path}")
    if len(samples) >= 10:
        # Slope of private bytes over cycles, ignoring the first 10% as warm-up.
        tail = samples[len(samples) // 10 :]
        xs = [s[0] for s in tail]
        ys = [s[2] for s in tail]
        slope = statistics.linear_regression(xs, ys).slope
        print(f"Private bytes: start {samples[0][2]:.1f} MB, end {samples[-1][2]:.1f} MB, trend {slope * 1000:+.2f} MB per 1000 cycles after warm-up")
        print("A trend that stays near zero means no leak; a steady positive slope does.")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
