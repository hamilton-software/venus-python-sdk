"""Pure-Python driver for the Hamilton Media Fill Module.

Like the Heater Cooler and ODTC drivers, this does **not** go through the VENUS
runtime. The module is PC-connected (a USB virtual COM port) and is driven by
its own vendor COM object. Two vendor libraries exist, and the driver uses
whichever is registered (the 2.0 library when both are):

* **2.0** (``HxMediaFill`` 2.0.8767 MSI): ``HxMediaFill.HxMediaFillCOM``
  (``Bin/Hamilton Media Fill/HxMediaFillCOM.dll``, .NET 4), wrapped by the HSL
  library ``HxMediaFill.hsl``.
* **1.1** (``HSLHamiltonMediaFillModule``): ``Hamilton.HxMediaFillModule``
  (``HxMediaFill.dll`` 1.1, .NET 2.0), wrapped by ``HSLHamiltonMediaFillModule.hsl`` / ``.hs_``.

``HAMILTON_MEDIA_FILL_PROGID`` picks one explicitly. The two differ in a few calls
(details below and in :class:`_ComMediaFillTransport`): pump out is
``EmptyLineToSource`` in 2.0 and ``WastePumpNoSensor`` in 1.1 (the same
behaviour), only 2.0 has ``StopPump``, only 1.1 has ``GetFirmwareVersion`` (with
2.0 the firmware comes from the module's own serial query before connecting),
and 2.0's instrument id is the COM port number.

The public surface is :class:`~hamilton_venus.devices.media_fill_commands.MediaFillClient`
(the ``media_fill_*`` methods, one per function of the vendor HSL library).
This module holds the stateful bits underneath: a pluggable transport and the
``device_id -> vendor instrument id`` registry.

Addressing
----------
One vendor COM object serves every module (the HSL keeps a single
``HxMediaFillModule`` object): ``Initialize(comPortNumber, simulation,
&instrumentId)`` opens one module per COM port and returns an instrument id. So
the manager owns **one** transport and maps SDK ``device_id`` values (``1..N``,
lowest free id first) to those instrument ids. Each module has pumps ``1..4``,
each with its own liquid level sensor.

Vendor semantics (vendor help ``HSLHamiltonMediaFillModuleEnu.chm``, confirmed
against the vendor COM server ``HxMediaFill.dll`` itself)
-----------------------------------------------------------------------------
* ``FillTrough`` starts a pump **asynchronously** and returns; the pump runs
  until its liquid level sensor triggers or ``timeout`` (seconds) elapses.
  ``speed`` is a relative rate, 30-100 (%). ``WaitForPump`` blocks until it
  stops (it has no timeout of its own). A fill on a trough whose sensor already
  reads liquid succeeds without pumping (the vendor's last error then reads
  ``"SENSOR ON"``).
* ``WastePumpNoSensor`` (1.1) / ``EmptyLineToSource`` (2.0) (firmware command
  ``EmptyWithoutUsingLiquidSensor``) starts a pump the same way but **ignores the liquid level sensor**: it runs
  until ``timeout`` elapses (or ``Disconnect``). It turns the **reverse** of the
  direction set with ``SetPumpDirection`` (verified on a real module, firmware
  ``V1.00 94821-01 A``, 2026-10-15: with the fill direction set it pulls liquid
  from the trough back toward the bottle; with the other direction set it pumps
  *into* the trough with no sensor stop) and leaves the stored direction as it
  was. Same pump/speed checks as ``FillTrough``; no ``"SENSOR ON"``
  short-circuit. The vendor HSL header dropped it in 2018 (its ``.hs_`` still
  defines it). The 1.1 vendor object checks no timeout range; Hamilton's limit for any
  pumping operation is 720 s (Installation Guide 95149-01/B s4.2.1). The 2.0 library's
  ``MaxTimeoutForBackflow`` is 20 s (:data:`PUMP_OUT_MAX_SECONDS_V2`).
* ``StopPump`` (2.0 only) stops one pump; ``WaitForPump`` in 2.0 returns an error
  once its default timeout of 1 minute passes (1.1 blocks until the pump stops).
* Pump direction is counter-clockwise (0) at the start of each run unless set
  to clockwise (1) with ``SetPumpDirection``.
* ``GetLiquidLevelSensorState``: 0 = liquid not detected; 1 = liquid detected,
  **or** the sensor is unplugged, **or** the controller is powered down.
* ``Disconnect`` stops every active pump on that module.
* Every call returns 0 on success, 1 on failure; ``GetLastErrorMessage`` says why.

The vendor COM object (not the HSL, not the device) rejects out-of-range values:
COM port 1-65535, pump 1-4, speed 30-100, direction 0/1, each with its own
message. The command layer here adds no checks of its own -- values go to the
vendor object unchanged and its error comes back as :class:`MediaFillError`. The
simulation transport applies the same checks with the vendor's exact messages.

Hosting (from ``HxMediaFill.dll``'s own metadata)
------------------------------------------------
``HxMediaFill.dll`` is a 32-bit-only .NET 2.0/3.5 assembly that talks to the
module over ``System.IO.Ports`` -- no Hamilton TransportLayer, so the 32-bit
worker needs no binding redirects. VENUS runs it on .NET 4 (``HxRun.exe.config``:
``useLegacyV2RuntimeActivationPolicy``); ``setup-venus-sdk`` gives the SDK's
32-bit host the same setting, so .NET Framework 3.5 isn't needed. The assembly
isn't strong-named, so a process outside VENUS's ``Bin`` folder can only load it
if its COM registration carries a ``CodeBase`` (``regasm /codebase``);
``hamilton-media-fill --diagnose`` checks, and ``--register-codebase`` adds it.

Transports
----------
``_ComMediaFillTransport``
    Drives ``Hamilton.HxMediaFillModule`` through the shared 32-bit COM bridge
    (:mod:`hamilton_venus._com32`): in-process on 32-bit Python, otherwise via
    the SDK's bundled 32-bit Python worker.
``_SimMediaFillTransport``
    Deterministic in-memory model used whenever ``simulate=True`` or the vendor
    driver isn't reachable.

``hamilton-media-fill`` (``python -m hamilton_venus.media_fill``) prints the
reachability diagnosis (``--diagnose``), lists the COM ports with a Media Fill
USB id (``--list-ports``), reads a real module without moving anything
(``--probe COMn``), tries a real activation (``--selftest``) and applies
install-time setup (``--configure``).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Protocol, TypedDict, TypeVar

from hamilton_venus import _com32
from hamilton_venus.exceptions import MediaFillError
from hamilton_venus.models.enums import PumpDirection

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

#: This driver's version.
DRIVER_VERSION = "1.5.0"

#: The vendor COM objects the driver can use, preferred first: the 2.0 library
#: (``HxMediaFill`` 2.0.8767 MSI) and the 1.1 library (``HSLHamiltonMediaFillModule``).
PROGID_V2 = "HxMediaFill.HxMediaFillCOM"
PROGID_V1 = "Hamilton.HxMediaFillModule"
_VENDOR_APIS = {PROGID_V2: "2.0", PROGID_V1: "1.1"}
#: Pick one vendor COM object explicitly (one of the ProgIDs above).
_PROGID_ENV = "HAMILTON_MEDIA_FILL_PROGID"
#: 2.0 ``Device.ConstantValues.MaxTimeoutForBackflow``: the longest ``EmptyLineToSource`` (pump out).
PUMP_OUT_MAX_SECONDS_V2 = 20
#: 2.0 ``Device.ReturnCode`` names (0 = ``Succeeds``).
RETURN_CODES_V2 = {1: "BadParameter", 2: "DeviceError", 3: "ConnectionError", 4: "GeneralError"}
_FORCE_ENABLE_ENV = "HAMILTON_MEDIA_FILL_FORCE_ENABLE"
_PY32_ENV = "HAMILTON_MEDIA_FILL_PYTHON32"
#: Optional override for the folder holding the vendor COM DLL (normally read
#: from the ProgID's registration).
_BIN_DIR_ENV = "HAMILTON_MEDIA_FILL_BIN_DIR"

_BUNDLED_PY32 = _com32._BUNDLED_PY32  # shared across every 32-bit-COM driver
_IS_64BIT = sys.maxsize > 2**32
_TRUTHY = {"1", "true", "yes", "on"}
_DLL_NAME = "HxMediaFill.dll"
#: The ``<startup>`` setting VENUS's own ``HxRun.exe.config`` uses to host .NET 2.0
#: COM servers such as this one on .NET 4; the installer puts it in the 32-bit host's config.
LEGACY_V2_ACTIVATION = "useLegacyV2RuntimeActivationPolicy"

#: Ranges the vendor COM object checks (``HxMediaFill.dll``); used by the simulator.
PUMP_IDS = range(1, 5)
SPEED_MIN_PERCENT = 30
SPEED_MAX_PERCENT = 100
COM_PORT_MAX = 65535

#: Vendor messages, verbatim from ``HxMediaFill.dll`` (typo included) -- the
#: simulator raises these too, and the manager recognises the "gone" ones.
VENDOR_NO_ERROR = "No error."
VENDOR_SENSOR_ON = "SENSOR ON"
VENDOR_UNKNOWN_INSTRUMENT = "Error, provided DeviceID does not correspond to an existing instrument."
VENDOR_BAD_PUMP = (
    "Error, PumpID variable is out of range of accepted values, PumpID variable must be between 1 and 4 inclusive."
)
VENDOR_BAD_SPEED = (
    "Error, Speeed variable is out of range of accepted values, Speed variable must be between 30 and 100 inclusive."
)
#: ``WastePumpNoSensor`` has its own wording (full stops, no typo).
VENDOR_BAD_SPEED_NO_SENSOR = (
    "Error. Speed variable is out of range of accepted values. Speed variable must be between 30 and 100 inclusive."
)
VENDOR_BAD_DIRECTION = (
    "Error, Direction variable is out of range of accepted values, Direction variable must be between 0 and 1 "
    "inclusive."
)
VENDOR_BAD_COM_PORT = (
    "Error, COMPort variable is out of range of accepted values, COMPort variable must be between 1 and 65535 "
    "inclusive."
)
VENDOR_PORT_IN_USE = (
    "Error, unable to connect to instrument on COM{0}; an instrument under COM{0} is already being controlled by HSL."
)
#: The vendor object drops a module whose port closed ("Instrument (...) lost connection
#: ... Initialize must be called to regain control of the instrument.") ...
_VENDOR_LOST = "lost connection with the following error message"
#: ... and a new vendor object (a restarted worker) knows none of the earlier ones.
_VENDOR_UNKNOWN = "does not correspond to an existing instrument"
#: 2.0: this instrument isn't connected in the vendor object (its id is its COM port, so
#: the message is about this one module only).
_VENDOR_NOT_CONNECTED_V2 = "is not in the collection of connected Media Fill devices"
#: Both libraries' wording for a COM port outside their range (1-65535 in 1.1, 1-256 in 2.0).
_VENDOR_BAD_COM_PORT_TEXT = "COMPort variable is out of range"


# --------------------------------------------------------------------------- #
# Vendor-driver discovery                                                      #
# --------------------------------------------------------------------------- #


def _force_enabled() -> bool:
    return os.environ.get(_FORCE_ENABLE_ENV, "").strip().lower() in _TRUTHY


def _progid() -> str:
    """The vendor COM object to use: ``HAMILTON_MEDIA_FILL_PROGID`` if set, else the
    first registered of :data:`PROGID_V2`, :data:`PROGID_V1` (:data:`PROGID_V2` when
    neither is). Never raises."""
    override = os.environ.get(_PROGID_ENV, "").strip()
    if override:
        return override
    return next((p for p in _VENDOR_APIS if _registration_for(p) is not None), PROGID_V2)


def vendor_api(progid: str | None = None) -> str:
    """``"2.0"`` or ``"1.1"``: which vendor library *progid* (default: the one in use) belongs to."""
    return _VENDOR_APIS.get(progid or _progid(), "unknown")


def _registration() -> dict[str, str] | None:
    """How the vendor object in use (:func:`_progid`) is registered; see :func:`_registration_for`."""
    return _registration_for(_progid())


def _registration_for(progid: str) -> dict[str, str] | None:
    """How *progid* is registered in the **32-bit** registry view, or
    ``None`` if it isn't. Never raises.

    The vendor object is a .NET class exposed to COM (the vendor help lists it
    as ``System.Object -> Hamilton.HxMediaFillModule``), so ``InprocServer32``'s
    default value is ``mscoree.dll`` and the assembly is named by ``Assembly``
    and, when registered with ``/codebase``, located by ``CodeBase``.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return None
    view = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0)
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\CLSID", 0, view) as key:
            clsid = str(winreg.QueryValueEx(key, "")[0])
        info: dict[str, str] = {"clsid": clsid}
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32", 0, view) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                info[name.lower() or "server"] = str(value)
                index += 1
    except OSError:
        return None
    return info


