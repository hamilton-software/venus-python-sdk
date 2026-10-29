"""Pure-Python driver for the Hamilton Heater Cooler (HHC).

Unlike every other peripheral in the SDK, the HHC does **not** go through the
VENUS runtime. It is a PC-connected device (Hamilton USB comm -> virtual COM),
independently addressable, so this module talks to it directly -- the same way
:mod:`hamilton_venus.taught_locations` is plain local I/O with no
``venus.send_command``.

The public surface is :class:`~hamilton_venus.devices.heater_cooler_commands.HeaterCoolerDeviceCommands`
(the ``hhc_*`` methods mixed into ``StarClient`` / ``VantageClient``). This module
holds the stateful bits underneath: a pluggable transport, the
``device_id <-> serial-number`` registry, and the temperature-band helper.

Transports
----------
``_ComHeaterCoolerTransport``
    Reuses the vendor COM object ``HamiltonHeaterCoolerCOM.HamiltonHeaterCoolerHSLCOM``
    (the one the vendor HSL library wraps). It is a **32-bit** .NET COM server, so:

    * on 32-bit Python it is created in-process;
    * on 64-bit Python the SDK runs :mod:`hamilton_venus._com32_worker` under a
      **32-bit Python** and proxies each call over a JSON pipe. The SDK bundles a
      private 32-bit Python at ``hamilton_venus/_com32_py32/python.exe`` (shared
      with every other 32-bit-COM driver in the SDK -- see
      :mod:`hamilton_venus._com32`); ``HAMILTON_HHC_PYTHON32`` or the ``py -3-32``
      launcher override it.

    (The DllSurrogate route was removed -- a non-elevated ``dllhost.exe`` cannot
    bind ``HamiltonHeaterCoolerCOM.dll``'s dependencies, so it never worked for
    unattended scripts.)
``_SimHeaterCoolerTransport``
    In-memory model of one or more units. Enforces the 0-110 degC clamp, ramps a
    current temperature toward the target so :meth:`wait_for_temp` converges, and
    returns plausible firmware / verification / serial values. Selected whenever
    ``simulate=True`` or no COM path is reachable, so the SDK imports and runs
    everywhere.

``hamilton-hhc`` (``python -m hamilton_venus.heater_cooler``) prints the
reachability diagnosis (``--diagnose``), tries a real activation (``--selftest``),
and applies the install-time setup (``--configure`` / ``--fix-permissions``).
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
from typing import Any, Protocol, cast

from hamilton_venus import _com32
from hamilton_venus.exceptions import HeaterCoolerError

logger = logging.getLogger(__name__)

_PROGID = "HamiltonHeaterCoolerCOM.HamiltonHeaterCoolerHSLCOM"
_FORCE_ENABLE_ENV = "HAMILTON_HHC_FORCE_ENABLE"

#: Where the vendor drops HamiltonHeaterCoolerCOM.dll and its native/interop deps.
_HHC_BIN_DIR = r"C:\Program Files (x86)\Hamilton\Bin\Hamilton HeaterCooler"
_HHC_KEY_FILES = (
    "HamiltonHeaterCoolerCOM.dll",
    "Hamilton.Components.TransportLayer.ComLink.dll",
    "Hamilton.Components.TransportLayer.Protocols.dll",
    "Hamilton.Module.HamiltonHeaterCooler.dll",
    "Interop.HXUSBCOMMLib.dll",
)
#: The SDK ships a private 32-bit CPython here (shared by every 32-bit-COM driver).
_BUNDLED_PY32 = _com32._BUNDLED_PY32
#: Runtime installed by ``setup-venus-sdk --install-py32`` (a module-level alias so
#: tests can monkeypatch it, like the other discovery seams).
_shared_python32_exe = _com32.shared_python32_exe

_IS_64BIT = sys.maxsize > 2**32


def _hhc_driver_installed() -> bool:
    """Whether the vendor Heater Cooler driver DLLs are on disk."""
    return os.path.isfile(os.path.join(_HHC_BIN_DIR, "HamiltonHeaterCoolerCOM.dll"))


def _hhc_bin_report() -> str:
    """One line: which of the vendor's key files are present in the Bin folder."""
    if not os.path.isdir(_HHC_BIN_DIR):
        return f"vendor Bin folder not found: {_HHC_BIN_DIR}"
    missing = [f for f in _HHC_KEY_FILES if not os.path.isfile(os.path.join(_HHC_BIN_DIR, f))]
    if missing:
        return f"missing from {_HHC_BIN_DIR}: {', '.join(missing)}"
    return f"all key vendor files present in {_HHC_BIN_DIR}"


