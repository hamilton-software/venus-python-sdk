"""Inheco ODTC hardware test: exercises every ODTC command against a real unit.

Runs against a real ODTC (``ODTCClient(simulate=False)``, the default), talking
directly to its SiLA SOAP interface (see ``hamilton_venus.odtc``). Edit
``DEVICE_IP`` for your unit. Prints a pass/fail line per command and a summary
at the end; the exit code is 1 if anything failed.

What it does, in order: connect, identification/status/temperature, list the
methods stored on the unit, door open/close, the device settings (CSV
separator, log level, clock), upload + run a custom "cool to 4 C, lid 100 C"
protocol, run a short stepped method after a PreMethod (trying pause/resume),
then run a stored pre-method (``PRE25``) by name and abort it. Any running
method is stopped before the unit is terminated -- even if a step raised.

The door is closed before anything heats and opened again when the run finishes; the unit is
stopped (a no-op if it is idle) before it is disconnected.

Each run prints the unit's own estimate of how long it will take, and waits are
sized from it (never more than ``MAX_WAIT_SECONDS``). The clock and log-level
changes each take about a minute: the unit only accepts them in ``standby``.

Left out on purpose: network configuration (it can take a unit off the network)
and ``GetConfiguration`` -- neither exists in the SDK any more.

NOTE: connecting always issues a device ``Reset`` (that is how the unit learns
where to send its async events), which aborts anything already running on it.
"""

from __future__ import annotations

import datetime
import logging
import time

from hamilton_venus import ODTCClient, ODTCError
from hamilton_venus.models import CommandResponse
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder

logging.basicConfig(level=logging.WARNING, format="%(message)s")

DEVICE_IP = "192.168.1.50"

COOL_TARGET_C = 4.0
LID_TARGET_C = 100.0
STORED_PRE_METHOD = "PRE25"  # ships on every unit: block 25 C, lid 110 C
POLL_SECONDS = 4
POLL_COUNT = 4
MAX_WAIT_SECONDS = 300  # never sit waiting on a run the unit says will take longer than this

results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    """Run *fn*, record pass/fail, print one line, return its result (or None)."""
    try:
        value = fn()
    except ODTCError as exc:
        results.append((name, False, str(exc).replace("\n", " ")))
        print(f"  FAIL  {name}: {exc}".replace("\n", " "))
        return None
    detail = "" if value is None or isinstance(value, (bool, CommandResponse)) else str(value)
    results.append((name, True, detail))
    print(f"  ok    {name}" + (f": {detail}" if detail else ""))
    return value


def estimate_of(response) -> str:
    """The unit's own estimate of a run's duration, as returned by the run commands."""
    seconds = response.return_parameters.estimated_duration_seconds
    if seconds is None:
        return "estimated duration unknown"
    minutes, secs = divmod(int(seconds), 60)
    return f"unit estimates {minutes}m{secs:02d}s"


def poll_temperatures(odtc, device_id: int) -> None:
    for _ in range(POLL_COUNT):
        time.sleep(POLL_SECONDS)
        t = odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]
        print(f"        block={t.block_temperature:.1f} C  lid={t.lid_temperature:.1f} C")


