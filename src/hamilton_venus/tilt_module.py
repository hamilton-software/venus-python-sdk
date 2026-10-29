"""Pure-Python driver for the Hamilton MFX Tilt Module (ambient, control-box / RS-232).

Converted from the VENUS library ``HSLMultiDaisyChainedTiltModuleAmbient`` (the
library named in the MFX Tilt Module operator's manual). The module is PC-connected
over an RS-232 "daisy chain" through its INTERFACE BOX, so -- unlike the Heater
Cooler or ODTC -- there is **no vendor COM object** and no 32-bit bridge: this
driver speaks the firmware's line protocol directly. It works with no VENUS runtime
and no ``StarClient`` / ``VantageClient``.

HSL function -> Python (see :mod:`hamilton_venus.devices.tilt_module_commands`)::

    InitializeCommunication(systemId, comPort, ...)  ->  tilt_module_connect(system_id, com_port)
    InitializeTiltModuleAmbient(systemId, module)    ->  tilt_module_initialize(system_id, module_name)
    MoveToPosition(systemId, module, angle)          ->  tilt_module_move_to_position(system_id, module_name, angle)
    TerminateTiltModuleAmbient(systemId, module)     ->  tilt_module_terminate_module(system_id, module_name)
    TerminateCommunication(systemId)                 ->  tilt_module_terminate_communication(system_id)
    EvaluateErrorMessage(code)                       ->  tilt_module_error_message(error_code)
    (not in the HSL)                                 ->  tilt_module_get_status(system_id, module_name)

A *system* (``system_id`` 1..4) is one COM port; up to eight modules, each with a
two-character module name, share it on a Y-cable chain.

Wire protocol -- the serial framing lives in Hamilton's ``HSLMultiDaisyChainCommunication``
library, which was not available. It was taken from the firmware documentation
(``HamiltonTiltModule_InstructionSet.pdf``) and from the sister library
``HSLDaisyChainCommunication.hsl`` that uses the same firmware, then confirmed on a real
unit (firmware A.0.0.1.0; the module's name was ``T1``)::

    1200 baud, 8 data bits, EVEN parity, 1 stop bit, CR/LF, half duplex
    request:  <name:2><cmd:2><param>            e.g. "T1GP5"      ("99" = any single module)
    reply:    <name:2><cmd:2>er<NN>[ <value>]
              e.g. "T1GPer00 ", "T1RFer00 A.0.0.1.0 2014-05-14 (SSW)"   (NN = firmware error code, 00 = OK)

The HSL expects exactly ``<module>GPer00`` after a move and ``<module>RFer00rf ...`` after
initialisation, which confirms the reply shape. Commands used: ``EI`` reset error, ``SI``
initialise/home, ``RF`` firmware version, ``GP<0..10>`` go to angle (whole degrees; 0 =
horizontal), ``PO`` power off; ``RS`` (0 idle / 1 busy) and ``RE`` (last error) for status.
The unit tested has no ``RS`` (it answers ``er07``) and answers ``RE`` with a bare ``er00``;
both are handled, and a move is acknowledged by the ``GP`` reply alone, as in the vendor library.

The module reports no position, so this driver tracks the last commanded angle.

Layering (so the simulator exercises the same code as real hardware)::

    TiltModuleManager        systems, module registry, locking   <- command group uses this
      TiltModuleTransport    framing, replies, error codes, polling (one per system / COM port)
        _LineLink            one request line -> one reply line
          _SimTiltLink       in-memory firmware simulator          (simulate=True / no driver)
          _Win32SerialLink   real COM port via pywin32              (hardware)

``tilt_module_available()`` / ``tilt_module_diagnosis()`` never raise.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from hamilton_venus.exceptions import TiltModuleError

logger = logging.getLogger(__name__)


#: Hardware limits of the MFX Tilt Module (operator's manual 8.1; library 0..10).
MIN_ANGLE_DEG = 0
MAX_ANGLE_DEG = 10


def validate_angle(angle_deg: float) -> int:
    """Return *angle_deg* as the integer degrees the module accepts.

    The firmware ``GP`` command only takes whole degrees ``0..10``. Raises
    :class:`ValueError` for anything else, including non-integral floats.
    """
    if isinstance(angle_deg, bool) or not isinstance(angle_deg, (int, float)):
        raise ValueError(f"tilt angle must be a number, got {angle_deg!r}")
    if isinstance(angle_deg, float):
        if not angle_deg.is_integer():
            raise ValueError(
                f"tilt angle {angle_deg!r} is not a whole number of degrees; "
                "the module only accepts 0..10 in 1-degree steps"
            )
        angle_deg = int(angle_deg)
    if not MIN_ANGLE_DEG <= angle_deg <= MAX_ANGLE_DEG:
        raise ValueError(f"tilt angle {angle_deg} out of range [{MIN_ANGLE_DEG}..{MAX_ANGLE_DEG}] degrees")
    return int(angle_deg)

_FORCE_ENABLE_ENV = "HAMILTON_TILT_MODULE_FORCE_ENABLE"
_TRUTHY = {"1", "true", "yes", "on"}

# -- serial / protocol constants ------------------------------------------------

BAUD_RATE = 1200
DEFAULT_PARITY = "E"  # 8 data bits, even parity, 1 stop bit, no flow control
_PARITIES = ("E", "N", "O")
EOL = "\r\n"
BROADCAST_ID = "99"
#: Ordinary command timeout (the single-system HSL library uses 2 s for its first transaction).
DEFAULT_TIMEOUT_S = 2.0
#: Move/home timeout. The HSL library blocks up to 120 s on the reply to a move.
MOVE_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 0.2

#: ``system_id`` range, from the HSL (``InitializeCommunication`` and friends).
MIN_SYSTEM_ID = 1
MAX_SYSTEM_ID = 4
#: ``com_port`` range, from the HSL.
MIN_COM_PORT = 1
MAX_COM_PORT = 255

#: Return codes and texts. Codes ``0..7`` are verbatim from
#: ``HSLMultiDaisyChainedTiltModuleAmbient.EvaluateErrorMessage`` and are also the firmware's
#: ``er<NN>`` codes. Negative codes are the communication library's own
#: (``HSLMultiDaisyChainCommunication`` return codes, from its help file).
ERROR_MESSAGES: dict[int, str] = {
    0: "No error.",
    1: "Init position not found!",
    2: "Steps lost (overload)!",
    3: "Drive not initialized!",
    4: "Parallel functions not allowed!",
    5: "Stepper motor power amp defective!",
    6: "Parameter out of range!",
    7: "Unknown command!",
    -1: "Assigned system (COM port) already initialized!",
    -2: "Assigned system (COM port) not yet initialized!",
    -3: "Assigned module already initialized!",
    -4: "Assigned module not yet initialized!",
    -5: "Parameter out of range!",
    -6: "Any HSL function failed!",
    -7: "Writing to COM port failed!",
    -8: "Reading from COM port failed (e.g. timeout)!",
    -9: "Unexpected error in transmitting command/receiving response occurred!",
    -10: "Unexpected error in transmitting software reset/receiving response occurred!",
    -11: "Unknown device name (module identifier)!",
}
_UNKNOWN_ERROR_MESSAGE = "Unknown error code!"

# Communication-library codes this driver raises (negative; see ERROR_MESSAGES).
ERR_SYSTEM_ALREADY_INITIALIZED = -1
ERR_SYSTEM_NOT_INITIALIZED = -2
ERR_MODULE_ALREADY_INITIALIZED = -3
ERR_MODULE_NOT_INITIALIZED = -4
ERR_OPEN_FAILED = -6
ERR_WRITE_FAILED = -7
ERR_READ_FAILED = -8
ERR_UNEXPECTED_RESPONSE = -9
ERR_UNKNOWN_MODULE_NAME = -11
ERR_UNKNOWN_COMMAND = 7  # a firmware ``er07``: the module does not know the command

_REPLY_RE = re.compile(r"^(?P<id>.{2})(?P<cmd>.{2})er(?P<err>\d{2})(?P<rest>.*)$", re.IGNORECASE)
#: What follows ``er<NN>``. The simulator (and the first reading of the docs) echoed a two-letter
#: name then a space ("rf SPS V2.0E"); a real unit (T1, firmware A.0.0.1.0, 2014-05-14) sends a
#: space and the value directly ("er00 A.0.0.1.0 2014-05-14 (SSW)").
_REPLY_NAMED_RE = re.compile(r"^(?P<name>[A-Za-z]{2}) (?P<value>.*)$")
_MODULE_NAME_RE = re.compile(r"^[!-~]{2}$")  # two printable, non-space ASCII characters


def evaluate_error_message(error_code: int) -> str:
    """Text for a return code (HSL ``EvaluateErrorMessage``)."""
    return ERROR_MESSAGES.get(error_code, _UNKNOWN_ERROR_MESSAGE)


def _checked_angle(angle: float) -> int:
    """:func:`validate_angle`, with its ``ValueError`` re-raised as :class:`TiltModuleError` (code 6)."""
    try:
        return validate_angle(angle)
    except ValueError as exc:
        raise TiltModuleError(str(exc), error_code=6) from None


def validate_system_id(system_id: int) -> int:
    """HSL range check: ``system_id`` must be an integer 1..4."""
    if isinstance(system_id, bool) or not isinstance(system_id, int) or not MIN_SYSTEM_ID <= system_id <= MAX_SYSTEM_ID:
        raise TiltModuleError(
            f"system ID {system_id!r} out of range [{MIN_SYSTEM_ID}..{MAX_SYSTEM_ID}]! ({evaluate_error_message(6)})",
            error_code=6,
        )
    return system_id


def validate_module_name(module_name: str) -> str:
    """Return *module_name* if it is a valid two-character module name, else raise.

    The two-character shape is a wire-protocol requirement (the HSL itself does not check it).
    """
    if not isinstance(module_name, str) or not _MODULE_NAME_RE.match(module_name):
        raise TiltModuleError(f"module name {module_name!r} must be exactly two printable characters (e.g. 'TM')")
    if module_name == BROADCAST_ID:
        raise TiltModuleError(f"module name {BROADCAST_ID!r} is the broadcast address and cannot name a module")
    return module_name


def normalize_port(port: str | int) -> str:
    """``3`` / ``"3"`` / ``"com3"`` -> ``"COM3"`` (the HSL takes a port number 1..255)."""
    text = str(port).strip()
    if text.isdigit():
        number = int(text)
        if not MIN_COM_PORT <= number <= MAX_COM_PORT:
            raise TiltModuleError(
                f"COM port number {number} out of range [{MIN_COM_PORT}..{MAX_COM_PORT}]!", error_code=6
            )
        return f"COM{number}"
    match = re.fullmatch(r"(?i)com(\d{1,3})", text)
    if not match or not MIN_COM_PORT <= int(match.group(1)) <= MAX_COM_PORT:
        raise TiltModuleError(f"cannot interpret serial port {port!r}; use e.g. 3 or 'COM3'")
    return f"COM{int(match.group(1))}"


# -- availability ---------------------------------------------------------------


def _force_enabled() -> bool:
    return os.environ.get(_FORCE_ENABLE_ENV, "").strip().lower() in _TRUTHY


def _pywin32_available() -> bool:
    try:
        import win32file  # noqa: F401
    except Exception:
        return False
    return True


def tilt_module_available() -> bool:
    """True when the serial transport can be used (or ``HAMILTON_TILT_MODULE_FORCE_ENABLE`` is set).

    This only says the PC *can* talk serial -- it cannot know whether a module is
    plugged in. Never raises.
    """
    try:
        if _force_enabled():
            return True
        return sys.platform == "win32" and _pywin32_available()
    except Exception:
        return False


def tilt_module_diagnosis() -> str:
    """One-line explanation of :func:`tilt_module_available`. Never raises."""
    try:
        if _force_enabled():
            return f"forced on by {_FORCE_ENABLE_ENV}."
        if sys.platform != "win32":
            return "not Windows: the serial transport (pywin32) is unavailable."
        if not _pywin32_available():
            return "pywin32 is not installed; the serial transport is unavailable (it is an SDK dependency)."
        return "pywin32 present; the Tilt Module is reached over a COM port (1200 baud, 8E1)."
    except Exception as exc:
        return f"diagnosis failed: {exc}"


def list_serial_ports() -> list[str]:
    """COM ports Windows currently reports (``HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM``). Never raises."""
    if sys.platform != "win32":
        return []
    try:
        import winreg

        ports: list[str] = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    _name, value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                ports.append(str(value))
                index += 1
        return sorted(ports, key=lambda p: (len(p), p))
    except Exception:
        return []


# -- framing --------------------------------------------------------------------


@dataclass(frozen=True)
class TiltReply:
    """A parsed firmware reply."""

    module_name: str
    command: str
    error_code: int
    name: str
    value: str
    raw: str

    @property
    def ok(self) -> bool:
        return self.error_code == 0


def build_command(module_name: str, command: str, param: str = "") -> str:
    """Build the request line (without the CR/LF terminator)."""
    if not re.fullmatch(r"[A-Za-z]{2}", command):
        raise TiltModuleError(f"command {command!r} must be two letters")
    if len(module_name) != 2:
        raise TiltModuleError(f"module name {module_name!r} must be two characters")
    return f"{module_name}{command.upper()}{param}"


def parse_reply(line: str) -> TiltReply:
    """Parse ``<name><cmd>er<NN>[<name> <value>]``; raise :class:`TiltModuleError` if garbled."""
    text = line.strip("\r\n \x00")
    match = _REPLY_RE.match(text)
    if not match:
        raise TiltModuleError(f"garbled reply from Tilt Module: {line!r}", error_code=ERR_UNEXPECTED_RESPONSE)
    rest = match.group("rest") or ""
    named = _REPLY_NAMED_RE.match(rest)
    name, value = (named.group("name"), named.group("value")) if named else ("", rest)
    return TiltReply(
        module_name=match.group("id"),
        command=match.group("cmd").upper(),
        error_code=int(match.group("err")),
        name=name,
        value=value.strip(),
        raw=text,
    )


# -- links ----------------------------------------------------------------------


class _LineLink(Protocol):
    """One request line in, one reply line out. ``exchange`` raises :class:`TimeoutError` on no reply."""

    def open(self, port: str) -> None: ...

    def close(self) -> None: ...

    def exchange(self, line: str, timeout_s: float) -> str: ...


class _SimUnit:
    """State of one simulated module's firmware."""

    def __init__(self, module_name: str, index: int) -> None:
        self.module_name = module_name
        self.firmware = f"Tilt module ambient simulation V1.{index}"
        self.initialized = False
        self.angle = 0
        self.powered = True
        self.last_error = 0
        self.fault = 0  # injected: motion commands fail with this code until EI
        self.busy_polls = 0  # RS reports busy this many more times after a move


