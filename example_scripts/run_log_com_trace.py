"""Enable the run log *and* embed VENUS's firmware COM trace into it.

``RunLogConfig(enabled=True, include_com_trace=True)`` tells the SDK to, on
top of the normal structured run log, snapshot VENUS's per-day firmware
communication trace (``.trc``) when the client opens and, when it closes,
embed the lines appended in between as ``com_trace`` entries in the
finalized ``*_SdkRunLog.json``. That is the raw ``< sent`` / ``> received``
firmware exchange.

Both are on by default for StarClient and VantageClient; this script sets
them explicitly to show the settings. To turn them off without touching code:

    setx HAMILTON_VENUS_RUN_LOG_ENABLED 0
    setx HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE 0

or in a config TOML::

    [venus.run_log]
    enabled = true
    include_com_trace = true
    # com_trace_logfiles_dir = ""          # "" = ask VENUS via system/paths, then the registry's LogFiles dir
    # com_trace_max_bytes = 5242880        # 0 = unlimited (keeps the newest lines)

This script runs against the simulator, does a little pipetting to generate
firmware traffic, then reopens the finished run log and prints what got
embedded. See ``docs/examples/advanced/run_log.md`` for the full reference.
"""

from __future__ import annotations

import json
from pathlib import Path

from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.config import RunLogConfig

OUTPUT_DIR = Path(__file__).parent / "run_logs"

TIP_CARRIER = LABWARE.CARRIER.TIP_CAR_480BC
TIP_RACK = LABWARE.TIP_RACK.TIP_RACK_300UL
PLATE_CARRIER = LABWARE.CARRIER.PLT_CAR_L5MD
PLATE = LABWARE.PLATE.COS_96_DW_1ML
WATER = LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
existing = {p.name for p in OUTPUT_DIR.glob("*_SdkRunLog.json")}

run_log = RunLogConfig(
    enabled=True,
    output_dir=str(OUTPUT_DIR),
    include_com_trace=True,   # <-- embeds the .trc (also the default)
    # com_trace_logfiles_dir="",     # override where VENUS writes its .trc
    # com_trace_max_bytes=5_242_880, # cap the embedded trace (0 = unlimited)
)

with StarClient(simulate=True, run_log=run_log) as star:
    star.add_carrier(labware_definition=TIP_CARRIER, left_track=1, labware_id="TipCarrier")
    star.add_tip_rack(labware_definition=TIP_RACK, carrier_id="TipCarrier", site="1", tip_pool="300uLTips")
    star.add_carrier(labware_definition=PLATE_CARRIER, left_track=10, labware_id="PlateCarrier")
    star.add_plate(labware_definition=PLATE, carrier_id="PlateCarrier", site="1", plate_id="Plate1")

    star.instrument_init()

    # A tiny transfer -- enough to make the instrument chatter over the wire.
    star.tip_pickup(channels=[1, 2], tip_pool="300uLTips")
    star.aspirate(channels=[1, 2], positions="Plate1@col:1", volumes=50.0, liquid_class=WATER)
    star.dispense(channels=[1, 2], positions="Plate1@col:2", volumes=50.0)
    star.tip_eject(channels=[1, 2])

# --- Inspect what landed in the finalized run log -------------------------

new_logs = [p for p in OUTPUT_DIR.glob("*_SdkRunLog.json") if p.name not in existing]
if not new_logs:
    raise SystemExit("No new *_SdkRunLog.json was written.")

log_path = max(new_logs, key=lambda p: p.stat().st_mtime)
data = json.loads(log_path.read_text(encoding="utf-8"))
entries = data["log"]

print(f"Run log: {log_path}")

snapshot = next((e for e in entries if e["type"] == "com_trace_snapshot"), None)
if snapshot:
    p = snapshot["payload"]
    print(f"COM trace file: {p['path']} (started at byte {p['start_offset']})")

com_chunks = [e for e in entries if e["type"] == "com_trace"]
trace_lines = [line for e in com_chunks for line in e["payload"]["lines"]]
truncated = any(e["payload"].get("truncated") for e in com_chunks)

print(f"Embedded {len(trace_lines)} firmware trace line(s) in {len(com_chunks)} chunk(s)"
      f"{' (truncated to newest com_trace_max_bytes)' if truncated else ''}:")
for line in trace_lines[:15]:
    print(f"  {line}")
if len(trace_lines) > 15:
    print(f"  ... {len(trace_lines) - 15} more (see the run log file)")
