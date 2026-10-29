"""Unit tests for hamilton_venus.tilt_module: framing, simulator, transport, manager, serial link."""

# FakeW32 mirrors the pywin32 ``win32file`` API, whose function names are CamelCase.
# ruff: noqa: N802

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest

from hamilton_venus import tilt_module as tm
from hamilton_venus.exceptions import TiltModuleError, VenusError
from hamilton_venus.tilt_module import (
    TiltModuleManager,
    TiltModuleTransport,
    _SimTiltLink,
    _Win32SerialLink,
    build_command,
    evaluate_error_message,
    normalize_port,
    parse_reply,
    validate_module_name,
    validate_system_id,
)


def make_transport(*modules: str, **kwargs) -> tuple[TiltModuleTransport, _SimTiltLink]:
    """A transport over a simulator; no module names = any name is accepted (auto-create)."""
    link = _SimTiltLink(modules or None)
    link.open("COM1")
    return TiltModuleTransport(link, sleep=lambda _s: None, **kwargs), link


def make_manager(*modules: str, **kwargs) -> tuple[TiltModuleManager, _SimTiltLink]:
    """One system's worth of simulator behind a manager (the link is closed until connect())."""
    link = _SimTiltLink(modules or None)
    transport = TiltModuleTransport(link, sleep=lambda _s: None)
    return TiltModuleManager(transport_factory=lambda _system_id: transport, **kwargs), link


class ScriptedLink:
    """A link that answers from a command -> reply table and records every request."""

    def __init__(self, replies: dict[str, str]) -> None:
        self.replies = replies
        self.sent: list[str] = []
        self.port: str | None = None

    def open(self, port: str) -> None:
        self.port = port

    def close(self) -> None:
        self.port = None

    def exchange(self, line: str, timeout_s: float) -> str:
        self.sent.append(line)
        return self.replies[line[2:4]]


# -- framing ---------------------------------------------------------------------


class TestFraming:
    def test_parse_reply_with_value(self):
        reply = parse_reply("00RFer00rf SPS V2.0E\r\n")  # example from the daisy-chain help
        assert (reply.module_name, reply.command, reply.error_code, reply.name, reply.value) == (
            "00",
            "RF",
            0,
            "rf",
            "SPS V2.0E",
        )
        assert reply.ok

    def test_parse_reply_without_value_and_with_error(self):
        reply = parse_reply("TMGPer03")
        assert (reply.command, reply.error_code, reply.value, reply.ok) == ("GP", 3, "", False)

    @pytest.mark.parametrize("garbage", ["", "T1", "T1GPxx00", "hello world", "T1GPer0"])
    def test_garbled_replies_raise_with_the_library_code(self, garbage):
        with pytest.raises(TiltModuleError) as info:
            parse_reply(garbage)
        assert info.value.error_code == -9

    def test_build_command(self):
        assert build_command("T1", "gp", "5") == "T1GP5"
        assert build_command("99", "RF") == "99RF"
        with pytest.raises(TiltModuleError):
            build_command("T", "GP")
        with pytest.raises(TiltModuleError):
            build_command("T1", "G")

    @pytest.mark.parametrize("name", ["T1", "00", "TM", "a!"])
    def test_valid_module_names(self, name):
        assert validate_module_name(name) == name

    @pytest.mark.parametrize("name", ["", "T", "T11", "T ", "99", None, 5])
    def test_invalid_module_names(self, name):
        with pytest.raises(TiltModuleError):
            validate_module_name(name)

    @pytest.mark.parametrize("system_id", [1, 2, 3, 4])
    def test_valid_system_ids(self, system_id):
        assert validate_system_id(system_id) == system_id

    @pytest.mark.parametrize("system_id", [0, 5, -1, "1", None, True, 1.0])
    def test_system_id_range_is_the_hsl_1_to_4(self, system_id):
        with pytest.raises(TiltModuleError) as info:
            validate_system_id(system_id)
        assert info.value.error_code == 6

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(3, "COM3"), ("3", "COM3"), ("com3", "COM3"), (" COM12 ", "COM12"), ("COM255", "COM255")],
    )
    def test_normalize_port(self, given, expected):
        assert normalize_port(given) == expected

    @pytest.mark.parametrize("bad", [0, 256, "COM0", "COM256", "ttyS0", "", "COMx"])
    def test_normalize_port_rejects(self, bad):
        with pytest.raises(TiltModuleError):
            normalize_port(bad)

    def test_error_is_a_venus_error(self):
        assert issubclass(TiltModuleError, VenusError)
        assert TiltModuleError("x", error_code=6).error_code == 6

    @pytest.mark.parametrize(
        ("code", "text"),
        [
            (0, "No error."),
            (1, "Init position not found!"),
            (3, "Drive not initialized!"),
            (6, "Parameter out of range!"),
            (7, "Unknown command!"),
            (-1, "Assigned system (COM port) already initialized!"),
            (-4, "Assigned module not yet initialized!"),
            (-8, "Reading from COM port failed (e.g. timeout)!"),
            (-11, "Unknown device name (module identifier)!"),
            (8, "Unknown error code!"),
            (-50, "Unknown error code!"),
        ],
    )
    def test_error_messages_are_the_vendors(self, code, text):
        assert evaluate_error_message(code) == text