def _codebase_path(codebase: str) -> str:
    """``file:///C:/Program Files (x86)/.../X.dll`` (a .NET ``CodeBase``) -> a file path."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    parsed = urlparse(codebase)
    if parsed.scheme.lower() != "file":
        return codebase
    path = f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
    return os.path.normpath(url2pathname(path))


def _registered_dll() -> str | None:
    """Path of the registered vendor DLL (its ``CodeBase``), a description when the
    registration doesn't say where it is, or ``None`` when the ProgID isn't registered."""
    info = _registration()
    if info is None:
        return None
    codebase = info.get("codebase", "")
    if codebase:
        return _codebase_path(codebase)
    server = info.get("server", "")
    if server and os.path.basename(server).lower() != "mscoree.dll":
        return server
    return f"(registered without a CodeBase; .NET assembly {info.get('assembly', '?')!r})"


def _codebase_problem(info: dict[str, str] | None = None) -> str | None:
    """Why the 32-bit worker can't load the vendor assembly, or ``None``.

    ``HxMediaFill.dll`` isn't strong-named, so without a ``CodeBase`` in its COM
    registration the CLR only finds it next to the host process's .exe -- true for
    VENUS (``HxRun.exe`` lives in the same ``Bin`` folder), not for the SDK's worker."""
    info = _registration() if info is None else info
    if not info or info.get("codebase") or os.path.basename(info.get("server", "")).lower() != "mscoree.dll":
        return None
    if "publickeytoken=null" not in info.get("assembly", "").replace(" ", "").lower():
        return None  # strong-named: the CLR can resolve it from the GAC
    return (
        f"{_progid()} is registered without a CodeBase, so only processes started from the vendor's own "
        f"folder (VENUS) can load {_DLL_NAME}. Run 'python -m hamilton_venus.media_fill --register-codebase' "
        f"as Administrator (it runs regasm /codebase)."
    )


def _vendor_dll() -> str | None:
    """Where ``HxMediaFill.dll`` is on disk: its registered ``CodeBase``, the
    ``HAMILTON_MEDIA_FILL_BIN_DIR`` folder, or VENUS's ``Bin`` folder."""
    override = os.environ.get(_BIN_DIR_ENV, "").strip().strip('"')
    candidates = [os.path.join(override, _DLL_NAME)] if override else []
    dll = _registered_dll()
    if dll and os.path.isabs(dll):
        candidates.append(dll)
    for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", "")):
        if base:
            candidates.append(os.path.join(base, "Hamilton", "Bin", _DLL_NAME))
    return next((c for c in candidates if os.path.isfile(c)), None)


def _vendor_bin_dir() -> str | None:
    override = os.environ.get(_BIN_DIR_ENV, "").strip().strip('"')
    if override:
        return override
    dll = _registered_dll()
    if dll and os.path.isabs(dll):
        return os.path.dirname(dll)
    return None


def _driver_installed() -> bool:
    """Whether a vendor Media Fill COM server (2.0 or 1.1) is registered."""
    return _registration() is not None


def find_python32() -> str | None:
    """A 32-bit Python able to host the vendor COM worker (see
    :func:`hamilton_venus._com32.find_python32`)."""
    return _com32.find_python32(_PY32_ENV)


def host_config_path(python32: str | None) -> str | None:
    """The ``<python32>.exe.config`` the CLR reads when that host loads the vendor object."""
    return f"{python32}.config" if python32 else None


def _host_runs_v2_on_clr4(python32: str | None) -> bool:
    """Whether *python32*'s ``.exe.config`` hosts .NET 2.0 COM servers on .NET 4 (like VENUS)."""
    cfg = host_config_path(python32)
    try:
        with open(cfg, encoding="utf-8", errors="replace") as fh:  # type: ignore[arg-type]
            return LEGACY_V2_ACTIVATION in fh.read()
    except (OSError, TypeError):
        return False


def _net35_installed() -> bool | None:
    """Whether .NET Framework 3.5 (CLR 2.0) is installed; ``None`` if unknown."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5") as key:
            return int(winreg.QueryValueEx(key, "Install")[0]) == 1
    except OSError:
        return False
    except Exception:
        return None


def _runtime_problem(python32: str | None) -> str | None:
    """Why the CLR can't host the (.NET 2.0) vendor object in *python32*, or ``None``."""
    info = _registration()
    if not info or not info.get("runtimeversion", "").startswith("v2."):
        return None
    if _host_runs_v2_on_clr4(python32) or _net35_installed() is not False:
        return None
    return (
        f"{_DLL_NAME} is a .NET 2.0/3.5 component and neither .NET Framework 3.5 is installed nor does "
        f"{host_config_path(python32) or 'the 32-bit host config'} run it on .NET 4 (as VENUS does). "
        f"Run 'hamilton-media-fill --configure' (or setup-venus-sdk), or turn on .NET Framework 3.5 "
        f"in Windows Features."
    )


def media_fill_available() -> bool:
    """Whether the vendor Media Fill COM driver is usable **from this process**.

    ``True`` when ``HAMILTON_MEDIA_FILL_FORCE_ENABLE`` is set, or when the vendor
    driver is registered *and* its 32-bit COM object is reachable (this
    interpreter is 32-bit, or a 32-bit Python exists for the worker bridge).
    Otherwise ``False`` and the driver falls back to simulation. Never raises.
    """
    try:
        if _force_enabled():
            return True
        if sys.platform != "win32" or not _driver_installed():
            return False
        if not _IS_64BIT:
            return True
        return find_python32() is not None
    except Exception:
        return False