class _SimTiltLink:
    """In-memory firmware simulator speaking the real line protocol.

    Behaviour is inferred from the HSL libraries and the instruction set; the replies to the
    commands a real unit supports were checked against one (it differs in answering ``RS`` /
    ``RE``, see :class:`TiltModuleTransport`): ``GP`` needs ``SI`` first (error 3),
    ``GP`` outside 0..10 is error 6, unknown commands error 7, a module only answers to
    its own name (or ``99`` when it is alone), and an unknown name simply times out.

    With ``module_names=None`` (the default) any valid two-character name is created on
    first use, so ``TiltModuleClient(simulate=True)`` works with whatever module names a
    script uses. Pass explicit names to model a fixed chain. Use :meth:`inject_error` to
    exercise failure paths.
    """

    def __init__(self, module_names: tuple[str, ...] | None = None) -> None:
        self.auto_create = module_names is None
        self.units: dict[str, _SimUnit] = {}
        for index, module_name in enumerate(module_names or (), start=1):
            self.units[validate_module_name(module_name)] = _SimUnit(module_name, index)
        self.port: str | None = None
        self.log: list[tuple[str, str]] = []  # (request, reply) for tests

    def open(self, port: str) -> None:
        self.port = port

    def close(self) -> None:
        self.port = None

    def inject_error(self, module_name: str, code: int) -> None:
        """Make motion commands on *module_name* fail with firmware error *code* until ``EI``."""
        self.units[module_name].fault = code

    def _unit_for(self, target: str) -> _SimUnit:
        if target == BROADCAST_ID:
            if not self.units and self.auto_create:
                self.units["00"] = _SimUnit("00", 1)
            if len(self.units) != 1:
                raise TimeoutError("sim: bus collision on broadcast address with several modules")
            return next(iter(self.units.values()))
        found = self.units.get(target)
        if found is None and self.auto_create and _MODULE_NAME_RE.match(target):
            found = self.units[target] = _SimUnit(target, len(self.units) + 1)
        if found is None:
            raise TimeoutError(f"sim: no module answers to name {target!r}")
        return found

    def exchange(self, line: str, timeout_s: float) -> str:
        if self.port is None:
            raise TimeoutError("sim link not open")
        text = line.rstrip("\r\n")
        if len(text) < 4:
            raise TimeoutError(f"sim: no reply to {text!r}")
        target, command, param = text[:2], text[2:4].upper(), text[4:]
        unit = self._unit_for(target)
        reply = self._handle(unit, command, param)
        self.log.append((text, reply))
        return reply

    @staticmethod
    def _reply(unit: _SimUnit, command: str, error: int, name: str = "", value: str = "") -> str:
        if error:
            unit.last_error = error
        body = f"{unit.module_name}{command}er{error:02d}"
        return f"{body}{name} {value}" if name else body

    def _handle(self, unit: _SimUnit, command: str, param: str) -> str:
        if command == "EI":
            unit.fault = 0
            unit.last_error = 0
            return self._reply(unit, command, 0)
        if command == "AI":
            unit.initialized = False
            unit.angle = 0
            unit.fault = 0
            unit.last_error = 0
            return self._reply(unit, command, 0)
        if command == "RF":
            return self._reply(unit, command, 0, "rf", unit.firmware)
        if command == "RN":
            return self._reply(unit, command, 0, "rn", unit.module_name)
        if command == "RS":
            busy = 1 if unit.busy_polls > 0 else 0
            unit.busy_polls = max(0, unit.busy_polls - 1)
            return self._reply(unit, command, 0, "rs", str(busy))
        if command == "RE":
            return self._reply(unit, command, 0, "re", str(unit.last_error))
        if command == "PO":
            unit.powered = False
            return self._reply(unit, command, 0)
        if command == "SI":
            if unit.fault:
                return self._reply(unit, command, unit.fault)
            unit.initialized = True
            unit.powered = True
            unit.angle = 0
            return self._reply(unit, command, 0)
        if command == "GP":
            if not unit.initialized:
                return self._reply(unit, command, 3)
            if not param.isdigit() or not 0 <= int(param) <= 10:
                return self._reply(unit, command, 6)
            if unit.fault:
                return self._reply(unit, command, unit.fault)
            unit.angle = int(param)
            unit.powered = True
            unit.busy_polls = 1
            return self._reply(unit, command, 0)
        return self._reply(unit, command, 7)