def main() -> int:
    with ODTCClient() as odtc:
        print(f"connecting to {DEVICE_IP} ...")
        connected = check("odtc_connect", lambda: odtc.odtc_connect(DEVICE_IP))
        if connected is None:
            return 1
        unit = connected.return_parameters.unit
        device_id = unit.device_id
        print(f"  firmware: {unit.firmware_version}   state: {unit.state}")

        try:
            # The door stays closed while anything runs; it is opened again at the very end.
            print("\nclosing the door before anything heats")
            check("odtc_close_door (before anything heats)", lambda: odtc.odtc_close_door(device_id=device_id))

            print("\nread-only queries")
            check("odtc_get_device_ids", lambda: odtc.odtc_get_device_ids().return_parameters.device_ids)
            check(
                "odtc_get_device_identification",
                lambda: odtc.odtc_get_device_identification(device_id).return_parameters.firmware_version,
            )
            check(
                "odtc_get_status",
                lambda: (
                    lambda s: f"state={s.state} locked={s.locked}"
                )(odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0]),
            )
            check(
                "odtc_get_temperature",
                lambda: (
                    lambda t: f"block={t.block_temperature:.1f} C lid={t.lid_temperature:.1f} C"
                )(odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]),
            )
            check(
                "odtc_get_parameters",
                lambda: f"{len(odtc.odtc_get_parameters(device_id).return_parameters.xml)} chars of XML",
            )

            print("\nmethods stored on the unit")
            methods = check(
                "odtc_list_methods", lambda: odtc.odtc_list_methods(device_id).return_parameters.methods
            )
            for m in methods or []:
                if m.kind == "PreMethod":
                    what = f"block {m.target_block_temperature:g} C, lid {m.target_lid_temperature:g} C"
                else:
                    what = f"{m.step_count} steps"
                print(f"        {m.kind:<10} {m.name:<44} {what}   [{m.creator}]")

            print("\ndoor")
            check("odtc_open_door", lambda: odtc.odtc_open_door(device_id=device_id))
            check("odtc_close_door", lambda: odtc.odtc_close_door(device_id=device_id))

            print("\ndevice settings")
            check("odtc_set_csv_separator", lambda: odtc.odtc_set_csv_separator(";", device_id=device_id))
            # The help file says the log level should only be changed when Hamilton
            # or Inheco asks -- INFO is the unit's default, so this is a no-op change.
            check("odtc_set_log_level", lambda: odtc.odtc_set_log_level("INFO", device_id=device_id))
            check(
                "odtc_set_date_time",
                lambda: odtc.odtc_set_date_time(datetime.datetime.now(datetime.timezone.utc), device_id=device_id),
            )
            check("odtc_add_allowed_return_code", lambda: odtc.odtc_add_allowed_return_code(4711, device_id=device_id))

            print(f"\nuploaded protocol: cool block to {COOL_TARGET_C:g} C, lid {LID_TARGET_C:g} C")
            hold = ODTCProtocolBuilder(
                "Cool4C",
                description="Hold block at 4 C, lid at 100 C",
                start_block_temperature=COOL_TARGET_C,
                start_lid_temperature=LID_TARGET_C,
            ).build()
            # A plain hold (no steps -> PreMethod) has no natural end, so don't wait for it.
            run = check("odtc_run_protocol (upload + run)", lambda: odtc.odtc_run_protocol(hold, device_id=device_id))
            if run:
                print(f"        {estimate_of(run)}; watching for a few polls, then stopping it")
                poll_temperatures(odtc, device_id)
                check("odtc_stop_method", lambda: odtc.odtc_stop_method(device_id))

            # Pause only takes effect at a step boundary, so it is tested on a short
            # stepped method (a plain hold never reaches one). Lid stays at 100 C so
            # the run doesn't wait for the lid to change temperature.
            print("\nstepped method: pause / resume")
            stepped = ODTCProtocolBuilder("PauseTest", start_lid_temperature=LID_TARGET_C)
            for block in (25, 26, 25, 26, 25, 26):
                stepped.add_hold(block, 10, lid_temperature=LID_TARGET_C)
            # The unit only starts a stepped Method after a PreMethod has finished
            # bringing the block and lid to its start temperatures (ExecuteMethod
            # otherwise says "PreMethod or enabled PostHeating is required").
            pre = ODTCProtocolBuilder(
                "PauseTestPre", start_block_temperature=25, start_lid_temperature=LID_TARGET_C
            ).build()
            pre_run = check(
                "odtc_run_protocol (pre-method)", lambda: odtc.odtc_run_protocol(pre, device_id=device_id)
            )
            pre_ok = False
            if pre_run:
                print(f"        {estimate_of(pre_run)}")
                estimate = pre_run.return_parameters.estimated_duration_seconds or 0
                if estimate > MAX_WAIT_SECONDS:
                    print(f"        longer than the {MAX_WAIT_SECONDS}s limit -- not waiting; stopping it")
                    check("odtc_stop_method", lambda: odtc.odtc_stop_method(device_id))
                else:
                    pre_ok = bool(
                        check(
                            "odtc_wait_for_protocol (pre-method)",
                            lambda: odtc.odtc_wait_for_protocol(device_id, timeout=int(estimate * 1.5) + 60),
                        )
                    )
            stepped_run = (
                check(
                    "odtc_run_protocol (stepped)",
                    lambda: odtc.odtc_run_protocol(stepped.build(), device_id=device_id),
                )
                if pre_ok
                else None
            )
            if stepped_run:
                print(f"        {estimate_of(stepped_run)}")
                time.sleep(POLL_SECONDS)
                if check("odtc_pause", lambda: odtc.odtc_pause(device_id)):
                    check(
                        "state is paused",
                        lambda: odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0].state,
                    )
                    check("odtc_resume", lambda: odtc.odtc_resume(device_id))
                    check("odtc_stop_method", lambda: odtc.odtc_stop_method(device_id))
                else:
                    # A pause request that is never honoured (seen on this unit) leaves it
                    # refusing resume/stop/temperature reads -- state busy, sub-state
                    # "pauseRequested". Reset (+ Initialize) is the only way out.
                    print("        pause was not honoured; recovering with a reset")
                    check("odtc_reset", lambda: odtc.odtc_reset(device_id))

            print("\nrun data (from the last run)")
            check(
                "odtc_get_run_data",
                lambda: f"{len(odtc.odtc_get_run_data(device_id=device_id).return_parameters.rows)} row(s)",
            )

            print(f"\nstored pre-method: {STORED_PRE_METHOD}")
            stored_run = check(
                "odtc_run_stored_method",
                lambda: odtc.odtc_run_stored_method(STORED_PRE_METHOD, device_id=device_id),
            )
            if stored_run:
                print(f"        {estimate_of(stored_run)}")
                poll_temperatures(odtc, device_id)
                # abort is the last thing tested: it may leave the unit needing a Reset
                # (the next odtc_connect does that anyway).
                check("odtc_abort", lambda: odtc.odtc_abort(device_id))
        finally:
            print("\nfinishing")
            # Stopping an idle unit is harmless, so this is unconditional: whatever is still
            # running (or was left running by a failed step) is stopped before disconnecting.
            check("odtc_stop_method (end of run)", lambda: odtc.odtc_stop_method(device_id))
            check("odtc_open_door (finished)", lambda: odtc.odtc_open_door(device_id=device_id))
            check("odtc_terminate_device", lambda: odtc.odtc_terminate_device(device_id=device_id))

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for name, detail in failed:
        print(f"  FAILED: {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
