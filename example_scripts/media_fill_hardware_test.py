"""Hamilton Media Fill Module -- field functionality test (VENUS Python SDK, Media Fill driver 1.5.0+).

For anyone checking that a Media Fill Module is fully functional: every function of the driver and
every status the module can report is exercised, every fitted pump is filled to its sensor, pumped
out and stopped, and the run ends with a PASS / FAIL / INCOMPLETE report per unit.

Modeled on Hamilton's own checkout steps for the module:
  * Service Manual 96784-01/A s6.1: verify tubing routing with "a 30 second FillTrough, one for
    each pump" and observe each trough fill. s3.1.2: check each liquid level sensor (dry and wet).
    s3.1.3: first use at 30 % or lower, raised in 1-10 % steps. s5.1: "continues pumping even after
    sensor has been triggered" = pump and sensor cables not paired (P1 with S1, ...).
  * Installation and User Guide 95149-01/B s4.2.1: no pumping operation over 720 s.
  * Verified on a real module (2026-10-15, 1.1 library): WastePumpNoSensor runs the REVERSE of the set direction
    and ignores the sensor -- with the fill direction left set it pulls liquid from the trough back
    toward the bottle. The module's own read-only queries (firmware, sensors, pump status,
    directions) answer without the vendor object; pump status says whether each pump is running.

Stages (the run stops at the first failure; the module is always disconnected at the end, on errors
and on Ctrl+C too -- Disconnect stops every pump):

  1. identity      vendor driver reachable; the unit's port by USB id (2341/0043 or 16D0/0613), its USB
                   serial; the firmware query says "Media Fill Module"                (nothing moves)
  2. firmware      the module's own read-only queries before the driver connects: firmware, sensors,
                   pump status (every pump must read stopped), directions               (nothing moves)
  3. driver        connect, device list, every pump's direction + sensor, get_status -- which must
                   agree with stage 2 -- last error message                             (nothing moves)
  4. direction     each tested pump: set clockwise -> read back -> counter-clockwise -> read back
  5. sensor check  optional: you move liquid by hand, the script watches each sensor   (nothing pumps)
  6. fill          each tested pump: FillTrough to its sensor (dry -> wet); all four sensors watched,
                   a different sensor tripping = cables swapped -> stopped at once; then a second fill
                   on the full trough must be a no-op ("SENSOR ON")
  7. pump out      each tested pump: WastePumpNoSensor (1.1) / EmptyLineToSource (2.0, at most 20 s) on
                   the fill direction (runs in reverse); its sensor must go wet -> dry; a sensor going
                   dry -> wet = filling instead -> stopped
  8. stop          each tested pump: with the 2.0 library, start a fill and StopPump after a few s (your
                   observation); then start a fill, disconnect after a few s; the firmware must then
                   report every pump stopped (plus your observation), and the driver reconnects
  9. final         after cleanup, the firmware reports every pump stopped

Sensors are proven both ways by stages 6 and 7 (dry -> wet, wet -> dry); stage 5 is for a sensor
that needs adjusting. Every driver call and firmware query is recorded; --full (the field test)
fails if one was missed.

Run with no options for a guided run (operator, unit serial, fitted pumps; works from the Hamilton
Script Manager, whose pop-ups answer the questions), or with options from the SDK folder:

  python example_scripts\\media_fill_hardware_test.py                                     guided
  python example_scripts\\media_fill_hardware_test.py --simulate --full                   dry run
  python example_scripts\\media_fill_hardware_test.py --real COM5                         stages 1-4 only
  python example_scripts\\media_fill_hardware_test.py --real COM5 --full --pumps 1 2 3 4 --operator "A. Tech" --unit-serial 12345
  python example_scripts\\media_fill_hardware_test.py --real --fill --pump-out 60 --pumps 1

--full defaults to 60 % and a 180 s fill timeout (a long source tube needs about 60 % and well
over 60 s to prime; 30 % is nearly inaudible); --speed / --timeout override.

Each run writes a .log, a .json and a readable report (mfm_report_*.txt) to Documents\\MFM Hardware
Test\\logs (--log-dir to change; a fixed folder, because the Script Manager runs a read-only copy of
this script). Exit code 0 = PASS, 1 = FAIL, 2 = INCOMPLETE (a requested check was skipped).

Part of the Media Fill Module driver; see docs\\media-fill-hardware-notes.md.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import cast

from hamilton_venus import MediaFillClient, MediaFillError, VenusError
from hamilton_venus import media_fill as mf
from hamilton_venus.devices.media_fill_commands import MediaFillDeviceCommands
from hamilton_venus.models import PumpDirection

TEST_VERSION = "2.0"
ALL_PUMPS = (1, 2, 3, 4)
MAX_PUMP_SECONDS = 720  # Installation and User Guide 95149-01/B s4.2.1
POLL_S = 0.5
DEFAULT_LOG_DIR = Path.home() / "Documents" / "MFM Hardware Test" / "logs"
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = DEFAULT_LOG_DIR / f"mfm_test_{STAMP}.log"  # set from --log-dir in main()
RESULTS_PATH = DEFAULT_LOG_DIR / f"mfm_test_{STAMP}.json"
REPORT_PATH = DEFAULT_LOG_DIR / f"mfm_report_{STAMP}.txt"

log = logging.getLogger("mfm_test")

#: Every public function of the installed driver -- the coverage report checks against these.
DRIVER_FUNCTIONS = sorted(n for n, _ in inspect.getmembers(MediaFillDeviceCommands, inspect.isfunction)
                          if n.startswith("media_fill_"))
#: The module's own read-only queries (firmware command ids) -- every status it can report.
FIRMWARE_QUERIES = {mf.QUERY_FIRMWARE: "firmware", mf.QUERY_SENSORS: "sensors",
                    mf.QUERY_PUMP_STATUS: "pump status", mf.QUERY_DIRECTIONS: "directions"}


class StageFailed(Exception):
    """A check failed; the run stops here."""


class CallLog:
    """Wraps the client and records which ``media_fill_*`` functions the run called."""

    def __init__(self, client: MediaFillClient) -> None:
        self._client = client
        self.used: set[str] = set()

    def __getattr__(self, name: str):
        attr = getattr(self._client, name)
        if not (name.startswith("media_fill_") and callable(attr)):
            return attr

        def call(*args, **kwargs):
            self.used.add(name)
            return attr(*args, **kwargs)

        return call


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.results: dict = {
            "test": f"Media Fill Module field functionality test {TEST_VERSION}",
            "driver_version": getattr(mf, "DRIVER_VERSION", "unknown"),
            "started": datetime.now().isoformat(timespec="seconds"),
            "mode": "simulation" if args.simulate else "real",
            "operator": args.operator or "",
            "unit_serial": args.unit_serial or "",
            "settings": dict(vars(args)),
            "unit": {},
            "stages": {},
        }
        self.checks: list[tuple[str, str, bool | None, str]] = []
        self.skipped: list[str] = []
        self.queries_used: set[int] = set()
        self.port = ""
        #: "2.0" / "1.1" (vendor library) or "simulated", from media_fill_connect.
        self.vendor_api = ""

    def expected_functions(self) -> list[str]:
        """The driver functions a --full run must use: all of them, except StopPump on the 1.1 library (it has none)."""
        return [n for n in DRIVER_FUNCTIONS if not (n == "media_fill_stop_pump" and self.vendor_api == "1.1")]

    def pump_out_limit(self) -> int:
        """Longest pump out the vendor library allows: 20 s on 2.0 (MaxTimeoutForBackflow), else 720 s."""
        return mf.PUMP_OUT_MAX_SECONDS_V2 if self.vendor_api == "2.0" else MAX_PUMP_SECONDS

    # -- helpers -------------------------------------------------------------

    def record(self, stage: str, key: str, value: object) -> None:
        self.results["stages"].setdefault(stage, {})[key] = value

    def skip(self, stage: str, key: str, value: object, what: str) -> None:
        """A requested check didn't run; the run ends INCOMPLETE rather than PASS."""
        self.record(stage, key, value)
        self.skipped.append(what)
        self.checks.append((stage, what, None, "skipped"))
        log.warning("  [SKIP] %s", what)

    @staticmethod
    def ask(prompt: str) -> str:
        # PowerShell pipes stdin with a UTF-8 BOM, which would make "FILL" never match.
        # No input at all (stdin closed) counts as an empty answer, i.e. "skip" / "no".
        try:
            return input(prompt).strip().lstrip("﻿")
        except EOFError:
            print()
            return ""

    def check(self, stage: str, name: str, ok: bool, detail: str = "") -> None:
        self.record(stage, name, {"ok": ok, "detail": detail})
        self.checks.append((stage, name, ok, detail))
        (log.info if ok else log.error)("  [%s] %s%s", "PASS" if ok else "FAIL", name, f" -- {detail}" if detail else "")
        if not ok:
            raise StageFailed(f"{stage}: {name} failed ({detail})")

    def confirm(self, prompt: str, expected: str) -> bool:
        if self.args.simulate:
            log.info("  (simulation: auto-confirming '%s')", expected)
            return True
        answer = self.ask(f"{prompt}\nType {expected} to continue, anything else to skip:")
        log.info("  operator answered %r", answer)
        return answer.upper() == expected

    def ask_yes_no(self, prompt: str) -> bool:
        if self.args.simulate:
            log.info("  (simulation: auto-answering yes to '%s')", prompt)
            return True
        answer = self.ask(f"{prompt} (y/n):").lower()
        log.info("  operator answered %r", answer)
        return answer.startswith("y")

    @staticmethod
    def sensor(mfm: MediaFillClient, pump: int) -> int:
        return mfm.media_fill_get_liquid_level_sensor_state(pump).return_parameters.liquid_level_sensor_state

    def sensors(self, mfm: MediaFillClient) -> dict[int, int]:
        return {p: self.sensor(mfm, p) for p in ALL_PUMPS}

    @staticmethod
    def direction(mfm: MediaFillClient, pump: int) -> int:
        return mfm.media_fill_get_pump_direction(pump).return_parameters.direction

    @staticmethod
    def last_error(mfm: MediaFillClient) -> str:
        return mfm.media_fill_get_last_error_message().return_parameters.error_message

    @property
    def raw(self) -> bool:
        """Whether the module's own queries can be used (real hardware, pywin32 present)."""
        return not self.args.simulate and mf.raw_serial_available()

    def firmware_status(self, stage: str) -> dict | None:
        """The module's four read-only queries (the driver must not hold the port). None in simulation."""
        if not self.raw:
            log.info("  (%s: firmware queries need real hardware -- not part of a simulated run)",
                     "simulation" if self.args.simulate else "no pywin32")
            self.record(stage, "firmware_status", "not available")
            return None
        st = mf.raw_status(self.port)
        self.queries_used.update(FIRMWARE_QUERIES)
        self.record(stage, "firmware_status", st)
        return st

    # -- stage 1 ---------------------------------------------------------------

    def identity(self) -> str:
        log.info("\n=== Stage 1: identity -- is this a Media Fill Module? (nothing moves) ===")
        if self.args.simulate:
            self.check("identity", "simulation mode", True, "no hardware or vendor driver used")
            self.port = self.args.port or "COM5"
            return self.port
        diagnosis = mf.media_fill_com_diagnosis()
        self.record("identity", "diagnosis", diagnosis)
        self.check("identity", "vendor driver reachable", mf.media_fill_available(), diagnosis)
        found = mf.find_media_fill_ports()
        self.record("identity", "usb_ports_found", found)
        described = dict(found)
        if self.args.port:
            port = self.args.port.upper()
            self.check("identity", "port has the module's USB id", port in described,
                       f"{port}: {described[port]}" if port in described else
                       f"{port} has no Media Fill USB device (USB id {' / '.join(mf.USB_IDS)}); not opened. "
                       f"Media Fill Modules on USB: {', '.join(described) or 'none'}")
        else:
            ports = list(described)
            if len(ports) > 1:
                log.info("  %d ports with the module's USB id (%s); asking each for its firmware (nothing moves)...",
                         len(ports), ", ".join(ports))
                modules = mf.identify_media_fill_modules()
                self.record("identity", "confirmed_modules", modules)
                ports = [p for p, _, _ in modules]
            self.check("identity", "module found on USB", len(ports) == 1,
                       f"{ports[0]}: {described.get(ports[0], '')}" if len(ports) == 1 else
                       f"found {len(ports)} Media Fill Modules on {', '.join(ports)} -- name the one to test "
                       f"(e.g. {ports[0]}); hamilton-media-fill --find lists each with its USB serial" if ports else
                       "found none; check the USB cable, the 24 V power, and Device Manager > Ports (or pass COMx)")
            port = ports[0]
        self.port = port
        usb_serial = described.get(port, "").rsplit("serial ", 1)[-1] if "serial " in described.get(port, "") else ""
        self.results["unit"].update(com_port=port, usb_serial=usb_serial)
        if self.raw:
            firmware = mf.raw_identify(port, usb_checked=True)
            self.queries_used.add(mf.QUERY_FIRMWARE)
            self.results["unit"]["firmware"] = firmware
            self.check("identity", "firmware identifies a Media Fill Module", True, f"{port} answered {firmware!r}")
        return port

    # -- stage 2 ---------------------------------------------------------------

    def firmware_before(self) -> None:
        log.info("\n=== Stage 2: the module's own status queries, before the driver connects (nothing moves) ===")
        st = self.firmware_status("firmware")
        if st is None:
            return
        self.firmware_at_start = st
        log.info("  firmware %r; sensors %s; pump status %s (field 0 = %s); directions %s", st["firmware"],
                 fmt_sensors(st["sensors"]), st["pump_status"], st["pump_status_field0"], st["directions"])
        self.check("firmware", "every pump reports stopped", all(v == 0 for v in st["pump_status"].values()),
                   f"pump status {st['pump_status']}")
        for pump in self.args.pumps:
            if st["sensors"][pump] == 1:
                log.warning("  pump %d's sensor reads 1 with nothing pumped: liquid in that trough, sensor S%d "
                            "unplugged, or controller power off.", pump, pump)

    # -- stage 3 ---------------------------------------------------------------

    def driver_read_only(self, mfm: MediaFillClient, port: str) -> None:
        log.info("\n=== Stage 3: driver read-only checks (nothing moves) ===")
        rp = mfm.media_fill_connect(port).return_parameters
        self.record("driver", "connect", rp.model_dump())
        self.check("driver", "connect", True, f"device {rp.device_id} on COM{rp.com_port}, instrument {rp.instrument_id}")
        self.vendor_api = rp.vendor_api
        self.results["unit"].setdefault("vendor_library", rp.vendor_api)
        log.info("  vendor library: %s", rp.vendor_api)
        if not self.args.simulate:
            self.check("driver", "real driver (not the simulator)", not rp.simulated,
                       "the SDK fell back to simulation" if rp.simulated else "")
        self.check("driver", "firmware version", bool(rp.firmware_version), rp.firmware_version or "empty")
        self.results["unit"].setdefault("firmware", rp.firmware_version)
        ids = mfm.media_fill_get_device_ids().return_parameters.device_ids
        listed = [(d.device_id, d.com_port, d.firmware_version) for d in ids]
        self.record("driver", "device_ids", listed)
        self.check("driver", "device list shows this module", listed == [(rp.device_id, rp.com_port, rp.firmware_version)],
                   f"{listed}")
        reads = {}
        for pump in ALL_PUMPS:
            d, s = self.direction(mfm, pump), self.sensor(mfm, pump)
            reads[pump] = (d, s)
            self.record("driver", f"pump{pump}", {"direction": d, "sensor": s})
            log.info("  pump %d: direction=%d (%s), sensor=%d%s", pump, d, "ccw" if d == 0 else "cw", s,
                     "  <- liquid, or sensor unplugged" if s == 1 else "")
        st = mfm.media_fill_get_status(rp.device_id).return_parameters
        self.record("driver", "status", st.model_dump())
        from_status = {p.pump_id: (p.direction, p.liquid_level_sensor_state) for p in st.pumps}
        self.check("driver", "get_status agrees with the individual reads",
                   from_status == reads and st.firmware_version == rp.firmware_version and st.com_port == rp.com_port,
                   f"COM{st.com_port}, {st.firmware_version}, pumps {from_status}, last error {st.last_error_message!r}")
        before = getattr(self, "firmware_at_start", None)
        if before is not None:
            # Initialize resets every direction to counter-clockwise; the sensors must read the same.
            self.check("driver", "driver and firmware report the same sensors and firmware",
                       {p: s for p, (_, s) in reads.items()} == before["sensors"]
                       and st.firmware_version == before["firmware"],
                       f"driver {fmt_sensors({p: s for p, (_, s) in reads.items()})}, firmware {fmt_sensors(before['sensors'])}")
        status = self.last_error(mfm)
        log.info("  module status message: %s", "none" if status == "No error." else repr(status))

    # -- stage 4 ---------------------------------------------------------------

    def directions(self, mfm: MediaFillClient) -> None:
        log.info("\n=== Stage 4: pump direction round-trip (nothing moves) ===")
        for pump in self.args.pumps:
            mfm.media_fill_set_pump_direction(pump, PumpDirection.CLOCKWISE)
            cw = self.direction(mfm, pump)
            mfm.media_fill_set_pump_direction(pump, PumpDirection.COUNTER_CLOCKWISE)
            ccw = self.direction(mfm, pump)
            self.check("direction", f"pump {pump} set/read back", (cw, ccw) == (1, 0), f"cw->{cw}, ccw->{ccw}")

    # -- stage 5 ---------------------------------------------------------------

    def sensor_check(self, mfm: MediaFillClient) -> None:
        seconds = self.args.sensor_check
        log.info("\n=== Stage 5: sensor check, %d s (nothing pumps; Service Manual s3.1.2) ===", seconds)
        if self.args.simulate:
            self.record("sensor_check", "skipped", "simulation has no physical sensor to move liquid past")
            log.info("  (simulation: skipped -- needs real sensors)")
            return
        pumps = ", ".join(f"S{p}" for p in self.args.pumps)
        if not self.confirm(f"Sensor check for {pumps}: for {seconds} s, lower and raise the liquid at each "
                            f"sensor (or pour some out and back in) and watch its orange LED.", "GO"):
            self.skip("sensor_check", "skipped", "not confirmed", "sensor check (not confirmed)")
            return
        seen: dict[int, set[int]] = {p: set() for p in ALL_PUMPS}
        last = self.sensors(mfm)
        for p, v in last.items():
            seen[p].add(v)
        log.info("  start: %s", fmt_sensors(last))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(POLL_S / 2)
            now = self.sensors(mfm)
            for p in ALL_PUMPS:
                seen[p].add(now[p])
                if now[p] != last[p]:
                    log.info("  %5.1f s  S%d: %d -> %d (%s)", seconds - (end - time.monotonic()), p, last[p], now[p],
                             "liquid detected, LED off" if now[p] else "no liquid, LED on")
            last = now
        for p in self.args.pumps:
            self.record("sensor_check", f"S{p}_values_seen", sorted(seen[p]))
            self.check("sensor_check", f"sensor S{p} saw both dry and wet", seen[p] == {0, 1},
                       f"values seen {sorted(seen[p])}" + ("" if seen[p] == {0, 1} else
                       "; recalibrate the detection height (Service Manual s3.1.2) or check the S cable"))
        moved_others = [p for p in ALL_PUMPS if p not in self.args.pumps and len(seen[p]) > 1]
        if moved_others:
            log.warning("  sensors you weren't testing also changed: %s -- check which trough each sensor is on",
                        ", ".join(f"S{p}" for p in moved_others))

    def trough_dry(self, mfm: MediaFillClient, stage: str, pump: int, why: str) -> bool:
        """The trough's sensor must read dry before a fill can start. If it doesn't, offer to pump the trough
        out (reverse, until the sensor reads dry) or let the operator empty it by hand."""
        if self.args.simulate or self.sensor(mfm, pump) == 0:
            return True
        log.warning("  pump %d: sensor S%d reads 1 (liquid in the trough, or the sensor is unplugged).", pump, pump)
        answer = "" if self.args.simulate else self.ask(
            f"Pump {pump}: S{pump} reads liquid, so a fill wouldn't start. Type OUT to pump the trough out now "
            f"(reverse, stops a few s after S{pump} reads dry, at most {self.pump_out_limit()} s), or empty it by hand "
            f"(and check the S{pump} cable is plugged in) and type READY; anything else skips:").upper()
        log.info("  operator answered %r", answer)
        if answer == "OUT":
            mfm.media_fill_set_pump_direction(pump, PumpDirection.COUNTER_CLOCKWISE)  # reverse of this = out
            t0 = time.monotonic()
            limit = self.pump_out_limit()
            mfm.media_fill_waste_pump_no_sensor(pump, self.args.speed, limit)
            log.info("  pumping pump %d's trough out (Ctrl+C stops it)...", pump)
            dry_at = None
            while time.monotonic() - t0 < limit:
                if self.sensor(mfm, pump) == 0 and dry_at is None:
                    dry_at = time.monotonic() - t0
                    log.info("  %5.1f s  S%d reads dry; a few more seconds to clear the trough", dry_at, pump)
                if dry_at is not None and time.monotonic() - t0 > dry_at + 5:
                    break
                time.sleep(POLL_S)
            mfm.media_fill_disconnect()  # ends the sensor-less run
            mfm.media_fill_connect(self.port)
            self.record(stage, f"pump{pump}_emptied_by_pump_out_s", round(dry_at, 1) if dry_at else None)
            if dry_at is not None and self.sensor(mfm, pump) == 0:
                log.info("  pump %d's trough emptied by pumping out (%.1f s to dry)", pump, dry_at)
                return True
        elif answer == "READY" and self.sensor(mfm, pump) == 0:
            return True
        self.skip(stage, f"pump{pump}", {"skipped": f"S{pump} still reads liquid"},
                  f"{why} pump {pump} (sensor S{pump} still reads liquid)")
        return False

    # -- stage 6 ---------------------------------------------------------------

    def fill(self, mfm: MediaFillClient) -> None:
        log.info("\n=== Stage 6: fill / routing check (speed %d %%, timeout %d s; Service Manual s6.1) ===",
                 self.args.speed, self.args.timeout)
        for pump in self.args.pumps:
            if not self.trough_dry(mfm, "fill", pump, "fill"):
                continue
            before = self.sensors(mfm)
            if not self.confirm(f"Pump {pump}: source bottle has liquid, tubing from P{pump} goes to the trough on "
                                f"sensor S{pump}, pump clamp closed, overflow tubing drains, someone watching?",
                                "FILL"):
                self.skip("fill", f"pump{pump}", {"skipped": "not confirmed"}, f"fill pump {pump} (not confirmed)")
                continue
            mfm.media_fill_set_pump_direction(pump, PumpDirection.COUNTER_CLOCKWISE)
            t0 = time.monotonic()
            mfm.media_fill_fill_trough(pump, self.args.speed, self.args.timeout)
            log.info("  pump %d started; watching all sensors (Ctrl+C stops it)...", pump)
            outcome, tripped_at, now = "timeout", None, before
            while time.monotonic() - t0 < self.args.timeout + 2:
                now = self.sensors(mfm)
                if now[pump] == 1:
                    outcome, tripped_at = "sensor", time.monotonic() - t0
                    break
                wrong = [p for p in ALL_PUMPS if p != pump and before[p] == 0 and now[p] == 1]
                if wrong:
                    mfm.media_fill_disconnect()  # stops every pump on the module, now
                    self.record("fill", f"pump{pump}", {"sensors_before": before, "sensors_during": now})
                    self.check("fill", f"pump {pump} paired with sensor S{pump}", False,
                               f"pumping P{pump} tripped {', '.join(f'S{p}' for p in wrong)} instead -- the pump stays on "
                               f"until its own sensor trips, so it was stopped. Swap the cables/tubing so P{pump} "
                               f"feeds the trough on S{pump} (Service Manual s5.1)")
                time.sleep(POLL_S)
            mfm.media_fill_wait_for_pump(pump)  # returns at once if the pump already stopped
            elapsed = time.monotonic() - t0
            after = self.sensors(mfm)
            self.record("fill", f"pump{pump}", {
                "outcome": outcome, "seconds_to_sensor": round(tripped_at, 1) if tripped_at else None,
                "total_s": round(elapsed, 1), "sensors_before": before, "sensors_after": after,
                "last_error": self.last_error(mfm)})
            self.check("fill", f"pump {pump} filled and stopped on sensor S{pump} (S{pump} dry -> wet)",
                       outcome == "sensor",
                       f"sensor tripped after {tripped_at:.1f} s" if tripped_at else
                       f"no sensor trip within {self.args.timeout} s -- check the clamp, tubing kinks and direction "
                       f"in the pump head, a long tube still priming (raise --speed / --timeout), and that "
                       f"P{pump}/S{pump} are paired")
            others = [p for p in ALL_PUMPS if p != pump and after[p] != before[p]]
            self.check("fill", f"pump {pump}: other sensors unchanged", not others,
                       ", ".join(f"S{p} {before[p]}->{after[p]}" for p in others))
            if not self.args.simulate:
                level_ok = self.ask_yes_no(f"Pump {pump}: trough filled to the sensor height, no overflow?")
                splashing = self.ask_yes_no(f"Pump {pump}: any splashing or foaming at {self.args.speed} %? "
                                            f"(if no, the manual suggests trying 1-10 % faster next run)")
                self.record("fill", f"pump{pump}_operator",
                            {"filled_to_sensor_no_overflow": level_ok, "splashing": splashing})
                self.check("fill", f"pump {pump}: trough level correct, no overflow", level_ok, "operator observation")
            # FillTrough on a trough whose sensor already reads liquid returns at once without pumping. With a
            # long source tube the level can sink back below the sensor after a fill (liquid running back down
            # the tube) -- then top it up first, so the check tests a trough that really is full.
            if self.sensor(mfm, pump) == 0:
                log.warning("  S%d went dry again after the fill (the level sank below the sensor -- liquid running "
                            "back down the source tube?); topping up before the full-trough check", pump)
                t0 = time.monotonic()
                mfm.media_fill_fill_trough(pump, self.args.speed, self.args.timeout)
                mfm.media_fill_wait_for_pump(pump)
                topped = time.monotonic() - t0
                self.record("fill", f"pump{pump}_top_up_s", round(topped, 1))
                self.check("fill", f"pump {pump}: topped up to the sensor again", self.sensor(mfm, pump) == 1,
                           f"{topped:.1f} s (note: the level sank after the first fill)")
            t0 = time.monotonic()
            mfm.media_fill_fill_trough(pump, self.args.speed, self.args.timeout)
            mfm.media_fill_wait_for_pump(pump)
            again, msg = time.monotonic() - t0, self.last_error(mfm)
            self.check("fill", f"pump {pump} refill on a full trough is a no-op",
                       again < 2.0 and "SENSOR ON" in msg, f"{again:.1f} s, module says {msg!r}")

    # -- stage 7 ---------------------------------------------------------------

    def pump_out(self, mfm: MediaFillClient) -> None:
        seconds = self.args.pump_out
        if seconds > self.pump_out_limit():
            log.info("  --pump-out %d s is longer than the %s library allows; using %d s",
                     seconds, self.vendor_api, self.pump_out_limit())
            seconds = self.pump_out_limit()
        log.info("\n=== Stage 7: pump out -- WastePumpNoSensor / EmptyLineToSource, reverse of the fill direction "
                 "(speed %d %%, %d s) ===",
                 self.args.speed, seconds)
        for pump in self.args.pumps:
            # The fill direction stays set: WastePumpNoSensor turns the other way (verified 2026-10-15).
            mfm.media_fill_set_pump_direction(pump, PumpDirection.COUNTER_CLOCKWISE)
            before = self.sensors(mfm)
            if not self.confirm(f"Pump {pump} will run in REVERSE for {seconds} s at {self.args.speed} %, ignoring the "
                                f"sensor: liquid should go from the trough back toward the bottle. Same setup as the "
                                f"fill, someone watching?", "OUT"):
                self.skip("pump_out", f"pump{pump}", {"skipped": "not confirmed"}, f"pump out pump {pump} (not confirmed)")
                continue
            t0 = time.monotonic()
            mfm.media_fill_waste_pump_no_sensor(pump, self.args.speed, seconds)
            log.info("  pump %d running in reverse; watching all sensors (Ctrl+C stops it)...", pump)
            went_dry_at = None
            while time.monotonic() - t0 < seconds + 2:
                now = self.sensors(mfm)
                if before[pump] == 1 and now[pump] == 0 and went_dry_at is None:
                    went_dry_at = time.monotonic() - t0
                    log.info("  %5.1f s  S%d went dry -- liquid is being pulled out", went_dry_at, pump)
                tripped = [p for p in ALL_PUMPS if before[p] == 0 and now[p] == 1]
                if tripped:
                    mfm.media_fill_disconnect()  # stops every pump on the module, now
                    self.record("pump_out", f"pump{pump}", {"sensors_before": before, "sensors_during": now})
                    self.check("pump_out", f"pump {pump} pumps out, not in", False,
                               f"{', '.join(f'S{p}' for p in tripped)} went dry -> wet during a pump out, so liquid went "
                               f"INTO a trough; the module was stopped. Check the tubing direction in the pump head "
                               f"(a fill must work first) and the P/S cable pairing")
                time.sleep(POLL_S)
            mfm.media_fill_wait_for_pump(pump)  # returns at once if the run already ended
            after_dir = self.direction(mfm, pump)
            self.record("pump_out", f"pump{pump}", {
                "sensors_before": before, "sensors_after": self.sensors(mfm),
                "seconds_to_dry": round(went_dry_at, 1) if went_dry_at else None,
                "direction_after": after_dir, "last_error": self.last_error(mfm)})
            self.check("pump_out", f"pump {pump}: stored direction unchanged", after_dir == 0,
                       f"direction reads {after_dir} (0 = counter-clockwise expected)")
            if self.args.simulate:
                log.info("  (simulation: liquid movement not modelled)")
            elif before[pump] == 1:
                self.check("pump_out", f"pump {pump} pulled liquid out of the trough (S{pump} wet -> dry)",
                           went_dry_at is not None,
                           f"after {went_dry_at:.1f} s" if went_dry_at is not None else
                           f"S{pump} stayed wet for {seconds} s -- liquid may be going IN (check the overflow "
                           f"drain and the tubing direction), the trough end of the tube may sit above the "
                           f"liquid, or raise --pump-out")
                if went_dry_at is not None and went_dry_at < 2.0:
                    # A level sitting right at the sensor can sink below it on its own (liquid running back
                    # down the source tube), so a dry reading this early doesn't prove the pump pulled it out.
                    moved = self.ask_yes_no(f"Pump {pump}: S{pump} read dry after only {went_dry_at:.1f} s -- did you "
                                            f"see liquid being pulled out of the trough / back toward the bottle?")
                    self.check("pump_out", f"pump {pump} pumped back toward the bottle", moved, "operator observation")
            else:
                moved = self.ask_yes_no(f"Pump {pump}: S{pump} was already dry -- did liquid move back toward the bottle?")
                self.check("pump_out", f"pump {pump} pumped back toward the bottle", moved, "operator observation")

    # -- stage 8 ---------------------------------------------------------------

    def stop_test(self, mfm: MediaFillClient, port: str) -> None:
        how = "Disconnect" if self.vendor_api == "1.1" else "StopPump, then Disconnect"
        log.info("\n=== Stage 8: stop mid-fill via %s (%s) ===", how, ", ".join(f"pump {p}" for p in self.args.pumps))
        for pump in self.args.pumps:
            if not self.trough_dry(mfm, "stop", pump, "stop test"):
                continue
            if not self.confirm(f"Pump {pump} will run for about {self.args.stop_after} s and then be stopped "
                                f"({how}). Same setup as the fill, someone watching?", "STOP"):
                self.skip("stop", f"pump{pump}", "not confirmed", f"stop test pump {pump} (not confirmed)")
                continue
            timeout = max(self.args.timeout, self.args.stop_after + 10)
            if self.vendor_api != "1.1":  # StopPump (2.0): stops one pump and keeps the module connected
                mfm.media_fill_fill_trough(pump, self.args.speed, timeout)
                time.sleep(self.args.stop_after)
                mfm.media_fill_stop_pump(pump)
                stopped = self.ask_yes_no(f"Did pump {pump} stop right at StopPump "
                                          f"(not about {timeout - self.args.stop_after} s later at its timeout)?")
                self.check("stop", f"pump {pump}: StopPump stops a running pump", stopped, "operator observation")
                if not self.trough_dry(mfm, "stop", pump, "stop test"):
                    continue
            mfm.media_fill_fill_trough(pump, self.args.speed, timeout)
            time.sleep(self.args.stop_after)
            t0 = time.monotonic()
            mfm.media_fill_disconnect()
            self.record("stop", f"pump{pump}_disconnect_s", round(time.monotonic() - t0, 2))
            st = self.firmware_status("stop")  # the port is free again: ask the module itself
            if st is not None:
                self.check("stop", f"pump {pump}: firmware reports every pump stopped after the disconnect",
                           all(v == 0 for v in st["pump_status"].values()), f"pump status {st['pump_status']}")
            stopped = self.ask_yes_no(f"Did pump {pump} stop right at the disconnect "
                                      f"(not about {timeout - self.args.stop_after} s later at its timeout)?")
            self.check("stop", f"pump {pump}: disconnect stops a running pump", stopped, "operator observation")
            rp = mfm.media_fill_connect(port).return_parameters
            self.check("stop", f"pump {pump}: reconnect after stop", True, f"device {rp.device_id} on COM{rp.com_port}")

    # -- stage 9 ---------------------------------------------------------------

    def final_check(self) -> None:
        log.info("\n=== Stage 9: final firmware status, after disconnecting (nothing moves) ===")
        st = self.firmware_status("final")
        if st is None:
            return
        self.check("final", "firmware reports every pump stopped", all(v == 0 for v in st["pump_status"].values()),
                   f"pump status {st['pump_status']}; sensors {fmt_sensors(st['sensors'])}")

    # -- driver ----------------------------------------------------------------

    def execute(self) -> int:
        failed: str | None = None
        calls: CallLog | None = None
        terminated = False
        try:
            port = self.identity()
            self.firmware_before()
            with MediaFillClient(simulate=self.args.simulate) as client:
                calls = CallLog(client)
                mfm = cast(MediaFillClient, calls)  # CallLog forwards every attribute to the client
                try:
                    self.driver_read_only(mfm, port)
                    self.directions(mfm)
                    if self.args.sensor_check:
                        self.sensor_check(mfm)
                    if self.args.fill:
                        self.fill(mfm)
                    if self.args.pump_out:
                        self.pump_out(mfm)
                    if self.args.stop_test:
                        self.stop_test(mfm, port)
                    if not (self.args.sensor_check or self.args.fill or self.args.pump_out or self.args.stop_test):
                        log.info("\n(Optional stages skipped: --sensor-check N, --fill, --pump-out N, --stop-test; "
                                 "--full runs the field test)")
                finally:
                    log.info("\n=== Cleanup: disconnecting (stops all pumps) ===")
                    try:
                        log.info("  %s", mfm.media_fill_terminate().return_parameters.message)
                        terminated = True
                    except Exception as exc:  # noqa: BLE001 - the context manager retries on exit
                        log.error("  terminate failed: %s", exc)
            if terminated:
                self.final_check()
        except StageFailed as exc:
            failed = str(exc)
        except KeyboardInterrupt:
            failed = "interrupted with Ctrl+C (module disconnected)"
            log.error("\n%s", failed)
        except (MediaFillError, VenusError) as exc:
            code = getattr(exc, "error_code", None)
            failed = f"{type(exc).__name__}: {exc}" + (f" (error_code={code})" if code is not None else "")
            log.error("\n%s", failed)
        if calls is not None:
            used = sorted(calls.used)
            missing = [n for n in self.expected_functions() if n not in calls.used]
            queries_missing = [f"{c} {n}" for c, n in FIRMWARE_QUERIES.items() if c not in self.queries_used]
            self.results["driver_functions"] = {"used": used, "not_used": missing}
            self.results["firmware_queries"] = {"used": sorted(self.queries_used), "not_used": queries_missing}
            log.info("\n=== Coverage: %d/%d driver functions, %d/%d firmware status queries ===", len(used),
                     len(self.expected_functions()), len(self.queries_used), len(FIRMWARE_QUERIES))
            for name in self.expected_functions():
                log.info("  %s %s", "[x]" if name in calls.used else "[ ]", name)
            for c, name in FIRMWARE_QUERIES.items():
                log.info("  %s firmware query :%d; (%s)", "[x]" if c in self.queries_used else "[ ]", c, name)
            if self.args.full and not failed and not self.skipped:  # skipped -> INCOMPLETE already
                if missing:
                    failed = f"--full did not use {', '.join(missing)}"
                elif queries_missing and self.raw:
                    failed = f"--full did not read firmware status {', '.join(queries_missing)}"
        self.results["finished"] = datetime.now().isoformat(timespec="seconds")
        if failed:
            self.results["result"] = "FAIL: " + failed
        elif self.skipped:
            self.results["result"] = "INCOMPLETE: skipped " + "; ".join(self.skipped)
        else:
            self.results["result"] = "PASS"
        RESULTS_PATH.write_text(json.dumps(self.results, indent=2, default=str), encoding="utf-8")
        REPORT_PATH.write_text(self.report(), encoding="utf-8")
        log.info("\nRESULT: %s\nreport: %s\nlog: %s\nresults: %s", self.results["result"], REPORT_PATH, LOG_PATH,
                 RESULTS_PATH)
        return 1 if failed else 2 if self.skipped else 0

    def report(self) -> str:
        """A readable one-page record of the run, for the unit's file."""
        r, unit, a = self.results, self.results["unit"], self.args
        field = a.full and a.fill and a.pump_out and a.stop_test
        lines = [
            "Hamilton Media Fill Module - " + ("field functionality test" if field else "hardware test") + " report",
            "=" * 72,
            f"Result:          {r['result']}",
            f"Date:            {r['started'].replace('T', ' ')}  (finished {r['finished'][11:]})",
            f"Operator:        {r['operator'] or '(not given)'}",
            f"Unit serial:     {r['unit_serial'] or '(not given)'}   (label on the module)",
            f"USB serial:      {unit.get('usb_serial') or '-'}",
            f"Firmware:        {unit.get('firmware') or '-'}",
            f"COM port:        {unit.get('com_port') or self.port or '-'}",
            f"Mode:            {r['mode']}",
            f"Pumps tested:    {', '.join(str(p) for p in a.pumps)}",
            f"Settings:        speed {a.speed} %, fill timeout {a.timeout} s, pump out {a.pump_out} s, "
            f"stop after {a.stop_after} s",
            f"Software:        {r['test']}, Media Fill driver {r['driver_version']}",
            "",
            "Checks",
            "-" * 72,
        ]
        for stage, name, ok, detail in self.checks:
            mark = "SKIP" if ok is None else "PASS" if ok else "FAIL"
            lines.append(f"[{mark}] {stage:<12} {name}" + (f"  ({detail})" if detail and ok is not None else ""))
        timings = []
        for pump in a.pumps:
            f = r["stages"].get("fill", {}).get(f"pump{pump}", {})
            o = r["stages"].get("pump_out", {}).get(f"pump{pump}", {})
            if isinstance(f, dict) and f.get("seconds_to_sensor"):
                timings.append(f"pump {pump}: filled to the sensor in {f['seconds_to_sensor']} s")
            if isinstance(o, dict) and o.get("seconds_to_dry"):
                timings.append(f"pump {pump}: pumped out below the sensor in {o['seconds_to_dry']} s")
        if timings:
            lines += ["", "Timings", "-" * 72, *timings]
        cov = r.get("driver_functions")
        if cov:
            q = r.get("firmware_queries", {})
            lines += ["", "Coverage", "-" * 72,
                      f"driver functions used: {len(cov['used'])}/{len(self.expected_functions())}"
                      + (f" (not used: {', '.join(cov['not_used'])})" if cov["not_used"] else ""),
                      f"firmware status queries read: {len(q.get('used', []))}/{len(FIRMWARE_QUERIES)}"
                      + (f" (not read: {', '.join(q['not_used'])})" if q.get("not_used") else "")]
        lines += ["", f"Log: {LOG_PATH}", f"Data: {RESULTS_PATH}", ""]
        return "\n".join(lines)