#: Hard temperature limits for the device (degrees Celsius).
TEMP_MIN_C = 0.0
TEMP_MAX_C = 110.0
#: Smallest tolerance band accepted by ``hhc_start_temp_control``.
MIN_TOLERANCE_C = 0.1

_TRUTHY = {"1", "true", "yes", "on"}


def _force_enabled() -> bool:
    return os.environ.get(_FORCE_ENABLE_ENV, "").strip().lower() in _TRUTHY


def heater_cooler_available() -> bool:
    """Whether the vendor Heater Cooler COM driver is usable **from this process**.

    ``True`` when ``HAMILTON_HHC_FORCE_ENABLE`` is set, or when the vendor driver
    is installed *and* there is a way to reach its 32-bit COM object: this
    interpreter is 32-bit, or a 32-bit Python (bundled / discovered) is available
    for the worker bridge. Otherwise ``False`` and the driver falls back to
    simulation instead of failing at ``hhc_connect``. Never raises.
    """
    if _force_enabled():
        return True
    if sys.platform != "win32" or not _hhc_driver_installed():
        return False
    if not _IS_64BIT:
        return True
    return find_python32() is not None


def heater_cooler_com_diagnosis() -> str:
    """A human-readable one-liner on why the vendor COM transport is / isn't usable."""
    if sys.platform != "win32":
        return "not Windows: the vendor HeaterCooler COM transport is unavailable."
    if not _hhc_driver_installed():
        return f"Hamilton HeaterCooler driver not installed ({_hhc_bin_report()})."
    if not _IS_64BIT:
        return "HamiltonHeaterCoolerCOM is reachable in-process (32-bit Python)."
    py32 = find_python32()
    if py32:
        via = "bundled" if os.path.normcase(py32) == os.path.normcase(_BUNDLED_PY32) else py32
        return f"HamiltonHeaterCoolerCOM is 32-bit; bridging through 32-bit Python ({via})."
    return (
        "HamiltonHeaterCoolerCOM is 32-bit and this Python is 64-bit, with no 32-bit "
        "Python for the worker bridge. Run `setup-venus-sdk --install-py32`, install a "
        "32-bit Python, set HAMILTON_HHC_PYTHON32, or use simulate=True."
    )


def validate_band(target: float, tolerance: float) -> tuple[float, float, float]:
    """Return ``(low, high, target)`` for a temperature setpoint.

    *target* must be within ``[0, 110]`` degC or :class:`ValueError` is raised.
    *tolerance* must be >= :data:`MIN_TOLERANCE_C`. The band is clamped into the
    device limits, so a target near an extreme still yields a valid window.
    """
    if not TEMP_MIN_C <= target <= TEMP_MAX_C:
        raise ValueError(
            f"target temperature {target} degC is outside the HeaterCooler range "
            f"[{TEMP_MIN_C}, {TEMP_MAX_C}] degC"
        )
    if tolerance < MIN_TOLERANCE_C:
        raise ValueError(f"tolerance must be >= {MIN_TOLERANCE_C} degC, got {tolerance}")
    low = max(TEMP_MIN_C, target - tolerance)
    high = min(TEMP_MAX_C, target + tolerance)
    return low, high, target


class _HeaterCoolerTransport(Protocol):
    """One method per vendor operation, keyed by device serial number."""

    def connect(self, address: str, keep_alive: int) -> tuple[int, list[str]]: ...
    def disconnect(self, chain_id: int) -> None: ...
    def get_firmware(self, serial: str) -> str: ...
    def get_temperature(self, serial: str) -> float: ...
    def get_temp_time_remaining(self, serial: str) -> str: ...
    def set_temperature(
        self, serial: str, low: float, high: float, target: float, wait: bool, timeout: int
    ) -> None: ...
    def set_temp_for_time(
        self, serial: str, low: float, high: float, target: float, minutes: float
    ) -> None: ...
    def wait_for_temp(self, serial: str, timeout: float) -> None: ...
    def stop_temp_control(self, serial: str) -> None: ...
    def get_verification_date(self, serial: str) -> str: ...
    def set_verification_date(self, serial: str, date: str) -> None: ...
    def identify(self, serial: str) -> None: ...
    def get_self_diagnostic(self, serial: str) -> bool: ...
    def set_self_diagnostic(self, serial: str, enable: bool) -> None: ...
    def set_display_brightness(self, serial: str, percentage: int) -> None: ...
    def turn_on_off_display(self, serial: str, on: bool) -> None: ...


