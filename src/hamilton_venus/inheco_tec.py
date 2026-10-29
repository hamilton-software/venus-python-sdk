"""Pure-Python driver for the Inheco Single/Multi TEC Controller (STC/MTC).

Like :mod:`hamilton_venus.heater_cooler` and :mod:`hamilton_venus.odtc` (see
those modules' docstrings for the full rationale), this device does **not**
go through the VENUS runtime -- it is driven directly from Python via the
vendor's COM object, ``InhecoMTCdll.GlobCom`` (registered **32-bit only**),
which this module reaches the same way as the other two: in-process on
32-bit Python, else bridged through :mod:`hamilton_venus._com32`'s 32-bit
worker subprocess.

Addressing (from the vendor ``HSLInhecoTECLib.hsl``, reverse-engineered
against ``C:\\Program Files (x86)\\Hamilton\\Library\\HSLInhecoTEC\\HSLInhecoTECLib.hsl``):

* **One COM object for the whole bus** (like the HHC, unlike the ODTC's
  one-instance-per-unit). Up to 8 controller boxes (``controller_id`` 0-7)
  can share the same USB/RS232 line; ``FindTheUniversalControl(controller_id)``
  is how the single shared object *selects* which box the next command talks
  to -- it is called before every single command, not just once at connect.
* Each controller exposes up to 6 device slots (``device_id`` 1-6: a
  Thermoshake, CPAC, Heated Lid, ... whatever is plugged into that slot);
  ``device_id`` 0 addresses the controller unit itself (firmware, serial,
  runtime, its own STC/MTC type).
* There is no chain auto-discovery: a caller names the ``controller_id`` it
  wants and :meth:`InhecoTECManager.connect` calls ``FindTheUniversalControl``
  to verify that box answers, mirroring the vendor's own ``Initialize()``.

The vendor's real COM surface -- confirmed via ``GetTypeInfo()`` against the
actual installed ``InhecoMTCdll.dll`` on the dev box this was built against,
**not** just read off the ``.hsl`` source -- is exactly 4 methods:
``initDll()`` (lowercase "i"; see the case-sensitivity note on
:meth:`_ComInhecoTECTransport.find_controller`), ``FindTheUniversalControl(controllerId)``,
``WriteOnly(command)`` and ``ReadSync()``. There is **no** ``ReleaseObject()``
on this build even though the currently-shipped ``HSLInhecoTECLib.hsl``
(v2.5) calls one in ``Terminate()`` -- see
:meth:`_ComInhecoTECTransport.release`. Everything else (building the
5-character ASCII command strings, retrying on a garbled/mismatched
response, decoding the 1-character trailing status code) is client-side
logic the vendor HSL itself implements around those calls. This driver
replicates that logic faithfully in :class:`_ComInhecoTECTransport` rather
than inventing a cleaner protocol, including two apparent (unfixed, as of
the vendor's own v2.5 ``.hsl``) upstream bugs -- see
:meth:`_ComInhecoTECTransport.get_firmware_version` and
:meth:`_ComInhecoTECTransport.get_sensor_values` -- and one confirmed hazard:
calling ``WriteOnly`` for a ``controller_id`` that ``FindTheUniversalControl``
just reported as not-found (return value ``0``) crashes the vendor DLL's own
background async worker thread with an unhandled ``IndexOutOfRangeException``,
which is fatal to whatever process hosts the COM object. Every call path in
this driver checks ``FindTheUniversalControl``'s result and raises
:class:`~hamilton_venus.exceptions.InhecoTECError` instead of ever writing
after a not-found result -- do not remove that guard.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Protocol

from hamilton_venus import _com32
from hamilton_venus.exceptions import InhecoTECError

logger = logging.getLogger(__name__)

_PROGID = "InhecoMTCdll.GlobCom"
_FORCE_ENABLE_ENV = "HAMILTON_INHECO_TEC_FORCE_ENABLE"
_PY32_ENV = "HAMILTON_INHECO_TEC_PYTHON32"

#: Where the vendor drops InhecoMTCdll.dll -- unlike HHC/ODTC, right in the
#: Library folder itself, confirmed via the registered CLSID's CodeBase.
_INHECO_TEC_BIN_DIR = r"C:\Program Files (x86)\Hamilton\Library\HSLInhecoTEC"
_INHECO_TEC_KEY_FILES = ("InhecoMTCdll.dll",)

#: The SDK ships a private 32-bit CPython here (shared with every other
#: 32-bit-COM driver -- see hamilton_venus._com32).
_BUNDLED_PY32 = _com32._BUNDLED_PY32

_IS_64BIT = sys.maxsize > 2**32
_TRUTHY = {"1", "true", "yes", "on"}

# --------------------------------------------------------------------------- #
# Vendor-documented ranges and enums (HSLInhecoTECLib.hsl constants)          #
# --------------------------------------------------------------------------- #

CONTROLLER_MIN = 0
CONTROLLER_MAX = 7
DEVICE_MIN = 1
DEVICE_MAX = 6
SPEED_CLAMP_ONLY = 0
SPEED_MIN = 60
SPEED_MAX = 3000
#: Default setpoint clamp the vendor library itself starts with (``TEMPERATURE_MIN``/
#: ``_MAX`` in the HSL). The vendor mutates these *globally* after a
#: ``GetDeviceTemperatureLimits`` call to reflect whatever the last-queried
#: device reported -- a single-threaded-VENUS-script quirk this driver does
#: not replicate; :func:`validate_target_temperature` always validates
#: against these fixed defaults.
TEMPERATURE_MIN_C = 0.0
TEMPERATURE_MAX_C = 199.9

DEVICE_TYPE_NAMES: dict[int, str] = {
    0: "Thermoshake",
    1: "CPAC",
    2: "Teleshake",
    3: "CPLC",
    4: "CPAC_2TEC",
    5: "Heat_PAC",
    6: "Heated_Lid",
    7: "Cycler",
    8: "ACAC",
    9: "LCAC",
    10: "CPHF",
    12: "Thermoshake_AC",
    13: "Teleshake_AC",
    14: "Teleshake_95_AC",
    15: "CPLC2",
    64: "No_Device_Connected",
    128: "Empty_Slot",
}
#: Device types that actually have a shaker motor (Thermoshake/Teleshake and
#: their AC variants) -- a CPAC, CPLC, Heat_PAC, Heated_Lid, ... is a
#: temperature-only block with no moving parts, per the vendor's own
#: `GetDeviceType` documentation (`HSLInhecoTECLib.chm`). This is
#: **informational only**: the vendor HSL itself never checks a slot's device
#: type before sending a shaker command -- it lets the physical device reject
#: an inapplicable one via its own wire error code -- so neither does this
#: driver. Callers (scripts, UIs) can use this set to decide which slots to
#: offer shaker controls for, e.g. ``device_type in SHAKER_CAPABLE_DEVICE_TYPES``.
SHAKER_CAPABLE_DEVICE_TYPES: frozenset[int] = frozenset({0, 2, 12, 13, 14})
CONTROLLER_TYPE_NAMES: dict[int, str] = {0: "STC", 1: "MTC"}
#: Physical device slot count by controller type, confirmed against real
#: hardware: a Single TEC (STC, 0) controller has exactly 1 slot; a Multi TEC
#: (MTC, 1) has up to DEVICE_MAX (6). Used by ``inheco_tec_connect`` to decide
#: how many slots to scan -- an unrecognized controller type falls back to
#: the full MTC range rather than under-scanning.
SLOT_COUNT_BY_CONTROLLER_TYPE: dict[int, int] = {0: 1, 1: DEVICE_MAX}
SHAKE_SHAPE_NAMES: dict[int, str] = {
    0: "Circular_CCW",
    1: "Circular_CW",
    2: "UpLeftDownRight",
    3: "UpRightDownLeft",
    4: "UpDown",
    5: "LeftRight",
}
FIRMWARE_INFO_NAMES: dict[int, str] = {
    0: "Bootstrap_Version",
    1: "Application_Version",
    2: "Serial_Number",
    3: "Hardware_Version",
    4: "Copyright",
}
SENSOR_INFO_NAMES: dict[int, str] = {
    0: "Power_Supply",
    1: "Housing_Fan",
    2: "Temperature_Sensor_1_Housing",
    3: "Humidity_Sensor_Housing",
    4: "Temperature_Sensor_2_Housing",
    5: "Temperature_Sensor_1_External",
    6: "Humidity_Sensor_External",
    7: "Analogue_Sensor_1_External",
    8: "Analogue_Sensor_2_External",
    9: "Maximum_Temperature",
}
TEMPERATURE_INFO_NAMES: dict[int, str] = {
    1: "Main_Sensor_No_Compensation",
    2: "Redundant_Sensor_No_Compensation",
    3: "Fully_Compensated",
}
RESERVOIR_STATUS_NAMES: dict[int, str] = {0: "Refill_Needed", 1: "OK"}
HEATER_STATUS_NAMES: dict[int, str] = {0: "Heating", 1: "Cooling", 2: "Off"}
HEATER_INFO_NAMES: dict[int, str] = {0: "Requested_Value", 1: "Realtime_Value"}

#: Command mnemonics -- exact wire strings, "HSLInhecoTECLib.hsl" CMD_* constants.
_CMD_SET_SHAKER = "ASE"
_CMD_GET_CALIBRATION_DATE = "RCM"
_CMD_GET_FIRMWARE_VERSION = "RFV"
_CMD_GET_SENSOR_VALUES = "RHV"
_CMD_GET_SERIAL_NUMBER = "RSN"
_CMD_GET_RUNTIME = "RRD"
_CMD_GET_DEVICE_TYPE = "RTD"
_CMD_GET_RESERVOIR_STATUS = "RRS"
_CMD_GET_TEMPERATURE_MAX = "RMT"
_CMD_GET_TEMPERATURE_MIN = "RLT"
_CMD_GET_ACTUAL_TEMPERATURE = "RAT"
_CMD_GET_TARGET_TEMPERATURE = "RTT"
_CMD_GET_HEATER_ENABLED_STATUS = "RHE"
_CMD_GET_SHAKER_REVOLUTIONS = "RSR"
_CMD_GET_SHAKER_SHAPE = "RSS"
_CMD_GET_SHAKER_STATUS = "RSE"
_CMD_SET_TARGET_TEMPERATURE = "STT"
_CMD_SET_TEMPERATURE_CONTROL = "ATE"
_CMD_SET_SHAKER_REVOLUTIONS = "SSR"
_CMD_SET_SHAKER_SHAPE = "SSS"
_CMD_SET_TOUCHSCREEN = "ADD"

#: Library-level error codes ("GetDescriptionForErrorCode", "000".."009", "2xx").
_LIBRARY_ERROR_DESCRIPTIONS: dict[str, str] = {
    "000": "No error",
    "001": "Library in simulation mode",
    "002": "Failed to create communication object from InhecoMTCdll.dll",
    "003": "Failed to find the controller for the specified ControllerID",
    "004": "Trying to initialize a controller that is already initialized",
    "005": "Trying to send a command to a controller that is not initialized",
    "006": "Shaker did not answer",
    "007": "Controller did not answer",
    "008": "Communication issues with controller",
    "009": "Library is not initialized",
    "201": "Value is not a bool",
    "203": "Value is not an integer or out of range",
    "204": "Value is not a string",
    "205": "Value is not a float or outside the range bounds",
}
#: Device-level (wire) error codes -- the 1-character code trailing the echoed
#: command name in every response, e.g. "0RTD1G" -> code "G" -> "device temp not OK".
_DEVICE_ERROR_DESCRIPTIONS: dict[str, str] = {
    "0": "Normal return message. Command successful",
    "1": "External message protocol violation",
    "2": "Internal message protocol violation",
    "3": "Command not executable",
    "4": "Command unknown",
    "5": "Wrong parameter",
    "6": "Reset detected",
    "7": "Slot Id unknown",
    "8": "Wrong keyword",
    "9": "Timeout from slot-module",
    "A": "Busy with an action command or startup",
    "B": "Reserved",
    "C": "Housing temperature not OK",
    "D": "Response time too long",
    "E": "Voltage power supply not OK",
    "F": "Housing fan not OK",
    "G": "Device temp not OK",
    "H": "RPM too high",
    "I": "CPAC voltage not OK",
    "J": "Shaker is currently busy",
    "K": "TEC current too low",
    "L": "Internal shaker Communication is down",
    "M": "Shaker does not work properly",
    "N": "Shaker bus is currently busy",
    "O": "Shaker bus has been blocked due to a serious error",
    "R": "Cable Break or Shortcut PT100",
    "T": "Delta T too high",
    "W": "Wrong device connected",
}
#: Response error-code characters the retry loop treats as "this is a real
#: reply, not corruption" even though they are non-zero -- HSL's own set.
_NON_RETRYABLE_ERROR_CODES = {"1", "2", "3", "4", "5", "6", "9", "A", "D"}


def describe_device_error_code(code: str) -> str:
    """Human-readable description for a 1-character device error code (see
    :data:`_DEVICE_ERROR_DESCRIPTIONS`), or ``""`` if unknown."""
    return _DEVICE_ERROR_DESCRIPTIONS.get(code.upper(), "")


def validate_target_temperature(target_c: float) -> float:
    """Validate *target_c* against the vendor's default clamp (see
    :data:`TEMPERATURE_MIN_C` / :data:`TEMPERATURE_MAX_C`). Raises :class:`ValueError`."""
    if not TEMPERATURE_MIN_C <= target_c <= TEMPERATURE_MAX_C:
        raise ValueError(
            f"target temperature {target_c} degC is outside the InhecoTEC range "
            f"[{TEMPERATURE_MIN_C}, {TEMPERATURE_MAX_C}] degC"
        )
    return target_c


def _check_range(name: str, value: int, lo: int, hi: int) -> int:
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in [{lo}, {hi}], got {value}")
    return value


def check_controller_id(controller_id: int) -> int:
    return _check_range("controller_id", controller_id, CONTROLLER_MIN, CONTROLLER_MAX)


def check_device_id(device_id: int, *, allow_controller: bool = False) -> int:
    return _check_range("device_id", device_id, DEVICE_MIN if not allow_controller else 0, DEVICE_MAX)


def check_shaker_revolutions(rpm: int) -> int:
    if rpm == SPEED_CLAMP_ONLY:
        return rpm
    return _check_range("shaker revolutions", rpm, SPEED_MIN, SPEED_MAX)


# --------------------------------------------------------------------------- #
# Availability / diagnosis                                                    #
# --------------------------------------------------------------------------- #


def _inheco_tec_driver_installed() -> bool:
    """Whether the vendor InhecoMTCdll.dll is on disk."""
    return os.path.isfile(os.path.join(_INHECO_TEC_BIN_DIR, _INHECO_TEC_KEY_FILES[0]))


def _inheco_tec_bin_report() -> str:
    if not os.path.isdir(_INHECO_TEC_BIN_DIR):
        return f"vendor library folder not found: {_INHECO_TEC_BIN_DIR}"
    missing = [f for f in _INHECO_TEC_KEY_FILES if not os.path.isfile(os.path.join(_INHECO_TEC_BIN_DIR, f))]
    if missing:
        return f"missing from {_INHECO_TEC_BIN_DIR}: {', '.join(missing)}"
    return f"all key vendor files present in {_INHECO_TEC_BIN_DIR}"


def _force_enabled() -> bool:
    return os.environ.get(_FORCE_ENABLE_ENV, "").strip().lower() in _TRUTHY


def find_python32() -> str | None:
    """Locate a 32-bit Python for the InhecoTEC worker bridge (see
    :func:`hamilton_venus._com32.find_python32`)."""
    return _com32.find_python32(_PY32_ENV)


def inheco_tec_available() -> bool:
    """Whether the vendor InhecoTEC COM driver is usable **from this process**.

    Same shape as :func:`hamilton_venus.heater_cooler.heater_cooler_available`
    -- see that function's docstring. Never raises.
    """
    if _force_enabled():
        return True
    if sys.platform != "win32" or not _inheco_tec_driver_installed():
        return False
    if not _IS_64BIT:
        return True
    return find_python32() is not None


def inheco_tec_com_diagnosis() -> str:
    """A human-readable one-liner on why the vendor COM transport is / isn't usable."""
    if sys.platform != "win32":
        return "not Windows: the vendor InhecoTEC COM transport is unavailable."
    if not _inheco_tec_driver_installed():
        return f"Inheco TEC driver not installed ({_inheco_tec_bin_report()})."
    if not _IS_64BIT:
        return f"{_PROGID} is reachable in-process (32-bit Python)."
    py32 = find_python32()
    if py32:
        via = "bundled" if os.path.normcase(py32) == os.path.normcase(_BUNDLED_PY32) else py32
        return f"{_PROGID} is 32-bit; bridging through 32-bit Python ({via})."
    return (
        f"{_PROGID} is 32-bit and this Python is 64-bit, with no 32-bit Python for "
        f"the worker bridge. Run `setup-venus-sdk --install-py32`, install a 32-bit "
        f"Python, set {_PY32_ENV}, or use simulate=True."
    )