# -- simulator through the real transport ---------------------------------------------


class TestSimulatedFirmware:
    def test_broadcast_discovers_a_single_module(self):
        transport, _ = make_transport("T1")
        assert transport.discover() == "T1"

    def test_broadcast_in_auto_mode_answers_as_the_factory_default_00(self):
        transport, _ = make_transport()
        assert transport.discover() == "00"  # a brand-new module is usually "00"

    def test_broadcast_with_several_modules_is_a_collision(self):
        transport, _ = make_transport("T1", "T2")
        with pytest.raises(TiltModuleError, match="no reply") as info:
            transport.discover()
        assert info.value.error_code == -8

    def test_unknown_module_in_a_fixed_chain_times_out_with_a_helpful_message(self):
        transport, _ = make_transport("T1")
        with pytest.raises(TiltModuleError, match="RS-232 cable"):
            transport.firmware("ZZ")

    def test_auto_mode_accepts_any_valid_name(self):
        transport, link = make_transport()
        assert transport.firmware("ZZ").startswith("Tilt module ambient simulation")
        assert "ZZ" in link.units

    def test_move_before_init_is_error_3(self):
        transport, _ = make_transport()
        with pytest.raises(TiltModuleError) as info:
            transport.move_to("T1", 5)
        assert info.value.error_code == 3
        assert "Drive not initialized!" in str(info.value)

    def test_init_then_move_and_wait_for_idle(self):
        sleeps: list[float] = []
        transport, link = make_transport()
        transport._sleep = sleeps.append
        transport.initialize("T1")
        transport.move_to("T1", 8)
        assert link.units["T1"].angle == 8
        assert len(sleeps) == 1  # sim reports busy once after a move
        assert not transport.is_busy("T1")

    @pytest.mark.parametrize("angle", [-1, 11, 2.5])
    def test_out_of_range_angle_rejected_client_side(self, angle):
        transport, link = make_transport()
        transport.initialize("T1")
        link.log.clear()
        with pytest.raises(TiltModuleError) as info:
            transport.move_to("T1", angle)
        assert info.value.error_code == 6
        assert link.log == []  # never reached the wire

    def test_firmware_rejects_out_of_range_parameter_with_error_6(self):
        transport, _ = make_transport()
        transport.initialize("T1")
        with pytest.raises(TiltModuleError) as info:
            transport.transact("T1", "GP", "11")
        assert info.value.error_code == 6

    def test_unknown_command_is_error_7(self):
        transport, _ = make_transport()
        with pytest.raises(TiltModuleError) as info:
            transport.transact("T1", "ZZ")
        assert info.value.error_code == 7

    def test_injected_fault_blocks_motion_until_error_reset(self):
        transport, link = make_transport()
        transport.initialize("T1")
        link.inject_error("T1", 2)
        with pytest.raises(TiltModuleError) as info:
            transport.move_to("T1", 3)
        assert info.value.error_code == 2
        assert transport.error_code("T1") == 2  # RE reports the last error
        transport.reset_error("T1")
        assert transport.error_code("T1") == 0
        transport.move_to("T1", 3)

    def test_reply_from_the_wrong_module_is_unknown_device_name(self):
        link = ScriptedLink({"RF": "T2RFer00rf X"})
        with pytest.raises(TiltModuleError) as info:
            TiltModuleTransport(link).transact("T1", "RF")
        assert info.value.error_code == -11

    def test_reply_to_the_wrong_command_is_unexpected(self):
        link = ScriptedLink({"RF": "T1GPer00"})
        with pytest.raises(TiltModuleError) as info:
            TiltModuleTransport(link).transact("T1", "RF")
        assert info.value.error_code == -9

    def test_wait_idle_times_out(self):
        link = ScriptedLink({"RS": "T1RSer00rs 1"})
        now = [0.0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        transport = TiltModuleTransport(
            link, sleep=sleep, clock=lambda: now[0], poll_interval_s=1.0, move_timeout_s=5.0
        )
        with pytest.raises(TiltModuleError, match="still busy"):
            transport.wait_idle("T1")

    def test_a_status_query_that_cannot_be_parsed_does_not_fail_a_move(self, caplog):
        """RS reply format is unconfirmed on hardware: GP's own acknowledgement is what counts."""
        link = ScriptedLink({"GP": "T1GPer00", "RS": "T1RSer00rs ?"})
        transport = TiltModuleTransport(link, sleep=lambda _s: None)
        with caplog.at_level(logging.WARNING, logger="hamilton_venus.tilt_module"):
            transport.move_to("T1", 4)
        assert link.sent == ["T1GP4", "T1RS"]
        assert "could not read busy status" in caplog.text
        with pytest.raises(TiltModuleError, match="expected a number"):
            transport.wait_idle("T1", strict=True)


# -- manager --------------------------------------------------------------------------


class TestManagerSystems:
    def test_connect_normalises_the_port_and_opens_the_link(self):
        manager, link = make_manager()
        assert manager.connect(1, "com3") == "COM3"
        assert link.port == "COM3" and manager.systems() == [1]

    @pytest.mark.parametrize("system_id", [0, 5, "1"])
    def test_connect_enforces_the_hsl_system_range(self, system_id):
        manager, link = make_manager()
        with pytest.raises(TiltModuleError) as info:
            manager.connect(system_id, 3)
        assert info.value.error_code == 6 and link.port is None

    def test_connect_rejects_a_bad_port_without_opening_anything(self):
        manager, link = make_manager()
        with pytest.raises(TiltModuleError):
            manager.connect(1, 256)
        assert link.port is None and manager.systems() == []

    def test_connecting_a_system_twice_is_error_minus_1(self):
        manager, _ = make_manager()
        manager.connect(1, 3)
        with pytest.raises(TiltModuleError) as info:
            manager.connect(1, 4)
        assert info.value.error_code == -1

    def test_two_systems_cannot_share_a_port(self):
        links: dict[int, _SimTiltLink] = {}

        def factory(system_id: int) -> TiltModuleTransport:
            links[system_id] = _SimTiltLink()
            return TiltModuleTransport(links[system_id], sleep=lambda _s: None)

        manager = TiltModuleManager(transport_factory=factory)
        manager.connect(1, 3)
        manager.connect(2, 4)
        assert manager.systems() == [1, 2]
        with pytest.raises(TiltModuleError) as info:
            manager.connect(3, "COM3")
        assert info.value.error_code == -1
        assert links[1].port == "COM3" and links[2].port == "COM4"

    def test_a_failed_open_leaves_the_system_unregistered(self):
        class Boom(_SimTiltLink):
            def open(self, port):
                raise TiltModuleError("cannot open", error_code=-6)

        manager = TiltModuleManager(transport_factory=lambda _s: TiltModuleTransport(Boom()))
        with pytest.raises(TiltModuleError):
            manager.connect(1, 3)
        assert manager.systems() == []

    def test_operations_on_an_unconnected_system_are_error_minus_2(self):
        manager, _ = make_manager()
        calls = (
            lambda: manager.initialize_module(1, "TM"),
            lambda: manager.move_to_position(1, "TM", 3),
            lambda: manager.terminate_module(1, "TM"),
            lambda: manager.terminate_communication(1),
            lambda: manager.status(1, "TM"),
        )
        for call in calls:
            with pytest.raises(TiltModuleError) as info:
                call()
            assert info.value.error_code == -2
            assert "tilt_module_connect" in str(info.value)

    def test_close_requires_every_module_to_be_terminated_first(self):
        manager, link = make_manager()
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        with pytest.raises(TiltModuleError, match="still initialised"):
            manager.terminate_communication(1)
        assert link.port == "COM3"  # still open
        manager.terminate_module(1, "TM")
        manager.terminate_communication(1)
        assert link.port is None and manager.systems() == []
        manager.connect(1, 3)  # can be connected again


class TestManagerModules:
    def connected(self, *modules: str, **kwargs) -> tuple[TiltModuleManager, _SimTiltLink]:
        manager, link = make_manager(*modules, **kwargs)
        manager.connect(1, 3)
        return manager, link

    def test_initialize_sends_the_hsl_command_list_in_order(self):
        manager, link = self.connected()
        firmware = manager.initialize_module(1, "TM")
        assert [r[0] for r in link.log] == ["TMEI", "TMSI", "TMRF"]  # the HSL's "EI,SI,RF"
        assert firmware.startswith("Tilt module ambient simulation")
        status = manager.status(1, "TM")
        assert (status.initialized, status.angle, status.powered) == (True, 0, True)

    def test_initialising_twice_is_error_minus_3(self):
        manager, _ = self.connected()
        manager.initialize_module(1, "TM")
        with pytest.raises(TiltModuleError) as info:
            manager.initialize_module(1, "TM")
        assert info.value.error_code == -3

    def test_a_failed_initialize_powers_the_module_off_as_the_hsl_does(self):
        link = ScriptedLink({"EI": "TMEIer00", "SI": "TMSIer01", "PO": "TMPOer00"})
        manager = TiltModuleManager(transport_factory=lambda _s: TiltModuleTransport(link))
        manager.connect(1, 3)
        with pytest.raises(TiltModuleError) as info:
            manager.initialize_module(1, "TM")
        assert info.value.error_code == 1
        assert link.sent == ["TMEI", "TMSI", "TMPO"]
        assert manager._systems[1].modules["TM"].initialized is False

    def test_moving_requires_initialize_error_minus_4(self):
        manager, link = self.connected()
        for call in (lambda: manager.move_to_position(1, "TM", 3), lambda: manager.terminate_module(1, "TM")):
            with pytest.raises(TiltModuleError) as info:
                call()
            assert info.value.error_code == -4
        assert link.log == []  # refused before anything was sent

    def test_move_tracks_the_angle_per_module(self):
        manager, link = self.connected()
        manager.initialize_module(1, "A1")
        manager.initialize_module(1, "B2")
        assert manager.move_to_position(1, "B2", 6) == 6
        assert manager.status(1, "A1").angle == 0 and manager.status(1, "B2").angle == 6
        assert (link.units["A1"].angle, link.units["B2"].angle) == (0, 6)

    @pytest.mark.parametrize("angle", [-1, 11, 4.5])
    def test_bad_angle_is_error_6(self, angle):
        manager, _ = self.connected()
        manager.initialize_module(1, "TM")
        with pytest.raises(TiltModuleError) as info:
            manager.move_to_position(1, "TM", angle)
        assert info.value.error_code == 6

    def test_failed_move_makes_the_tracked_angle_unknown(self):
        manager, link = self.connected()
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 5)
        link.inject_error("TM", 2)
        with pytest.raises(TiltModuleError) as info:
            manager.move_to_position(1, "TM", 9)
        assert info.value.error_code == 2
        assert manager.status(1, "TM").angle is None

    def test_terminate_module_is_gp0_then_po(self):
        manager, link = self.connected()
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 7)
        link.log.clear()
        manager.terminate_module(1, "TM")
        sent = [r[0] for r in link.log]
        assert sent[0] == "TMGP0" and sent[-1] == "TMPO"  # the HSL's "GP0,PO"
        assert link.units["TM"].angle == 0 and not link.units["TM"].powered
        status = manager.status(1, "TM")
        assert (status.initialized, status.angle, status.powered) == (False, 0, False)

    def test_terminate_module_does_not_power_off_if_it_cannot_go_flat(self):
        manager, link = self.connected()
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 7)
        link.inject_error("TM", 2)
        link.log.clear()
        with pytest.raises(TiltModuleError):
            manager.terminate_module(1, "TM")
        assert "TMPO" not in [r[0] for r in link.log]
        assert link.units["TM"].powered