def fmt_sensors(states: dict[int, int]) -> str:
    return "  ".join(f"S{p}={v}" for p, v in states.items())


def ask_settings() -> list[str]:
    """No command-line options: a guided run (in the Script Manager these appear as pop-ups)."""

    ask = Run.ask  # BOM-stripped; a closed stdin reads as "" (= the default / no)

    def yes(prompt: str) -> bool:
        return ask(f"{prompt} (y/n):").lower().startswith("y")

    argv: list[str] = []
    real = yes("Test a REAL Media Fill Module? (n = simulation, no hardware)")
    argv.append("--real" if real else "--simulate")
    if real:
        operator = ask("Your name (for the report; Enter to skip):")
        if operator:
            argv += ["--operator", operator]
        unit = ask("Serial number on the module's label (for the report; Enter to skip):")
        if unit:
            argv += ["--unit-serial", unit]
    pumps = ask("Pumps fitted / to test, e.g. 1 or 1 2 3 4 (Enter = 1):").replace(",", " ").split() or ["1"]
    argv += ["--pumps", *pumps]
    if yes("Run the FULL field test? (recommended: fill, pump out and stop on every pump, all statuses; "
           "you confirm before anything pumps)"):
        argv.append("--full")
        argv += ["--speed", ask("Pump speed % 30-100 (Enter = 60; the manual's first-use value is 30):") or "60"]
        argv += ["--timeout", ask("Fill timeout seconds (Enter = 180, enough for a long source tube):") or "180"]
        argv += ["--pump-out", ask("Pump-out seconds (Enter = 60):") or "60"]
        if yes("Also run the hand sensor check first? (you move liquid by hand; not needed for a PASS)"):
            argv += ["--sensor-check", ask("Seconds to watch the sensors (Enter = 60):") or "60"]
        return argv
    if yes("Run the sensor check? (you move liquid by hand; nothing pumps)"):
        argv += ["--sensor-check", ask("Seconds to watch the sensors (Enter = 60):") or "60"]
    if yes("Run the fill test? (pumps liquid; you confirm each pump first)"):
        argv.append("--fill")
        argv += ["--speed", ask("Pump speed % 30-100 (Enter = 30, the manual's first-use value; "
                                "60 for a long source tube):") or "30"]
        argv += ["--timeout", ask("Fill timeout seconds (Enter = 30, Hamilton's routing check; "
                                  "180 for a long source tube):") or "30"]
        if yes("Run the pump-out test? (reverse, ignores the sensor; pulls the trough back toward the bottle)"):
            argv += ["--pump-out", ask("Pump-out seconds (Enter = 60):") or "60"]
        if yes("Run the stop test? (starts a fill and stops it by disconnecting)"):
            argv.append("--stop-test")
    return argv


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true", help="dry run with the SDK's simulated module")
    mode.add_argument("--real", action="store_true", help="drive the real module")
    p.add_argument("com_port", nargs="?", metavar="COMn", help="COM port (same as --port)")
    p.add_argument("--port", help="COM port (e.g. COM5); found automatically from the USB ID if omitted")
    p.add_argument("--operator", help="who ran the test (for the report)")
    p.add_argument("--unit-serial", help="the serial number on the module's label (for the report)")
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR,
                   help=f"folder for the .log, .json and report files (default {DEFAULT_LOG_DIR})")
    p.add_argument("--pumps", type=int, nargs="+", default=[1], choices=ALL_PUMPS, metavar="N",
                   help="pumps to test -- the fitted ones (1-4; default 1)")
    p.add_argument("--sensor-check", type=int, default=0, metavar="SECONDS",
                   help="stage 5: watch the sensors this long while you move liquid by hand")
    p.add_argument("--fill", action="store_true", help="stage 6: fill each pump's trough (asks before each pump)")
    p.add_argument("--pump-out", type=int, default=0, metavar="SECONDS",
                   help="stage 7: pump out (reverse, no sensor) this long after the fill (max 720)")
    p.add_argument("--stop-test", action="store_true", help="stage 8: stop a running fill by disconnecting")
    p.add_argument("--full", action="store_true",
                   help="the field test: --fill, --pump-out (default 60 s) and --stop-test on every pump, at 60 %% / "
                        "180 s unless --speed / --timeout say otherwise; fails unless every driver function and "
                        "firmware status query was used")
    p.add_argument("--speed", type=int, default=None, help="relative pump speed 30-100 %% (default 30; --full 60)")
    p.add_argument("--timeout", type=int, default=None, help="fill timeout, seconds (default 30; --full 180; max 720)")
    p.add_argument("--stop-after", type=int, default=3, help="seconds to pump before the stop test disconnects")
    a = p.parse_args(argv)
    if a.com_port and a.port and a.com_port.upper() != a.port.upper():
        p.error(f"two different COM ports given: {a.com_port} and --port {a.port}")
    a.port = a.port or a.com_port
    if a.full:
        a.fill, a.stop_test = True, True
        a.pump_out = a.pump_out or 60
    a.speed = a.speed if a.speed is not None else (60 if a.full else 30)
    a.timeout = a.timeout if a.timeout is not None else (180 if a.full else 30)
    if not 30 <= a.speed <= 100:
        p.error("--speed must be 30-100")
    if not 1 <= a.timeout <= MAX_PUMP_SECONDS or not 0 <= a.pump_out <= MAX_PUMP_SECONDS:
        p.error(f"--timeout and --pump-out must be within {MAX_PUMP_SECONDS} s (the module's maximum pumping time)")
    if a.stop_after < 1 or a.sensor_check < 0:
        p.error("--stop-after must be >= 1 and --sensor-check >= 0")
    a.pumps = sorted(set(a.pumps))
    return a


def main(argv: list[str] | None = None) -> int:
    global LOG_PATH, RESULTS_PATH, REPORT_PATH  # noqa: PLW0603 - one run per process
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ask_settings()
    args = parse_args(argv)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    LOG_PATH = args.log_dir / f"mfm_test_{STAMP}.log"
    RESULTS_PATH = args.log_dir / f"mfm_test_{STAMP}.json"
    REPORT_PATH = args.log_dir / f"mfm_report_{STAMP}.txt"
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")])
    logging.getLogger("hamilton_venus").setLevel(logging.WARNING)
    log.info("Media Fill Module %s %s -- %s mode, %s\n  options: %s",
             "field functionality test" if args.full else "hardware test", TEST_VERSION,
             "SIMULATION" if args.simulate else "REAL", datetime.now().strftime("%Y-%m-%d %H:%M"), " ".join(argv))
    return Run(args).execute()


if __name__ == "__main__":
    raise SystemExit(main())