# --------------------------------------------------------------------------- #
# Transport protocol                                                          #
# --------------------------------------------------------------------------- #
#
# The vendor's real COM surface is just InitDll/FindTheUniversalControl/
# WriteOnly/ReadSync/ReleaseObject -- see the module docstring. This Protocol
# is instead keyed to the *logical* operations HSLInhecoTECLib.hsl's own
# public functions already group them into (that file combines what would
# otherwise be a separate "hsl_"/"hsl" implementation/interface pair -- see
# its own changelog), which is the useful parity boundary for both transports
# to share.


class _InhecoTECTransport(Protocol):
    def find_controller(self, controller_id: int) -> bool: ...
    def release(self) -> None: ...
    def get_calibration_date(self, controller_id: int, device_id: int) -> str: ...
    def get_firmware_version(self, controller_id: int, selector: int) -> str: ...
    def get_sensor_values(self, controller_id: int, selector: int) -> str: ...
    def get_device_serial_number(self, controller_id: int, device_id: int) -> str: ...
    def get_device_runtime(self, controller_id: int, device_id: int) -> int: ...
    def get_device_type(self, controller_id: int, device_id: int) -> int: ...
    def get_reservoir_status(self, controller_id: int, device_id: int) -> int: ...
    def get_actual_temperature(self, controller_id: int, device_id: int, selector: int) -> float: ...
    def get_temperature_limits(self, controller_id: int, device_id: int) -> tuple[float, float]: ...
    def get_target_temperature(self, controller_id: int, device_id: int) -> float: ...
    def set_target_temperature(self, controller_id: int, device_id: int, target_c: float) -> None: ...
    def get_heater_status(self, controller_id: int, device_id: int, selector: int) -> int: ...
    def start_temperature_control(self, controller_id: int, device_id: int) -> None: ...
    def stop_temperature_control(self, controller_id: int, device_id: int) -> None: ...
    def set_shaker_revolutions(self, controller_id: int, device_id: int, rpm: int) -> None: ...
    def get_shaker_revolutions(self, controller_id: int, device_id: int) -> int: ...
    def set_shaker_shape(self, controller_id: int, device_id: int, shape: int) -> None: ...
    def get_shaker_shape(self, controller_id: int, device_id: int) -> int: ...
    def get_shaker_status(self, controller_id: int, device_id: int) -> int: ...
    def start_shaker(self, controller_id: int, device_id: int) -> None: ...
    def stop_shaker(self, controller_id: int, device_id: int) -> None: ...
    def set_touchscreen(self, controller_id: int, enabled: bool) -> None: ...
    def send_command_string(self, controller_id: int, command: str) -> str: ...