class TestManagerStatus:
    def test_status_reports_firmware_error_and_busy(self):
        manager, link = make_manager()
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 4)
        status = manager.status(1, "TM")
        assert (status.module_name, status.angle, status.busy, status.error_code) == ("TM", 4, False, 0)
        assert status.error_message == "No error." and status.query_error is None
        link.inject_error("TM", 5)
        with pytest.raises(TiltModuleError):
            manager.move_to_position(1, "TM", 1)
        status = manager.status(1, "TM")
        assert status.error_code == 5 and status.error_message == "Stepper motor power amp defective!"

    def test_unreadable_status_still_returns_the_tracked_fields(self):
        link = ScriptedLink({"EI": "TMEIer00", "SI": "TMSIer00", "RF": "TMRFer00rf V1", "RE": "TMREer00re ?"})
        manager = TiltModuleManager(transport_factory=lambda _s: TiltModuleTransport(link))
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        status = manager.status(1, "TM")
        assert (status.initialized, status.angle, status.firmware) == (True, 0, "V1")
        assert status.busy is None and status.error_code is None
        assert "expected a number" in (status.query_error or "")

    def test_status_of_a_module_nobody_answers_does_not_raise(self):
        manager, _ = make_manager("T1")
        manager.connect(1, 3)
        status = manager.status(1, "ZZ")
        assert status.initialized is False and status.angle is None
        assert "no reply" in (status.query_error or "")


