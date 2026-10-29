"""Inheco ODTC: build a pre-method and a short 3-cycle PCR method, run them, and
plot the temperature over time.

Both methods are built in Python (``ODTCProtocolBuilder``) and uploaded to the
unit, then run in the order the unit requires: the ``PreMethod`` first, to bring
the block and lid to the start temperatures, then the stepped PCR ``Method``::

    PreMethod   block 25 C, lid 110 C
    PCR         95 C 15 s  ->  [ 95 C 10 s, 60 C 10 s, 72 C 15 s ] with Cycles = 3  ->  72 C 15 s  ->  25 C 10 s

The PCR is built with ``add_pcr``, which writes the step layout, ramp slopes and overshoot the way
Inheco's Script Editor does for the chosen fluid volume (``FLUID_QUANTITY``, default 0 = 10-29 ul).

Cycles = 3 is Inheco's convention (its Script Editor's "Cycles" field): the block runs once and
then 3 more times, so the unit does four passes -- four 60 C anneals -- exactly as Inheco's editor
plots the same steps.

While each runs the script polls the block and lid temperature (about every two
seconds). After each run it also downloads the unit's *own* trace of that run
(``odtc_download_run_trace``: block target, block actual and lid about five times a
second, matched by method name). Everything is saved to CSV under ``odtc_runs/``
and plotted to a PNG; the PCR plot numbers the 60 C annealing plateaus, one per
pass the unit ran.

The door is closed before the first method starts and opened again when the script finishes; the
unit is stopped (a no-op if idle) before it is terminated, even if a step failed.

Run with **no plate in the block** (it goes to 95 C). Needs matplotlib
(``pip install matplotlib``). Edit ``DEVICE_IP`` for your unit. Connecting always
Resets the unit, which aborts anything already running on it.

    python odtc_pcr_temperature_trace.py                       # run, then plot
    python odtc_pcr_temperature_trace.py --plot odtc_runs/<stamp>   # re-plot saved data
"""

from __future__ import annotations

import argparse
import csv
import datetime
import sys
import time
from pathlib import Path

from hamilton_venus import ODTCClient, ODTCError
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder

DEVICE_IP = "192.168.1.50"

LID_C = 110.0
START_BLOCK_C = 25.0
CYCLES = 3
FLUID_QUANTITY = 0  # 0 = 10-29 ul, 1 = 30-74 ul, 2 = 75-100 ul: picks the editor's slopes/overshoot
OUT_DIR = Path("odtc_runs")

POLL_SECONDS = 2.0
PRINT_EVERY_SECONDS = 15.0
MAX_PRE_WAIT_SECONDS = 720  # cap on waiting for the PreMethod (the unit estimated 6-8 minutes)
MAX_PCR_WAIT_SECONDS = 900  # cap on the PCR run


def build_methods():
    pre = ODTCProtocolBuilder(
        "TracePre", description="Bring block and lid to the PCR start temperatures",
        start_block_temperature=START_BLOCK_C, start_lid_temperature=LID_C,
    ).build()

    # add_pcr lays the steps out and tunes the ramp slopes and overshoot the way Inheco's
    # Script Editor does for this fluid volume, instead of one fixed slope for every step.
    pcr = ODTCProtocolBuilder(
        "Trace3Cycle", description="Short PCR (Cycles = 3) for a temperature trace",
        start_block_temperature=START_BLOCK_C, start_lid_temperature=LID_C, fluid_quantity=FLUID_QUANTITY,
    )
    pcr.add_pcr(
        initial_denaturation=(95, 15), denaturation=(95, 10), annealing=(60, 10), extension=(72, 15),
        cycles=CYCLES, final_extension=(72, 15), cooling=(25, 10), lid_temperature=LID_C,
    )
    return pre, pcr.build()


