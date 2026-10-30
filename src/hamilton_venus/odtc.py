"""Pure-Python driver for the Inheco ODTC (On-Deck Thermal Cycler).

Like :mod:`hamilton_venus.heater_cooler` (see that module's docstring for the
full rationale), the ODTC does **not** go through the VENUS runtime -- it is
driven directly from Python via the vendor's COM object,
``Inheco.ODTCInterface`` (COM class ``Inheco_ODTC_Interface.ThermoCycler``).
That object is registered **32-bit only**, so on 64-bit Python the SDK bridges
through the same :mod:`hamilton_venus._com32` worker infrastructure the HHC
driver uses -- see ``installer/HANDOFF.md`` for why that infrastructure was
generalized rather than copy-pasted for this, the second 32-bit-COM driver.

Structurally the ODTC differs from the HHC in three ways this module reflects:

* **One COM object instance per physical unit.** The vendor HSL creates up to
  ``MAX_DEVICES`` (8) separate ``Inheco.ODTCInterface`` instances
  (``gInheco_ODTC_objDevice_01`` .. ``_08``), one per unit, rather than HHC's
  single object fronting a whole daisy chain. :class:`ODTCManager` mirrors
  that: :meth:`ODTCManager.connect` spawns (or reuses) one transport per
  ``device_id``, picking the lowest free slot the way the HSL's
  ``_GetFreeDeviceNumber`` does.
* **Protocol-driven, not setpoint-driven.** There is no ``SetTemperature``.
  A PCR run uploads a ``<MethodSet>`` XML document (``SetMethod``) and then
  runs one named method from it (``ExecuteMethod``) -- see
  :mod:`hamilton_venus.odtc_protocol` for building one in Python, or pass the
  path to a vendor-authored file straight through.
* **Every operation needs a lock token.** Per this driver's design, locking is
  fully internal: :class:`ODTCManager` acquires one lock per connection at
  connect time and holds it for the connection's lifetime, so no ``lock_id``
  ever appears in the public ``odtc_*`` command surface.
"""

from __future__ import annotations

import contextlib
import http.server
import itertools
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any, Protocol, cast

from hamilton_venus import _com32
from hamilton_venus.exceptions import ODTCError
from hamilton_venus.odtc_protocol import ODTCProtocol

logger = logging.getLogger(__name__)

_PROGID = "Inheco.ODTCInterface"
_FORCE_ENABLE_ENV = "HAMILTON_ODTC_FORCE_ENABLE"
_PY32_ENV = "HAMILTON_ODTC_PYTHON32"

#: Where the vendor drops the ODTC COM interop DLL and its dependencies.
_ODTC_LIB_DIR = r"C:\Program Files (x86)\Hamilton\Library\Inheco ODTC"
_ODTC_KEY_FILES = ("Inheco ODTC Interface.DLL",)

#: The SDK ships a private 32-bit CPython here (shared with every other
#: 32-bit-COM driver -- see hamilton_venus._com32).
_BUNDLED_PY32 = _com32._BUNDLED_PY32

_IS_64BIT = sys.maxsize > 2**32

#: The vendor HSL caps the number of simultaneously-registered units at 8
#: (one COM object instance per unit; see the module docstring).
MAX_DEVICES = 8

_TRUTHY = {"1", "true", "yes", "on"}

#: The device's own log levels (per the Hamilton help file for SetLogLevel).
ODTC_LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")


def parse_stored_methods(parameters_xml: str) -> list[dict[str, Any]]:
    """List the methods held on an ODTC from its ``GetParameters`` payload.

    The payload is a ``ResponseData`` document whose ``MethodsXML`` parameter
    holds every stored ``<MethodSet>`` as an escaped string. Returns one dict
    per method -- see :func:`parse_method_set`. Returns ``[]`` for a payload
    that has no ``MethodsXML``.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(parameters_xml)
    except ET.ParseError as exc:
        raise ODTCError(f"could not parse the ODTC parameters payload: {exc}") from exc
    methods_text = next(
        (
            (el.findtext("String") or "")
            for el in root.iter("Parameter")
            if el.attrib.get("name") == "MethodsXML"
        ),
        "",
    )
    return parse_method_set(methods_text) if methods_text.strip() else []


def parse_method_set(method_set_xml: str) -> list[dict[str, Any]]:
    """List the methods in a ``<MethodSet>`` document (a vendor protocol file, or
    what a unit stores): one dict per ``<PreMethod>`` (a plain block + lid hold)
    or ``<Method>`` (a stepped program), with the keys
    :class:`~hamilton_venus.models.command_types.ODTCMethodInfo` accepts."""
    import xml.etree.ElementTree as ET

    try:
        # utf-8-sig files decode fine, but a BOM left on a str is not valid XML.
        method_set = ET.fromstring(method_set_xml.lstrip("﻿"))
    except ET.ParseError as exc:
        raise ODTCError(f"could not parse the ODTC method-set XML: {exc}") from exc

    def number(el: ET.Element, tag: str) -> float | None:
        text = el.findtext(tag)
        try:
            return float(text) if text is not None else None
        except ValueError:
            return None

    out: list[dict[str, Any]] = []
    for el in method_set:
        if el.tag == "PreMethod":
            out.append(
                {
                    "name": el.attrib.get("methodName", ""),
                    "kind": "PreMethod",
                    "creator": el.attrib.get("creator", ""),
                    "targetBlockTemperature": number(el, "TargetBlockTemperature"),
                    "targetLidTemperature": number(el, "TargetLidTemp"),
                }
            )
        elif el.tag == "Method":
            out.append(
                {
                    "name": el.attrib.get("methodName", ""),
                    "kind": "Method",
                    "creator": el.attrib.get("creator", ""),
                    "stepCount": len(el.findall("Step")),
                }
            )
    return out


def _odtc_driver_installed() -> bool:
    """Whether the vendor ODTC interop DLL is on disk."""
    return os.path.isfile(os.path.join(_ODTC_LIB_DIR, "Inheco ODTC Interface.DLL"))


def _odtc_bin_report() -> str:
    if not os.path.isdir(_ODTC_LIB_DIR):
        return f"vendor library folder not found: {_ODTC_LIB_DIR}"
    missing = [f for f in _ODTC_KEY_FILES if not os.path.isfile(os.path.join(_ODTC_LIB_DIR, f))]
    if missing:
        return f"missing from {_ODTC_LIB_DIR}: {', '.join(missing)}"
    return f"all key vendor files present in {_ODTC_LIB_DIR}"


def _force_enabled() -> bool:
    return os.environ.get(_FORCE_ENABLE_ENV, "").strip().lower() in _TRUTHY


def odtc_available() -> bool:
    """Whether the vendor ODTC COM driver is usable **from this process**.

    Same shape as :func:`hamilton_venus.heater_cooler.heater_cooler_available`
    -- see that function's docstring. Never raises.
    """
    if _force_enabled():
        return True
    if sys.platform != "win32" or not _odtc_driver_installed():
        return False
    if not _IS_64BIT:
        return True
    return find_python32() is not None


def odtc_com_diagnosis() -> str:
    """A human-readable one-liner on why the vendor COM transport is / isn't usable."""
    if sys.platform != "win32":
        return "not Windows: the vendor ODTC COM transport is unavailable."
    if not _odtc_driver_installed():
        return f"Inheco ODTC driver not installed ({_odtc_bin_report()})."
    if not _IS_64BIT:
        return "Inheco.ODTCInterface is reachable in-process (32-bit Python)."
    py32 = find_python32()
    if py32:
        via = "bundled" if os.path.normcase(py32) == os.path.normcase(_BUNDLED_PY32) else py32
        return f"Inheco.ODTCInterface is 32-bit; bridging through 32-bit Python ({via})."
    return (
        "Inheco.ODTCInterface is 32-bit and this Python is 64-bit, with no 32-bit "
        "Python for the worker bridge. Run `setup-venus-sdk --install-py32`, install a "
        "32-bit Python, set HAMILTON_ODTC_PYTHON32, or use simulate=True."
    )


def find_python32() -> str | None:
    """Locate a 32-bit Python for the ODTC worker bridge (see
    :func:`hamilton_venus._com32.find_python32`)."""
    return _com32.find_python32(_PY32_ENV)


#: Folders on the unit's FTP server that hold its logs (anonymous login, no password).
#: Found by listing a real unit: SiLA/Logs has InhecoSiLA.log (the SiLA stack's own
#: log -- what explains a state change such as "InError"), Odtc/Logs and Logs hold
#: Log_#1.csv, Backup/Logs older copies. Traces holds one folder per day.
ODTC_LOG_FOLDERS = ("Logs", "Odtc", "SiLA", "Backup")
ODTC_TRACE_FOLDER = "Traces"


def _parse_ftp_listing(lines: list[str]) -> list[tuple[str, bool, int]]:
    """``(name, is_dir, size)`` from ``LIST`` output, DOS style (what the unit's
    Windows CE server sends: ``01-01-06  13:02  <DIR>  CrashDumps``) or Unix style."""
    import re

    entries: list[tuple[str, bool, int]] = []
    for line in lines:
        if m := re.match(r"^\S+\s+\S+\s+(<DIR>|\d+)\s+(.+)$", line):
            is_dir = m.group(1) == "<DIR>"
            entries.append((m.group(2).strip(), is_dir, 0 if is_dir else int(m.group(1))))
        elif m := re.match(r"^([d-])\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\w+\s+\d+\s+\S+\s+(.+)$", line):
            entries.append((m.group(3).strip(), m.group(1) == "d", int(m.group(2))))
    return entries