class TestManagerShutdown:
    def test_terminate_returns_modules_to_flat_powers_off_and_closes_everything(self):
        manager, link = make_manager()
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 7)
        link.log.clear()
        assert manager.terminate() == []
        sent = [r[0] for r in link.log]
        assert sent[0] == "TMGP0" and sent[-1] == "TMPO"
        assert link.units["TM"].angle == 0 and not link.units["TM"].powered
        assert link.port is None and manager.systems() == []
        assert manager.terminate() == []  # idempotent

    def test_terminate_can_leave_a_tilted_plate_alone(self):
        manager, link = make_manager(return_to_flat_on_close=False)
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 7)
        link.log.clear()
        manager.terminate()
        assert link.log == []  # no move and no power off
        assert link.units["TM"].angle == 7 and link.units["TM"].powered and link.port is None

    def test_terminate_never_raises_and_leaves_a_module_that_cannot_go_flat_powered(self):
        manager, link = make_manager()
        manager.connect(1, 3)
        manager.initialize_module(1, "TM")
        manager.move_to_position(1, "TM", 3)
        link.inject_error("TM", 2)
        problems = manager.terminate()
        assert any("shutdown failed" in p for p in problems)
        assert link.units["TM"].powered and link.port is None and manager.systems() == []

    def test_simulate_flag_builds_the_simulator(self):
        manager = TiltModuleManager(simulate=True)
        manager.connect(2, 9)
        manager.initialize_module(2, "A1")
        manager.terminate()

    def test_falls_back_to_the_simulator_when_serial_is_unavailable(self, monkeypatch, caplog):
        monkeypatch.setattr(tm, "tilt_module_available", lambda: False)
        with caplog.at_level(logging.WARNING, logger="hamilton_venus.tilt_module"):
            manager = TiltModuleManager()
        manager.connect(1, 1)
        assert isinstance(manager.transport(1).link, _SimTiltLink)
        assert ("using the simulation transport" in caplog.text) == (sys.platform == "win32")