def media_fill_com_diagnosis() -> str:
    """A human-readable one-liner on why the vendor COM transport is / isn't usable."""
    if sys.platform != "win32":
        return "not Windows: the vendor Media Fill COM transport is unavailable."
    dll = _registered_dll()
    if dll is None:
        return (
            f"Hamilton Media Fill Module driver not installed (neither {PROGID_V2} nor {PROGID_V1} is "
            "registered); install the Hamilton Media Fill Module library."
        )
    problem = _codebase_problem()
    if problem:
        return problem
    if not _IS_64BIT:  # in-process: the CLR reads the config of the interpreter actually running
        runtime = _runtime_problem(getattr(sys, "_base_executable", None) or sys.executable)
        return runtime or f"{_progid()} ({vendor_api()}) is reachable in-process (32-bit Python); registered: {dll}"
    py32 = find_python32()
    if py32:
        runtime = _runtime_problem(py32)
        if runtime:
            return runtime
        via = "bundled" if os.path.normcase(py32) == os.path.normcase(_BUNDLED_PY32) else py32
        return f"{_progid()} ({vendor_api()}) is 32-bit; bridging through 32-bit Python ({via}); registered: {dll}"
    return (
        f"{_progid()} is 32-bit and this Python is 64-bit, with no 32-bit Python for the "
        f"worker bridge. Reinstall the SDK (it bundles one), install a 32-bit Python, "
        f"set {_PY32_ENV}, or use simulate=True."
    )


def parse_com_port(com_port: int | str) -> int:
    """``5``, ``"5"`` or ``"COM5"`` -> ``5`` (the vendor ``Initialize`` takes the port number)."""
    if isinstance(com_port, bool):
        raise ValueError(f"invalid COM port {com_port!r}")
    if isinstance(com_port, int):
        number = com_port
    else:
        text = str(com_port).strip().upper()
        if text.startswith("COM"):
            text = text[3:]
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"invalid COM port {com_port!r}; expected e.g. 5 or 'COM5'") from None
    if number < 1:
        raise ValueError(f"invalid COM port {com_port!r}; must be >= 1")
    return number


def direction_value(direction: PumpDirection | int | str) -> int:
    """The vendor ``direction`` value to send: a :class:`PumpDirection`, an int (passed
    on unchanged, like every other value -- the vendor object rejects anything but
    0/1), or a string: ``"0"``/``"1"`` or a name (``"counter_clockwise"``,
    ``"clockwise"``, ``"ccw"``, ``"cw"``)."""
    if isinstance(direction, bool):
        raise ValueError(f"invalid pump direction {direction!r}")
    if isinstance(direction, int):  # includes PumpDirection; the vendor object rejects anything but 0/1
        return int(direction)
    if isinstance(direction, float) and direction.is_integer():
        return int(direction)
    if isinstance(direction, str):
        text = direction.strip()
        try:
            return int(text)
        except ValueError:
            pass
        key = text.upper().replace("-", "_").replace(" ", "_")
        key = {"CW": "CLOCKWISE", "CCW": "COUNTER_CLOCKWISE", "COUNTERCLOCKWISE": "COUNTER_CLOCKWISE"}.get(key, key)
        if key in PumpDirection.__members__:
            return int(PumpDirection[key])
    raise ValueError(
        f"invalid pump direction {direction!r}; expected PumpDirection, 0 (counter-clockwise) or 1 (clockwise)"
    )


def direction_name(value: int) -> str:
    """``"counter_clockwise"`` / ``"clockwise"`` for the vendor values, else ``"unknown(<value>)"``."""
    try:
        return PumpDirection(value).name.lower()
    except ValueError:
        return f"unknown({value})"


# --------------------------------------------------------------------------- #
# Transport protocol                                                           #
# --------------------------------------------------------------------------- #