def _ftp_download_tree(
    host: str, roots: tuple[str, ...], dest_dir: os.PathLike[str] | str, timeout: float = 30.0
) -> list[dict[str, Any]]:
    """Copy every file under *roots* on *host*'s anonymous FTP server into
    *dest_dir* (keeping the folder layout). Roots that don't exist are skipped.

    Returns ``{"remote", "path", "size"}`` per file. Names come from the device,
    so any that could escape *dest_dir* (path separators, ``..``) are skipped.
    """
    import ftplib
    from pathlib import Path

    dest = Path(dest_dir)
    files: list[dict[str, Any]] = []

    def walk(ftp: ftplib.FTP, remote: str) -> None:
        try:
            ftp.cwd(remote)
        except ftplib.error_perm:
            return  # folder not on this unit
        lines: list[str] = []
        ftp.retrlines("LIST", lines.append)
        for name, is_dir, _size in _parse_ftp_listing(lines):
            if name in ("", ".", "..") or "/" in name or "\\" in name:
                continue
            child = f"{remote.rstrip('/')}/{name}"
            if is_dir:
                walk(ftp, child)
                continue
            local = dest / child.lstrip("/")
            local.parent.mkdir(parents=True, exist_ok=True)
            with open(local, "wb") as fh:
                ftp.retrbinary(f"RETR {child}", fh.write)
            files.append({"remote": child, "path": str(local), "size": local.stat().st_size})

    try:
        with ftplib.FTP(host, timeout=timeout) as ftp:
            ftp.login()
            for root in roots:
                walk(ftp, "/" + root)
    except (ftplib.Error, OSError) as exc:
        raise ODTCError(f"could not download logs from ftp://{host}/: {exc}") from exc
    return files