# --------------------------------------------------------------------------- #
# Simulation transport                                                         #
# --------------------------------------------------------------------------- #


class _SimUnit:
    __slots__ = (
        "brightness",
        "controlling",
        "current",
        "display_on",
        "firmware_version",
        "high",
        "low",
        "self_diagnostic",
        "serial",
        "target",
        "verification_date",
    )

    def __init__(self, index: int) -> None:
        self.serial = f"HC-SIM-{index:03d}"
        self.firmware_version = "1.0S 2020-07-22"
        self.verification_date = "2026-01-15"
        self.target = 25.0
        self.current = 25.0
        self.low = 24.5
        self.high = 25.5
        self.controlling = False
        self.self_diagnostic = False
        self.display_on = True
        self.brightness = 100

    def step(self) -> None:
        """Move *current* a fraction of the way toward *target* (no wall clock)."""
        if not self.controlling:
            return
        gap = self.target - self.current
        if abs(gap) <= 0.05:
            self.current = self.target
        else:
            self.current += gap * 0.5


class _SimHeaterCoolerTransport:
    """Deterministic in-memory HeaterCooler used for tests, demos and offline runs."""

    def __init__(self, units: int = 1) -> None:
        self._units: dict[str, _SimUnit] = {}
        self._order: list[str] = []
        self._count = max(1, units)
        self._connected = False

    # -- helpers --
    def _unit(self, serial: str) -> _SimUnit:
        try:
            return self._units[serial]
        except KeyError:
            raise HeaterCoolerError(f"unknown HeaterCooler serial {serial!r}") from None

    # -- transport surface --
    def connect(self, address: str, keep_alive: int) -> tuple[int, list[str]]:
        if not self._connected:
            self._units = {}
            self._order = []
            for i in range(1, self._count + 1):
                unit = _SimUnit(i)
                self._units[unit.serial] = unit
                self._order.append(unit.serial)
            self._connected = True
        return 1, list(self._order)

    def disconnect(self, chain_id: int) -> None:
        self._units = {}
        self._order = []
        self._connected = False

    def get_firmware(self, serial: str) -> str:
        return self._unit(serial).firmware_version

    def get_temperature(self, serial: str) -> float:
        unit = self._unit(serial)
        unit.step()
        return round(unit.current, 2)

    def get_temp_time_remaining(self, serial: str) -> str:
        unit = self._unit(serial)
        if not unit.controlling or abs(unit.current - unit.target) <= 0.05:
            return "00:00:00"
        return "00:05:00"

    def set_temperature(
        self, serial: str, low: float, high: float, target: float, wait: bool, timeout: int
    ) -> None:
        unit = self._unit(serial)
        unit.low, unit.high, unit.target = low, high, target
        unit.controlling = True
        if wait:
            self.wait_for_temp(serial, float(timeout))

    def set_temp_for_time(
        self, serial: str, low: float, high: float, target: float, minutes: float
    ) -> None:
        unit = self._unit(serial)
        unit.low, unit.high, unit.target = low, high, target
        unit.controlling = True

    def wait_for_temp(self, serial: str, timeout: float) -> None:
        unit = self._unit(serial)
        for _ in range(100):
            if unit.low <= unit.current <= unit.high:
                return
            unit.step()
        unit.current = unit.target

    def stop_temp_control(self, serial: str) -> None:
        self._unit(serial).controlling = False

    def get_verification_date(self, serial: str) -> str:
        return self._unit(serial).verification_date

    def set_verification_date(self, serial: str, date: str) -> None:
        self._unit(serial).verification_date = date

    def identify(self, serial: str) -> None:
        self._unit(serial)

    def get_self_diagnostic(self, serial: str) -> bool:
        return self._unit(serial).self_diagnostic

    def set_self_diagnostic(self, serial: str, enable: bool) -> None:
        self._unit(serial).self_diagnostic = enable

    def set_display_brightness(self, serial: str, percentage: int) -> None:
        self._unit(serial).brightness = percentage

    def turn_on_off_display(self, serial: str, on: bool) -> None:
        self._unit(serial).display_on = on