class _MediaFillTransport(Protocol):
    """One method per vendor COM operation the HSL library uses (names as
    called in ``HSLHamiltonMediaFillModule.hs_``; ``AbortAll`` is only used by
    its abort handler, and here only as the fallback when a disconnect fails;
    ``WastePumpNoSensor`` is defined in the ``.hs_`` but no longer declared in its header)."""

    def initialize(self, com_port: int) -> int: ...
    def disconnect(self, instrument_id: int) -> None: ...
    def get_firmware_version(self, instrument_id: int) -> str: ...
    def get_pump_direction(self, instrument_id: int, pump_id: int) -> int: ...
    def set_pump_direction(self, instrument_id: int, pump_id: int, direction: int) -> None: ...
    def get_liquid_level_sensor_state(self, instrument_id: int, pump_id: int) -> int: ...
    def fill_trough(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None: ...
    def waste_pump_no_sensor(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None: ...
    def wait_for_pump(self, instrument_id: int, pump_id: int) -> None: ...
    def stop_pump(self, instrument_id: int, pump_id: int) -> None: ...
    def get_last_error_message(self) -> str: ...
    def abort_all(self) -> None: ...


# --------------------------------------------------------------------------- #
# Simulation transport                                                         #
# --------------------------------------------------------------------------- #


class _SimPump:
    """One pump + its liquid level sensor. ``step()`` advances a running fill one
    tick (no wall clock): after a few ticks the sensor triggers and the pump stops.
    A sensor-less run (``WastePumpNoSensor``) just stops when its ticks run out --
    its timeout -- and leaves the sensor as it was."""

    FILL_TICKS = 3
    __slots__ = ("direction", "running", "sensor", "ticks_left", "uses_sensor")

    def __init__(self) -> None:
        self.direction = int(PumpDirection.COUNTER_CLOCKWISE)  # vendor default per run
        self.running = False
        self.sensor = 0
        self.ticks_left = 0
        self.uses_sensor = True

    def step(self, reaches_sensor: bool = True) -> None:
        if not self.running:
            return
        self.ticks_left -= 1
        if self.ticks_left <= 0:
            self.running = False  # sensor triggered -- or, if it never does, the timeout elapsed
            if self.uses_sensor and reaches_sensor:
                self.sensor = 1


class _SimMediaFillTransport:
    """Deterministic in-memory Media Fill Module(s). Checks what the vendor COM
    object checks (COM port 1-65535 and not already open, pump 1-4, speed
    30-100 %, direction 0/1), in the same order and with the vendor's exact
    messages, and fails the way it does -- :class:`MediaFillError`, with the text
    also available from :meth:`get_last_error_message` (which, like the vendor's,
    keeps the last error until the next one)."""

    FIRMWARE = "MFM-SIM 1.0"

    def __init__(self, *, fill_reaches_sensor: bool = True) -> None:
        #: False makes every fill run until its timeout without the sensor
        #: triggering -- for exercising a script's "timed out" branch.
        self.fill_reaches_sensor = fill_reaches_sensor
        self._ports: dict[int, int] = {}  # instrument_id -> COM port
        self._pumps: dict[tuple[int, int], _SimPump] = {}
        self._last_error = VENDOR_NO_ERROR

    def _fail(self, call: str, message: str) -> MediaFillError:
        self._last_error = message
        return MediaFillError(f"MediaFill {call} failed with return code 1: {message}", error_code=1)

    def _instrument(self, call: str, instrument_id: int) -> None:
        if instrument_id not in self._ports:
            raise self._fail(call, VENDOR_UNKNOWN_INSTRUMENT)

    def _pump(self, call: str, instrument_id: int, pump_id: int) -> _SimPump:
        self._instrument(call, instrument_id)
        if pump_id not in PUMP_IDS:
            raise self._fail(call, VENDOR_BAD_PUMP)
        return self._pumps.setdefault((instrument_id, pump_id), _SimPump())

    def initialize(self, com_port: int) -> int:
        if not 1 <= com_port <= COM_PORT_MAX:
            raise self._fail("Initialize", VENDOR_BAD_COM_PORT)
        if com_port in self._ports.values():
            raise self._fail("Initialize", VENDOR_PORT_IN_USE.format(com_port))
        instrument_id = next(i for i in range(1, len(self._ports) + 2) if i not in self._ports)  # lowest free
        self._ports[instrument_id] = com_port
        for pump_id in PUMP_IDS:  # a new run starts every pump counter-clockwise
            self._pumps[(instrument_id, pump_id)] = _SimPump()
        return instrument_id

    def disconnect(self, instrument_id: int) -> None:
        self._instrument("Disconnect", instrument_id)
        del self._ports[instrument_id]
        for key in [k for k in self._pumps if k[0] == instrument_id]:
            del self._pumps[key]  # stops any running pump

    def get_firmware_version(self, instrument_id: int) -> str:
        self._instrument("GetFirmwareVersion", instrument_id)
        return self.FIRMWARE

    def get_pump_direction(self, instrument_id: int, pump_id: int) -> int:
        return self._pump("GetPumpDirection", instrument_id, pump_id).direction

    def set_pump_direction(self, instrument_id: int, pump_id: int, direction: int) -> None:
        pump = self._pump("SetPumpDirection", instrument_id, pump_id)
        if direction not in (0, 1):
            raise self._fail("SetPumpDirection", VENDOR_BAD_DIRECTION)
        pump.direction = direction

    def get_liquid_level_sensor_state(self, instrument_id: int, pump_id: int) -> int:
        pump = self._pump("GetLiquidLevelSensorState", instrument_id, pump_id)
        pump.step(self.fill_reaches_sensor)
        return pump.sensor

    def fill_trough(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None:
        pump = self._pump("FillTrough", instrument_id, pump_id)
        if not SPEED_MIN_PERCENT <= speed <= SPEED_MAX_PERCENT:
            raise self._fail("FillTrough", VENDOR_BAD_SPEED)
        if pump.sensor == 1:  # sensor already reads liquid: the vendor reports success, pumps nothing
            pump.running = False
            self._last_error = VENDOR_SENSOR_ON
            return
        pump.running, pump.uses_sensor = True, True
        pump.ticks_left = _SimPump.FILL_TICKS

    def waste_pump_no_sensor(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None:
        pump = self._pump("WastePumpNoSensor", instrument_id, pump_id)
        if not SPEED_MIN_PERCENT <= speed <= SPEED_MAX_PERCENT:
            raise self._fail("WastePumpNoSensor", VENDOR_BAD_SPEED_NO_SENSOR)
        pump.running, pump.uses_sensor = True, False  # runs whatever the sensor reads
        pump.ticks_left = _SimPump.FILL_TICKS

    def wait_for_pump(self, instrument_id: int, pump_id: int) -> None:
        pump = self._pump("WaitForPump", instrument_id, pump_id)
        while pump.running:
            pump.step(self.fill_reaches_sensor)

    def stop_pump(self, instrument_id: int, pump_id: int) -> None:
        """Vendor 2.0 ``StopPump``: stops one pump (the simulator supports it for either library)."""
        self._pump("StopPump", instrument_id, pump_id).running = False

    def get_last_error_message(self) -> str:
        return self._last_error

    def abort_all(self) -> None:
        """Vendor ``AbortAll``: stops every pump and disconnects every instrument."""
        self._ports.clear()
        self._pumps.clear()

    def is_running(self, instrument_id: int, pump_id: int) -> bool:
        """Test helper -- not part of the vendor API."""
        return self._pump("is_running", instrument_id, pump_id).running


# --------------------------------------------------------------------------- #
# COM transport                                                                #
# --------------------------------------------------------------------------- #


def _candidate_backends(progid: str) -> list[object]:
    bin_dir = _vendor_bin_dir()
    return _com32.candidate_backends(
        progid=progid,
        bin_dirs=[bin_dir] if bin_dir else [],
        # Neither vendor DLL (HxMediaFill.dll, HxMediaFillCOM.dll) references
        # Hamilton's TransportLayer, so the shared 32-bit host must not be given
        # TransportLayer binding redirects on its behalf (VENUS's Bin folder holds
        # TransportLayer DLLs of its own, which a folder-based guess would pick up).
        tl_bin_dir=None,
        env_vars=(_PY32_ENV,),
        error_cls=MediaFillError,
        diagnosis=media_fill_com_diagnosis(),
    )


class _ComMediaFillTransport:
    """Drives the vendor COM object: ``HxMediaFill.HxMediaFillCOM`` (2.0) or
    ``Hamilton.HxMediaFillModule`` (1.1).

    ``variable&`` output parameters are passed as placeholders and come back
    appended to the return code; :meth:`_call` splits ``(returnCode, *outputs)``
    and, on a non-zero code, fetches ``GetLastErrorMessage`` for the error text
    -- the same thing the vendor HSL does after every failed call.

    Where the libraries differ:

    =========================  ==============================  =================================
    Operation                  1.1 (``HxMediaFillModule``)      2.0 (``HxMediaFillCOM``)
    =========================  ==============================  =================================
    pump out, no sensor        ``WastePumpNoSensor``            ``EmptyLineToSource``
    firmware version           ``GetFirmwareVersion``           serial query ``:11;`` at connect
    stop one pump              --                               ``StopPump``
    stop everything            ``AbortAll``                     ``Abort``
    instrument id              1, 2, ... (lowest free)          the COM port number
    =========================  ==============================  =================================
    """

    def __init__(self, backend: object | None = None, *, progid: str | None = None) -> None:
        self._backend: object | None = backend
        #: The vendor object in use. An injected *backend* speaks the 1.1 API unless *progid* says otherwise.
        self.progid = progid or (PROGID_V1 if backend is not None else _progid())
        #: ``"2.0"`` or ``"1.1"``.
        self.api = vendor_api(self.progid)
        self._candidates: list[object] = [] if backend is not None else _candidate_backends(self.progid)
        self._epoch = 0
        self._holder: object | None = None  # what currently holds the vendor object (see epoch())
        #: 2.0 has no GetFirmwareVersion: the firmware read by identify(), per COM port, and each instrument's port.
        self._firmware_by_port: dict[int, str] = {}
        self._port_by_instrument: dict[int, int] = {}

    @staticmethod
    def _split(result: object) -> tuple[int, list[object]]:
        if isinstance(result, (tuple, list)):
            code = int(result[0]) if result else 0
            return code, list(result[1:])
        return int(result or 0), []  # type: ignore[call-overload]

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
                logger.info("MediaFill: using %s", type(candidate).__name__)
                return candidate
            except Exception as exc:
                errors.append(f"{type(candidate).__name__}: {exc}")
        raise MediaFillError(
            f"could not create {self.progid!r}. {media_fill_com_diagnosis()}"
            + ("  Tried -- " + "; ".join(errors) if errors else "")
        )

    def _raw(self, name: str, *args: object) -> tuple[int, list[object]]:
        backend = self._select_backend()
        try:
            raw = backend.raw_call(name, *args)  # type: ignore[attr-defined]
        except MediaFillError:
            raise
        except Exception as exc:
            raise MediaFillError(f"MediaFill {name} raised: {exc}") from exc
        return self._split(raw)

    def _call(self, name: str, *args: object) -> list[object]:
        code, outputs = self._raw(name, *args)
        if code != 0:
            detail = self.get_last_error_message()
            label = f"{code} ({RETURN_CODES_V2[code]})" if self.api == "2.0" and code in RETURN_CODES_V2 else str(code)
            raise MediaFillError(
                f"MediaFill {name} failed with return code {label}" + (f": {detail}" if detail else ""),
                error_code=code,
            )
        return outputs

    @staticmethod
    def _out(name: str, outputs: list[object]) -> object:
        if not outputs:  # the bridge passed no output parameters back: don't make one up
            raise MediaFillError(f"MediaFill {name} returned no output value from the vendor COM object")
        return outputs[0]

    @staticmethod
    def _out_int(name: str, outputs: list[object]) -> int:
        return int(_ComMediaFillTransport._out(name, outputs))  # type: ignore[call-overload,no-any-return]

    def epoch(self) -> int:
        """Changes whenever the vendor object behind this transport is (or may be) a
        new one -- the SDK's 32-bit worker process holding it ended (crash, Ctrl+C,
        :meth:`close`) and the bridge starts another on the next call, or the
        in-process object was released. Instrument ids from before mean nothing to it."""
        backend = self._backend
        if backend is None:
            return self._epoch
        if hasattr(backend, "_proc"):  # _com32.Bridge32Backend: the worker process, while it runs
            proc = backend._proc
            try:
                holder = proc if proc is not None and proc.poll() is None else None
            except Exception:
                holder = None
        else:  # _com32.InProcBackend32 (or an injected backend)
            holder = getattr(backend, "_obj", backend)
        if holder is not self._holder:
            if self._holder is not None:
                self._epoch += 1
            self._holder = holder
        return self._epoch

    def close(self) -> None:
        seen = {self._backend, *self._candidates}
        seen.discard(None)
        for backend in seen:
            close = getattr(backend, "close", None)
            if callable(close):
                close()
        self._epoch += 1  # whatever comes next is a new vendor object
        self._holder = None

    def identify(self, com_port: int) -> str | None:
        """Before ``Initialize``: confirm a Media Fill Module is on *com_port* with the firmware query
        alone (:func:`raw_identify`) -- the vendor's ``Initialize`` has no identity check and writes the
        pump directions to whatever answers. Raises if it isn't one; ``None`` = not checked (an injected
        backend, or no pywin32)."""
        if (self._backend is not None and not self._candidates) or not raw_serial_available():
            return None
        firmware = raw_identify(com_port)
        self._firmware_by_port[com_port] = firmware
        return firmware

    def initialize(self, com_port: int) -> int:
        outputs = self._call("Initialize", com_port, 0, 0)  # simulation=0: real hardware
        instrument_id = self._out_int("Initialize", outputs)
        self._port_by_instrument[instrument_id] = com_port
        return instrument_id

    def disconnect(self, instrument_id: int) -> None:
        self._call("Disconnect", instrument_id)

    def get_firmware_version(self, instrument_id: int) -> str:
        if self.api == "2.0":
            # No GetFirmwareVersion in 2.0: check the instrument is still connected with a read-only
            # query, then report the firmware the module gave its serial query before connecting.
            self._call("GetPumpDirection", instrument_id, 1, 0)
            return self._firmware_by_port.get(self._port_by_instrument.get(instrument_id, -1), "")
        outputs = self._call("GetFirmwareVersion", instrument_id, "")
        return str(self._out("GetFirmwareVersion", outputs))

    def get_pump_direction(self, instrument_id: int, pump_id: int) -> int:
        outputs = self._call("GetPumpDirection", instrument_id, pump_id, 0)
        return self._out_int("GetPumpDirection", outputs)

    def set_pump_direction(self, instrument_id: int, pump_id: int, direction: int) -> None:
        self._call("SetPumpDirection", instrument_id, pump_id, direction)

    def get_liquid_level_sensor_state(self, instrument_id: int, pump_id: int) -> int:
        outputs = self._call("GetLiquidLevelSensorState", instrument_id, pump_id, 0)
        return self._out_int("GetLiquidLevelSensorState", outputs)

    def fill_trough(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None:
        self._call("FillTrough", instrument_id, pump_id, speed, timeout)

    def waste_pump_no_sensor(self, instrument_id: int, pump_id: int, speed: int, timeout: int) -> None:
        name = "EmptyLineToSource" if self.api == "2.0" else "WastePumpNoSensor"
        self._call(name, instrument_id, pump_id, speed, timeout)

    def wait_for_pump(self, instrument_id: int, pump_id: int) -> None:
        self._call("WaitForPump", instrument_id, pump_id)

    def stop_pump(self, instrument_id: int, pump_id: int) -> None:
        if self.api != "2.0":
            raise MediaFillError(
                f"StopPump needs the Media Fill 2.0 library ({PROGID_V2}); the 1.1 library in use "
                f"({self.progid}) has none -- media_fill_disconnect stops every pump on the module"
            )
        self._call("StopPump", instrument_id, pump_id)

    def get_last_error_message(self) -> str:
        try:
            code, outputs = self._raw("GetLastErrorMessage", "")
        except MediaFillError:
            return ""
        return str(outputs[0]) if code == 0 and outputs else ""

    def abort_all(self) -> None:
        self._raw("Abort" if self.api == "2.0" else "AbortAll")  # void in the vendor API: no return code to check


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class MediaFillManager:
    """Owns the transport, the ``device_id -> (com_port, instrument_id)`` registry
    and a lock. One instance per client; ``device_id`` is the lowest free id
    ``1..N`` (reused after a disconnect).

    Instrument ids belong to one vendor object. The SDK's 32-bit worker that holds it
    is started again on demand if it ends (it can crash when a USB-serial device is
    pulled, or catch a Ctrl+C), and a new vendor object hands out ids from 1 again.
    So a module registered with an earlier vendor object -- or one the vendor
    reports lost -- is *expired*: commands on it raise instead of reaching whichever
    module now has its old instrument id, and its ``device_id`` stays reserved for its
    COM port until that port is connected again (or it is disconnected / terminated).
    """

    def __init__(self, *, simulate: bool = False, transport: _MediaFillTransport | None = None) -> None:
        self.lock = threading.RLock()
        #: device_id -> (com_port, instrument_id, transport epoch at connect)
        self._by_id: dict[int, tuple[int, int, int]] = {}
        #: device_id -> com_port of expired modules (reserved until reconnected or disconnected)
        self._expired: dict[int, int] = {}
        #: a failed connect left a port reserved in the vendor object (see connect())
        self._port_left_reserved = False
        if transport is not None:
            self._transport: _MediaFillTransport = transport
        elif simulate:
            self._transport = _SimMediaFillTransport()
        elif not media_fill_available():
            self._transport = _SimMediaFillTransport()
            if sys.platform == "win32":
                logger.warning("MediaFill: using the simulation transport. %s", media_fill_com_diagnosis())
        else:  # pragma: no cover - needs the vendor driver
            self._transport = _ComMediaFillTransport()

    @property
    def transport(self) -> _MediaFillTransport:
        return self._transport

    @property
    def simulated(self) -> bool:
        return isinstance(self._transport, _SimMediaFillTransport)

    # -- registry --------------------------------------------------------------

    def _epoch(self) -> int:
        epoch = getattr(self._transport, "epoch", None)
        return int(epoch()) if callable(epoch) else 0

    def _expire(self, device_ids: list[int], why: str) -> None:
        for device_id in device_ids:
            port, _inst, _epoch = self._by_id.pop(device_id)
            self._expired[device_id] = port
        if device_ids:
            logger.warning(
                "MediaFill: %s; device_id %s must be connected again", why, ", ".join(map(str, sorted(device_ids)))
            )

    def _expire_stale(self) -> None:
        """Expire every module registered with an earlier vendor object."""
        now = self._epoch()
        self._expire([d for d, (_p, _i, epoch) in self._by_id.items() if epoch != now], "the vendor driver restarted")

    def _after_failure(self, device_id: int, exc: Exception) -> None:
        """Bring the registry in line with the vendor object after a failed call on *device_id*."""
        self._expire_stale()  # the worker ended (and was restarted) during the call
        if device_id not in self._by_id:
            return
        text = str(exc)
        if _VENDOR_LOST in text or _VENDOR_NOT_CONNECTED_V2 in text:  # the vendor dropped this module
            self._expire([device_id], f"the vendor driver lost device_id {device_id}")
        elif _VENDOR_UNKNOWN in text:  # a vendor object that knows none of them
            self._expire(list(self._by_id), "the vendor driver no longer knows its modules")

    def _lookup(self, device_id: int) -> tuple[int, int, int]:
        self._expire_stale()
        if device_id in self._expired:
            port = self._expired[device_id]
            raise MediaFillError(
                f"device_id {device_id} (COM{port}) is no longer connected -- the vendor driver lost it or "
                f"restarted; call media_fill_connect('COM{port}') again"
            )
        try:
            return self._by_id[device_id]
        except KeyError:
            raise MediaFillError(
                f"no Media Fill module registered with device_id {device_id}; call media_fill_connect first"
            ) from None

    def devices(self) -> list[tuple[int, int, int]]:
        """``[(device_id, com_port, instrument_id), ...]`` of the connected modules."""
        with self.lock:
            self._expire_stale()
            return [(did, port, inst) for did, (port, inst, _epoch) in self._by_id.items()]

    def instrument_for(self, device_id: int) -> int:
        with self.lock:
            return self._lookup(device_id)[1]

    # -- lifecycle -------------------------------------------------------------

    def _release_vendor_object(self) -> None:
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()
        self._port_left_reserved = False

    def connect(self, com_port: int) -> tuple[int, int]:
        with self.lock:
            self._expire_stale()
            if self._port_left_reserved and not self._by_id:
                self._release_vendor_object()  # a fresh vendor object, without the stale reservation
            for did, (port, inst, _epoch) in list(self._by_id.items()):
                if port != com_port:
                    continue
                try:  # still there? (a vendor object that lost it says so)
                    self._transport.get_firmware_version(inst)
                except MediaFillError as exc:
                    self._after_failure(did, exc)
                if did in self._by_id:
                    raise MediaFillError(f"COM{com_port} is already connected as device_id {did}")
            try:
                instrument_id = self._transport.initialize(com_port)
            except MediaFillError as exc:
                if _VENDOR_BAD_COM_PORT_TEXT in str(exc):
                    raise  # rejected before the vendor object reserved anything
                # The vendor object reserves the port in a process-wide table before
                # opening it and doesn't release it when the open fails, so a retry
                # in the same process is refused ("already being controlled by HSL").
                # Closing the transport ends the vendor's process on the 32-bit worker
                # bridge (64-bit Python, the SDK's default), so the next connect starts
                # clean -- now if nothing else is connected, else once nothing is. (In-
                # process on 32-bit Python the reservation lasts until Python exits.)
                self._expire_stale()
                if not self._by_id:
                    self._release_vendor_object()
                    raise
                self._port_left_reserved = True
                raise MediaFillError(
                    f"{exc} (the vendor driver keeps COM{com_port} reserved after a failed connect while other "
                    f"modules are connected: disconnect them, or call media_fill_terminate(), then connect again)"
                ) from exc
            self._expire_stale()  # Initialize may have started a new worker
            if any(inst == instrument_id for _p, inst, _e in self._by_id.values()):
                # The vendor never hands out an id in use: every registered module
                # belongs to an earlier vendor object.
                self._expire(list(self._by_id), "the vendor driver restarted")
            device_id = next((did for did, port in self._expired.items() if port == com_port), None)
            if device_id is None:  # lowest id that is neither connected nor reserved
                taken = set(self._by_id) | set(self._expired)
                device_id = next(i for i in range(1, len(taken) + 2) if i not in taken)
            self._expired.pop(device_id, None)
            self._by_id[device_id] = (com_port, instrument_id, self._epoch())
            return device_id, instrument_id

    def call(self, device_id: int, operation: Callable[..., _T], *args: object) -> _T:
        """``operation(instrument_id, *args)`` for *device_id*. A module the vendor
        driver lost, or one connected before the vendor driver restarted, is expired
        (see the class docstring), so it can simply be connected again."""
        with self.lock:
            port, instrument_id, _epoch = self._lookup(device_id)
            try:
                return operation(instrument_id, *args)
            except MediaFillError as exc:
                self._after_failure(device_id, exc)
                if device_id in self._by_id:
                    raise
                raise MediaFillError(
                    f"{exc} (device_id {device_id} is no longer connected; "
                    f"call media_fill_connect('COM{port}') again)"
                ) from exc

    def disconnect(self, device_id: int) -> None:
        """Disconnect one module (the vendor driver stops its pumps). If the vendor
        call fails, the module stays registered, so :meth:`terminate` (and
        ``close()``) retries it and falls back to ``AbortAll``. A module the vendor
        driver no longer has (lost, or connected before it restarted) just leaves
        the registry."""
        with self.lock:
            self._expire_stale()
            if self._expired.pop(device_id, None) is not None:
                return  # nothing left of it in the vendor driver
            _port, instrument_id, _epoch = self._lookup(device_id)
            try:
                self._transport.disconnect(instrument_id)
            except MediaFillError as exc:
                self._after_failure(device_id, exc)
                if device_id in self._by_id:
                    raise
                logger.warning("MediaFill: device_id=%d was already disconnected (%s)", device_id, exc)
                self._expired.pop(device_id, None)
                return
            self._by_id.pop(device_id, None)

    def terminate(self) -> None:
        """Disconnect every module (the vendor driver stops their pumps) and release
        the vendor object. If any disconnect fails, falls back to the vendor
        ``AbortAll`` -- what the HSL library's own abort handler calls; a pump the
        vendor can't reach any more still stops at its sensor or its fill timeout."""
        with self.lock:
            errors: list[str] = []
            for device_id in list(self._by_id):
                try:
                    self.disconnect(device_id)
                except Exception as exc:
                    errors.append(f"device_id {device_id}: {exc}")
            if errors:
                try:
                    self._transport.abort_all()
                    errors.append("fell back to the vendor AbortAll")
                except Exception as exc:
                    errors.append(f"AbortAll also failed: {exc}")
                self._by_id = {}  # AbortAll disconnects every instrument; nothing left to retry
            self._expired.clear()
            self._release_vendor_object()
            if errors:
                raise MediaFillError("errors while disconnecting: " + "; ".join(errors))

    def __del__(self) -> None:  # best-effort release
        with contextlib.suppress(Exception):
            self.terminate()


# --------------------------------------------------------------------------- #
# Install-time setup + CLI                                                     #
# --------------------------------------------------------------------------- #


#: The block the driver adds to the 32-bit host's ``python.exe.config`` (``--configure`` /
#: ``setup-venus-sdk``); the marker comments identify it.
HOST_CONFIG_BLOCK = (
    "  <!-- >>> media-fill-driver -->\n"
    "  <!-- Run .NET 2.0 COM servers (HxMediaFill.dll) on .NET 4, as VENUS's HxRun.exe.config does. -->\n"
    '  <startup useLegacyV2RuntimeActivationPolicy="true">\n'
    '    <supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.0"/>\n'
    "  </startup>\n"
    "  <!-- <<< media-fill-driver -->\n"
)


def ensure_host_config(python32: str) -> tuple[bool, str]:
    """Give *python32*'s ``.exe.config`` VENUS's ``<startup>`` setting, so the CLR
    runs the .NET 2.0 vendor object on .NET 4 (no .NET 3.5 needed). Adds
    :data:`HOST_CONFIG_BLOCK` on the lines
    after ``<configuration>`` -- or after ``<configSections>``, which .NET requires
    to come first -- in the file's own line endings. Everything else in the file
    (other drivers' binding redirects) stays; a file with ``<startup>`` settings of
    its own, or one the edit wouldn't leave valid XML, is left alone. Never raises."""
    import re
    import xml.etree.ElementTree as ET

    cfg = host_config_path(python32) or ""
    text: str | None = None
    try:
        if os.path.isfile(cfg):
            # newline="": keep the file's own line endings (another driver may have written it)
            with open(cfg, encoding="utf-8", newline="") as fh:
                text = fh.read()
    except (OSError, ValueError) as exc:
        return False, f"could not read {cfg}: {exc}"
    if text is not None and LEGACY_V2_ACTIVATION in text:
        return True, f"{cfg} already runs .NET 2.0 COM servers on .NET 4"
    if text is not None and "<startup" in text:
        return False, f"{cfg} has <startup> settings of its own; left unchanged"
    if text is None:
        new = '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n' + HOST_CONFIG_BLOCK + "</configuration>\n"
    else:
        lines = re.findall(r"[^\n]*\n|[^\n]+$", text)
        crlf = sum(line.endswith("\r\n") for line in lines)
        eol = "\r\n" if crlf and crlf >= sum(line.endswith("\n") for line in lines) - crlf else "\n"
        anchor = None
        for pattern in (r"</configSections>|<configSections\b[^>]*/>", r"<configuration\b[^>]*>"):
            anchor = next((i for i, line in enumerate(lines) if re.search(pattern, line)), None)
            if anchor is not None:
                break
        if anchor is None:
            return False, f"{cfg} is not a .NET configuration file; left unchanged"
        if not lines[anchor].endswith("\n"):
            lines[anchor] += eol
        lines.insert(anchor + 1, HOST_CONFIG_BLOCK.replace("\n", eol))
        new = "".join(lines)
        try:
            ET.fromstring(new.encode("utf-8"))
        except ET.ParseError:
            return False, f"{cfg}: the <startup> setting can't be added to this file safely; left unchanged"
    tmp = cfg + ".media-fill-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
        os.replace(tmp, cfg)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return False, f"could not write {cfg}: {exc} (run as Administrator)"
    return True, f"{cfg}: runs .NET 2.0 COM servers on .NET 4 now"


def register_codebase() -> tuple[bool, str]:
    """Add a ``CodeBase`` to the vendor object's COM registration (``regasm
    /codebase``), so processes outside VENUS's ``Bin`` folder can load it. Needs
    Administrator. Never raises."""
    import subprocess

    if sys.platform != "win32":
        return False, "not Windows"
    info = _registration()
    if info is None:
        return False, f"{_progid()} is not registered; install the Hamilton Media Fill Module library first"
    if info.get("codebase"):
        return True, f"already registered with a CodeBase: {_codebase_path(info['codebase'])}"
    dll = _vendor_dll()
    if dll is None:
        return False, f"can't find {_DLL_NAME}; set {_BIN_DIR_ENV} to the folder that holds it"
    windir = os.environ.get("WINDIR", r"C:\Windows")
    # The 32-bit (Framework, not Framework64) RegAsm writes the 32-bit registration; the
    # .NET 4 one is always there and records the assembly's own runtime (v2.0.50727).
    regasms = [os.path.join(windir, "Microsoft.NET", "Framework", version, "RegAsm.exe")
               for version in ("v4.0.30319", "v2.0.50727")]
    regasm = next((r for r in regasms if os.path.isfile(r)), None)
    if regasm is None:
        return False, "RegAsm.exe (32-bit .NET Framework) not found"
    try:
        proc = subprocess.run([regasm, dll, "/codebase", "/nologo"], capture_output=True, text=True,
                              errors="replace", timeout=120, check=False)
    except Exception as exc:
        return False, f"RegAsm failed to run: {exc}"
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
        return False, f"RegAsm exit {proc.returncode}: {tail[0]} (run as Administrator)"
    if not (_registration() or {}).get("codebase"):
        return False, f"RegAsm ran, but {_progid()} still has no CodeBase in the 32-bit registry"
    return True, f"registered {dll} with /codebase"


def configure_media_fill() -> tuple[bool, str]:
    """Install-time setup (run by ``setup-venus-sdk`` and ``hamilton-media-fill --configure``).
    Never raises; ``(ok, message)``.

    * The vendor DLL references no Hamilton TransportLayer assembly, so -- unlike
      the HHC -- no binding redirects are written for it.
    * It is a .NET 2.0/3.5 assembly: the SDK's bundled 32-bit host gets VENUS's
      ``<startup useLegacyV2RuntimeActivationPolicy>`` setting (:func:`ensure_host_config`).
    * No ProgramData ACL grant: the vendor DLL has no ``.dll.config`` and logs
      nothing (errors go through ``GetLastErrorMessage``), so there's no log folder.
    * A registration without ``CodeBase`` is reported (see ``--register-codebase``),
      not changed -- that is the vendor's registration.
    """
    try:
        if sys.platform != "win32":
            return True, "not Windows; nothing to configure"
        messages: list[str] = []
        ok = True
        if os.path.isfile(_BUNDLED_PY32):
            host_ok, msg = ensure_host_config(_BUNDLED_PY32)
            ok &= host_ok
            messages.append(msg)
        if not _driver_installed():
            messages.append("no Media Fill COM object registered (install the Hamilton Media Fill Module library)")
        else:
            problem = _codebase_problem()
            if problem:
                ok = False
                messages.append(problem)
        return ok, "; ".join(messages) or "nothing to configure"
    except Exception as exc:
        return False, f"Media Fill configuration failed: {exc}"


# --------------------------------------------------------------------------- #
# Finding the module on USB                                                    #
# --------------------------------------------------------------------------- #

#: USB ids a Media Fill Module enumerates with. A real module (firmware ``V1.00 94821-01 A``)
#: reports 2341/0043 -- an Arduino Uno's id, so an actual Uno matches too; ``--probe`` tells them
#: apart. 16D0/0613 is the id in the vendor's ``Ruggeduino.inf``.
USB_IDS = ("VID_2341&PID_0043", "VID_16D0&PID_0613")
#: What a real module's firmware string contains (``Media Fill Module V1.00 94821-01 A``). The USB id
#: is shared with every Arduino Uno, so this is what proves a port is a Media Fill Module.
FIRMWARE_ID = "media fill module"


def is_media_fill_firmware(firmware: str) -> bool:
    """True if *firmware* (``GetFirmwareVersion``) identifies a Media Fill Module."""
    return FIRMWARE_ID in str(firmware).lower()


def _parse_pnp_ports(lines: str) -> list[tuple[str, str]]:
    """``"<DeviceID>\\t<Name>"`` lines (Win32_PnPEntity) -> sorted ``(COMn, description)`` for Media Fill
    USB ids. Identical modules share the USB id; the description adds each one's USB serial number (the
    last part of its device id), which stays with the unit and tells several modules apart."""
    found: dict[str, str] = {}
    for line in lines.splitlines():
        device_id, _, name = line.partition("\t")
        port = re.search(r"\((COM\d+)\)", name)
        if port and any(usb_id in device_id.upper() for usb_id in USB_IDS):
            serial = device_id.strip().rsplit("\\", 1)[-1]
            found[port.group(1).upper()] = f"{name.strip()}  serial {serial}"
    return sorted(found.items(), key=lambda item: int(item[0][3:]))


def find_media_fill_ports() -> list[tuple[str, str]]:
    """COM ports of USB devices with a Media Fill Module's USB id, as ``(COMn, device name)``.

    Windows only (WMI ``Win32_PnPEntity`` through PowerShell); elsewhere, or if the
    lookup fails, an empty list. Nothing is opened -- use ``--probe`` to talk to one.
    """
    return _usb_lookup() or []


def _usb_lookup() -> list[tuple[str, str]] | None:
    """:func:`find_media_fill_ports`, but ``None`` when the lookup itself couldn't run (not Windows,
    PowerShell/WMI failed) -- so a caller can tell "no module" from "couldn't look"."""
    if os.name != "nt":
        return None
    ps = "Get-CimInstance Win32_PnPEntity | ForEach-Object { \"$($_.DeviceID)`t$($_.Name)\" }"
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                              timeout=60, check=False)
    except Exception as exc:
        logger.warning("MediaFill: USB port lookup failed: %s", exc)
        return None
    if proc.returncode != 0 or not proc.stdout:
        logger.warning("MediaFill: USB port lookup failed: %s", (proc.stderr or "no output").strip()[:200])
        return None
    return _parse_pnp_ports(proc.stdout)


def check_usb_id(com_port: int | str) -> None:
    """Refuse -- without opening it -- a COM port whose USB device doesn't carry a Media Fill USB id
    (:data:`USB_IDS`): a Tilt Module's RS-232 adapter, a Bluetooth serial link, a camera, ... are never
    opened. If the USB lookup itself can't run, nothing is refused here (the firmware check still is)."""
    port = f"COM{parse_com_port(com_port)}"
    found = _usb_lookup()
    if found is not None and port not in {p for p, _ in found}:
        raise MediaFillError(
            f"{port} is not a Media Fill Module's USB device (USB id {' / '.join(USB_IDS)}); not opened. "
            f"Media Fill Modules found: {', '.join(p for p, _ in found) or 'none'}"
        )


# --------------------------------------------------------------------------- #
# Read-only raw serial queries (no vendor object)                              #
# --------------------------------------------------------------------------- #
#
# The module's own protocol, read from HxMediaFill.dll (``MediaFillModule.SendCommand`` /
# ``Hamilton.Commands``) and checked on a real module 2026-10-15: 9600 baud 8N1, no handshake,
# frames ``:<id>[,arg...];`` + LF out, ``:<status>[,field...];`` + CR/LF back, status 0 = OK.
# Only these four commands are pure queries; the others start or stop pumps (8, 9, 14, 15),
# write the directions (12), or are unknown (5 "Ready", 6 "Test"), and are never sent here.

QUERY_FIRMWARE = 11       #: ``:0,<firmware>;``
QUERY_SENSORS = 7         #: ``:0,<mask>;`` -- bit p-1 SET = pump p's sensor reads no liquid (inverted)
QUERY_PUMP_STATUS = 10    #: ``:0,<x>,<p1>,<p2>,<p3>,<p4>;`` -- 0 = stopped, else time until it stops
QUERY_DIRECTIONS = 13     #: ``:0,<d1>,<d2>,<d3>,<d4>;`` -- 0 counter-clockwise, 1 clockwise
READ_ONLY_COMMANDS = frozenset({QUERY_FIRMWARE, QUERY_SENSORS, QUERY_PUMP_STATUS, QUERY_DIRECTIONS})
SERIAL_BAUD = 9600


def raw_serial_available() -> bool:
    """True if raw serial queries can run here (Windows with pywin32 -- an SDK dependency)."""
    if os.name != "nt":
        return False
    try:
        import win32file  # noqa: F401
    except ImportError:
        return False
    return True


def raw_query(com_port: int | str, commands: list[int], timeout: float = 2.0) -> dict[int, list[str]]:
    """Send read-only *commands* to the module on *com_port* over its own serial protocol and return
    ``{command: [field, ...]}`` (the fields after a ``0`` status). Opens the port with DTR/RTS off and
    closes it again; the vendor object must not have the port open. Raises :class:`MediaFillError`
    if the port can't be opened, a reply is missing/malformed or its status isn't 0, and refuses any
    command outside :data:`READ_ONLY_COMMANDS`."""
    bad = [c for c in commands if c not in READ_ONLY_COMMANDS]
    if bad:
        raise ValueError(f"refusing non-query Media Fill command(s) {bad}; allowed: {sorted(READ_ONLY_COMMANDS)}")
    import pywintypes
    import win32file

    port = parse_com_port(com_port)
    try:
        handle = win32file.CreateFile(f"\\\\.\\COM{port}", win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                                      0, None, win32file.OPEN_EXISTING, 0, None)
    except pywintypes.error as exc:
        raise MediaFillError(f"COM{port} could not be opened ({exc.strerror}); is it in use?") from exc
    try:
        dcb = win32file.GetCommState(handle)  # type: ignore[arg-type]
        dcb.BaudRate, dcb.ByteSize, dcb.Parity, dcb.StopBits = (  # type: ignore[misc]
            SERIAL_BAUD,
            8,
            win32file.NOPARITY,
            win32file.ONESTOPBIT,
        )
        dcb.fBinary, dcb.fParity, dcb.fOutxCtsFlow, dcb.fOutxDsrFlow, dcb.fOutX, dcb.fInX = (  # type: ignore[misc]
            1,
            0,
            0,
            0,
            0,
            0,
        )
        dcb.fDtrControl = win32file.DTR_CONTROL_DISABLE  # type: ignore[misc]  # an Uno-type board resets on DTR
        dcb.fRtsControl = win32file.RTS_CONTROL_DISABLE  # type: ignore[misc]
        win32file.SetCommState(handle, dcb)  # type: ignore[arg-type]
        win32file.SetCommTimeouts(handle, (50, 0, 100, 0, int(timeout * 1000)))  # type: ignore[arg-type]
        win32file.PurgeComm(handle, win32file.PURGE_RXCLEAR | win32file.PURGE_TXCLEAR)  # type: ignore[arg-type]
        replies: dict[int, list[str]] = {}
        for command in commands:
            win32file.WriteFile(handle, f":{command};\n".encode("ascii"))  # type: ignore[arg-type]
            buf, deadline = b"", time.monotonic() + timeout
            while b";" not in buf and time.monotonic() < deadline:
                _, chunk = win32file.ReadFile(handle, 256)  # type: ignore[call-overload]
                buf += bytes(chunk)
            text = buf.decode("ascii", "replace").strip()
            if not (text.startswith(":") and ";" in text):
                raise MediaFillError(f"COM{port}: no Media Fill reply to :{command}; (got {text!r})")
            status, *fields = text[1:text.index(";")].split(",")
            if status != "0":
                raise MediaFillError(f"COM{port}: :{command}; answered status {status} {fields}")
            replies[command] = fields
        return replies
    finally:
        win32file.CloseHandle(handle)  # type: ignore[arg-type]


def raw_identify(com_port: int | str, timeout: float = 2.0, *, usb_checked: bool = False) -> str:
    """The firmware string of the Media Fill Module on *com_port*, read with the query ``:11;`` alone
    (nothing else is sent, so another device on the port is never told to do anything). A port without
    a Media Fill USB id is refused unopened (:func:`check_usb_id`; skipped when *usb_checked*). Raises
    :class:`MediaFillError` if the port doesn't answer like a Media Fill Module."""
    if not usb_checked:
        check_usb_id(com_port)
    fields = raw_query(com_port, [QUERY_FIRMWARE], timeout)[QUERY_FIRMWARE]
    firmware = ",".join(fields)
    if not is_media_fill_firmware(firmware):
        raise MediaFillError(f"COM{parse_com_port(com_port)} answered {firmware!r}, which is not a Media Fill Module")
    return firmware


class RawStatus(TypedDict):
    firmware: str
    is_media_fill_module: bool
    sensors: dict[int, int]
    pump_status: dict[int, int]
    pump_status_field0: int
    directions: dict[int, int]


def raw_status(com_port: int | str, timeout: float = 2.0) -> RawStatus:
    """Everything the module reports, read with the four query commands only (no vendor ``Initialize``,
    which would rewrite the directions): firmware, each pump's sensor state (0/1 as the vendor reports
    it), pump status (``0`` = stopped, else time until it stops -- the "is it running" query the vendor
    API doesn't offer) and direction."""
    check_usb_id(com_port)
    r = raw_query(com_port, [QUERY_FIRMWARE, QUERY_SENSORS, QUERY_PUMP_STATUS, QUERY_DIRECTIONS], timeout)
    firmware = ",".join(r[QUERY_FIRMWARE])
    mask = int(r[QUERY_SENSORS][0])
    status = [int(v) for v in r[QUERY_PUMP_STATUS]]
    directions = [int(v) for v in r[QUERY_DIRECTIONS]]
    return {
        "firmware": firmware,
        "is_media_fill_module": is_media_fill_firmware(firmware),
        "sensors": {p: 0 if mask & (1 << (p - 1)) else 1 for p in PUMP_IDS},  # the vendor's inverted reading
        "pump_status": {p: status[p] for p in PUMP_IDS},  # field 0 is undocumented; pumps follow
        "pump_status_field0": status[0],
        "directions": {p: directions[p - 1] for p in PUMP_IDS},
    }


def identify_media_fill_modules() -> list[tuple[str, str, str]]:
    """The Media Fill Modules on USB, confirmed by firmware: ``(COMn, description, firmware)``.

    Only ports with a Media Fill USB id (:func:`find_media_fill_ports`) are opened -- any other
    serial device (a Tilt Module's RS-232 adapter, ...) is never touched. Each candidate gets the
    firmware query ``:11;`` and nothing else (:func:`raw_identify`, 2 s); without pywin32 it is
    connected through the vendor object instead (whose ``Initialize`` also writes the pump
    directions, and can take minutes to give up on a port that doesn't answer). A candidate that
    isn't a Media Fill Module (e.g. an Arduino Uno, which shares the USB id) is left out.
    """
    from hamilton_venus.devices.media_fill_commands import MediaFillClient

    confirmed = []
    for port, description in find_media_fill_ports():
        try:
            if raw_serial_available():
                confirmed.append((port, description, raw_identify(port, usb_checked=True)))
                continue
            with MediaFillClient(simulate=False) as mfm:
                rp = mfm.media_fill_connect(port).return_parameters
                if not rp.simulated:
                    confirmed.append((port, description, rp.firmware_version))
        except Exception as exc:
            logger.info("MediaFill: %s is not a usable Media Fill Module: %s", port, exc)
    return confirmed


def probe(com_port: int | str) -> tuple[bool, str]:
    """Read-only check of a real module. With pywin32 (the SDK has it) only the four query
    commands are sent (:func:`raw_status`) -- no vendor ``Initialize``, which would rewrite the
    directions -- and the report includes each pump's running status. Otherwise: connect through
    the vendor object, :meth:`media_fill_get_status`, disconnect. Nothing moves either way.
    Returns ``(ok, report)``."""
    from hamilton_venus.devices.media_fill_commands import MediaFillClient

    port = parse_com_port(com_port)
    if raw_serial_available():
        try:
            st = raw_status(port)
        except Exception as exc:
            return False, f"probe FAILED on COM{port}: {exc}"
        if not st["is_media_fill_module"]:
            return False, f"probe FAILED: COM{port} answered firmware {st['firmware']!r}, not a Media Fill Module"
        pumps = ", ".join(
            f"P{p} {direction_name(st['directions'][p])} S{p}={st['sensors'][p]} "
            f"{'stopped' if st['pump_status'][p] == 0 else 'RUNNING (' + str(st['pump_status'][p]) + ')'}"
            for p in PUMP_IDS)
        return True, f"probe OK: COM{port} firmware {st['firmware']!r}; {pumps} (raw read-only queries)"
    try:
        with MediaFillClient(simulate=False) as mfm:
            rp = mfm.media_fill_connect(com_port).return_parameters
            if rp.simulated:
                return False, f"probe FAILED: the vendor driver isn't reachable ({media_fill_com_diagnosis()})"
            status = mfm.media_fill_get_status(rp.device_id).return_parameters
    except Exception as exc:
        return False, f"probe FAILED on COM{parse_com_port(com_port)}: {exc}"
    pumps = ", ".join(
        f"P{p.pump_id} {p.direction_name} S{p.pump_id}={p.liquid_level_sensor_state}" for p in status.pumps
    )
    return True, (
        f"probe OK: COM{status.com_port} firmware {status.firmware_version!r}; {pumps}; "
        f"last error {status.last_error_message!r}"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="hamilton-media-fill")
    parser.add_argument("--diagnose", action="store_true", help="print the COM reachability diagnosis")
    parser.add_argument("--list-ports", action="store_true",
                        help="list COM ports with a Media Fill Module's USB id (nothing is opened)")
    parser.add_argument("--find", action="store_true",
                        help="connect read-only to each of those ports and list the confirmed Media Fill "
                             "Modules (firmware check; other devices are never opened)")
    parser.add_argument("--probe", metavar="COMn",
                        help="read-only check of the module on COMn: firmware, directions, sensors (nothing moves)")
    parser.add_argument("--selftest", action="store_true", help="try to create the COM object (no device I/O)")
    parser.add_argument("--configure", action="store_true", help="install-time setup (32-bit host config)")
    parser.add_argument("--register-codebase", action="store_true",
                        help="add a CodeBase to the vendor COM registration (regasm /codebase; Administrator)")
    args = parser.parse_args(argv)

    if args.list_ports:
        ports = find_media_fill_ports()
        for port, name in ports:
            print(f"{port}  {name}")
        if not ports:
            print("no Media Fill Module found on USB (check the cable, the 24 V power and Device Manager > Ports)")
        else:
            print("(USB id only -- an Arduino Uno has the same id; --find confirms each by its firmware)")
        return 0 if ports else 1
    if args.find:
        modules = identify_media_fill_modules()
        for port, description, firmware in modules:
            print(f"{port}  {firmware!r}  {description}")
        if not modules:
            print(
                "no Media Fill Module confirmed (none on USB, the vendor driver isn't reachable, "
                "or the port is busy)"
            )
        return 0 if modules else 1
    if args.probe:
        ok, msg = probe(args.probe)
        print(msg)
        return 0 if ok else 1
    if args.configure:
        ok, msg = configure_media_fill()
        print(msg)
        return 0 if ok else 1
    if args.register_codebase:
        ok, msg = register_codebase()
        print(msg)
        return 0 if ok else 1
    if args.selftest:
        transport = _ComMediaFillTransport()
        try:
            backend = transport._select_backend()
        except Exception as exc:
            print("selftest FAILED:", exc)
            return 1
        finally:
            transport.close()
        print(f"selftest OK: created {transport.progid} ({transport.api}) via {type(backend).__name__}")
        return 0

    info = _registration() or {}
    py32 = find_python32()
    net35 = _net35_installed()
    print("64-bit Python:  ", _IS_64BIT)
    print("vendor object:  ", f"{_progid()} ({vendor_api()} library)" if _driver_installed() else "(none)")
    print("registered:     ", _registered_dll() or "(not registered)")
    if info:
        print("CLSID:          ", info.get("clsid", ""))
        print("assembly:       ", info.get("assembly", "(native / n.a.)"))
        print("runtime:        ", info.get("runtimeversion", "(n.a.)"))
        print("CodeBase:       ", _codebase_path(info["codebase"]) if info.get("codebase") else "(none)")
    print("available:      ", media_fill_available())
    print("diagnosis:      ", media_fill_com_diagnosis())
    print("32-bit Python:  ", py32 or "(none found)")
    if py32 and vendor_api() == "1.1":  # the .NET 2.0 host setting only matters for the 1.1 object
        print("host config:    ", f"{host_config_path(py32)} "
              f"({'runs .NET 2.0 COM on .NET 4' if _host_runs_v2_on_clr4(py32) else 'no .NET 4 policy'})")
    print(".NET 3.5:       ", {True: "installed", False: "not installed", None: "unknown"}[net35])
    return 0


__all__ = [
    "FIRMWARE_ID",
    "HOST_CONFIG_BLOCK",
    "PROGID_V1",
    "PROGID_V2",
    "PUMP_IDS",
    "PUMP_OUT_MAX_SECONDS_V2",
    "SPEED_MAX_PERCENT",
    "SPEED_MIN_PERCENT",
    "USB_IDS",
    "MediaFillError",
    "MediaFillManager",
    "PumpDirection",
    "configure_media_fill",
    "direction_name",
    "direction_value",
    "ensure_host_config",
    "find_media_fill_ports",
    "find_python32",
    "identify_media_fill_modules",
    "is_media_fill_firmware",
    "main",
    "media_fill_available",
    "media_fill_com_diagnosis",
    "parse_com_port",
    "probe",
    "register_codebase",
    "vendor_api",
]


if __name__ == "__main__":
    raise SystemExit(main())