class _Win32SerialLink:
    """Real COM port through pywin32 (an SDK dependency; no ``pyserial`` needed).

    ``win32file`` is injectable so the framing can be tested without a port.
    """

    def __init__(
        self,
        win32file_module: object | None = None,
        *,
        baudrate: int = BAUD_RATE,
        parity: str = DEFAULT_PARITY,
    ) -> None:
        if parity.upper() not in _PARITIES:
            raise TiltModuleError(f"parity {parity!r} must be one of 'E' (even), 'N' (none), 'O' (odd)")
        self._w32 = win32file_module
        self._baudrate = int(baudrate)
        self._parity = parity.upper()
        self._handle: object | None = None
        self._port = ""

    def _mod(self) -> object:
        if self._w32 is None:
            try:
                import win32file
            except Exception as exc:
                raise TiltModuleError(f"pywin32 is required for the serial transport: {exc}") from exc
            self._w32 = win32file
        return self._w32

    def open(self, port: str) -> None:
        w = self._mod()
        self._port = port
        try:
            handle = w.CreateFile(  # type: ignore[attr-defined]
                rf"\\.\{port}",
                w.GENERIC_READ | w.GENERIC_WRITE,  # type: ignore[attr-defined]
                0,
                None,
                w.OPEN_EXISTING,  # type: ignore[attr-defined]
                0,
                None,
            )
            w.SetupComm(handle, 4096, 4096)  # type: ignore[attr-defined]
            dcb = w.GetCommState(handle)  # type: ignore[attr-defined]
            dcb.BaudRate = self._baudrate
            dcb.ByteSize = 8
            dcb.Parity = {
                "E": w.EVENPARITY,  # type: ignore[attr-defined]
                "N": w.NOPARITY,  # type: ignore[attr-defined]
                "O": w.ODDPARITY,  # type: ignore[attr-defined]
            }[self._parity]
            dcb.StopBits = w.ONESTOPBIT  # type: ignore[attr-defined]
            dcb.fBinary = 1
            dcb.fParity = 0 if self._parity == "N" else 1
            # Flow control "None" (Hamilton's HyperTerminal settings, HSLMultiDaisyChainCommunication help):
            # no handshaking, but -- as HyperTerminal does -- keep DTR and RTS asserted.
            dcb.fOutxCtsFlow = 0
            dcb.fOutxDsrFlow = 0
            dcb.fOutX = 0
            dcb.fInX = 0
            dcb.fDtrControl = 1  # DTR_CONTROL_ENABLE
            dcb.fRtsControl = 1  # RTS_CONTROL_ENABLE
            w.SetCommState(handle, dcb)  # type: ignore[attr-defined]
            # ReadFile returns after at most 100 ms; exchange() loops until a full line.
            w.SetCommTimeouts(handle, (0, 0, 100, 0, 1000))  # type: ignore[attr-defined]
            w.PurgeComm(handle, w.PURGE_RXCLEAR | w.PURGE_TXCLEAR)  # type: ignore[attr-defined]
        except TiltModuleError:
            raise
        except Exception as exc:
            raise TiltModuleError(
                f"cannot open {port} ({self._baudrate} baud, 8{self._parity}1): {exc}", error_code=ERR_OPEN_FAILED
            ) from exc
        self._handle = handle
        logger.info("TiltModule: opened %s at %d baud, 8%s1", port, self._baudrate, self._parity)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                self._mod().CloseHandle(handle)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("TiltModule: closing %s raised %s", self._port, exc)

    def exchange(self, line: str, timeout_s: float) -> str:
        if self._handle is None:
            raise TiltModuleError("serial port is not open")
        w = self._mod()
        try:
            w.PurgeComm(self._handle, w.PURGE_RXCLEAR)  # type: ignore[attr-defined]
            w.WriteFile(self._handle, (line + EOL).encode("ascii"))  # type: ignore[attr-defined]
        except Exception as exc:
            raise TiltModuleError(f"writing to {self._port} failed: {exc}", error_code=ERR_WRITE_FAILED) from exc
        deadline = time.monotonic() + timeout_s
        received = b""
        while time.monotonic() < deadline:
            try:
                _hr, chunk = w.ReadFile(self._handle, 64)  # type: ignore[attr-defined]
            except Exception as exc:
                raise TiltModuleError(f"reading from {self._port} failed: {exc}", error_code=ERR_READ_FAILED) from exc
            received += bytes(chunk)
            if b"\n" in received:
                return received.split(b"\n", 1)[0].decode("ascii", errors="replace").strip("\r")
        raise TimeoutError(f"no complete reply from {self._port} within {timeout_s:g} s (got {received!r})")