# -- serial link (no port needed: win32file is injected) ---------------------------------


class FakeW32:
    GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING = 1, 2, 3
    EVENPARITY, NOPARITY, ODDPARITY, ONESTOPBIT = 2, 0, 1, 0
    PURGE_RXCLEAR, PURGE_TXCLEAR = 8, 4

    def __init__(self, reply: bytes = b"", chunk: int = 64, fail_open: bool = False) -> None:
        self.reply, self.chunk, self.fail_open = reply, chunk, fail_open
        self.calls: list[tuple] = []
        self.dcb = SimpleNamespace()
        self.written = b""

    def CreateFile(self, *args):
        if self.fail_open:
            raise OSError("The system cannot find the file specified.")
        self.calls.append(("CreateFile", args[0]))
        return 42

    def SetupComm(self, h, in_size, out_size):
        self.calls.append(("SetupComm", in_size, out_size))

    def GetCommState(self, h):
        return self.dcb

    def SetCommState(self, h, dcb):
        self.calls.append(("SetCommState",))

    def SetCommTimeouts(self, h, timeouts):
        self.calls.append(("SetCommTimeouts", timeouts))

    def PurgeComm(self, h, flags):
        self.calls.append(("PurgeComm", flags))

    def WriteFile(self, h, data):
        self.written += data
        return (0, len(data))

    def CloseHandle(self, h):
        self.calls.append(("CloseHandle", h))

    def ReadFile(self, h, n):
        out, self.reply = self.reply[: self.chunk], self.reply[self.chunk :]
        return (0, out)