# --------------------------------------------------------------------------- #
# Simulation transport                                                        #
# --------------------------------------------------------------------------- #


class _SimUnit:
    """In-memory state for one (controller_id, device_id) slot."""

    __slots__ = (
        "calibration_date",
        "current",
        "device_type",
        "heater_status",
        "reservoir_status",
        "runtime_minutes",
        "serial",
        "shaker_rpm",
        "shaker_running",
        "shaker_shape",
        "target",
    )

    def __init__(self, controller_id: int, device_id: int) -> None:
        # A representative small bench: slot 1 is a CPAC (temperature-only,
        # no shaker motor -- see SHAKER_CAPABLE_DEVICE_TYPES), slot 2 is a
        # Thermoshake (shakes and controls temperature); the rest are empty.
        self.device_type = {1: 1, 2: 0}.get(device_id, 64)
        self.serial = f"INHECOTEC-SIM-{controller_id}-{device_id:02d}"
        self.runtime_minutes = 4711
        self.calibration_date = "2026-01-15"
        self.target = 25.0
        self.current = 25.0
        self.heater_status = 2  # Off
        self.reservoir_status = 1  # OK
        self.shaker_rpm = 0
        self.shaker_shape = 0
        self.shaker_running = False

    def step(self) -> None:
        """Nudge *current* toward *target* one tick (no wall clock)."""
        if self.heater_status == 2:  # Off
            return
        gap = self.target - self.current
        if abs(gap) <= 0.05:
            self.current = self.target
        else:
            self.current += gap * 0.5