def estimate_text(response) -> str:
    seconds = response.return_parameters.estimated_duration_seconds
    if seconds is None:
        return "unknown"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def track(odtc, device_id: int, phase: str, samples: list[dict], t0: float, cap_seconds: float) -> bool:
    """Poll temperature + state into *samples* until the unit is idle again.

    Returns False if the run was still going after *cap_seconds*. "Idle" only counts
    once the unit has been seen busy (or 20 s have passed): right after a start the
    state can still read idle for a moment.
    """
    started = time.monotonic()
    seen_busy = False
    last_print = -PRINT_EVERY_SECONDS
    while True:
        loop_start = time.monotonic()
        elapsed = loop_start - started
        if elapsed > cap_seconds:
            return False
        state = odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0].state
        seen_busy = seen_busy or state.lower() == "busy"
        try:
            t = odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]
            block, lid = t.block_temperature, t.lid_temperature
        except ODTCError:
            block = lid = float("nan")  # a read can be refused while the unit is switching steps
        now = time.monotonic() - t0
        samples.append({"time_s": round(now, 2), "phase": phase, "state": state, "block_c": block, "lid_c": lid})
        if now - last_print >= PRINT_EVERY_SECONDS:
            print(f"    {phase:<4} t={now:6.0f}s  {state:<5} block={block:6.1f} C  lid={lid:6.1f} C")
            last_print = now
        if state.lower() == "idle" and (seen_busy or elapsed > 20):
            return True
        time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - loop_start)))


def fetch_trace(odtc, device_id: int, method_name: str, path: Path) -> None:
    """Download the unit's trace for *method_name* and save its samples to *path*.

    Retries a few times: the file can take a moment to appear once a run ends.
    """
    for attempt in range(4):
        try:
            trace = odtc.odtc_download_run_trace(device_id, OUT_DIR / "traces", method_name=method_name)
            save_csv(path, [row.model_dump(by_alias=True) for row in trace.return_parameters.rows])
            print(f"    unit trace: {len(trace.return_parameters.rows)} samples -> {trace.return_parameters.path}")
            return
        except ODTCError as exc:
            if attempt == 3:
                print(f"    could not get the unit's trace for {method_name}: {exc}")
                return
            time.sleep(5)


def save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k: (float(v) if k not in ("phase", "state", "series") else v) for k, v in row.items()} for row in csv.DictReader(fh)]


def plateau_spans(trace: list[dict], temperature: float, tolerance: float = 0.5, min_seconds: float = 3.0):
    """``(start_s, end_s)`` of each stretch where the block *target* sits at *temperature*.

    Stretches shorter than *min_seconds* are ignored: the target passes through
    every temperature on its way between two others.
    """
    spans, current = [], None
    for row in trace:
        t = row["elapsedMs"] / 1000
        if abs(row["targetTemperature"] - temperature) <= tolerance:
            current = [t, t] if current is None else [current[0], t]
        elif current is not None:
            spans.append(tuple(current))
            current = None
    if current is not None:
        spans.append(tuple(current))
    return [sp for sp in spans if sp[1] - sp[0] >= min_seconds]


def plot(prefix: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    polled = load_csv(Path(f"{prefix}_polled.csv"))
    pcr_trace = load_csv(Path(f"{prefix}_device_pcr.csv"))
    if not polled:
        raise SystemExit(f"no data at {prefix}_polled.csv")

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 8), gridspec_kw={"height_ratios": [3, 2]})

    phases = {"pre": ("#bbbbbb", "PreMethod"), "pcr": ("#9ecae1", "PCR (Cycles = 3)")}
    for phase, (color, label) in phases.items():
        rows = [r for r in polled if r["phase"] == phase]
        if rows:
            top.axvspan(rows[0]["time_s"], rows[-1]["time_s"], color=color, alpha=0.35, label=label)
    top.plot([r["time_s"] for r in polled], [r["block_c"] for r in polled], color="tab:blue", lw=1.6, label="block")
    top.plot([r["time_s"] for r in polled], [r["lid_c"] for r in polled], color="tab:red", lw=1.6, label="lid")
    top.set(xlabel="time since the PreMethod started [s]", ylabel="temperature [C]", title="ODTC run: polled temperatures")
    top.grid(alpha=0.3)
    top.legend(loc="center right")

    if pcr_trace:
        t = [r["elapsedMs"] / 1000 for r in pcr_trace]
        bottom.plot(t, [r["targetTemperature"] for r in pcr_trace], "k--", lw=1.2, label="block target")
        bottom.plot(t, [r["currentTemperature"] for r in pcr_trace], color="tab:blue", lw=1.6, label="block actual")
        bottom.plot(t, [r["lidTemperature"] for r in pcr_trace], color="tab:red", lw=1.2, label="lid")
        anneals = plateau_spans(pcr_trace, 60)
        for number, (start, end) in enumerate(anneals, 1):
            bottom.axvspan(start, end, color="#fdd0a2", alpha=0.6)
            bottom.text((start + end) / 2, 64, str(number), ha="center", fontsize=11, fontweight="bold")
        bottom.set(
            xlabel="time since the PCR method started [s]",
            ylabel="temperature [C]",
            title=f"PCR method, the unit's own trace: {len(anneals)} annealing (60 C) plateaus = Cycles {CYCLES} + the first pass",
        )
        bottom.grid(alpha=0.3)
        bottom.legend(loc="center right")
    else:
        bottom.text(0.5, 0.5, "no device trace saved", ha="center", va="center", transform=bottom.transAxes)

    fig.tight_layout()
    out = Path(f"{prefix}.png")
    fig.savefig(out, dpi=130)
    return out