class TestWin32SerialLink:
    def test_open_configures_what_the_vendor_help_shows(self):
        """1200 baud, 8 data bits, even parity, 1 stop bit, flow control none (DTR/RTS asserted)."""
        w = FakeW32()
        link = _Win32SerialLink(w)
        link.open("COM3")
        assert ("CreateFile", r"\\.\COM3") in w.calls
        assert (w.dcb.BaudRate, w.dcb.ByteSize, w.dcb.Parity, w.dcb.StopBits) == (1200, 8, w.EVENPARITY, w.ONESTOPBIT)
        assert (w.dcb.fOutxCtsFlow, w.dcb.fOutxDsrFlow, w.dcb.fOutX, w.dcb.fInX) == (0, 0, 0, 0)
        assert (w.dcb.fDtrControl, w.dcb.fRtsControl) == (1, 1)
        link.close()
        assert ("CloseHandle", 42) in w.calls

    def test_serial_settings_can_be_overridden_for_bring_up(self):
        w = FakeW32()
        _Win32SerialLink(w, baudrate=9600, parity="n").open("COM3")
        assert (w.dcb.BaudRate, w.dcb.Parity, w.dcb.fParity) == (9600, w.NOPARITY, 0)
        w = FakeW32()
        _Win32SerialLink(w, baudrate=2400, parity="O").open("COM3")
        assert (w.dcb.BaudRate, w.dcb.Parity, w.dcb.fParity) == (2400, w.ODDPARITY, 1)

    def test_bad_parity_is_rejected(self):
        with pytest.raises(TiltModuleError, match="parity"):
            _Win32SerialLink(FakeW32(), parity="X")

    def test_open_failure_is_error_minus_6(self):
        link = _Win32SerialLink(FakeW32(fail_open=True))
        with pytest.raises(TiltModuleError, match="cannot open COM3") as info:
            link.open("COM3")
        assert info.value.error_code == -6

    def test_exchange_writes_crlf_and_reads_one_line_across_chunks(self):
        w = FakeW32(reply=b"00RFer00rf SPS V2.0E\r\n", chunk=5)
        link = _Win32SerialLink(w)
        link.open("COM3")
        assert link.exchange("00RF", 1.0) == "00RFer00rf SPS V2.0E"
        assert w.written == b"00RF\r\n"

    def test_exchange_times_out(self):
        link = _Win32SerialLink(FakeW32(reply=b"00RFer"))
        link.open("COM3")
        with pytest.raises(TimeoutError):
            link.exchange("00RF", 0.05)

    def test_a_timeout_through_the_transport_is_error_minus_8(self):
        link = _Win32SerialLink(FakeW32())
        transport = TiltModuleTransport(link, timeout_s=0.05)
        transport.open("COM3")
        with pytest.raises(TiltModuleError) as info:
            transport.firmware("TM")
        assert info.value.error_code == -8

    def test_exchange_requires_an_open_port(self):
        with pytest.raises(TiltModuleError, match="not open"):
            _Win32SerialLink(FakeW32()).exchange("00RF", 1.0)

    def test_full_stack_over_the_fake_port(self):
        w = FakeW32(reply=b"TMRFer00rf SPS V2.0E\r\n")
        transport = TiltModuleTransport(_Win32SerialLink(w))
        transport.open("COM3")
        assert transport.firmware("TM") == "SPS V2.0E"
        assert w.written == b"TMRF\r\n"