class _SimInhecoTECTransport:
    """Deterministic in-memory InhecoTEC used for tests, demos and offline runs.

    Any ``controller_id``/``device_id`` in the vendor-documented range answers
    (there is no real bus to fail to discover on), matching the "always found"
    behavior of a bench sitting right next to Python with nothing plugged in
    yet -- callers still get realistic per-slot device types from
    :meth:`get_device_type` (slot 1 = a CPAC -- temperature only, no shaker
    motor; slot 2 = a Thermoshake -- shakes and controls temperature; the
    rest report "no device"; see :data:`SHAKER_CAPABLE_DEVICE_TYPES`).
    """

    def __init__(self) -> None:
        self._units: dict[tuple[int, int], _SimUnit] = {}

    def _unit(self, controller_id: int, device_id: int) -> _SimUnit:
        key = (controller_id, device_id)
        unit = self._units.get(key)
        if unit is None:
            unit = _SimUnit(controller_id, device_id)
            self._units[key] = unit
        return unit

    def find_controller(self, controller_id: int) -> bool:
        return True

    def release(self) -> None:
        self._units = {}

    def get_calibration_date(self, controller_id: int, device_id: int) -> str:
        return self._unit(controller_id, device_id).calibration_date

    def get_firmware_version(self, controller_id: int, selector: int) -> str:
        return {
            0: "1.0S",
            1: "2.3S",
            2: f"SIM-CTRL-{controller_id:02d}",
            3: "HW1.0",
            4: "(c) Inheco",
        }.get(selector, "")

    def get_sensor_values(self, controller_id: int, selector: int) -> str:
        return "0"

    def get_device_serial_number(self, controller_id: int, device_id: int) -> str:
        return self._unit(controller_id, device_id).serial

    def get_device_runtime(self, controller_id: int, device_id: int) -> int:
        return self._unit(controller_id, device_id).runtime_minutes

    def get_device_type(self, controller_id: int, device_id: int) -> int:
        if device_id == 0:
            return 1  # MTC
        return self._unit(controller_id, device_id).device_type

    def get_reservoir_status(self, controller_id: int, device_id: int) -> int:
        return self._unit(controller_id, device_id).reservoir_status

    def get_actual_temperature(self, controller_id: int, device_id: int, selector: int) -> float:
        unit = self._unit(controller_id, device_id)
        unit.step()
        return round(unit.current, 1)

    def get_temperature_limits(self, controller_id: int, device_id: int) -> tuple[float, float]:
        return TEMPERATURE_MIN_C, TEMPERATURE_MAX_C

    def get_target_temperature(self, controller_id: int, device_id: int) -> float:
        return self._unit(controller_id, device_id).target

    def set_target_temperature(self, controller_id: int, device_id: int, target_c: float) -> None:
        self._unit(controller_id, device_id).target = target_c

    def get_heater_status(self, controller_id: int, device_id: int, selector: int) -> int:
        return self._unit(controller_id, device_id).heater_status

    def start_temperature_control(self, controller_id: int, device_id: int) -> None:
        unit = self._unit(controller_id, device_id)
        unit.heater_status = 0 if unit.target >= unit.current else 1

    def stop_temperature_control(self, controller_id: int, device_id: int) -> None:
        self._unit(controller_id, device_id).heater_status = 2

    def set_shaker_revolutions(self, controller_id: int, device_id: int, rpm: int) -> None:
        self._unit(controller_id, device_id).shaker_rpm = rpm

    def get_shaker_revolutions(self, controller_id: int, device_id: int) -> int:
        return self._unit(controller_id, device_id).shaker_rpm

    def set_shaker_shape(self, controller_id: int, device_id: int, shape: int) -> None:
        self._unit(controller_id, device_id).shaker_shape = shape

    def get_shaker_shape(self, controller_id: int, device_id: int) -> int:
        return self._unit(controller_id, device_id).shaker_shape

    def get_shaker_status(self, controller_id: int, device_id: int) -> int:
        return 0 if self._unit(controller_id, device_id).shaker_running else 2

    def start_shaker(self, controller_id: int, device_id: int) -> None:
        self._unit(controller_id, device_id).shaker_running = True

    def stop_shaker(self, controller_id: int, device_id: int) -> None:
        self._unit(controller_id, device_id).shaker_running = False

    def set_touchscreen(self, controller_id: int, enabled: bool) -> None:
        pass

    def send_command_string(self, controller_id: int, command: str) -> str:
        return f"{command[:4].lower()}0"