def parse_trace_csv(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse one of the unit's per-run trace files (``Traces/<date>/<start>.csv``).

    The file starts with ``*`` comment lines, the second of which names the run
    (``* ODTC Temperature trace = <method> = 2026-09-23T17:24:36Z``), then a
    ``;``-separated table sampled about 5 times a second with many sensor columns
    (temperatures in 1/100 C). Returns ``(header, rows)``: ``header`` has
    ``methodName`` and ``startedAt``; each row has ``elapsedMs`` and the
    ``targetTemperature`` / ``currentTemperature`` / ``lidTemperature`` (block
    target, block actual, lid) in degrees C. The other columns are not surfaced.
    """
    header = {"methodName": "", "startedAt": ""}
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("*"):
            parts = [p.strip() for p in line.lstrip("*").split("=")]
            if len(parts) >= 3 and "trace" in parts[0].lower():
                header["methodName"], header["startedAt"] = parts[1], "=".join(parts[2:]).strip()
            continue
        cells = line.split(";")
        if len(cells) < 4 or not cells[0].strip().lstrip("-").isdigit():
            continue  # the column-name line, the "End of trace" footer, blanks
        try:
            elapsed, target, current, lid = (float(c) for c in cells[:4])
        except ValueError:
            continue
        rows.append(
            {
                "elapsedMs": elapsed,
                "targetTemperature": target / 100.0,
                "currentTemperature": current / 100.0,
                "lidTemperature": lid / 100.0,
            }
        )
    return header, rows


def _ftp_download_latest_trace(
    host: str, dest_dir: os.PathLike[str] | str, method_name: str | None, max_candidates: int = 6, timeout: float = 30.0
) -> dict[str, Any] | None:
    """Download the newest trace file (optionally the newest one for *method_name*).

    Traces are ``Traces/<date>/<start time>.csv``; both levels sort by name, so
    walking newest-first finds the latest run without fetching them all.
    Looks at no more than *max_candidates* files. Returns ``{"remote", "path",
    "methodName", "startedAt", "rows"}`` or None if none matched.
    """
    import ftplib
    import io
    from pathlib import Path

    def names(ftp: ftplib.FTP, remote: str, want_dirs: bool) -> list[str]:
        try:
            ftp.cwd(remote)
        except ftplib.error_perm:
            return []
        lines: list[str] = []
        ftp.retrlines("LIST", lines.append)
        found = [
            n
            for n, is_dir, _ in _parse_ftp_listing(lines)
            if is_dir == want_dirs and "/" not in n and "\\" not in n
        ]
        return sorted((n for n in found if n not in (".", "..")), reverse=True)

    try:
        with ftplib.FTP(host, timeout=timeout) as ftp:
            ftp.login()
            tried = 0
            for day in names(ftp, "/Traces", True):
                for name in names(ftp, f"/Traces/{day}", False):
                    if tried >= max_candidates:
                        return None
                    tried += 1
                    remote = f"/Traces/{day}/{name}"
                    buffer = io.BytesIO()
                    ftp.retrbinary(f"RETR {remote}", buffer.write)
                    header, rows = parse_trace_csv(buffer.getvalue().decode("latin-1"))
                    if method_name is not None and header["methodName"] != method_name:
                        continue
                    local = Path(dest_dir) / day / name
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(buffer.getvalue())
                    return {"remote": remote, "path": str(local), "rows": rows, **header}
    except (ftplib.Error, OSError) as exc:
        raise ODTCError(f"could not download the run trace from ftp://{host}/: {exc}") from exc
    return None



# --------------------------------------------------------------------------- #
# Transport protocol                                                          #
# --------------------------------------------------------------------------- #


class _ODTCTransport(Protocol):
    """One transport instance drives **one physical unit** (unlike HHC's
    single transport for a whole chain -- see the module docstring)."""

    def connect(self, device_ip: str, device_port: str, local_ip: str, simulate: bool) -> None: ...
    def initialize(self) -> None: ...
    def get_device_identification(self) -> dict[str, Any]: ...
    def get_status(self) -> dict[str, Any]: ...
    def read_actual_temperature(self) -> dict[str, Any]: ...
    def open_door(self) -> None: ...
    def close_door(self) -> None: ...
    def set_method(self, xml_text: str) -> None: ...
    def execute_method(self, method_name: str, priority: int) -> str: ...
    def wait_for_end_of_execute_method(self, request_id: str, timeout: int) -> None: ...
    def stop_method(self) -> None: ...
    def pause(self) -> None: ...
    def do_continue(self) -> None: ...
    def abort(self) -> None: ...
    def reset(self, timeout: int, simulate_on_device_base: bool) -> None: ...
    def get_last_data(self) -> list[dict[str, Any]]: ...
    def get_parameters(self) -> str: ...
    def set_parameters(self, name: str, type_: str, value: str) -> None: ...
    def set_log_level(self, level: str) -> None: ...
    def set_csv_separator(self, character: str) -> None: ...
    def set_date_time(self, iso_datetime: str) -> None: ...
    def add_allowed_return_code(self, code: int) -> None: ...
    def lock(self, lock_id: str, timeout: int) -> None: ...
    def unlock(self) -> None: ...
    def terminate(self) -> None: ...
    def download_logs(self, dest_dir: str, include_traces: bool) -> list[dict[str, Any]]: ...
    def download_run_trace(self, dest_dir: str, method_name: str | None) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Simulation transport                                                        #
# --------------------------------------------------------------------------- #


class _SimODTCUnit:
    def __init__(self, index: int) -> None:
        self.serial = f"ODTC-SIM-{index:03d}"
        self.firmware_version = "3.1.0-sim"
        self.manufacturer = "Inheco (simulated)"
        self.block_temperature = 25.0
        self.lid_temperature = 25.0
        self.door_open = False
        self.locked = False
        self.state = "Idle"
        self.protocol_xml: str | None = None
        # Methods "stored on the unit", keyed by name. Seeded like a real
        # unit (which ships with PRE25/PRE55 among others); SetMethod adds to it.
        self.stored_methods: dict[str, str] = {
            name: (
                f'<PreMethod methodName="{name}" creator="HAN" dateTime="2014-02-27T10:37:38">'
                f"<TargetBlockTemperature>{block}</TargetBlockTemperature>"
                "<TargetLidTemp>110</TargetLidTemp></PreMethod>"
            )
            for name, block in (("PRE25", 25), ("PRE55", 55))
        }
        self.protocol: ODTCProtocol | None = None
        self.method_name: str | None = None
        self.running = False
        self.request_id: str | None = None
        self._step_index = 0
        self._steps_done_in_plateau = False
        self._loop_counts: dict[int, int] = {}
        self.run_log: list[dict[str, Any]] = []

    def step(self) -> None:
        """Advance the simulated run by one tick (no wall clock)."""
        if not self.running or self.protocol is None or not self.protocol.steps:
            return
        steps = self.protocol.steps
        current = steps[self._step_index]
        # Ramp block temperature toward the current step's plateau.
        gap = current.temperature - self.block_temperature
        if abs(gap) > 0.1:
            self.block_temperature += gap * 0.5
            self.lid_temperature = current.lid_temperature
            self.run_log.append(
                {"step": current.number, "target": current.temperature, "current": round(self.block_temperature, 2)}
            )
            return
        self.block_temperature = current.temperature
        self.run_log.append(
            {"step": current.number, "target": current.temperature, "current": self.block_temperature}
        )
        # Plateau reached: advance, honoring GotoNumber/LoopNumber.
        if current.loop_number and current.goto_number:
            done = self._loop_counts.get(current.number, 0) + 1
            self._loop_counts[current.number] = done
            if done <= current.loop_number:  # LoopNumber = extra passes, as on the real unit
                target_number = current.goto_number
                self._step_index = next(
                    (i for i, s in enumerate(steps) if s.number == target_number), self._step_index
                )
                return
        if self._step_index + 1 < len(steps):
            self._step_index += 1
        else:
            self.running = False
            self.state = "Idle"

    def run_to_completion(self, max_ticks: int = 5000) -> None:
        for _ in range(max_ticks):
            if not self.running:
                return
            self.step()
        self.running = False
        self.state = "Idle"


class _SimODTCTransport:
    """Deterministic in-memory ODTC unit used for tests, demos and offline runs."""

    def __init__(self, index: int = 1) -> None:
        self._unit = _SimODTCUnit(index)
        self._connected = False

    def connect(self, device_ip: str, device_port: str, local_ip: str, simulate: bool) -> None:
        self._connected = True
        self._unit.locked = True  # mirrors _ComODTCTransport.connect()'s internal LockDevice

    def initialize(self) -> None:
        pass

    def get_device_identification(self) -> dict[str, Any]:
        u = self._unit
        return {"firmwareVersion": u.firmware_version, "serialNumber": u.serial, "manufacturer": u.manufacturer}

    def get_status(self) -> dict[str, Any]:
        u = self._unit
        return {"state": u.state, "locked": u.locked, "doorOpen": u.door_open}

    def read_actual_temperature(self) -> dict[str, Any]:
        u = self._unit
        return {"blockTemperature": round(u.block_temperature, 2), "lidTemperature": round(u.lid_temperature, 2)}

    def open_door(self) -> None:
        self._unit.door_open = True

    def close_door(self) -> None:
        self._unit.door_open = False

    def set_method(self, xml_text: str) -> None:
        import xml.etree.ElementTree as ET

        self._unit.protocol_xml = xml_text
        for el in ET.fromstring(xml_text):
            if el.tag in ("Method", "PreMethod") and el.attrib.get("methodName"):
                self._unit.stored_methods[el.attrib["methodName"]] = ET.tostring(el, encoding="unicode")

    def execute_method(self, method_name: str, priority: int) -> str:
        u = self._unit
        stored = u.stored_methods.get(method_name)
        if stored is None:
            raise ODTCError(f"no method downloaded named {method_name!r}; call SetMethod first")
        u.method_name = method_name
        u.protocol = _parse_protocol_for_sim(f"<MethodSet>{stored}</MethodSet>", method_name)
        u.running = True
        u.state = "Running"
        u._step_index = 0
        u._loop_counts = {}
        u.run_log = []
        u.request_id = uuid.uuid4().hex
        return u.request_id

    def wait_for_end_of_execute_method(self, request_id: str, timeout: int) -> None:
        u = self._unit
        if request_id and u.request_id and request_id != u.request_id:
            raise ODTCError(f"unknown request_id {request_id!r}")
        u.run_to_completion()

    def stop_method(self) -> None:
        self._unit.running = False
        self._unit.state = "Idle"

    def pause(self) -> None:
        self._unit.state = "Paused"

    def do_continue(self) -> None:
        if self._unit.running:
            self._unit.state = "Running"

    def abort(self) -> None:
        self._unit.running = False
        self._unit.state = "Idle"

    def reset(self, timeout: int, simulate_on_device_base: bool) -> None:
        self._unit.state = "Idle"
        self._unit.running = False

    def get_last_data(self) -> list[dict[str, Any]]:
        return list(self._unit.run_log)

    def get_parameters(self) -> str:
        # Same envelope the real device returns: a ResponseData wrapping one
        # "MethodsXML" parameter whose string is the (escaped) stored MethodSet.
        from xml.sax.saxutils import escape

        methods_xml = (
            '<?xml version="1.0" encoding="utf-8"?><MethodSet><DeleteAllMethods>false</DeleteAllMethods>'
            + "".join(self._unit.stored_methods.values())
            + "</MethodSet>"
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?><ResponseData><ParameterSet>'
            f'<Parameter name="MethodsXML"><String>{escape(methods_xml)}</String></Parameter>'
            "</ParameterSet></ResponseData>"
        )

    def set_parameters(self, name: str, type_: str, value: str) -> None:
        pass

    def set_log_level(self, level: str) -> None:
        pass

    def set_csv_separator(self, character: str) -> None:
        pass

    def set_date_time(self, iso_datetime: str) -> None:
        pass

    def add_allowed_return_code(self, code: int) -> None:
        pass

    def download_logs(self, dest_dir: str, include_traces: bool) -> list[dict[str, Any]]:
        from pathlib import Path

        files = ["SiLA/Logs/InhecoSiLA.log", "Odtc/Logs/Log_#1.csv"] + (
            ["Traces/sim/trace.csv"] if include_traces else []
        )
        out = []
        for remote in files:
            local = Path(dest_dir) / remote
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(f"simulated log for {self._unit.serial}\n", encoding="utf-8")
            out.append({"remote": "/" + remote, "path": str(local), "size": local.stat().st_size})
        return out

    def download_run_trace(self, dest_dir: str, method_name: str | None) -> dict[str, Any] | None:
        from pathlib import Path

        u = self._unit
        if u.method_name is None or (method_name is not None and u.method_name != method_name):
            return None
        lines = [
            "********************************************************",
            f"* ODTC Temperature trace = {u.method_name} = 2026-01-01T00:00:00Z",
            "********************************************************",
            "Elapsed time [ms];Target temperature [1/100C];Current temperature [1/100C];Lid temperature [1/100C]",
        ]
        for i, row in enumerate(u.run_log):
            lines.append(
                f"{i * 1000};{round(row['target'] * 100)};{round(row['current'] * 100)};"
                f"{round(u.lid_temperature * 100)}"
            )
        lines.append(";End of trace.")
        local = Path(dest_dir) / "sim" / f"{u.method_name}.csv"
        local.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(lines) + "\n"
        local.write_text(text, encoding="utf-8")
        header, rows = parse_trace_csv(text)
        return {"remote": f"/Traces/sim/{local.name}", "path": str(local), "rows": rows, **header}

    def lock(self, lock_id: str, timeout: int) -> None:
        self._unit.locked = True

    def unlock(self) -> None:
        self._unit.locked = False

    def terminate(self) -> None:
        self._connected = False

    def close(self) -> None:
        pass


def _parse_protocol_for_sim(xml_text: str, method_name: str) -> ODTCProtocol | None:
    """Reparse the downloaded XML back into an ``ODTCProtocol`` so the sim
    transport's step interpreter (which walks ``ODTCStep`` objects) can drive
    it, regardless of whether the XML came from :mod:`hamilton_venus.odtc_protocol`
    or a vendor-authored file. Returns ``None`` (an immediate no-op run) for a
    ``<PreMethod>`` (a simple hold, no stepping needed)."""
    import xml.etree.ElementTree as ET

    from hamilton_venus.odtc_protocol import ODTCStep

    root = ET.fromstring(xml_text)
    for method in root.findall("Method"):
        if method.attrib.get("methodName") != method_name:
            continue
        steps = []
        for step_el in method.findall("Step"):
            steps.append(
                ODTCStep(
                    number=int(step_el.findtext("Number", "0")),
                    slope=float(step_el.findtext("Slope", "2")),
                    temperature=float(step_el.findtext("PlateauTemperature", "25")),
                    hold_seconds=float(step_el.findtext("PlateauTime", "0")),
                    lid_temperature=float(step_el.findtext("LidTemp", "110")),
                    goto_number=int(step_el.findtext("GotoNumber", "0")),
                    loop_number=int(step_el.findtext("LoopNumber", "0")),
                )
            )
        return ODTCProtocol(method_name=method_name, steps=steps)
    # A PreMethod (or unknown name): treat as an immediate single-step hold so
    # wait_for_end_of_execute_method still converges.
    for premethod in root.findall("PreMethod"):
        if premethod.attrib.get("methodName") != method_name:
            continue
        from hamilton_venus.odtc_protocol import ODTCStep as _Step

        target = float(premethod.findtext("TargetBlockTemperature", "25"))
        lid = float(premethod.findtext("TargetLidTemp", "110"))
        return ODTCProtocol(
            method_name=method_name, steps=[_Step(number=1, temperature=target, hold_seconds=0, lid_temperature=lid)]
        )
    return None


# --------------------------------------------------------------------------- #
# COM-interop transport                                                       #
# --------------------------------------------------------------------------- #


class _ComODTCTransport:
    """Drives one ``Inheco.ODTCInterface`` COM object instance (one unit).

    Most vendor calls take a lock token (acquired internally at
    :meth:`connect` and threaded through every subsequent call, so callers
    never see it -- see the module docstring's "every operation needs a lock
    token" note) -- but not all: ``GetStatus``, ``WaitForEndOfExecuteMethod``,
    ``Terminate`` and ``AddAllowedReturnCode`` take no lock at all, and
    ``LockDevice`` itself takes it *last*, not first. Every method's true
    input-argument list/order below is taken directly from the
    ``objDevice.<Method>(...)`` call sites in the vendor's own
    ``Inheco ODTC.hsl`` (not the ``.hsl``'s own wrapper-function parameter
    list, which is per-device-ID-routing scaffolding the real COM object
    doesn't see).

    Confirmed live against real hardware (a raw probe of ``.raw_call()``,
    bypassing this class's own field mapping): every method's pywin32 result
    is ``(success: bool, *outs)`` where ``success`` is the vendor .NET
    method's own return value (the thing the ``.hsl`` negates with
    ``if(!objDevice.Method(...))``) and ``outs`` are its declared ``out``
    parameters, in declared order -- **not**, as an earlier version of this
    class assumed, a numeric SiLA return code at a fixed position (the
    ``o_intSiLAReturnValue`` out param some methods also carry is not a
    reliable 0-means-success code -- e.g. a real, successful
    ``GetDeviceIdentification`` returned ``ReturnValue=1`` alongside
    ``Message="Success."``). :meth:`_call` strips the leading bool and raises
    on it directly; every method below indexes into the plain vendor `out`
    list :meth:`_call` returns.
    """

    def __init__(self, backend: object | None = None) -> None:
        self._backend: object | None = backend
        self._candidates: list[object] = [] if backend is not None else _candidate_backends()
        self._lock_id: str | None = None

    def _select_backend(self) -> object:
        if self._backend is not None:
            return self._backend
        errors: list[str] = []
        for candidate in self._candidates:
            ensure = getattr(candidate, "_ensure", None)
            try:
                if callable(ensure):
                    ensure()
                self._backend = candidate
                logger.info("ODTC: using %s", type(candidate).__name__)
                return candidate
            except Exception as exc:
                errors.append(f"{type(candidate).__name__}: {exc}")
        raise ODTCError(
            f"could not create {_PROGID!r}. {odtc_com_diagnosis()}"
            + ("  Tried -- " + "; ".join(errors) if errors else "")
        )

    def _call(self, name: str, *args: object) -> list[object]:
        """Invoke *name*, raise on vendor failure, and return its real ``out`` values.

        See the class docstring: the raw pywin32 result is ``(success,
        *outs)``. ``success`` is consumed here; callers get only ``outs``, in
        the vendor's own declared order, so every wire method below can
        index into it directly without re-deriving this shape itself.
        """
        backend = self._select_backend()
        try:
            raw = backend.raw_call(name, *args)  # type: ignore[attr-defined]
        except ODTCError:
            raise
        except Exception as exc:
            raise ODTCError(f"ODTC {name} raised: {exc}") from exc
        result = list(raw) if isinstance(raw, (tuple, list)) else [raw]
        success, outputs = (result[0], result[1:]) if result else (False, [])
        if not success:
            message = str(outputs[-1]) if outputs else ""
            raise ODTCError(f"ODTC {name} failed" + (f": {message}" if message else ""))
        return outputs

    def close(self) -> None:
        seen = {self._backend, *self._candidates}
        seen.discard(None)
        for backend in seen:
            close = getattr(backend, "close", None)
            if callable(close):
                close()

    # -- lifecycle --
    def connect(self, device_ip: str, device_port: str, local_ip: str, simulate: bool) -> None:
        # Vendor signature: Connect(LocalIP, DeviceIP, DevicePort, TraceLevel, out Message).
        # TraceLevel 0 = no extra vendor-side tracing; *simulate* (this
        # transport's own always-real vs. the manager's simulation-fallback
        # flag) has no wire equivalent and is accepted only for Protocol
        # parity with _SimODTCTransport.connect().
        self._call("Connect", local_ip, device_ip, device_port, 0)
        self._lock_id = uuid.uuid4().hex
        # Vendor signature is (Timeout, PMSID, LockID, ...), not (LockID, Timeout).
        self._call("LockDevice", 3600, "", self._lock_id)

    def initialize(self) -> None:
        self._call("Initialize", self._lock_id)

    def get_device_identification(self) -> dict[str, Any]:
        # Vendor outputs, in order: FirmwareVersion, Manufacturer, Name,
        # SerialNumber, SiLAInterfaceVersion, SiLASubDeviceClass, Wsdl.
        outputs = self._call("GetDeviceIdentification", self._lock_id)
        return {
            "firmwareVersion": str(outputs[0]) if len(outputs) > 0 else "",
            "manufacturer": str(outputs[1]) if len(outputs) > 1 else "",
            "serialNumber": str(outputs[3]) if len(outputs) > 3 else "",
        }

    def get_status(self) -> dict[str, Any]:
        # Vendor GetStatus takes no input at all (not even the lock) and
        # outputs, in order: DeviceId, State, Locked, PMSId, CurrentTime.
        # There is no separate door-open output on this interface --
        # "doorOpen" is a best-effort read of the State string (confirmed
        # real values include "inError"; a real door-open value is not yet
        # confirmed) until hardware exercises that state.
        outputs = self._call("GetStatus")
        state = str(outputs[1]) if len(outputs) > 1 else ""
        return {
            "state": state,
            "locked": bool(outputs[2]) if len(outputs) > 2 else False,
            "doorOpen": "door" in state.lower(),
        }

    def read_actual_temperature(self) -> dict[str, Any]:
        # Vendor outputs, in order: Time, ActualTemperatures[], ActualTemperatureNames[].
        # Block/lid temperature are picked out of the parallel arrays by
        # name rather than assumed positions.
        outputs = self._call("ReadActualTemperature", self._lock_id)
        values = outputs[1] if len(outputs) > 1 and isinstance(outputs[1], (list, tuple)) else []
        names = outputs[2] if len(outputs) > 2 and isinstance(outputs[2], (list, tuple)) else []
        by_name = {str(n).lower(): float(v) for n, v in zip(names, values, strict=False)}
        block = next((v for k, v in by_name.items() if "block" in k), None)
        lid = next((v for k, v in by_name.items() if "lid" in k), None)
        if block is None and values:
            block = float(values[0])
        if lid is None and len(values) > 1:
            lid = float(values[1])
        return {"blockTemperature": block or 0.0, "lidTemperature": lid or 0.0}

    def open_door(self) -> None:
        self._call("OpenDoor", self._lock_id)

    def close_door(self) -> None:
        self._call("CloseDoor", self._lock_id)

    def set_method(self, xml_text: str) -> None:
        self._call("SetMethod", self._lock_id, xml_text)

    def execute_method(self, method_name: str, priority: int) -> str:
        # Vendor outputs, in order: RequestId, Duration.
        outputs = self._call("ExecuteMethod", self._lock_id, method_name, priority)
        return str(outputs[0]) if outputs else ""

    def wait_for_end_of_execute_method(self, request_id: str, timeout: int) -> None:
        # Vendor signature: WaitForEndOfExecuteMethod(TimeOut, RequestId, ...) --
        # no lock token at all.
        self._call("WaitForEndOfExecuteMethod", timeout, request_id)

    def stop_method(self) -> None:
        self._call("StopMethod", self._lock_id)

    def pause(self) -> None:
        self._call("Pause", self._lock_id)

    def do_continue(self) -> None:
        self._call("DoContinue", self._lock_id)

    def abort(self) -> None:
        self._call("Abort", self._lock_id)

    def reset(self, timeout: int, simulate_on_device_base: bool) -> None:
        # Vendor signature: Reset(SimulateOnDeviceBase, TimeToWait, LockID,
        # DeviceId, PMSId, ...) -- DeviceId/PMSId are vendor-internal
        # identifiers this driver has no value for; empty string, as used
        # elsewhere for PMSID, is the only sensible default.
        self._call("Reset", simulate_on_device_base, timeout, self._lock_id, "", "")

    def get_last_data(self) -> list[dict[str, Any]]:
        # Vendor outputs: Result (the only one).
        outputs = self._call("GetLastData", self._lock_id)
        raw = str(outputs[0]) if outputs else ""
        return _parse_run_data(raw)

    def get_parameters(self) -> str:
        outputs = self._call("GetParameters", self._lock_id)
        return str(outputs[0]) if outputs else ""

    def set_parameters(self, name: str, type_: str, value: str) -> None:
        self._call("SetParameters", self._lock_id, name, type_, value)

    def set_log_level(self, level: str) -> None:
        # Vendor's own variable is i_strLogLevel -- a string.
        self._call("SetLogLevel", self._lock_id, level)

    def set_csv_separator(self, character: str) -> None:
        self._call("SetCSVCharacter", self._lock_id, character)

    def set_date_time(self, iso_datetime: str) -> None:
        self._call("SetTimeConfiguration", self._lock_id, iso_datetime)

    def add_allowed_return_code(self, code: int) -> None:
        # No lock token and no declared out params at all on this one.
        self._call("AddAllowedReturnCode", code)

    def download_logs(self, dest_dir: str, include_traces: bool) -> list[dict[str, Any]]:
        raise ODTCError("downloading logs is only available over the SOAP transport")

    def download_run_trace(self, dest_dir: str, method_name: str | None) -> dict[str, Any] | None:
        raise ODTCError("downloading run traces is only available over the SOAP transport")

    def lock(self, lock_id: str, timeout: int) -> None:
        pass

    def unlock(self) -> None:
        if self._lock_id:
            self._call("UnlockDevice", self._lock_id)

    def terminate(self) -> None:
        try:
            if self._lock_id:
                self._call("UnlockDevice", self._lock_id)
                # Vendor Terminate() takes no lock/args at all.
                self._call("Terminate")
        finally:
            self._lock_id = None


def _parse_run_data(raw: str) -> list[dict[str, Any]]:
    """Parse ``GetLastData``'s payload into one dict per trace sample.

    Confirmed on a real unit: the payload is XML inside XML (a ``ResponseData``
    whose ``AnyData`` holds an escaped ``containerData`` document) with one
    ``dataSeries`` per recorded run, whose ``stringValue`` is a CSV trace at
    about 1 Hz::

        Elapsed time [ms];Target temperature [1/100 C];Current temperature [1/100 C];Lid temperature [1/100 C]
        102;3028;3035;7110

    Each sample becomes ``{"series", "elapsedMs", "targetTemperature",
    "currentTemperature", "lidTemperature"}`` (temperatures in degrees C; the
    ``series`` name is the run's start time). The separator is whatever the
    header uses (``odtc_set_csv_separator`` changes it). A payload in some other
    shape falls back to ``[{"raw": ...}]`` -- a diagnostic read should never
    itself fail.
    """
    import html
    import re

    text = raw.strip()
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    for name, csv in re.findall(
        r"<dataSeries[^>]*?nameId=\"([^\"]*)\"[^>]*>.*?<stringValue[^>]*>(.*?)</stringValue>",
        html.unescape(text),
        re.S,
    ):
        lines = [ln for ln in csv.replace("\r", "").split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        sep = ";" if ";" in lines[0] else ","
        for line in lines[1:]:
            try:
                values = [float(v) for v in line.split(sep)]
            except ValueError:
                continue
            if len(values) == 4:
                rows.append(
                    {
                        "series": name,
                        "elapsedMs": values[0],
                        "targetTemperature": values[1] / 100.0,
                        "currentTemperature": values[2] / 100.0,
                        "lidTemperature": values[3] / 100.0,
                    }
                )
            else:
                rows.append({"series": name, "values": values})
    if rows:
        return rows
    return [{"raw": text}]


def _candidate_backends() -> list[object]:
    return _com32.candidate_backends(
        progid=_PROGID,
        bin_dirs=[_ODTC_LIB_DIR],
        tl_bin_dir=None,  # Inheco's own WCF client, not Hamilton's TransportLayer stack
        env_vars=(_PY32_ENV,),
        error_cls=ODTCError,
        diagnosis=odtc_com_diagnosis(),
    )


# --------------------------------------------------------------------------- #
# SOAP transport                                                              #
# --------------------------------------------------------------------------- #
#
# The vendor's Inheco.ODTCInterface COM object (above) turned out, on real
# hardware, to have a genuine bug in its own local event-receiver listener
# setup (it asks Windows for a dynamic port -- "0" -- via HTTP.SYS, which
# does not support that for a non-reserved port even when run elevated; see
# CHANGELOG/HANDOFF for the full diagnosis). The ODTC's real transport is a
# plain SOAP/WSDL service the vendor exposes directly at
# ``http://<device_ip>/odtc.wsdl`` (SOAP address ``http://<device_ip>:8080/``)
# -- talking to it directly sidesteps the COM object, the 32-bit bridge and
# the broken listener entirely, at the cost of this driver hosting its own
# (much simpler) event-receiver listener for the SiLA commands that reply
# asynchronously. This is now the default real transport; ``_ComODTCTransport``
# is kept for reference/fallback but is not used unless injected explicitly.
#
# SiLA basics learned from the WSDL + live hardware, load-bearing for
# everything below:
#   * Every command takes a client-chosen ``requestId`` (int) that must be
#     unique per in-flight command -- reusing one gets "Error on requestId."
#   * A command either answers inline (``returnCode=1``, e.g. GetStatus,
#     GetDeviceIdentification) or is accepted asynchronously (``returnCode=2``,
#     "Asynchronous command accepted") and its real result/completion arrives
#     later as a POST to ``eventReceiverURI`` -- ``ResponseEvent`` (command
#     finished, carries ``responseData``) and/or ``StatusEvent`` (state
#     changed). Polling :meth:`get_status` until the device leaves a
#     transient state (``busy``/``resetting``/``initializing``) is a reliable,
#     simpler stand-in for correlating specific events for every command
#     except :meth:`read_actual_temperature`/:meth:`get_last_data`, whose
#     actual payload *only* exists in the pushed event, never in the ack.
#   * ``lockTimeout``/``errorHandlingTimeout`` are XML ``TimeSpan`` strings
#     (``"PT3600S"``), not bare numbers -- a bare number is accepted
#     syntactically but corrupts the device's own event-sending code
#     (a real, reproducible ``NullReferenceException`` in its SiLA stack,
#     confirmed via its own log over FTP) and leaves it in ``inError``.
#   * A fresh boot starts in ``state="startup"``, which refuses
#     ``LockDevice``; call :meth:`reset` once to reach ``standby`` first.
#   * ``SetMethod``/protocol upload has **no** SOAP operation in this WSDL at
#     all (confirmed against the full schema) -- only :meth:`execute_method`
#     for a method already present on the device. Uploading a new ad hoc
#     protocol is not implemented here; the device's FTP server likely holds
#     method files, but that was not pinned down against real hardware.

#: Hamilton's installer pre-reserves these for the ODTC's SiLA event
#: receiver (both a firewall allow-rule and an HTTP.SYS URL ACL granting
#: ``\Everyone`` -- confirmed via ``netsh http show urlacl`` -- so this
#: driver's own listener can bind one without admin rights).
_SILA_EVENT_PORTS = list(range(18001, 18009))
_SILA_EVENT_PATH = "/Inheco_ODTC_EventReceiver"
_SILA_NS = "http://sila.coop"


def _local_ip_for(device_ip: str) -> str:
    """The local interface address this machine would use to reach *device_ip*.

    Mirrors the vendor HSL's own ``i_strLocalIP=""`` auto-detect behavior
    (see its Connect() help text) via the standard UDP-connect trick -- no
    packet is actually sent, this just asks the OS to pick a route.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((device_ip, 1))
        return str(sock.getsockname()[0])


def _timespan(seconds: float) -> str:
    """Render *seconds* as an XML ``TimeSpan`` (e.g. ``"PT60S"``).

    The device's own event-sending code null-refs on a non-conformant value
    here (see the module note above) -- always go through this, never pass a
    bare number.
    """
    return f"PT{seconds:g}S"


class _SilaEventListener:
    """Hosts the SiLA ``ISiLAEventReceiver`` callback this driver's SOAP
    commands ask the device to POST ``ResponseEvent``/``StatusEvent`` to.

    Binds the first free port in :data:`_SILA_EVENT_PORTS` (pre-reserved for
    this purpose, see the module note above). One listener is shared by every
    :class:`_SoapODTCTransport` in a process (one physical port, `MAX_DEVICES`
    units) -- callers correlate their own command's completion by
    ``requestId``.
    """

    def __init__(self, local_ip: str) -> None:
        self._events: dict[int, dict[str, Any]] = {}
        self._cond = threading.Condition()
        last_exc: Exception | None = None
        for port in _SILA_EVENT_PORTS:
            try:
                self._server = http.server.HTTPServer((local_ip, port), self._make_handler())
                self.port = port
                break
            except OSError as exc:
                last_exc = exc
        else:
            raise ODTCError(
                f"could not bind an ODTC event-receiver listener on any of {_SILA_EVENT_PORTS} "
                f"at {local_ip}: {last_exc}"
            )
        self.uri = f"http://{local_ip}:{self.port}{_SILA_EVENT_PATH}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _make_handler(self) -> type:
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                import re
                import xml.etree.ElementTree as ET

                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                action = (self.headers.get("SOAPAction") or "").strip('"')
                op = action.rsplit("/", 1)[-1] or "Unknown"
                try:
                    root = ET.fromstring(body)
                    payload = {
                        re.sub(r"^\{.*\}", "", child.tag): child.text
                        for child in next(iter(root)).iter()
                        if list(child) == []
                    }
                except ET.ParseError:
                    payload = {}
                # Only ResponseEvent carries a requestId; StatusEvent (state
                # changes) does not. Both must still be acknowledged below --
                # an unacknowledged event makes the device log an event error
                # and drop to "inError".
                # Only ResponseEvents are kept: a run's DataEvents carry the same
                # requestId and would otherwise clobber the completion event.
                request_id = payload.get("requestId")
                if op == "ResponseEvent" and request_id and request_id.strip().lstrip("-").isdigit():
                    with listener._cond:
                        listener._events[int(request_id)] = {"op": op, **payload}
                        while len(listener._events) > 256:  # nobody waits on most of them
                            listener._events.pop(next(iter(listener._events)))
                        listener._cond.notify_all()
                resp = (
                    "<s:Envelope xmlns:s='http://schemas.xmlsoap.org/soap/envelope/'><s:Body>"
                    f"<{op}Response xmlns='{_SILA_NS}'><{op}Result>true</{op}Result></{op}Response>"
                    "</s:Body></s:Envelope>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, fmt: str, *args: object) -> None:
                logger.debug("ODTC event listener: " + fmt, *args)

        return Handler

    def wait_for_response_event(self, request_id: int, timeout: float) -> dict[str, Any] | None:
        """Block for the ``ResponseEvent`` payload for *request_id*, or None on timeout."""
        with self._cond:
            end = time.monotonic() + timeout
            while request_id not in self._events:
                remaining = end - time.monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    return None
            return self._events.pop(request_id)

    def close(self) -> None:
        self._server.shutdown()


_shared_listener: _SilaEventListener | None = None
_shared_listener_lock = threading.Lock()


def _get_shared_listener(local_ip: str) -> _SilaEventListener:
    global _shared_listener
    with _shared_listener_lock:
        if _shared_listener is None:
            _shared_listener = _SilaEventListener(local_ip)
        return _shared_listener


#: Request IDs are seeded from the clock, not 1. The device keeps re-sending
#: undelivered ResponseEvents from earlier sessions to whichever listener is
#: registered now, and a new process that also counted from 1 matched them to
#: its own commands -- returning from a Reset/Initialize instantly, before it
#: had finished (the device log showed them fired within one second and the
#: next commands rejected "busy"). The vendor wrapper avoids this by persisting
#: its counter to a file; a clock seed is monotonic across sessions without one.
_request_ids = itertools.count(int(time.time()))


class _SoapODTCTransport:
    """Drives one physical ODTC unit over its SiLA SOAP interface directly.

    See the module note above for why this, rather than the vendor COM
    object, is the default real transport.

    Deliberately does **not** call ``LockDevice``/``UnlockDevice``. Confirmed
    live against real hardware: ``lockId`` is optional (``minOccurs="0"``,
    nillable) on every command except ``LockDevice``/``UnlockDevice``
    themselves, and every command works fine with ``lockId=None`` as long as
    *nothing else* holds the lock. Actually acquiring one bought nothing but
    risk: a lock survives only in the calling process's memory, so any
    partial failure (a crash, a bug, even just Ctrl-C) between ``LockDevice``
    and ``UnlockDevice`` leaves the device permanently locked by a token
    nobody has anymore -- recoverable only by a physical power cycle, which
    is exactly what happened repeatedly while first building this transport.
    Running lock-free avoids that whole failure class; it does give up
    exclusivity against a second concurrent client, which this driver's
    one-unit-per-``device_id`` model doesn't need anyway.
    """

    #: States that block Initialize/door/etc. and only clear via Reset: a
    #: fresh boot starts in "startup"; "inError" is reachable any time
    #: (confirmed on real hardware after a malformed call, but nothing rules
    #: out a genuine device fault too -- Reset is the device's own recovery
    #: path for both, so this driver doesn't try to tell them apart).
    _needs_reset_states = ("startup", "inError")
    #: Decompiled from ThermoCycler.SetInstance(), which seeds these on every
    #: connect -- codes above 3 the vendor's own wrapper treats as non-fatal
    #: rather than real errors. :meth:`add_allowed_return_code` extends this
    #: set (matching AddAllowedReturnCode, which is purely client-side -- no
    #: device call at all).
    _DEFAULT_ALLOWED_CODES = frozenset({12, 1004, 2005, 2006, 4711})

    def __init__(self) -> None:
        self._client: Any | None = None
        self._local_ip: str = ""
        self._device_ip: str = ""
        self._listener: _SilaEventListener | None = None
        #: The device's estimated duration of the last ExecuteMethod, in seconds.
        self.last_estimated_seconds: float | None = None
        self._allowed_codes: set[int] = set(self._DEFAULT_ALLOWED_CODES)

    def _rid(self) -> int:
        return (next(_request_ids) % 2_147_483_646) + 1

    @staticmethod
    def _return_value(result: object) -> tuple[int, str]:
        """Pull ``(returnCode, message)`` out of *result*, whatever shape it is:
        a bare ``SiLAReturnValue`` (ack-only ops) or a wrapper with a
        ``<Op>Result`` field (data-returning ops like GetStatus)."""
        rv: Any = result
        for attr in dir(result):
            if attr.endswith("Result") and not attr.startswith("_"):
                rv = getattr(result, attr)
                break
        return int(rv.returnCode), str(rv.message or "")

    @staticmethod
    def _duration_seconds(duration: object) -> float:
        """Seconds in an XML duration string such as ``"PT6M12S"`` (0 if unparseable)."""
        import re

        m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(duration or ""))
        if not m:
            return 0.0
        hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())
        return hours * 3600 + minutes * 60 + seconds

    def _check_code(self, op: str, code: int, message: str) -> None:
        # Mirrors ThermoCycler's own _HandleAsyncReturnValue: codes 0-3 are
        # never a failure, and above 3 only the allow-list (seeded from
        # AddAllowedReturnCode) is non-fatal -- everything else is an error.
        if code > 3 and code not in self._allowed_codes:
            raise ODTCError(f"ODTC {op} failed: {message or f'return code {code}'}")

    def _invoke(self, op: str, settle: bool = True, **kwargs: object) -> Any:
        """Call *op*; for an asynchronously-accepted command (return code 2)
        also wait for its completion event when *settle* is true.

        Completion is the command's own ``ResponseEvent`` (matched by
        ``requestId``), not polling ``GetStatus``: right after an ack the
        state has often not flipped to "busy" yet, so polling races -- it
        let a second command through while the first was still running
        ("SetConfiguration already in progress"). This is also what the
        vendor's own wrapper waits for. Pass ``settle=False`` for commands
        that must return at once (``ExecuteMethod`` runs for minutes).
        """
        assert self._client is not None, "ODTC SOAP transport used before connect()"
        result = getattr(self._client.service, op)(**kwargs)
        code, message = self._return_value(result)
        if code == 2:  # "Asynchronous command accepted"
            if settle:
                self._await_completion(op, cast(int, kwargs["requestId"]), self._ack_duration(result))
                if op in self._SETTLES_TO_IDLE:
                    self._wait_not_busy()
        else:
            self._check_code(op, code, message)
        return result

    #: Commands after which the unit returns to idle/standby. Their completion
    #: event arrives a moment *before* the state actually leaves "busy" (the
    #: device log shows the next command being rejected "busy" in the very
    #: same second), so wait for the state too. Not applied to commands that
    #: legitimately leave the unit busy (a running method, reads mid-run).
    _SETTLES_TO_IDLE = frozenset(
        {"Reset", "Initialize", "OpenDoor", "CloseDoor", "SetParameters", "SetConfiguration", "StopMethod", "Abort"}
    )

    def _wait_not_busy(self, timeout: float = 15.0) -> None:
        end = time.monotonic() + timeout
        while self.get_status()["state"] in ("busy", "resetting", "initializing") and time.monotonic() < end:
            time.sleep(0.5)

    def _ack_duration(self, result: object) -> float:
        rv = result
        for attr in dir(result):
            if attr.endswith("Result") and not attr.startswith("_"):
                rv = getattr(result, attr)
                break
        return self._duration_seconds(getattr(rv, "duration", ""))

    def _await_completion(
        self, op: str, request_id: int, expected_seconds: float, extra: float = 0.0
    ) -> dict[str, Any]:
        """Block for *request_id*'s ``ResponseEvent`` and return its payload.

        Waits the device's own estimate plus 30 s (``additionalTime`` in the
        vendor wrapper) plus *extra*; raises if it never arrives or reports
        an error code.
        """
        timeout = expected_seconds + 30.0 + extra
        event = self._listener.wait_for_response_event(int(request_id), timeout) if self._listener else None
        if event is None:
            raise ODTCError(f"ODTC {op} timed out: no completion event within {timeout:.0f}s")
        try:
            code = int(event.get("returnCode", 0))
        except ValueError:
            code = 0
        self._check_code(op, code, str(event.get("message") or ""))
        return event

    def _invoke_async_data(self, op: str, timeout: float = 30.0, **kwargs: object) -> str:
        """Call an op whose real payload only exists in its pushed
        ``ResponseEvent`` (its SOAP response is ack-only -- confirmed for
        ``ReadActualTemperature``/``GetLastData``/``GetParameters``, none of
        which declare a data field in their own ``*Response`` schema).
        Returns the raw ``responseData`` XML string."""
        request_id = self._rid()
        ack = self._invoke(op, settle=False, requestId=request_id, **kwargs)
        event = self._await_completion(op, request_id, self._ack_duration(ack), extra=timeout)
        return event.get("responseData") or ""

    # -- lifecycle --
    def connect(self, device_ip: str, device_port: str, local_ip: str, simulate: bool) -> None:
        import zeep

        self._device_ip = device_ip
        self._local_ip = local_ip or _local_ip_for(device_ip)
        self._listener = _get_shared_listener(self._local_ip)
        wsdl = f"http://{device_ip}/odtc.wsdl"
        client_cls: Any = zeep.Client
        try:
            self._client = client_cls(wsdl=wsdl)
        except Exception as exc:
            raise ODTCError(f"could not fetch/parse ODTC WSDL at {wsdl}: {exc}") from exc

        # Always Reset on connect, even from "idle". The device learns where to
        # push its async events (ResponseEvent/StatusEvent) only from the
        # eventReceiverURI carried by Reset/LockDevice -- and LockDevice is
        # refused from "idle" -- so skipping this leaves it pushing to a dead
        # listener from some earlier session. Confirmed live: the next
        # ReadActualTemperature then returns no data, and the device's own log
        # shows "ResponseEvent: ConnectFailure" followed by "State changed:
        # InError". Hamilton's own flow also opens a session with
        # Reset + Initialize. A Reset from "inError" can itself land back in
        # "inError" once (observed live), so retry before giving up loudly.
        try:
            self.reset(timeout=60, simulate_on_device_base=False)
        except ODTCError as exc:
            logger.warning("ODTC: first Reset on connect failed (%s); checking state", exc)
        for _ in range(2):
            state = self.get_status()["state"]
            if state not in self._needs_reset_states:
                break
            self.reset(timeout=60, simulate_on_device_base=False)
        else:
            raise ODTCError(
                f"ODTC stuck in state {state!r} after repeated Reset attempts; "
                "a physical power cycle is likely needed"
            )

    def initialize(self) -> None:
        # Only valid from "standby" (post-Reset) -- calling it again on an
        # already-"idle" device (e.g. reconnecting to one left over from a
        # prior session) is refused ("Command not allowed in this state"),
        # so make this idempotent rather than making every caller know that.
        if self.get_status()["state"] == "idle":
            return
        self._invoke("Initialize", requestId=self._rid(), lockId=None)

    def get_device_identification(self) -> dict[str, Any]:
        result = self._invoke("GetDeviceIdentification", requestId=self._rid(), lockId=None)
        desc = result.deviceDescription
        return {
            "firmwareVersion": desc.DeviceFirmwareVersion or "",
            "manufacturer": desc.DeviceManufacturer or "",
            "serialNumber": desc.DeviceSerialNumber or "",
        }

    def get_status(self) -> dict[str, Any]:
        result = self._invoke("GetStatus", settle=False, requestId=self._rid())
        state = str(result.state)
        return {"state": state, "locked": bool(result.locked), "doorOpen": "door" in state.lower()}

    def read_actual_temperature(self) -> dict[str, Any]:
        # Decompiled from ThermoCycler.ReadActualTemperature: responseData
        # wraps a <String>...</String>-delimited, XML-entity-escaped
        # SensorValues document with named integer fields in centidegrees
        # (divide by 100). "Mount" is the block/plate sensor -- there is no
        # field literally named "Block" -- and "Lid" (not "Lid_Monitor") is
        # the lid heater sensor; Ambient/Heatsink/Heatsink_TEC/Mount_Monitor/
        # PCB are also present but not surfaced by this driver's API.
        response_data = self._invoke_async_data("ReadActualTemperature", lockId=None)
        block = lid = 0.0
        if response_data:
            import xml.etree.ElementTree as ET

            start = response_data.find("<String>")
            end = response_data.find("</String>", start)
            if start >= 0 and end > start:
                sensor_xml = response_data[start + len("<String>") : end].replace("&gt;", ">").replace("&lt;", "<")
                try:
                    root = ET.fromstring(sensor_xml)

                    def sensor(tag: str) -> float:
                        el = root.find(tag)
                        return float(el.text) / 100.0 if el is not None and el.text else 0.0

                    block = sensor("Mount")
                    lid = sensor("Lid")
                except (ET.ParseError, ValueError):
                    logger.debug("ODTC: could not parse SensorValues payload: %r", sensor_xml)
        return {"blockTemperature": block, "lidTemperature": lid}

    def open_door(self) -> None:
        self._invoke("OpenDoor", requestId=self._rid(), lockId=None)

    def close_door(self) -> None:
        self._invoke("CloseDoor", requestId=self._rid(), lockId=None)

    @staticmethod
    def _xml_escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def set_method(self, xml_text: str) -> None:
        # SetMethod is not a real SOAP operation -- decompiling the vendor's
        # Inheco ODTC Interface.dll (ThermoCycler.SetMethod) shows it's
        # implemented as SetParameters with a specific payload shape: the
        # whole method-set XML, entity-escaped, with everything before its
        # own "<MethodSet" tag (the "<?xml ...?>" prolog) stripped, wrapped
        # in a single String parameter named "MethodsXML".
        escaped = self._xml_escape(xml_text)
        idx = escaped.find("&lt;MethodSet", 1, 101)  # vendor: IndexOf(value, startIndex=1, count=100)
        if idx < 0:
            raise ODTCError("XML File has wrongFormat < MethodSet > is missing within the first 100 characters")
        params_xml = (
            '<ParameterSet><Parameter parameterType="String" name="MethodsXML"><String>'
            + escaped[idx:]
            + "</String></Parameter></ParameterSet>"
        )
        self._invoke("SetParameters", requestId=self._rid(), lockId=None, paramsXML=params_xml)

    def execute_method(self, method_name: str, priority: int) -> str:
        request_id = self._rid()
        # settle=False: the ack says how long the run will take (e.g. PT6M12S);
        # like the vendor's ExecuteMethod, return as soon as it is accepted and
        # let wait_for_end_of_execute_method wait for the run's completion event.
        ack = self._invoke(
            "ExecuteMethod",
            settle=False,
            requestId=request_id,
            lockId=None,
            methodName=method_name.replace('"', ""),  # matches ThermoCycler.ExecuteMethod
            # The device rejects anything outside [1; 2147483647] ("Invalid
            # command parameter") -- unlike the vendor HSL, which accepts 0.
            priority=max(1, priority),
        )
        # The device's own estimate (e.g. "PT6M12S"), which the vendor wrapper
        # also hands back as programDuration.
        self.last_estimated_seconds = self._ack_duration(ack)
        return str(request_id)

    def wait_for_end_of_execute_method(self, request_id: str, timeout: int) -> None:
        # The run's ResponseEvent arrives when it finishes (or is stopped).
        self._await_completion("ExecuteMethod", int(request_id), 0.0, extra=max(0, timeout - 30))

    def stop_method(self, busy_retry_seconds: float = 60.0) -> None:
        """StopMethod, retried while the unit is still busy with another command.

        A stop sent right after an ``Abort`` (or a door move) is refused with "Device is
        busy due to other command execution" until that command has finished, so a
        caller that stops before disconnecting would otherwise fail spuriously.
        """
        end = time.monotonic() + busy_retry_seconds
        while True:
            try:
                self._invoke("StopMethod", requestId=self._rid(), lockId=None)
                return
            except ODTCError as exc:
                if "busy due to other command" not in str(exc) or time.monotonic() >= end:
                    raise
                time.sleep(2.0)

    def pause(self) -> None:
        self._invoke("Pause", requestId=self._rid(), lockId=None)

    def do_continue(self) -> None:
        self._invoke("DoContinue", requestId=self._rid(), lockId=None)

    def abort(self) -> None:
        self._invoke("Abort", requestId=self._rid(), lockId=None)

    def reset(self, timeout: int, simulate_on_device_base: bool) -> None:
        if self._listener is None:
            self._listener = _get_shared_listener(self._local_ip or _local_ip_for("0.0.0.0"))
        self._invoke(
            "Reset",
            requestId=self._rid(),
            lockId=None,
            deviceId="",
            eventReceiverURI=self._listener.uri,
            PMSId="",
            errorHandlingTimeout=_timespan(timeout),
            simulationMode=simulate_on_device_base,
        )

    def get_last_data(self) -> list[dict[str, Any]]:
        # ThermoCycler.GetLastData waits longer than other async reads
        # (_waitForAsync(300) vs the default) -- fetching the run log can
        # take a while.
        raw = self._invoke_async_data("GetLastData", timeout=330, lockId=None)
        return _parse_run_data(raw) if raw else []

    def get_parameters(self) -> str:
        return self._invoke_async_data("GetParameters", lockId=None)

    def set_parameters(self, name: str, type_: str, value: str) -> None:
        # SetParameters' real SOAP schema is a single paramsXML string, not
        # separate name/type/value fields. The <ParameterSet><Parameter
        # parameterType="X" name="Y"><X>value</X></Parameter></ParameterSet>
        # envelope (and that the inner tag echoes parameterType) is confirmed
        # against three decompiled ThermoCycler examples: SetMethod's own
        # "MethodsXML" (String), SetLogLevel's "LogLevel" (String, via
        # SetConfiguration not SetParameters -- see set_log_level), and
        # SetTimeConfiguration's "SysDateTime" (DateTime). SetCSVCharacter
        # omits parameterType entirely -- see set_csv_separator, which builds
        # its own envelope directly rather than going through this generic
        # method.
        params_xml = (
            f'<ParameterSet><Parameter parameterType="{self._xml_escape(type_)}" name="{self._xml_escape(name)}">'
            f"<{type_}>{self._xml_escape(value)}</{type_}></Parameter></ParameterSet>"
        )
        self._invoke("SetParameters", requestId=self._rid(), lockId=None, paramsXML=params_xml)

    def _configure(self, config_xml: str) -> None:
        """Send *config_xml* via SetConfiguration.

        Confirmed on real hardware: SetConfiguration (and GetConfiguration) are
        only allowed in the "standby" state, while SetParameters is only
        allowed in "idle". From "idle" that means a Reset -> configure ->
        Initialize round trip (about a minute); a running method must be
        stopped first, since Reset would abort it.
        """
        state = self.get_status()["state"]
        if state not in ("standby", "idle"):
            raise ODTCError(
                f"cannot change the device configuration while it is {state!r}; "
                "stop any running method and wait until it is idle"
            )
        if state == "idle":
            self.reset(timeout=60, simulate_on_device_base=False)
        try:
            self._invoke(
                "SetConfiguration",
                requestId=self._rid(),
                lockId=None,
                configLevel=1,
                password=None,
                configXML=config_xml,
            )
        finally:
            if state == "idle":
                self.initialize()

    def set_log_level(self, level: str) -> None:
        # Decompiled ThermoCycler.SetLogLevel: goes through SetConfiguration
        # (configLevel=1, password=None), not SetParameters. *level* is one of
        # ODTC_LOG_LEVELS (validated by the command layer).
        self._configure(
            f'<ParameterSet><Parameter parameterType="String" name="LogLevel">'
            f'<String>{level}</String></Parameter></ParameterSet>'
        )

    def set_csv_separator(self, character: str) -> None:
        # Decompiled ThermoCycler.SetCSVCharacter: SetParameters, but -- unlike
        # set_parameters()'s generic envelope -- no parameterType attribute.
        params_xml = (
            f'<ParameterSet><Parameter name="CSVSeparatorCharacter">'
            f'<String>{self._xml_escape(character)}</String></Parameter></ParameterSet>'
        )
        self._invoke("SetParameters", requestId=self._rid(), lockId=None, paramsXML=params_xml)

    def set_date_time(self, iso_datetime: str) -> None:
        # Decompiled ThermoCycler.SetTimeConfiguration: SetConfiguration
        # (configLevel=1, password=None) with a DateTime-typed parameter.
        # The help file specifies the format 'YYYY-MM-DDTHH:MM:SSZ'.
        self._configure(
            f'<ParameterSet><Parameter parameterType="DateTime" name="SysDateTime">'
            f'<DateTime>{iso_datetime}</DateTime></Parameter></ParameterSet>'
        )

    def download_logs(self, dest_dir: str, include_traces: bool) -> list[dict[str, Any]]:
        # Not a SiLA command: the unit serves its logs over anonymous FTP.
        roots = ODTC_LOG_FOLDERS + ((ODTC_TRACE_FOLDER,) if include_traces else ())
        return _ftp_download_tree(self._device_ip, roots, dest_dir)

    def download_run_trace(self, dest_dir: str, method_name: str | None) -> dict[str, Any] | None:
        return _ftp_download_latest_trace(self._device_ip, dest_dir, method_name)

    def add_allowed_return_code(self, code: int) -> None:
        # Decompiled ThermoCycler.AddAllowedReturnCode: purely client-side
        # bookkeeping, no device call at all -- see _DEFAULT_ALLOWED_CODES
        # and _invoke().
        self._allowed_codes.add(code)

    def lock(self, lock_id: str, timeout: int) -> None:
        pass

    def unlock(self) -> None:
        pass  # never locked; see class docstring

    def terminate(self) -> None:
        self._client = None

    def close(self) -> None:
        pass  # nothing held that needs releasing; see class docstring


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class ODTCManager:
    """Owns up to :data:`MAX_DEVICES` per-unit transports and their hidden locks.

    One instance per client. ``device_id`` values are the lowest free slot
    ``1..MAX_DEVICES``, matching the vendor HSL's own ``_GetFreeDeviceNumber``.
    Unlike :class:`~hamilton_venus.heater_cooler.HeaterCoolerManager` (one
    transport for a whole daisy chain), each ``device_id`` here owns its own
    independent transport instance -- see the module docstring.
    """

    def __init__(self, *, simulate: bool = False, transport_factory: object | None = None) -> None:
        self.lock = threading.RLock()
        self._simulate = simulate
        self._transport_factory = transport_factory
        self._by_id: dict[int, _ODTCTransport] = {}
        self._last_request_id: dict[int, str] = {}

    def _make_transport(self, device_id: int) -> _ODTCTransport:
        if self._transport_factory is not None:
            return cast(_ODTCTransport, self._transport_factory(device_id))  # type: ignore[operator]
        if self._simulate:
            return _SimODTCTransport(device_id)
        return _SoapODTCTransport()  # pragma: no cover - needs real hardware

    def _next_free_slot(self) -> int:
        for candidate in range(1, MAX_DEVICES + 1):
            if candidate not in self._by_id:
                return candidate
        raise ODTCError(f"no free ODTC device slot (max {MAX_DEVICES} connected)")

    def connect(
        self, device_ip: str, *, device_port: str = "8080", local_ip: str = "", initialize: bool = True
    ) -> int:
        with self.lock:
            device_id = self._next_free_slot()
            transport = self._make_transport(device_id)
            try:
                transport.connect(device_ip, device_port, local_ip, self._simulate)
                if initialize:
                    transport.initialize()
            except Exception:
                close = getattr(transport, "close", None)
                if callable(close):
                    close()
                raise
            self._by_id[device_id] = transport
            return device_id

    def resolve(self, device_id: int | None) -> list[tuple[int, _ODTCTransport]]:
        """``[(device_id, transport), ...]`` for one unit or, when *device_id*
        is None, all connected units."""
        if not self._by_id:
            raise ODTCError("no ODTC connected; call odtc_connect first")
        if device_id is None:
            return list(self._by_id.items())
        return [(device_id, self.transport_for(device_id))]

    def transport_for(self, device_id: int) -> _ODTCTransport:
        try:
            return self._by_id[device_id]
        except KeyError:
            raise ODTCError(
                f"no ODTC registered with device_id {device_id}; call odtc_connect first"
            ) from None

    def device_ids(self) -> list[int]:
        return list(self._by_id)

    def note_request_id(self, device_id: int, request_id: str) -> None:
        self._last_request_id[device_id] = request_id

    def last_request_id(self, device_id: int) -> str | None:
        return self._last_request_id.get(device_id)

    def terminate_one(self, device_id: int) -> None:
        with self.lock:
            transport = self._by_id.pop(device_id, None)
            self._last_request_id.pop(device_id, None)
            if transport is None:
                return
            try:
                transport.unlock()
                transport.terminate()
            finally:
                close = getattr(transport, "close", None)
                if callable(close):
                    close()

    def terminate(self) -> None:
        with self.lock:
            for device_id in list(self._by_id):
                self.terminate_one(device_id)

    def __del__(self) -> None:  # best-effort release
        with contextlib.suppress(Exception):
            self.terminate()


# --------------------------------------------------------------------------- #
# Install-time setup                                                          #
# --------------------------------------------------------------------------- #

#: Best guess by analogy with HHC's ProgramData log tree; the ODTC's own
#: ``Inheco ODTC Interface.dll.config`` has no NLog/log4net section, so this
#: grant is likely a no-op -- shipped anyway since it is harmless.
_ODTC_DATA_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "Hamilton", "Drivers", "Venus", "Inheco ODTC",
)


def grant_odtc_data_access() -> tuple[bool, str]:
    """Give BUILTIN\\Users modify access to the vendor driver's ProgramData tree
    (see :data:`_ODTC_DATA_DIR`). Needs admin. Returns ``(ok, message)``; never raises."""
    return _com32.grant_data_access(_ODTC_DATA_DIR)


def configure_odtc() -> tuple[bool, str]:
    """Install-time setup (run by ``setup-venus-sdk``), mirroring
    :func:`hamilton_venus.heater_cooler.configure_heater_cooler`. Never raises."""
    if sys.platform != "win32":
        return True, "not Windows; nothing to configure"
    if not _odtc_driver_installed():
        return True, "Inheco ODTC driver not installed; nothing to configure"
    grant_ok, grant_msg = grant_odtc_data_access()
    return grant_ok, f"ProgramData ACL: {grant_msg}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="hamilton-odtc")
    parser.add_argument("--diagnose", action="store_true", help="print the COM reachability diagnosis")
    parser.add_argument(
        "--selftest", action="store_true", help="try to create the COM object (no device I/O)"
    )
    parser.add_argument(
        "--configure", action="store_true", help="install-time setup: grant ProgramData log access (admin)"
    )
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="grant Users write access to the vendor driver's ProgramData tree (admin)",
    )
    args = parser.parse_args(argv)

    if args.configure:
        ok, msg = configure_odtc()
        print(msg)
        return 0 if ok else 1
    if args.fix_permissions:
        ok, msg = grant_odtc_data_access()
        print(msg)
        return 0 if ok else 1
    if args.selftest:
        transport = _ComODTCTransport()
        try:
            backend = transport._select_backend()
        except Exception as exc:
            print("selftest FAILED:", exc)
            return 1
        finally:
            transport.close()
        print(f"selftest OK: created {_PROGID} via {type(backend).__name__}")
        return 0

    print("64-bit Python:  ", _IS_64BIT)
    print("driver:         ", "installed" if _odtc_driver_installed() else "NOT installed")
    print("available:      ", odtc_available())
    print("diagnosis:      ", odtc_com_diagnosis())
    print("vendor files:   ", _odtc_bin_report())
    py32 = find_python32()
    print("32-bit Python:  ", py32 or "(none found -- run setup-venus-sdk --install-py32)")
    return 0


__all__ = [
    "MAX_DEVICES",
    "ODTCError",
    "ODTCManager",
    "configure_odtc",
    "find_python32",
    "grant_odtc_data_access",
    "main",
    "odtc_available",
    "odtc_com_diagnosis",
]


if __name__ == "__main__":
    raise SystemExit(main())