# -- bring-up helpers ----------------------------------------------------------------


class SilentLink(ScriptedLink):
    """Never answers (a unit at the wrong serial settings)."""

    def exchange(self, line: str, timeout_s: float) -> str:
        self.sent.append(line)
        raise TimeoutError("no answer")


class TestBringUp:
    def make_factory(self, answer_at: tuple[int, str] | None):
        created: list[ScriptedLink] = []

        def factory(baud: int, parity: str) -> ScriptedLink:
            link: ScriptedLink = (
                ScriptedLink({"RF": "00RFer00rf SPS V2.0E"}) if (baud, parity) == answer_at else SilentLink({})
            )
            created.append(link)
            return link

        return factory, created

    def test_scan_finds_the_setting_the_module_answers_at(self):
        factory, _ = self.make_factory((9600, "N"))
        results = tm.scan_serial_settings("COM3", link_factory=factory)
        answered = [(b, p) for b, p, outcome in results if outcome.startswith("ANSWERED")]
        assert answered == [(9600, "N")]
        assert len(results) == len(tm.SCAN_SETTINGS)
        assert "SPS V2.0E" in next(o for b, p, o in results if (b, p) == (9600, "N"))

    def test_scan_only_ever_sends_the_read_only_firmware_request(self):
        factory, created = self.make_factory((1200, "E"))
        tm.scan_serial_settings("COM3", link_factory=factory)
        sent = [line for link in created for line in link.sent]
        assert sent and set(sent) == {"99RF"}  # nothing that could move the module

    def test_scan_reports_when_nothing_answers(self):
        factory, _ = self.make_factory(None)
        results = tm.scan_serial_settings("3", "TM", link_factory=factory)
        assert all(outcome.startswith("no valid reply") for _, _, outcome in results)

    def test_documented_setting_is_scanned_first(self):
        assert tm.SCAN_SETTINGS[0] == (1200, "E")

    def test_cli_scan_exit_codes(self, monkeypatch, capsys):
        monkeypatch.setattr(tm, "scan_serial_settings", lambda *a, **k: [(1200, "E", "ANSWERED: 'x'")])
        assert tm.main(["--scan", "COM3"]) == 0
        assert "answered at: 1200 8E1" in capsys.readouterr().out
        monkeypatch.setattr(tm, "scan_serial_settings", lambda *a, **k: [(1200, "E", "no valid reply (x)")])
        assert tm.main(["--scan", "COM3"]) == 1

    def test_configure_never_raises_and_changes_nothing(self):
        ok, message = tm.configure_tilt_module()
        assert ok is True and message.startswith("Tilt Module:")
        assert tm.configure_tilt_module(dry_run=True)[0] is True