def run() -> Path | None:
    OUT_DIR.mkdir(exist_ok=True)
    prefix = OUT_DIR / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pre, pcr = build_methods()
    samples: list[dict] = []
    ok = False
    with ODTCClient() as odtc:
        device_id = odtc.odtc_connect(DEVICE_IP).return_parameters.unit.device_id
        print(f"connected (device {device_id}); saving to {prefix}_*")
        t0 = time.monotonic()
        try:
            print("\nclosing the door (it stays closed while the methods run)")
            odtc.odtc_close_door(device_id=device_id)

            print(f"\nPreMethod: block {START_BLOCK_C:g} C, lid {LID_C:g} C")
            run_ = odtc.odtc_run_protocol(pre, device_id=device_id)
            print(f"    started; unit estimates {estimate_text(run_)}")
            if not track(odtc, device_id, "pre", samples, t0, MAX_PRE_WAIT_SECONDS):
                print(f"    still running after {MAX_PRE_WAIT_SECONDS}s -- stopping it")
                return None
            print("    finished")
            fetch_trace(odtc, device_id, pre.method_name, Path(f"{prefix}_device_pre.csv"))

            print(f"\nPCR (Cycles = {CYCLES}, fluid setting {FLUID_QUANTITY}: Script Editor slopes and overshoot)")
            run_ = odtc.odtc_run_protocol(pcr, device_id=device_id)
            print(f"    started; unit estimates {estimate_text(run_)}")
            if not track(odtc, device_id, "pcr", samples, t0, MAX_PCR_WAIT_SECONDS):
                print(f"    still running after {MAX_PCR_WAIT_SECONDS}s -- stopping it")
                return None
            print("    finished")
            fetch_trace(odtc, device_id, pcr.method_name, Path(f"{prefix}_device_pcr.csv"))
            ok = True
        except ODTCError as exc:
            print(f"\nFAILED: {exc}")
        finally:
            save_csv(Path(f"{prefix}_polled.csv"), samples)
            # Always stop before disconnecting (a no-op on an idle unit), then open the door
            # so the plate can be removed; each step is attempted even if the one before failed.
            for label, action in (
                ("stop", lambda: odtc.odtc_stop_method(device_id)),
                ("open the door", lambda: odtc.odtc_open_door(device_id=device_id)),
            ):
                try:
                    action()
                    print(f"finished: {label}")
                except ODTCError as exc:
                    print(f"could not {label}: {exc}")
            odtc.odtc_terminate_device(device_id=device_id)
    return prefix if ok else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plot", metavar="PREFIX", help="only re-plot saved data (e.g. odtc_runs/20260923_120000)")
    args = parser.parse_args()
    prefix = Path(args.plot) if args.plot else run()
    if prefix is None:
        return 1
    print(f"\nplot saved to {plot(prefix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