# --------------------------------------------------------------------------- #
# 32-bit Python discovery + subprocess bridge                                  #
# --------------------------------------------------------------------------- #
#
# HHC-specific discovery is kept local (rather than delegated to
# hamilton_venus._com32.find_python32) because several unit tests monkeypatch
# its individual steps (_BUNDLED_PY32, _is_python_32bit, _IS_64BIT) directly --
# see tests/unit/test_heater_cooler.py::TestPython32Discovery. The generic
# version in _com32 is what new drivers (e.g. ODTC) use; this ~15-line
# duplicate is the deliberate cost of not disturbing those seams.

_PY32_ENV = "HAMILTON_HHC_PYTHON32"

_is_python_32bit = _com32._is_python_32bit


def find_python32() -> str | None:
    """Locate a 32-bit Python that can host the HeaterCooler COM worker.

    Order: ``HAMILTON_HHC_PYTHON32`` env var, the SDK's bundled
    ``hamilton_venus/_com32_py32/python.exe``, the runtime installed by
    ``setup-venus-sdk --install-py32`` under
    ``%PROGRAMDATA%\\Hamilton\\VenusSDK\\py32``, this interpreter if it is
    already 32-bit, the ``py`` launcher's ``-3-32`` targets, then the per-user
    ``%LOCALAPPDATA%\\Programs\\Python\\Python3*-32`` installs. Returns the
    executable path, or ``None``.
    """
    if sys.platform != "win32":
        return None
    override = os.environ.get(_PY32_ENV, "").strip().strip('"')
    if override:
        return override if _is_python_32bit(override) else None
    if os.path.isfile(_BUNDLED_PY32):  # our own artifact -- trust it, skip the probe
        return _BUNDLED_PY32
    if os.path.isfile(_shared_python32_exe()):  # setup-venus-sdk artifact -- trust it, skip the probe
        return _shared_python32_exe()
    if not _IS_64BIT:
        return sys.executable

    import shutil
    import subprocess

    launcher = shutil.which("py")
    if launcher:
        for tag in ("-3-32", "-3.13-32", "-3.12-32", "-3.11-32", "-3.10-32"):
            try:
                out = subprocess.run(
                    [launcher, tag, "-c", "import sys;print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            exe = out.stdout.strip()
            if out.returncode == 0 and exe and _is_python_32bit(exe):
                return exe

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        base = os.path.join(local, "Programs", "Python")
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                if name.lower().startswith("python3") and name.endswith("-32"):
                    exe = os.path.join(base, name, "python.exe")
                    if os.path.isfile(exe) and _is_python_32bit(exe):
                        return exe
    return None


class _Bridge32Backend(_com32.Bridge32Backend):
    """Runs ``hamilton_venus._com32_worker`` (ProgID=HamiltonHeaterCoolerCOM...)
    under a 32-bit Python and proxies calls."""

    def __init__(self, python32: str) -> None:
        super().__init__(
            python32,
            _PROGID,
            bin_dirs=[_HHC_BIN_DIR],
            tl_bin_dir=_HHC_BIN_DIR,
            error_cls=HeaterCoolerError,
        )


# --------------------------------------------------------------------------- #
# COM-interop transport                                                        #
# --------------------------------------------------------------------------- #


def _candidate_backends() -> list[object]:
    """The backend to use for creating the vendor COM object: in-process on
    32-bit Python, otherwise the 32-bit worker bridge."""
    if not _IS_64BIT:
        return [
            _com32.InProcBackend32(
                _PROGID, bin_dirs=[_HHC_BIN_DIR], error_cls=HeaterCoolerError, diagnosis=heater_cooler_com_diagnosis()
            )
        ]
    py32 = find_python32()
    if py32 is not None:
        return [_Bridge32Backend(py32)]
    return [
        _com32.InProcBackend32(
            _PROGID, bin_dirs=[_HHC_BIN_DIR], error_cls=HeaterCoolerError, diagnosis=heater_cooler_com_diagnosis()
        )
    ]  # will raise the diagnosis on first use


class _ComHeaterCoolerTransport:
    """Drives the vendor ``HamiltonHeaterCoolerCOM`` object.

    Chooses a backend lazily on first call: in-process (32-bit Python), else a
    32-bit subprocess worker (:mod:`hamilton_venus._com32_worker`). Output
    ``variable&`` parameters come back appended to the return value;
    :meth:`_call` normalises that and treats a non-zero leading return code as
    a failure.
    """

    def __init__(self, backend: object | None = None) -> None:
        self._backend: object | None = backend
        self._candidates: list[object] = [] if backend is not None else _candidate_backends()

    @staticmethod
    def _split(result: object) -> tuple[int, list[Any]]:
        if isinstance(result, (tuple, list)):
            code = int(result[0]) if result else 0
            return code, list(result[1:])
        return int(cast(Any, result)), []

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
                logger.info("HeaterCooler: using %s", type(candidate).__name__)
                return candidate
            except Exception as exc:
                errors.append(f"{type(candidate).__name__}: {exc}")
        raise HeaterCoolerError(
            f"could not create {_PROGID!r}. {heater_cooler_com_diagnosis()}"
            + ("  Tried -- " + "; ".join(errors) if errors else "")
        )

    def _call(self, name: str, *args: object) -> list[Any]:
        backend = self._select_backend()
        try:
            raw = backend.raw_call(name, *args)  # type: ignore[attr-defined]
        except HeaterCoolerError:
            raise
        except Exception as exc:
            raise HeaterCoolerError(f"HeaterCooler {name} raised: {exc}") from exc
        code, outputs = self._split(raw)
        if code != 0:
            raise HeaterCoolerError(f"HeaterCooler {name} failed with return code {code}")
        return outputs

    def close(self) -> None:
        seen = {self._backend, *self._candidates}
        seen.discard(None)
        for backend in seen:
            close = getattr(backend, "close", None)
            if callable(close):
                close()

    def connect(self, address: str, keep_alive: int) -> tuple[int, list[str]]:
        outputs = self._call("Connect", address, keep_alive, 0, [])
        chain_id = int(outputs[0]) if outputs else 0
        serials = [str(s) for s in outputs[1]] if len(outputs) > 1 and outputs[1] else []
        return chain_id, serials

    def disconnect(self, chain_id: int) -> None:
        self._call("Disconnect", chain_id)

    def get_firmware(self, serial: str) -> str:
        outputs = self._call("GetFirmware", serial, "")
        return str(outputs[0]) if outputs else ""

    def get_temperature(self, serial: str) -> float:
        outputs = self._call("GetTemperature", serial, 0.0)
        return float(outputs[0]) if outputs else 0.0

    def get_temp_time_remaining(self, serial: str) -> str:
        outputs = self._call("GetTempTimeRemaining", serial, "")
        return str(outputs[0]) if outputs else ""

    def set_temperature(
        self, serial: str, low: float, high: float, target: float, wait: bool, timeout: int
    ) -> None:
        self._call("SetTemperature", serial, low, high, target, wait, timeout)

    def set_temp_for_time(
        self, serial: str, low: float, high: float, target: float, minutes: float
    ) -> None:
        self._call("SetTempForTime", serial, low, high, target, minutes)

    def wait_for_temp(self, serial: str, timeout: float) -> None:
        self._call("WaitForTempComplete", serial, timeout)

    def stop_temp_control(self, serial: str) -> None:
        self._call("StopTemperatureControl", serial)

    def get_verification_date(self, serial: str) -> str:
        outputs = self._call("GetVerificationDate", serial, "")
        return str(outputs[0]) if outputs else ""

    def set_verification_date(self, serial: str, date: str) -> None:
        self._call("SetVerificationDate", serial, date)

    def identify(self, serial: str) -> None:
        self._call("Identify", serial)

    def get_self_diagnostic(self, serial: str) -> bool:
        outputs = self._call("GetSelfDiagnostic", serial, 0)
        return bool(outputs[0]) if outputs else False

    def set_self_diagnostic(self, serial: str, enable: bool) -> None:
        self._call("SetSelfDiagnostic", serial, 1 if enable else 0)

    def set_display_brightness(self, serial: str, percentage: int) -> None:
        self._call("SetDisplayBrightness", serial, percentage)

    def turn_on_off_display(self, serial: str, on: bool) -> None:
        self._call("TurnOnOffDisplay", serial, on)


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class HeaterCoolerManager:
    """Owns the transport, the ``device_id <-> serial`` registry and a lock.

    One instance per client. ``device_id`` values are assigned ``1..N`` in the
    order the daisy chain reports serial numbers, mirroring the HHS convention.
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport: _HeaterCoolerTransport | None = None,
        sim_units: int = 1,
    ) -> None:
        self.lock = threading.RLock()
        self._chain_id: int | None = None
        self._by_id: dict[int, str] = {}
        self._controlling: set[str] = set()
        if transport is not None:
            self._transport: _HeaterCoolerTransport = transport
        elif simulate:
            self._transport = _SimHeaterCoolerTransport(units=sim_units)
        elif not heater_cooler_available():
            self._transport = _SimHeaterCoolerTransport(units=sim_units)
            if sys.platform == "win32":
                logger.warning(
                    "HeaterCooler: using the simulation transport. %s",
                    heater_cooler_com_diagnosis(),
                )
        else:  # pragma: no cover - needs the vendor driver
            self._transport = _ComHeaterCoolerTransport()

    # -- registry --
    @property
    def connected(self) -> bool:
        return self._chain_id is not None

    @property
    def chain_id(self) -> int:
        return self._chain_id or 0

    def serial_for(self, device_id: int) -> str:
        try:
            return self._by_id[device_id]
        except KeyError:
            raise HeaterCoolerError(
                f"no HeaterCooler registered with device_id {device_id}; call hhc_connect first"
            ) from None

    def resolve(self, device_id: int | None) -> list[tuple[int, str]]:
        """``[(device_id, serial), ...]`` for one unit or, when *device_id* is None, all."""
        if not self._by_id:
            raise HeaterCoolerError("no HeaterCooler connected; call hhc_connect first")
        if device_id is None:
            return list(self._by_id.items())
        return [(device_id, self.serial_for(device_id))]

    def devices(self) -> list[tuple[int, str]]:
        return list(self._by_id.items())

    # -- lifecycle --
    def connect(self, address: str, keep_alive: int) -> list[int]:
        with self.lock:
            chain_id, serials = self._transport.connect(address, keep_alive)
            if not serials:
                raise HeaterCoolerError(
                    f"HeaterCooler connect on {address!r} reported no units"
                )
            self._chain_id = chain_id
            self._by_id = {i: sn for i, sn in enumerate(serials, start=1)}
            self._controlling = set()
            return list(self._by_id)

    def terminate(self) -> None:
        with self.lock:
            if self._chain_id is not None:
                try:
                    self._transport.disconnect(self._chain_id)
                finally:
                    self._chain_id = None
                    self._by_id = {}
                    self._controlling = set()
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()

    # -- pass-throughs used by the command group (call under self.lock) --
    @property
    def transport(self) -> _HeaterCoolerTransport:
        return self._transport

    def mark_controlling(self, serial: str, on: bool) -> None:
        if on:
            self._controlling.add(serial)
        else:
            self._controlling.discard(serial)

    def is_controlling(self, serial: str) -> bool:
        return serial in self._controlling

    def __del__(self) -> None:  # best-effort release
        with contextlib.suppress(Exception):
            self.terminate()


#: The vendor driver + its NLog target write here (see HamiltonHeaterCoolerCOM_NLog.config:
#: %CommonApplicationData%\Hamilton\Drivers\Venus\Hamilton HeaterCooler\Logs). A standard
#: user cannot write files an elevated run created there, so a non-elevated activation of
#: the (debug-built, throw-on-log-error) COM object fails. Granting Users modify fixes it.
_HHC_DATA_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "Hamilton", "Drivers", "Venus", "Hamilton HeaterCooler",
)


def grant_heater_cooler_data_access() -> tuple[bool, str]:
    """Give BUILTIN\\Users modify access to the vendor driver's ProgramData tree
    so scripts can activate the COM object **without elevation**. Needs admin.
    Returns ``(ok, message)``; never raises.
    """
    return _com32.grant_data_access(_HHC_DATA_DIR)


# HamiltonHeaterCoolerCOM.dll is built against an older Hamilton.Components.TransportLayer.*
# than the one shipped in the Bin folder, and its .dll.config redirect does not
# cover the newer build -> the CLR fails to bind it (HRESULT 0x80070002). The
# fix is a <bindingRedirect> in the 32-bit worker's python.exe.config -- see
# hamilton_venus._com32.
_dll_file_version = _com32.dll_file_version


def _transport_layer_redirects() -> dict[str, str]:
    return _com32.transport_layer_redirects(_HHC_BIN_DIR)


_merge_binding_redirects = _com32.merge_binding_redirects


def write_py32_binding_config(python32: str) -> tuple[bool, str]:
    """Write ``<python32>.exe.config`` with the TransportLayer binding redirects
    the worker needs (versions read from the on-disk vendor DLLs). ``(ok, msg)``."""
    return _com32.write_py32_binding_config(python32, _HHC_BIN_DIR)


def configure_heater_cooler() -> tuple[bool, str]:
    """Install-time setup (run elevated by ``setup-venus-sdk``):

    1. write the binding-redirect ``.config`` next to the bundled / discovered
       32-bit Python so the worker can bind ``HamiltonHeaterCoolerCOM.dll``;
    2. grant ``Users`` write access to the vendor driver's ProgramData log tree
       so non-elevated scripts can activate the device.

    Never raises; returns ``(ok, message)`` where *ok* is True if at least the
    ProgramData grant (or the whole run on a driver-less box) succeeded.
    """
    if sys.platform != "win32":
        return True, "not Windows; nothing to configure"
    if not _hhc_driver_installed():
        return True, "Hamilton HeaterCooler driver not installed; nothing to configure"

    parts: list[str] = []
    py32 = find_python32()
    if py32:
        _ok, msg = write_py32_binding_config(py32)
        parts.append(f"py32 config: {msg}")
    else:
        parts.append("py32 config: skipped (no 32-bit Python found)")

    grant_ok, grant_msg = grant_heater_cooler_data_access()
    parts.append(f"ProgramData ACL: {grant_msg}")
    return grant_ok, "; ".join(parts)


def _hhc_data_access_report() -> str:
    if sys.platform != "win32":
        return "n/a"
    logs = os.path.join(_HHC_DATA_DIR, "Logs")
    if not os.path.isdir(_HHC_DATA_DIR):
        return f"{_HHC_DATA_DIR} does not exist yet"
    probe = os.path.join(logs, ".hhc-write-probe")
    try:
        os.makedirs(logs, exist_ok=True)
        with open(probe, "w") as fh:
            fh.write("")
        os.remove(probe)
        return f"writable: {logs}"
    except OSError:
        return f"NOT writable without elevation: {logs} -- run 'hamilton-hhc --fix-permissions' (admin)"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="hamilton-hhc")
    parser.add_argument("--diagnose", action="store_true", help="print the COM reachability diagnosis")
    parser.add_argument(
        "--selftest", action="store_true", help="try to create the COM object (no device I/O)"
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="install-time setup: write the 32-bit-Python binding config and grant "
        "ProgramData log access (admin)",
    )
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="grant Users write access to the vendor driver's ProgramData tree (admin)",
    )
    args = parser.parse_args(argv)

    if args.configure:
        ok, msg = configure_heater_cooler()
        print(msg)
        return 0 if ok else 1
    if args.fix_permissions:
        ok, msg = grant_heater_cooler_data_access()
        print(msg)
        return 0 if ok else 1
    if args.selftest:
        transport = _ComHeaterCoolerTransport()
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
    print("driver:         ", "installed" if _hhc_driver_installed() else "NOT installed")
    print("available:      ", heater_cooler_available())
    print("diagnosis:      ", heater_cooler_com_diagnosis())
    print("vendor files:   ", _hhc_bin_report())
    print("data dir:       ", _hhc_data_access_report())
    py32 = find_python32()
    print("32-bit Python:  ", py32 or "(none found -- run setup-venus-sdk --install-py32)")
    return 0


__all__ = [
    "MIN_TOLERANCE_C",
    "TEMP_MAX_C",
    "TEMP_MIN_C",
    "HeaterCoolerError",
    "HeaterCoolerManager",
    "configure_heater_cooler",
    "find_python32",
    "grant_heater_cooler_data_access",
    "heater_cooler_available",
    "heater_cooler_com_diagnosis",
    "main",
    "validate_band",
    "write_py32_binding_config",
]


if __name__ == "__main__":
    raise SystemExit(main())