# -- availability / CLI -----------------------------------------------------------------


class TestAvailabilityAndCli:
    def test_force_enable(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_TILT_MODULE_FORCE_ENABLE", "1")
        assert tm.tilt_module_available() is True
        assert "forced" in tm.tilt_module_diagnosis()

    def test_not_windows_is_unavailable_and_never_raises(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_TILT_MODULE_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(tm.sys, "platform", "linux")
        assert tm.tilt_module_available() is False
        assert "not Windows" in tm.tilt_module_diagnosis()
        assert tm.list_serial_ports() == []

    def test_cli_selftest_and_diagnose(self, capsys):
        assert tm.main(["--selftest"]) == 0
        assert "selftest OK" in capsys.readouterr().out
        assert tm.main([]) == 0
        assert "diagnosis" in capsys.readouterr().out


class TestRealUnitReplies:
    """Replies a REAL module sent (2026-10-14, module T1, firmware A.0.0.1.0 2014-05-14, COM1 1200 8E1;
    confirmed by the VENUS HSL library's own trace on the same unit)."""

    def test_rf_reply_has_no_two_letter_echo(self) -> None:
        reply = parse_reply("T1RFer00 A.0.0.1.0 2014-05-14 (SSW)")
        assert reply.module_name == "T1"
        assert reply.command == "RF"
        assert reply.ok
        assert reply.value == "A.0.0.1.0 2014-05-14 (SSW)"  # the leading "A" is part of the version

    def test_echoed_simulator_style_is_still_parsed(self) -> None:
        reply = parse_reply("00RFer00rf SPS V2.0E")
        assert (reply.name, reply.value) == ("rf", "SPS V2.0E")

    def test_acknowledgements_have_a_trailing_space_and_no_value(self) -> None:
        for line in ("T1EIer00 ", "T1SIer00 ", "T1GPer00 ", "T1POer00 "):
            reply = parse_reply(line)
            assert reply.ok
            assert reply.value == ""

    def test_rs_is_rejected_as_an_unknown_command_and_not_asked_again(self) -> None:
        link = ScriptedLink({"GP": "T1GPer00 ", "RS": "T1RSer07"})
        transport = TiltModuleTransport(link, sleep=lambda _s: None)
        transport.move_to("T1", 3)  # RS is tried once after GP, rejected, remembered
        transport.move_to("T1", 10)  # ... and no longer sent
        assert link.sent.count("T1RS") == 1
        assert link.sent.count("T1GP3") == 1 and link.sent.count("T1GP10") == 1
        with pytest.raises(TiltModuleError, match="does not support RS"):
            transport.is_busy("T1")
        assert link.sent.count("T1RS") == 1

    def test_re_without_a_number_means_no_error(self) -> None:
        link = ScriptedLink({"RE": "T1REer00"})
        assert TiltModuleTransport(link, sleep=lambda _s: None).error_code("T1") == 0

    def test_re_unknown_command_is_reported_not_taken_as_error_7(self) -> None:
        link = ScriptedLink({"RE": "T1REer07"})
        transport = TiltModuleTransport(link, sleep=lambda _s: None)
        with pytest.raises(TiltModuleError, match="does not support RE"):
            transport.error_code("T1")