# --------------------------------------------------------------------------- #
# COM-interop transport                                                       #
# --------------------------------------------------------------------------- #


def _candidate_backends() -> list[object]:
    return _com32.candidate_backends(
        progid=_PROGID,
        bin_dirs=[_INHECO_TEC_BIN_DIR],
        tl_bin_dir=None,  # InhecoMTCdll.dll is Inheco's own .NET wrapper, not Hamilton's TransportLayer stack
        env_vars=(_PY32_ENV,),
        error_cls=InhecoTECError,
        diagnosis=inheco_tec_com_diagnosis(),
    )


class _ComInhecoTECTransport:
    """Drives the shared ``InhecoMTCdll.GlobCom`` COM object.

    Only 5 real COM operations exist (``InitDll``, ``FindTheUniversalControl``,
    ``WriteOnly``, ``ReadSync``, ``ReleaseObject``); every method below builds
    its own 5-character-header ASCII command, sends it through :meth:`_send`
    (which replicates the vendor's own ``_SendCommandToController`` retry
    loop verbatim -- garbled/short/mismatched responses are resent up to
    *resend_attempts* times), and slices the payload out of the response the
    same way the vendor's ``_ExtractAnswer`` does (``response[5:]``).
    """

    def __init__(self, backend: object | None = None) -> None:
        self._backend: object | None = backend
        self._candidates: list[object] = [] if backend is not None else _candidate_backends()
        self._dll_ready = False

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
                logger.info("InhecoTEC: using %s", type(candidate).__name__)
                return candidate
            except Exception as exc:
                errors.append(f"{type(candidate).__name__}: {exc}")
        raise InhecoTECError(
            f"could not create {_PROGID!r}. {inheco_tec_com_diagnosis()}"
            + ("  Tried -- " + "; ".join(errors) if errors else "")
        )

    def _raw(self, name: str, *args: object) -> object:
        backend = self._select_backend()
        try:
            return backend.raw_call(name, *args)  # type: ignore[attr-defined]
        except InhecoTECError:
            raise
        except Exception as exc:
            raise InhecoTECError(f"InhecoTEC {name} raised: {exc}") from exc

    def close(self) -> None:
        seen = {self._backend, *self._candidates}
        seen.discard(None)
        for backend in seen:
            close = getattr(backend, "close", None)
            if callable(close):
                close()

    def find_controller(self, controller_id: int) -> bool:
        if not self._dll_ready:
            # Confirmed via GetTypeInfo() against the real installed
            # InhecoMTCdll.dll: the IDispatch method is "initDll" (lowercase
            # "i") -- pywin32's dynamic dispatch resolves the attribute for
            # either casing but only successfully *binds* the exact one, so
            # "InitDll" silently returns a non-callable None instead of
            # raising. Don't "fix" this casing without re-confirming against
            # hardware first.
            self._raw("initDll")
            self._dll_ready = True
        return bool(self._raw("FindTheUniversalControl", controller_id))

    def release(self) -> None:
        # Confirmed via GetTypeInfo() against the real installed
        # InhecoMTCdll.dll: its IDispatch interface exposes exactly 4
        # business methods -- initDll, WriteOnly, ReadSync,
        # FindTheUniversalControl -- and no ReleaseObject, even though the
        # currently-shipped HSLInhecoTECLib.hsl (v2.5) calls one in
        # Terminate(). Likely a DLL/HSL version skew on this box. Call it
        # best-effort: a newer DLL that does implement it still gets
        # released properly, but a missing method here must never block
        # termination -- the worker subprocess exiting (see close()) is what
        # actually frees the COM object either way.
        try:
            self._raw("ReleaseObject")
        except InhecoTECError as exc:
            logger.debug("InhecoTEC: ReleaseObject not available on this vendor DLL build: %s", exc)
        self._dll_ready = False

    def _send(self, controller_id: int, command: str, *, resend_attempts: int = 10) -> str:
        """Replicates ``_SendCommandToController``: select *controller_id* via
        ``FindTheUniversalControl``, then write/read *command* with retry on a
        garbled, too-short, or command-name-mismatched response. Returns the
        raw (not yet header-stripped) successful response.
        """
        if self._raw("FindTheUniversalControl", controller_id) == 0:
            raise InhecoTECError(f"failed to find the controller for controller_id {controller_id}")

        sent_name = command[:4].lower()
        response_name = ""
        response = ""
        # Always wait 200ms before sending, mirroring the vendor's own
        # anti-spam delay.
        time.sleep(0.2)
        for attempt in range(resend_attempts + 1):
            if response_name != "0rdc":
                self._raw("WriteOnly", command)
            response = str(self._raw("ReadSync"))
            lowered = response.lower()
            garbled = (
                "errd1llcalc" in lowered
                or "errd1llcrc" in lowered
                or "errd1llnoreply" in lowered
                or len(lowered) <= 4
            )
            if not garbled:
                response_name = lowered[:4]
                if response_name != "0rdc":
                    error_code = response[4:5]
                    if error_code not in _NON_RETRYABLE_ERROR_CODES and response_name == sent_name:
                        # Flush a stale duplicate the way the vendor does before
                        # declaring success, discarding its response.
                        self._raw("WriteOnly", "0RDC1")
                        self._raw("ReadSync")
                        return response
            if attempt >= resend_attempts:
                raise InhecoTECError(
                    f"communication issues with controller {controller_id} sending {command!r} "
                    f"(no valid response after {resend_attempts + 1} attempt(s))"
                )
            time.sleep(1.0)
        raise InhecoTECError(f"communication issues with controller {controller_id} sending {command!r}")

    @staticmethod
    def _answer(response: str) -> str:
        return response[5:]

    # -- logical operations (mirrors HSLInhecoTECLib.hsl's public functions) --

    def get_calibration_date(self, controller_id: int, device_id: int) -> str:
        response = self._send(controller_id, f"0{_CMD_GET_CALIBRATION_DATE}{device_id}")
        return self._answer(response)

    def get_firmware_version(self, controller_id: int, selector: int) -> str:
        # Vendor bug (unfixed as of HSLInhecoTECLib.hsl v2.5): uses
        # controller_id as the command's leading device digit instead of a
        # literal "0" the way GetCalibrationDate/GetDeviceSerialNumber/etc.
        # do. Replicated verbatim for wire fidelity with the shipped vendor
        # library -- see the module docstring.
        response = self._send(controller_id, f"{controller_id}{_CMD_GET_FIRMWARE_VERSION}{selector}")
        return self._answer(response)

    def get_sensor_values(self, controller_id: int, selector: int) -> str:
        # Vendor bug (unfixed as of HSLInhecoTECLib.hsl v2.5): sends
        # CMD_GET_FIRMWARE_VERSION ("RFV") instead of CMD_GET_SENSOR_VALUES
        # ("RHV") -- see GetSensorValues in the .hsl. Replicated verbatim; a
        # real controller answers this with firmware info, not sensor data.
        response = self._send(controller_id, f"{controller_id}{_CMD_GET_FIRMWARE_VERSION}{selector}")
        return self._answer(response)

    def get_device_serial_number(self, controller_id: int, device_id: int) -> str:
        response = self._send(controller_id, f"0{_CMD_GET_SERIAL_NUMBER}{device_id}")
        return self._answer(response)

    def get_device_runtime(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"0{_CMD_GET_RUNTIME}{device_id}")
        return int(self._answer(response))

    def get_device_type(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"0{_CMD_GET_DEVICE_TYPE}{device_id}")
        return int(self._answer(response))

    def get_reservoir_status(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_RESERVOIR_STATUS}")
        return int(self._answer(response))

    def get_actual_temperature(self, controller_id: int, device_id: int, selector: int) -> float:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_ACTUAL_TEMPERATURE}{selector}")
        return int(self._answer(response)) * 0.1

    def get_temperature_limits(self, controller_id: int, device_id: int) -> tuple[float, float]:
        low_response = self._send(controller_id, f"{device_id}{_CMD_GET_TEMPERATURE_MIN}")
        low = int(self._answer(low_response)) * 0.1
        high_response = self._send(controller_id, f"{device_id}{_CMD_GET_TEMPERATURE_MAX}1")
        high = int(self._answer(high_response)) * 0.1
        return low, high

    def get_target_temperature(self, controller_id: int, device_id: int) -> float:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_TARGET_TEMPERATURE}")
        return int(self._answer(response)) * 0.1

    def set_target_temperature(self, controller_id: int, device_id: int, target_c: float) -> None:
        tenths = int(target_c * 10)  # vendor: Floor(i_fltTargetTemperature * 10)
        self._send(controller_id, f"{device_id}{_CMD_SET_TARGET_TEMPERATURE}{tenths}")

    def get_heater_status(self, controller_id: int, device_id: int, selector: int) -> int:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_HEATER_ENABLED_STATUS}{selector}")
        return int(self._answer(response))

    def start_temperature_control(self, controller_id: int, device_id: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_TEMPERATURE_CONTROL}1")

    def stop_temperature_control(self, controller_id: int, device_id: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_TEMPERATURE_CONTROL}0")

    def set_shaker_revolutions(self, controller_id: int, device_id: int, rpm: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_SHAKER_REVOLUTIONS}{rpm}")

    def get_shaker_revolutions(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_SHAKER_REVOLUTIONS}")
        return int(self._answer(response))

    def set_shaker_shape(self, controller_id: int, device_id: int, shape: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_SHAKER_SHAPE}{shape}")

    def get_shaker_shape(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_SHAKER_SHAPE}")
        return int(self._answer(response))

    def get_shaker_status(self, controller_id: int, device_id: int) -> int:
        response = self._send(controller_id, f"{device_id}{_CMD_GET_SHAKER_STATUS}")
        return int(self._answer(response))

    def start_shaker(self, controller_id: int, device_id: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_SHAKER}1")

    def stop_shaker(self, controller_id: int, device_id: int) -> None:
        self._send(controller_id, f"{device_id}{_CMD_SET_SHAKER}0")

    def set_touchscreen(self, controller_id: int, enabled: bool) -> None:
        self._send(controller_id, f"{controller_id}{_CMD_SET_TOUCHSCREEN}{1 if enabled else 0}")

    def send_command_string(self, controller_id: int, command: str) -> str:
        return self._send(controller_id, command)


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class InhecoTECManager:
    """Owns the transport and the set of connected ``controller_id``\\ s.

    Unlike :class:`~hamilton_venus.heater_cooler.HeaterCoolerManager` (which
    invents a flat ``device_id`` from discovered serials), this device's own
    two-level addressing (``controller_id`` 0-7, ``device_id`` 0-6 within it)
    is already the natural, vendor-faithful API -- callers pass both
    explicitly, mirroring ``HSLInhecoTECLib.hsl``'s own public functions.
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport: _InhecoTECTransport | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self._connected: set[int] = set()
        if transport is not None:
            self._transport: _InhecoTECTransport = transport
        elif simulate:
            self._transport = _SimInhecoTECTransport()
        elif not inheco_tec_available():
            self._transport = _SimInhecoTECTransport()
            if sys.platform == "win32":
                logger.warning("InhecoTEC: using the simulation transport. %s", inheco_tec_com_diagnosis())
        else:  # pragma: no cover - needs the vendor driver
            self._transport = _ComInhecoTECTransport()

    @property
    def transport(self) -> _InhecoTECTransport:
        return self._transport

    def connected_controllers(self) -> list[int]:
        return sorted(self._connected)

    def connect(self, controller_id: int) -> None:
        check_controller_id(controller_id)
        with self.lock:
            if controller_id in self._connected:
                # Vendor Initialize() is idempotent for an already-connected
                # controller (returns TRUE with error code "004", not a
                # failure) -- mirrored here as a no-op success.
                logger.info("InhecoTEC: controller_id=%s is already connected", controller_id)
                return
            if not self._transport.find_controller(controller_id):
                raise InhecoTECError(f"failed to find the InhecoTEC controller for controller_id {controller_id}")
            self._connected.add(controller_id)

    def require_connected(self, controller_id: int) -> None:
        if controller_id not in self._connected:
            raise InhecoTECError(
                f"controller_id {controller_id} is not connected; call inheco_tec_connect first"
            )

    def terminate(self, *, stop_all_devices: bool = True) -> None:
        with self.lock:
            if stop_all_devices:
                for controller_id in list(self._connected):
                    for device_id in range(DEVICE_MIN, DEVICE_MAX + 1):
                        stops: tuple[Callable[[], None], ...] = (
                            functools.partial(self._transport.stop_shaker, controller_id, device_id),
                            functools.partial(self._transport.stop_temperature_control, controller_id, device_id),
                        )
                        for stop in stops:
                            try:
                                stop()
                            except InhecoTECError as exc:
                                logger.warning("InhecoTEC: could not stop device during terminate: %s", exc)
            try:
                self._transport.release()
            finally:
                self._connected = set()
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()

    def __del__(self) -> None:  # best-effort release
        with contextlib.suppress(Exception):
            self.terminate(stop_all_devices=False)


# --------------------------------------------------------------------------- #
# Install-time setup / CLI                                                    #
# --------------------------------------------------------------------------- #
#
# InhecoMTCdll.dll ships with no .dll.config at all (confirmed: the vendor's
# Library folder has no NLog/log4net target and no TransportLayer dependency
# to redirect), unlike HHC/ODTC -- so, per the "don't invent a grant the
# vendor doesn't need" gotcha, there is no ProgramData ACL step here.


def configure_inheco_tec() -> tuple[bool, str]:
    """Install-time setup (run by ``setup-venus-sdk``). Never raises.

    Currently a presence check only -- see the module note above for why
    there is no binding-redirect or ProgramData-ACL step to perform, unlike
    HHC/ODTC.
    """
    if sys.platform != "win32":
        return True, "not Windows; nothing to configure"
    if not _inheco_tec_driver_installed():
        return True, "Inheco TEC driver not installed; nothing to configure"
    return True, "nothing to configure (vendor driver ships with no external config)"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="hamilton-inheco-tec")
    parser.add_argument("--diagnose", action="store_true", help="print the COM reachability diagnosis")
    parser.add_argument(
        "--selftest", action="store_true", help="try to create the COM object (no device I/O)"
    )
    parser.add_argument(
        "--configure", action="store_true", help="install-time setup (currently a presence check only)"
    )
    args = parser.parse_args(argv)

    if args.configure:
        ok, msg = configure_inheco_tec()
        print(msg)
        return 0 if ok else 1
    if args.selftest:
        transport = _ComInhecoTECTransport()
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
    print("driver:         ", "installed" if _inheco_tec_driver_installed() else "NOT installed")
    print("available:      ", inheco_tec_available())
    print("diagnosis:      ", inheco_tec_com_diagnosis())
    print("vendor files:   ", _inheco_tec_bin_report())
    py32 = find_python32()
    print("32-bit Python:  ", py32 or "(none found -- run setup-venus-sdk --install-py32)")
    return 0


__all__ = [
    "CONTROLLER_MAX",
    "CONTROLLER_MIN",
    "CONTROLLER_TYPE_NAMES",
    "DEVICE_MAX",
    "DEVICE_MIN",
    "DEVICE_TYPE_NAMES",
    "FIRMWARE_INFO_NAMES",
    "HEATER_INFO_NAMES",
    "HEATER_STATUS_NAMES",
    "RESERVOIR_STATUS_NAMES",
    "SENSOR_INFO_NAMES",
    "SHAKER_CAPABLE_DEVICE_TYPES",
    "SHAKE_SHAPE_NAMES",
    "SLOT_COUNT_BY_CONTROLLER_TYPE",
    "SPEED_CLAMP_ONLY",
    "SPEED_MAX",
    "SPEED_MIN",
    "TEMPERATURE_INFO_NAMES",
    "TEMPERATURE_MAX_C",
    "TEMPERATURE_MIN_C",
    "InhecoTECError",
    "InhecoTECManager",
    "check_controller_id",
    "check_device_id",
    "check_shaker_revolutions",
    "configure_inheco_tec",
    "describe_device_error_code",
    "find_python32",
    "inheco_tec_available",
    "inheco_tec_com_diagnosis",
    "main",
    "validate_target_temperature",
]


if __name__ == "__main__":
    raise SystemExit(main())
