"""Inheco ODTC: import methods from a vendor XML file, then run them.

Uses Hamilton's sample file ``PLR001_ODTCProtocols.xml`` (3 PreMethods and 2 PCR
Methods). Runs against a real unit -- edit ``DEVICE_IP``. The block gets hot
(the PCR method's first step is 95 C), so run it with **no plate in the block**.

Steps: import the whole file (the unit stores every method in it), confirm they
appear in the unit's method list, run a PreMethod *from the file* to completion
(a stepped Method only starts after a PreMethod has finished), start the PCR
method ``PLR001_IndexPCR`` and watch the block heat, stop it, then run the
``PLR001_Cool8C`` PreMethod to bring the block back down and wait for it to finish
(about 8 minutes) so the block isn't left hot.

The door is closed before the first method starts and opened again when the script finishes; the
unit is stopped (a no-op if idle) before it is terminated, even if a step failed.

Never disconnect while a method is still running: the unit reports a finished run
to this PC, and if nobody is listening any more it logs an event error and drops
into ``inError`` (the next connect clears it with a Reset).

Each run prints the unit's own estimate; waits are capped (``MAX_WAIT_SECONDS``).
Connecting always Resets the unit, which aborts anything already running on it.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from hamilton_venus import ODTCClient, ODTCError

logging.basicConfig(level=logging.WARNING, format="%(message)s")

DEVICE_IP = "192.168.1.50"
PROTOCOL_FILE = Path(r"C:\Program Files (x86)\Hamilton\Library\Inheco ODTC\PLR001_ODTCProtocols.xml")

PRE_METHOD = "PLR001_Init"  # block 25 C, lid 110 C
PCR_METHOD = "PLR001_IndexPCR"  # 9 steps, first step 95 C for 120 s
COOL_METHOD = "PLR001_Cool8C"  # block 8 C, lid 110 C

POLL_SECONDS = 15
MAX_WAIT_SECONDS = 600  # cap on waiting for a PreMethod to finish
PCR_WATCH_SECONDS = 150  # how long to watch the PCR method before stopping it
PCR_TARGET_C = 90.0  # stop early once the block gets this hot


def estimate_text(response) -> str:
    seconds = response.return_parameters.estimated_duration_seconds
    if seconds is None:
        return "unknown"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def report(odtc, device_id: int, label: str) -> tuple[str, float, float]:
    state = odtc.odtc_get_status(device_id=device_id).return_parameters.device_ids[0].state
    t = odtc.odtc_get_temperature(device_id=device_id).return_parameters.device_ids[0]
    print(f"    {label:<8} state={state:<6} block={t.block_temperature:5.1f} C  lid={t.lid_temperature:5.1f} C")
    return state, t.block_temperature, t.lid_temperature


def wait_until_idle(odtc, device_id: int, what: str) -> bool:
    """Poll (printing temperatures) until the unit is idle again; stop the run and
    return False if it is still going after MAX_WAIT_SECONDS."""
    waited = 0
    while waited < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        state, _, _ = report(odtc, device_id, f"t+{waited}s")
        if state.lower() == "idle":
            return True
    print(f"    {what} still running after {MAX_WAIT_SECONDS}s -- stopping it and giving up")
    odtc.odtc_stop_method(device_id)
    return False


def main() -> int:
    if not PROTOCOL_FILE.is_file():
        print(f"protocol file not found: {PROTOCOL_FILE}")
        return 1
    with ODTCClient() as odtc:
        device_id = odtc.odtc_connect(DEVICE_IP).return_parameters.unit.device_id
        print(f"connected (device {device_id})")
        try:
            print("closing the door (it stays closed while the methods run)")
            odtc.odtc_close_door(device_id=device_id)

            print(f"\nimporting {PROTOCOL_FILE.name}")
            imported = odtc.odtc_import_methods(PROTOCOL_FILE, device_id=device_id).return_parameters.methods
            for m in imported:
                detail = (
                    f"block {m.target_block_temperature:g} C, lid {m.target_lid_temperature:g} C"
                    if m.kind == "PreMethod"
                    else f"{m.step_count} steps"
                )
                print(f"    imported  {m.kind:<10} {m.name:<20} {detail}")

            on_unit = {m.name: m for m in odtc.odtc_list_methods(device_id).return_parameters.methods}
            missing = [m.name for m in imported if m.name not in on_unit]
            print(f"    on the unit now: {'all ' + str(len(imported)) if not missing else 'MISSING ' + str(missing)}")
            if missing:
                return 1

            print(f"\nPreMethod from the file: {PRE_METHOD}")
            run = odtc.odtc_run_protocol(PROTOCOL_FILE, method_name=PRE_METHOD, device_id=device_id)
            print(f"    started; unit estimates {estimate_text(run)}")
            if not wait_until_idle(odtc, device_id, PRE_METHOD):
                return 1
            print("    finished")

            print(f"\nPCR method from the file: {PCR_METHOD}")
            run = odtc.odtc_run_protocol(PROTOCOL_FILE, method_name=PCR_METHOD, device_id=device_id)
            print(f"    started; unit estimates {estimate_text(run)}; watching {PCR_WATCH_SECONDS}s, then stopping")
            waited = 0
            while waited < PCR_WATCH_SECONDS:
                time.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                _, block, _ = report(odtc, device_id, f"t+{waited}s")
                if block >= PCR_TARGET_C:
                    print(f"    block reached {PCR_TARGET_C:g} C -- the PCR program is running")
                    break
            odtc.odtc_stop_method(device_id)
            print("    stopped")

            print(f"\ncool back down: {COOL_METHOD}")
            run = odtc.odtc_run_protocol(PROTOCOL_FILE, method_name=COOL_METHOD, device_id=device_id)
            print(f"    started; unit estimates {estimate_text(run)}")
            if not wait_until_idle(odtc, device_id, COOL_METHOD):
                return 1
            print("    finished; the block is cool")
        except ODTCError as exc:
            print(f"\nFAILED: {exc}")
            return 1
        finally:
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
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