# -- transport ------------------------------------------------------------------


class TiltModuleTransport:
    """Framing, reply checking, error decoding and idle polling on top of a :class:`_LineLink`.

    One transport per system (= one COM port).
    """

    def __init__(
        self,
        link: _LineLink,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        move_timeout_s: float = MOVE_TIMEOUT_S,
        poll_interval_s: float = POLL_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.link = link
        self._timeout_s = timeout_s
        self._move_timeout_s = move_timeout_s
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep
        self._clock = clock
        #: (module, command) pairs the module rejected with er07 (unknown command): never asked again. A real unit
        #: (T1, A.0.0.1.0) rejects RS; the vendor library only ever waits for the GP reply.
        self._unsupported: set[tuple[str, str]] = set()

    def open(self, port: str) -> None:
        self.link.open(port)

    def close(self) -> None:
        self.link.close()

    def transact(
        self,
        module_name: str,
        command: str,
        param: str = "",
        *,
        timeout_s: float | None = None,
        check: bool = True,
    ) -> TiltReply:
        """Send one command and return its reply. Non-zero firmware codes raise when *check*."""
        request = build_command(module_name, command, param)
        logger.debug("TiltModule: -> %s", request)
        try:
            raw = self.link.exchange(request, self._timeout_s if timeout_s is None else timeout_s)
        except TimeoutError as exc:
            raise TiltModuleError(
                f"no reply from module {module_name!r} to {request!r}: {exc}. "
                "Check the RS-232 cable, INTERFACE BOX power, COM port and module name.",
                error_code=ERR_READ_FAILED,
            ) from exc
        reply = parse_reply(raw)
        logger.debug("TiltModule: <- %s", reply.raw)
        if module_name != BROADCAST_ID and reply.module_name != module_name:
            raise TiltModuleError(
                f"unexpected reply {reply.raw!r} to {request!r}: {evaluate_error_message(ERR_UNKNOWN_MODULE_NAME)}",
                error_code=ERR_UNKNOWN_MODULE_NAME,
            )
        if reply.command != command.upper():
            raise TiltModuleError(f"unexpected reply {reply.raw!r} to {request!r}", error_code=ERR_UNEXPECTED_RESPONSE)
        if check and not reply.ok:
            raise TiltModuleError(
                f"module {reply.module_name!r} rejected {request!r}: error {reply.error_code} "
                f"({evaluate_error_message(reply.error_code)})",
                error_code=reply.error_code,
            )
        return reply

    @staticmethod
    def _as_int(reply: TiltReply) -> int:
        try:
            return int(reply.value.split()[-1])
        except (ValueError, IndexError):
            raise TiltModuleError(f"expected a number in reply {reply.raw!r}") from None

    # -- operations (one per firmware command the driver uses) --

    def discover(self) -> str:
        """Name of the single module on the bus (``99RF``). Fails if none or several answer."""
        return self.transact(BROADCAST_ID, "RF").module_name

    def reset_error(self, module_name: str) -> None:
        self.transact(module_name, "EI")

    def firmware(self, module_name: str) -> str:
        return self.transact(module_name, "RF").value

    def initialize(self, module_name: str) -> None:
        """``SI`` -- home the drive to horizontal."""
        self.transact(module_name, "SI", timeout_s=self._move_timeout_s)

    def move_to(self, module_name: str, angle: int) -> None:
        """``GP<angle>``; then wait (best effort) until the module reports idle.

        The firmware's acknowledgement of ``GP`` is what the vendor library waits for. The
        extra ``RS`` poll is a safeguard: if ``RS`` itself misbehaves (an unconfirmed reply
        format) that is logged and the move still counts as done; only a module that stays
        *busy* past the move timeout is an error.
        """
        angle = _checked_angle(angle)
        self.transact(module_name, "GP", str(angle), timeout_s=self._move_timeout_s)
        self.wait_idle(module_name, strict=False)

    def _require_supported(self, module_name: str, command: str) -> None:
        if (module_name, command) in self._unsupported:
            raise TiltModuleError(
                f"module {module_name!r} does not support {command} (it answered error {ERR_UNKNOWN_COMMAND}, "
                f"{evaluate_error_message(ERR_UNKNOWN_COMMAND)}); not asking again",
                error_code=ERR_UNKNOWN_COMMAND,
            )

    def _note_unsupported(self, module_name: str, command: str, exc: TiltModuleError) -> None:
        if exc.error_code == ERR_UNKNOWN_COMMAND and (module_name, command) not in self._unsupported:
            self._unsupported.add((module_name, command))
            logger.info(
                "TiltModule: module %r does not support %s (error %d); it will not be asked again. "
                "Moves are acknowledged by the GP reply alone, as in the vendor library.",
                module_name,
                command,
                ERR_UNKNOWN_COMMAND,
            )

    def is_busy(self, module_name: str) -> bool:
        """``RS`` (0 idle / 1 busy). Not supported by every firmware: after the first er07 it is not asked again."""
        self._require_supported(module_name, "RS")
        try:
            return self._as_int(self.transact(module_name, "RS")) != 0
        except TiltModuleError as exc:
            self._note_unsupported(module_name, "RS", exc)
            raise

    def error_code(self, module_name: str) -> int:
        """``RE`` (last error). The simulator answers ``re <code>``; a real unit (A.0.0.1.0) answers
        just ``er00``, so with no number the reply's own ``er`` field is taken as the code
        (unconfirmed for a module that has an error)."""
        self._require_supported(module_name, "RE")
        reply = self.transact(module_name, "RE", check=False)
        if reply.error_code == ERR_UNKNOWN_COMMAND and not reply.value:
            self._unsupported.add((module_name, "RE"))
            self._require_supported(module_name, "RE")
        if reply.value:
            return self._as_int(reply)
        return reply.error_code

    def power_off(self, module_name: str) -> None:
        self.transact(module_name, "PO")

    def wait_idle(self, module_name: str, timeout_s: float | None = None, *, strict: bool = True) -> None:
        limit = self._move_timeout_s if timeout_s is None else timeout_s
        if not strict and (module_name, "RS") in self._unsupported:
            return  # this module has no RS: the GP reply is all there is to wait for
        deadline = self._clock() + limit
        while True:
            try:
                busy = self.is_busy(module_name)
            except TiltModuleError as exc:
                if strict:
                    raise
                if exc.error_code == ERR_UNKNOWN_COMMAND:
                    return
                logger.warning("TiltModule: could not read busy status of %r (%s); not waiting", module_name, exc)
                return
            if not busy:
                return
            if self._clock() >= deadline:
                raise TiltModuleError(f"module {module_name!r} still busy after {limit:g} s")
            self._sleep(self._poll_interval_s)


# -- manager --------------------------------------------------------------------


@dataclass
class _ModuleState:
    initialized: bool = False
    angle: int | None = None  # last commanded; None = unknown (never moved after a failure)
    powered: bool = False
    firmware: str = ""


@dataclass
class _System:
    system_id: int
    com_port: str
    transport: TiltModuleTransport
    modules: dict[str, _ModuleState] = field(default_factory=dict)


@dataclass(frozen=True)
class TiltModuleStatus:
    """Snapshot of one module. ``angle`` is the last *commanded* angle (the module cannot report it)."""

    system_id: int
    module_name: str
    initialized: bool
    angle: int | None
    powered: bool
    firmware: str
    busy: bool | None = None
    error_code: int | None = None
    error_message: str | None = None
    query_error: str | None = None


TransportFactory = Callable[[int], TiltModuleTransport]


class TiltModuleManager:
    """Owns the systems (one transport per COM port), the per-module registry and a lock.

    Mirrors the HSL's model: ``connect`` opens a system's port once, ``initialize_module``
    brings each module up, and the two ``terminate_*`` calls undo them.
    """

    def __init__(
        self,
        *,
        simulate: bool = False,
        transport_factory: TransportFactory | None = None,
        sim_modules: tuple[str, ...] | None = None,
        return_to_flat_on_close: bool = True,
        baudrate: int = BAUD_RATE,
        parity: str = DEFAULT_PARITY,
    ) -> None:
        self.lock = threading.RLock()
        self.return_to_flat_on_close = return_to_flat_on_close
        self._systems: dict[int, _System] = {}
        if transport_factory is not None:
            self._factory: TransportFactory = transport_factory
        elif simulate:
            self._factory = lambda _system_id: TiltModuleTransport(_SimTiltLink(sim_modules))
        elif not tilt_module_available():
            self._factory = lambda _system_id: TiltModuleTransport(_SimTiltLink(sim_modules))
            if sys.platform == "win32":
                logger.warning("TiltModule: using the simulation transport. %s", tilt_module_diagnosis())
        else:  # pragma: no cover - needs a COM port
            self._factory = lambda _system_id: TiltModuleTransport(_Win32SerialLink(baudrate=baudrate, parity=parity))

    # -- lookup --

    def systems(self) -> list[int]:
        return list(self._systems)

    def _system(self, system_id: int) -> _System:
        validate_system_id(system_id)
        try:
            return self._systems[system_id]
        except KeyError:
            raise TiltModuleError(
                f"system {system_id} is not connected; call tilt_module_connect first "
                f"({evaluate_error_message(ERR_SYSTEM_NOT_INITIALIZED)})",
                error_code=ERR_SYSTEM_NOT_INITIALIZED,
            ) from None

    def _initialized_module(self, system: _System, module_name: str) -> _ModuleState:
        """The state of a module that has been initialised, else the HSL's 'module not yet initialized' error."""
        state = system.modules.get(module_name)
        if state is None or not state.initialized:
            raise TiltModuleError(
                f"module {module_name!r} on system {system.system_id} is not initialised; "
                f"call tilt_module_initialize first ({evaluate_error_message(ERR_MODULE_NOT_INITIALIZED)})",
                error_code=ERR_MODULE_NOT_INITIALIZED,
            )
        return state

    def transport(self, system_id: int) -> TiltModuleTransport:
        return self._system(system_id).transport

    # -- InitializeCommunication / TerminateCommunication --

    def connect(self, system_id: int, com_port: int | str) -> str:
        """Open *com_port* for *system_id* (HSL ``InitializeCommunication``). Returns e.g. ``"COM3"``."""
        with self.lock:
            validate_system_id(system_id)
            port_name = normalize_port(com_port)
            if system_id in self._systems:
                raise TiltModuleError(
                    f"system {system_id} is already connected on {self._systems[system_id].com_port}; "
                    f"call tilt_module_terminate_communication first "
                    f"({evaluate_error_message(ERR_SYSTEM_ALREADY_INITIALIZED)})",
                    error_code=ERR_SYSTEM_ALREADY_INITIALIZED,
                )
            for other in self._systems.values():
                if other.com_port == port_name:
                    raise TiltModuleError(
                        f"{port_name} is already in use by system {other.system_id} "
                        f"({evaluate_error_message(ERR_SYSTEM_ALREADY_INITIALIZED)})",
                        error_code=ERR_SYSTEM_ALREADY_INITIALIZED,
                    )
            transport = self._factory(system_id)
            transport.open(port_name)  # raises (and leaves the port closed) on failure
            self._systems[system_id] = _System(system_id, port_name, transport)
            logger.info("TiltModule: system %d connected on %s", system_id, port_name)
            return port_name

    def terminate_communication(self, system_id: int) -> None:
        """Close the system's port (HSL ``TerminateCommunication``).

        As the comm library documents, every module must be terminated first; otherwise this
        raises and the port stays open.
        """
        with self.lock:
            system = self._system(system_id)
            still_up = [name for name, st in system.modules.items() if st.initialized]
            if still_up:
                raise TiltModuleError(
                    f"cannot close system {system_id}: module(s) {still_up} still initialised; "
                    "call tilt_module_terminate_module for each first",
                    error_code=ERR_OPEN_FAILED,
                )
            try:
                system.transport.close()
            finally:
                del self._systems[system_id]
            logger.info("TiltModule: system %d closed", system_id)

    # -- InitializeTiltModuleAmbient / MoveToPosition / TerminateTiltModuleAmbient --

    def initialize_module(self, system_id: int, module_name: str) -> str:
        """Bring a module up: ``EI`` (reset error), ``SI`` (home), ``RF`` (firmware). Returns the firmware text.

        Same command list as the HSL (``"EI,SI,RF"``). On failure the module is sent ``PO``
        (as the HSL does) and the error is raised.
        """
        with self.lock:
            system = self._system(system_id)
            validate_module_name(module_name)
            existing = system.modules.get(module_name)
            if existing is not None and existing.initialized:
                raise TiltModuleError(
                    f"module {module_name!r} on system {system_id} is already initialised "
                    f"({evaluate_error_message(ERR_MODULE_ALREADY_INITIALIZED)})",
                    error_code=ERR_MODULE_ALREADY_INITIALIZED,
                )
            state = system.modules.setdefault(module_name, _ModuleState())
            transport = system.transport
            logger.info("TiltModule: initialising module %r on system %d", module_name, system_id)
            try:
                transport.reset_error(module_name)
                transport.initialize(module_name)
                state.firmware = transport.firmware(module_name)
            except Exception:
                state.initialized = False
                state.angle = None
                try:
                    transport.power_off(module_name)
                except TiltModuleError as exc:
                    logger.warning("TiltModule: PO after failed initialise also failed: %s", exc)
                raise
            state.initialized = True
            state.powered = True
            state.angle = 0
            return state.firmware

    def move_to_position(self, system_id: int, module_name: str, angle: int) -> int:
        """Tilt to *angle* (HSL ``MoveToPosition``); returns the angle. Whole degrees 0..10."""
        angle = _checked_angle(angle)
        with self.lock:
            system = self._system(system_id)
            validate_module_name(module_name)
            state = self._initialized_module(system, module_name)
            logger.info("TiltModule: system %d module %r -> %d deg", system_id, module_name, angle)
            try:
                system.transport.move_to(module_name, angle)
            except Exception:
                state.angle = None  # position unknown after a failed move
                raise
            state.angle = angle
            state.powered = True
            return angle

    def terminate_module(self, system_id: int, module_name: str) -> None:
        """Return to horizontal, then power off (HSL ``TerminateTiltModuleAmbient``: ``GP0,PO``).

        Like the HSL's command list it stops at the first failure: if the module cannot
        return to horizontal it is **not** powered off.
        """
        with self.lock:
            system = self._system(system_id)
            validate_module_name(module_name)
            state = self._initialized_module(system, module_name)
            logger.info("TiltModule: terminating module %r on system %d (GP0, PO)", module_name, system_id)
            try:
                system.transport.move_to(module_name, 0)
            except Exception:
                state.angle = None
                raise
            state.angle = 0
            system.transport.power_off(module_name)
            state.initialized = False
            state.powered = False

    def status(self, system_id: int, module_name: str) -> TiltModuleStatus:
        """Registry state plus a live ``RS`` / ``RE`` query (not in the HSL).

        The tracked fields always come back; if the live query fails (an unconfirmed reply
        format, or no module) ``busy`` / ``error_code`` are ``None`` and ``query_error`` says why.
        """
        with self.lock:
            system = self._system(system_id)
            validate_module_name(module_name)
            state = system.modules.get(module_name, _ModuleState())
            busy: bool | None = None
            code: int | None = None
            query_error: str | None = None
            try:
                code = system.transport.error_code(module_name)
                busy = system.transport.is_busy(module_name)
            except TiltModuleError as exc:
                query_error = str(exc)
            return TiltModuleStatus(
                system_id=system_id,
                module_name=module_name,
                initialized=state.initialized,
                angle=state.angle,
                powered=state.powered,
                firmware=state.firmware,
                busy=busy,
                error_code=code,
                error_message=None if code is None else evaluate_error_message(code),
                query_error=query_error,
            )

    # -- whole-client shutdown --

    def terminate(self) -> list[str]:
        """Shut everything down: return each initialised module to flat (optional), power off, close every port.

        Never raises; returns the problems it hit. A module that cannot return to horizontal is
        left powered (as the vendor ``GP0,PO`` list would) and reported.
        """
        problems: list[str] = []
        with self.lock:
            for system_id in list(self._systems):
                system = self._systems[system_id]
                for module_name, state in list(system.modules.items()):
                    if not state.initialized:
                        continue
                    try:
                        if self.return_to_flat_on_close:
                            system.transport.move_to(module_name, 0)
                            state.angle = 0
                        elif state.angle not in (0, None):
                            continue  # left tilted on purpose: do not power it off either
                        system.transport.power_off(module_name)
                        state.initialized = False
                        state.powered = False
                    except Exception as exc:
                        problems.append(f"system {system_id} module {module_name}: shutdown failed: {exc}")
                try:
                    system.transport.close()
                except Exception as exc:
                    problems.append(f"system {system_id}: closing port failed: {exc}")
                del self._systems[system_id]
        for problem in problems:
            logger.warning("TiltModule: %s", problem)
        return problems


# -- bring-up helpers -----------------------------------------------------------

#: Serial settings tried by :func:`scan_serial_settings`, most likely first. The first is what
#: Hamilton documents (HSLMultiDaisyChainCommunication help); the rest are only there to
#: diagnose a unit that does not answer.
SCAN_SETTINGS: tuple[tuple[int, str], ...] = (
    (1200, "E"),
    (1200, "N"),
    (9600, "N"),
    (9600, "E"),
    (2400, "E"),
    (4800, "E"),
    (19200, "N"),
)


def scan_serial_settings(
    port: str | int,
    module_name: str = BROADCAST_ID,
    *,
    settings: tuple[tuple[int, str], ...] = SCAN_SETTINGS,
    timeout_s: float = 1.0,
    link_factory: Callable[[int, str], _LineLink] | None = None,
) -> list[tuple[int, str, str]]:
    """Read-only: send ``RF`` (firmware version) at each setting and report who answered.

    Returns ``[(baudrate, parity, outcome), ...]`` where *outcome* is the raw reply on success
    or the error text. Nothing that moves the module is ever sent.
    """
    port_name = normalize_port(port)
    make = link_factory or (lambda baud, parity: _Win32SerialLink(baudrate=baud, parity=parity))
    results: list[tuple[int, str, str]] = []
    for baud, parity in settings:
        transport = TiltModuleTransport(make(baud, parity), timeout_s=timeout_s)
        try:
            transport.open(port_name)
            reply = transport.transact(module_name, "RF", check=False)
            outcome = f"ANSWERED: {reply.raw!r}"
        except TiltModuleError as exc:
            outcome = f"no valid reply ({exc})"
        finally:
            transport.close()
        results.append((baud, parity, outcome))
    return results


def configure_tilt_module(*, dry_run: bool = False) -> tuple[bool, str]:
    """Best-effort install-time check. Never raises.

    Nothing needs registering: no COM object, no binding redirects, no ProgramData ACL. The only
    requirement is pywin32 (already an SDK dependency) for the serial port.
    """
    del dry_run  # nothing is ever changed
    if sys.platform != "win32":
        return True, "Tilt Module: not Windows; the serial transport is unavailable (simulation only)."
    if _pywin32_available():
        return True, "Tilt Module: pywin32 present; no further configuration required."
    return True, "Tilt Module: pywin32 is NOT installed (it is an SDK dependency); the serial transport is unavailable."


# -- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """``hamilton-tilt-module``: ``--diagnose`` (default), ``--list-ports``, ``--selftest``, ``--probe``, ``--scan``."""
    import argparse

    parser = argparse.ArgumentParser(prog="hamilton-tilt-module", description=__doc__.splitlines()[0])
    parser.add_argument("--diagnose", action="store_true", help="print availability and COM ports (default)")
    parser.add_argument("--list-ports", action="store_true", help="list COM ports Windows reports")
    parser.add_argument(
        "--selftest", action="store_true", help="run connect/initialize/move/terminate against the simulator"
    )
    parser.add_argument("--configure", action="store_true", help="install-time check (changes nothing)")
    parser.add_argument(
        "--probe",
        metavar="PORT",
        help="read-only hardware check: send 'RF' (firmware version) to MODULE (default: broadcast 99) on PORT",
    )
    parser.add_argument(
        "--scan",
        metavar="PORT",
        help="read-only: send 'RF' on PORT at several common baud/parity settings to find one the module answers",
    )
    parser.add_argument(
        "--module", default=BROADCAST_ID, help="module name for --probe/--scan (default 99 = the only module)"
    )
    parser.add_argument("--baud", type=int, default=BAUD_RATE, help=f"baud rate for --probe (default {BAUD_RATE})")
    parser.add_argument(
        "--parity", default=DEFAULT_PARITY, choices=list(_PARITIES), help="parity for --probe (default E)"
    )
    args = parser.parse_args(argv)

    if args.configure:
        ok, message = configure_tilt_module()
        print(message)
        return 0 if ok else 1

    if args.list_ports:
        ports = list_serial_ports()
        print("\n".join(ports) if ports else "(no COM ports reported)")
        return 0

    if args.selftest:
        manager = TiltModuleManager(simulate=True)
        try:
            manager.connect(1, 1)
            firmware = manager.initialize_module(1, "TM")
            manager.move_to_position(1, "TM", 7)
            status = manager.status(1, "TM")
            manager.terminate_module(1, "TM")
            manager.terminate_communication(1)
        except TiltModuleError as exc:
            print("selftest FAILED:", exc)
            return 1
        finally:
            manager.terminate()
        print(
            f"selftest OK: TM fw={firmware!r} reached {status.angle} deg, busy={status.busy}, then back to 0 and closed"
        )
        return 0

    if args.scan:
        try:
            results = scan_serial_settings(args.scan, args.module)
        except TiltModuleError as exc:
            print("scan FAILED:", exc)
            return 1
        for baud, parity, outcome in results:
            print(f"{baud:>6} baud, 8{parity}1: {outcome}")
        answered = [(b, p) for b, p, o in results if o.startswith("ANSWERED")]
        print("answered at:", ", ".join(f"{b} 8{p}1" for b, p in answered) if answered else "(no setting)")
        return 0 if answered else 1

    if args.probe:
        transport = TiltModuleTransport(_Win32SerialLink(baudrate=args.baud, parity=args.parity))
        try:
            transport.open(normalize_port(args.probe))
            reply = transport.transact(args.module, "RF")
        except TiltModuleError as exc:
            print("probe FAILED:", exc)
            return 1
        finally:
            transport.close()
        print(f"probe OK: module {reply.module_name!r} firmware {reply.value!r} (raw reply {reply.raw!r})")
        return 0

    print("available:  ", tilt_module_available())
    print("diagnosis:  ", tilt_module_diagnosis())
    print("COM ports:  ", ", ".join(list_serial_ports()) or "(none reported)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
