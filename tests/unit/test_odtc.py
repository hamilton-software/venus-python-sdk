"""Unit tests for the pure-Python ODTC driver module."""

from __future__ import annotations

import pytest

from hamilton_venus import odtc as odtc_module
from hamilton_venus.exceptions import ODTCError
from hamilton_venus.odtc import (
    MAX_DEVICES,
    ODTCManager,
    _SimODTCTransport,
    odtc_available,
    odtc_com_diagnosis,
)
from hamilton_venus.odtc_protocol import ODTCProtocolBuilder, render_protocol_xml


class TestAvailability:
    def test_force_enable_env(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_ODTC_FORCE_ENABLE", "1")
        assert odtc_available() is True

    def test_driverless_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_ODTC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(odtc_module.sys, "platform", "win32")
        monkeypatch.setattr(odtc_module, "_odtc_driver_installed", lambda: False)
        assert odtc_available() is False

    def test_64bit_with_driver_and_py32_is_available(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_ODTC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(odtc_module.sys, "platform", "win32")
        monkeypatch.setattr(odtc_module, "_IS_64BIT", True)
        monkeypatch.setattr(odtc_module, "_odtc_driver_installed", lambda: True)
        monkeypatch.setattr(odtc_module, "find_python32", lambda: r"C:\py32\python.exe")
        assert odtc_available() is True

    def test_64bit_with_driver_no_py32_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_ODTC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(odtc_module.sys, "platform", "win32")
        monkeypatch.setattr(odtc_module, "_IS_64BIT", True)
        monkeypatch.setattr(odtc_module, "_odtc_driver_installed", lambda: True)
        monkeypatch.setattr(odtc_module, "find_python32", lambda: None)
        assert odtc_available() is False

    def test_diagnosis_is_a_string(self):
        assert isinstance(odtc_com_diagnosis(), str)
        assert odtc_com_diagnosis()


class TestSimTransport:
    def test_connect_and_read_identification(self):
        t = _SimODTCTransport(1)
        t.connect("192.168.1.50", "8080", "", False)
        ident = t.get_device_identification()
        assert ident["serialNumber"] == "ODTC-SIM-001"
        assert ident["firmwareVersion"]

    def test_premethod_hold_converges(self):
        t = _SimODTCTransport(1)
        t.connect("192.168.1.50", "8080", "", True)
        builder = ODTCProtocolBuilder("Cool8", description="hold")
        protocol = builder.build()
        protocol.target_block_temperature = 8.0
        protocol.target_lid_temperature = 110.0
        # Render as a PreMethod (no steps) the way ODTCProtocol does by default.
        xml_text = render_protocol_xml(protocol)
        t.set_method(xml_text)
        request_id = t.execute_method("Cool8", 0)
        t.wait_for_end_of_execute_method(request_id, 60)
        temps = t.read_actual_temperature()
        assert temps["blockTemperature"] == pytest.approx(8.0, abs=0.5)

    def test_cycling_protocol_runs_through_loop_and_completes(self):
        t = _SimODTCTransport(1)
        t.connect("192.168.1.50", "8080", "", True)
        builder = ODTCProtocolBuilder("Cycle")
        builder.add_hold(95, 5, slope=2)
        from hamilton_venus.odtc_protocol import ODTCStep

        builder.add_cycle(
            [ODTCStep(temperature=60, hold_seconds=5), ODTCStep(temperature=72, hold_seconds=5)], repeats=3
        )
        protocol = builder.build()
        xml_text = render_protocol_xml(protocol)

        t.set_method(xml_text)
        request_id = t.execute_method("Cycle", 0)
        t.wait_for_end_of_execute_method(request_id, 120)

        status = t.get_status()
        assert status["state"] == "Idle"
        run_data = t.get_last_data()
        assert len(run_data) > 0

    def test_unknown_request_id_raises(self):
        t = _SimODTCTransport(1)
        t.connect("x", "8080", "", True)
        builder = ODTCProtocolBuilder("A")
        builder.add_hold(25, 1)
        t.set_method(render_protocol_xml(builder.build()))
        t.execute_method("A", 0)
        with pytest.raises(ODTCError, match="unknown request_id"):
            t.wait_for_end_of_execute_method("not-the-real-id", 5)

    def test_execute_without_set_method_raises(self):
        t = _SimODTCTransport(1)
        t.connect("x", "8080", "", True)
        with pytest.raises(ODTCError, match="no method downloaded"):
            t.execute_method("A", 0)

    def test_door_and_lock_state(self):
        t = _SimODTCTransport(1)
        t.connect("x", "8080", "", True)
        assert t.get_status()["doorOpen"] is False
        t.open_door()
        assert t.get_status()["doorOpen"] is True
        t.close_door()
        assert t.get_status()["doorOpen"] is False
        t.lock("token", 60)
        assert t.get_status()["locked"] is True
        t.unlock()
        assert t.get_status()["locked"] is False


class TestODTCManager:
    def test_connect_assigns_lowest_free_slot(self):
        mgr = ODTCManager(simulate=True)
        a = mgr.connect("192.168.1.50")
        b = mgr.connect("192.168.1.51")
        assert (a, b) == (1, 2)
        mgr.terminate_one(a)
        c = mgr.connect("192.168.1.52")
        assert c == 1  # slot 1 reused, matching _GetFreeDeviceNumber's lowest-free convention

    def test_max_devices_cap_raises(self):
        mgr = ODTCManager(simulate=True)
        for i in range(MAX_DEVICES):
            mgr.connect(f"192.168.1.{50 + i}")
        with pytest.raises(ODTCError, match="no free ODTC device slot"):
            mgr.connect("192.168.1.99")

    def test_resolve_all_vs_one(self):
        mgr = ODTCManager(simulate=True)
        mgr.connect("192.168.1.50")
        mgr.connect("192.168.1.51")
        assert len(mgr.resolve(None)) == 2
        assert mgr.resolve(2)[0][0] == 2

    def test_resolve_before_connect_raises(self):
        mgr = ODTCManager(simulate=True)
        with pytest.raises(ODTCError, match="no ODTC connected"):
            mgr.resolve(None)

    def test_unknown_device_id_raises(self):
        mgr = ODTCManager(simulate=True)
        mgr.connect("192.168.1.50")
        with pytest.raises(ODTCError, match="device_id 5"):
            mgr.transport_for(5)

    def test_terminate_clears_registry(self):
        mgr = ODTCManager(simulate=True)
        mgr.connect("192.168.1.50")
        mgr.connect("192.168.1.51")
        mgr.terminate()
        assert mgr.device_ids() == []

    def test_real_manager_selects_soap_transport(self):
        # The SOAP transport talks to the device's own WSDL directly and
        # doesn't depend on the vendor COM driver being installed at all, so
        # simulate=False always selects it -- constructing it does no I/O
        # (only .connect() does), so this doesn't need real hardware.
        mgr = ODTCManager(simulate=False)
        assert isinstance(mgr._make_transport(1), odtc_module._SoapODTCTransport)

    def test_last_request_id_tracking(self):
        mgr = ODTCManager(simulate=True)
        device_id = mgr.connect("192.168.1.50")
        assert mgr.last_request_id(device_id) is None
        mgr.note_request_id(device_id, "abc123")
        assert mgr.last_request_id(device_id) == "abc123"


class TestHiddenLockNeverExposed:
    def test_no_public_odtc_command_takes_a_lock_id(self):
        import inspect

        from hamilton_venus.devices.odtc_commands import ODTCDeviceCommands

        for name, member in inspect.getmembers(ODTCDeviceCommands, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            sig = inspect.signature(member)
            assert "lock_id" not in sig.parameters, f"{name} exposes lock_id"


class _FakeSoap:
    """Stands in for a zeep client: ``service.<Op>(**kw)`` returns queued acks."""

    def __init__(self, acks):
        self.acks = dict(acks)
        self.calls = []
        self.service = self

    def __getattr__(self, op):
        def call(**kw):
            self.calls.append((op, kw))
            return self.acks[op]

        return call


class _Rv:
    def __init__(self, code, message="", duration="PT1S"):
        self.returnCode, self.message, self.duration = code, message, duration


class _Status:
    """A GetStatus reply: the ack lives in ``GetStatusResult`` like the real one."""

    def __init__(self, state):
        self.GetStatusResult = _Rv(1, "Success.")
        self.state, self.locked = state, False


class _FakeListener:
    def __init__(self, events):
        self.events = events

    def wait_for_response_event(self, request_id, timeout):
        return self.events.get(request_id)


def _soap(acks, events=None):
    t = odtc_module._SoapODTCTransport()
    t._client = _FakeSoap(acks)
    t._listener = _FakeListener(events or {})
    return t


class TestSoapTransportInternals:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [("PT5S", 5), ("PT6M12S", 372), ("PT1H", 3600), ("PT0S", 0), ("", 0), ("garbage", 0)],
    )
    def test_duration_seconds(self, text, seconds):
        assert odtc_module._SoapODTCTransport._duration_seconds(text) == seconds

    def test_async_command_waits_for_its_own_completion_event(self):
        t = _soap(
            {"OpenDoor": _Rv(2), "GetStatus": _Status("idle")}, events={1: {"returnCode": "3", "message": "done"}}
        )
        t._invoke("OpenDoor", requestId=1, lockId=None)  # no raise

    def test_settling_command_waits_until_the_state_leaves_busy(self, monkeypatch):
        # The completion event lands slightly before the device returns to idle;
        # the next command would be rejected "busy" if we returned on the event.
        monkeypatch.setattr(odtc_module.time, "sleep", lambda s: None)
        t = _soap({"CloseDoor": _Rv(2)}, events={1: {"returnCode": "3"}})
        states = iter(["busy", "busy", "idle"])
        t.get_status = lambda: {"state": next(states), "locked": False, "doorOpen": False}  # type: ignore[method-assign]
        t._invoke("CloseDoor", requestId=1, lockId=None)
        assert next(states, "drained") == "drained"  # all three polled: waited for idle

    def test_missing_completion_event_times_out_loudly(self):
        t = _soap({"OpenDoor": _Rv(2)})
        with pytest.raises(ODTCError, match="timed out"):
            t._invoke("OpenDoor", requestId=1, lockId=None)

    def test_error_code_in_completion_event_raises(self):
        t = _soap({"OpenDoor": _Rv(2)}, events={1: {"returnCode": "9", "message": "Command not allowed"}})
        with pytest.raises(ODTCError, match="Command not allowed"):
            t._invoke("OpenDoor", requestId=1, lockId=None)

    def test_settle_false_returns_without_waiting(self):
        t = _soap({"ExecuteMethod": _Rv(2, duration="PT6M12S")})  # no event ever arrives
        t._invoke("ExecuteMethod", settle=False, requestId=1)  # no raise

    def test_allow_listed_code_above_three_is_not_an_error(self):
        t = _soap({"Pause": _Rv(12, "tolerated")})
        t._invoke("Pause", requestId=1)  # 12 is in the vendor's default allow-list
        t2 = _soap({"Pause": _Rv(13, "boom")})
        with pytest.raises(ODTCError, match="boom"):
            t2._invoke("Pause", requestId=1)
        t2.add_allowed_return_code(13)
        t2._invoke("Pause", requestId=2)

    def test_stop_method_retries_while_the_unit_is_busy_with_another_command(self, monkeypatch):
        monkeypatch.setattr(odtc_module.time, "sleep", lambda s: None)
        t = _soap({})
        replies = iter([_Rv(4, "Device is busy due to other command execution."), _Rv(1, "Success.")])
        t._client.service.StopMethod = lambda **kw: next(replies)  # type: ignore[attr-defined]
        t.stop_method()  # first refused as busy, second accepted
        assert next(replies, "drained") == "drained"

    def test_stop_method_does_not_retry_other_errors(self, monkeypatch):
        monkeypatch.setattr(odtc_module.time, "sleep", lambda s: None)
        t = _soap({"StopMethod": _Rv(9, "Command not allowed")})
        with pytest.raises(ODTCError, match="not allowed"):
            t.stop_method()

    def test_configuration_changes_refuse_while_a_method_runs(self):
        t = _soap({})
        t.get_status = lambda: {"state": "busy", "locked": False, "doorOpen": False}  # type: ignore[method-assign]
        with pytest.raises(ODTCError, match="cannot change the device configuration"):
            t.set_log_level("INFO")

    def test_configuration_from_idle_goes_through_standby(self):
        t = _soap({"SetConfiguration": _Rv(1)})
        order = []
        t.get_status = lambda: {"state": "idle", "locked": False, "doorOpen": False}  # type: ignore[method-assign]
        t.reset = lambda timeout, simulate_on_device_base: order.append("reset")  # type: ignore[method-assign]
        t.initialize = lambda: order.append("initialize")  # type: ignore[method-assign]
        t.set_log_level("INFO")
        assert order == ["reset", "initialize"]
        assert [c[0] for c in t._client.calls] == ["SetConfiguration"]


class TestParseRunData:
    _CSV = (
        "Elapsed time [ms];Target temperature [1/100 C];Current temperature [1/100 C];Lid temperature [1/100 C]\r\n"
        "102;3028;3035;7110\r\n1083;2998;3029;7225\r\n"
    )

    def _payload(self, csv):
        import html

        inner = (
            '<?xml version="1.0" encoding="utf-8"?><containerData version="1.0">'
            '<experimentStep name="Temperature Trace">'
            '<dataSeries nameId="2026-09-23T17-56-50Z" unit="CSV"><seriesValueSet>'
            f'<stringValue mapId="">{csv}</stringValue></seriesValueSet></dataSeries></experimentStep></containerData>'
        )
        return f'<?xml version="1.0"?><ResponseData><AnyData>{html.escape(inner)}</AnyData></ResponseData>'

    def test_real_device_shape_becomes_rows_in_degrees(self):
        rows = odtc_module._parse_run_data(self._payload(self._CSV))
        assert rows == [
            {"series": "2026-09-23T17-56-50Z", "elapsedMs": 102.0, "targetTemperature": 30.28,
             "currentTemperature": 30.35, "lidTemperature": 71.1},
            {"series": "2026-09-23T17-56-50Z", "elapsedMs": 1083.0, "targetTemperature": 29.98,
             "currentTemperature": 30.29, "lidTemperature": 72.25},
        ]

    def test_comma_separator_is_detected_from_the_header(self):
        rows = odtc_module._parse_run_data(self._payload(self._CSV.replace(";", ",")))
        assert len(rows) == 2 and rows[0]["currentTemperature"] == 30.35

    def test_unrecognised_payload_falls_back_to_raw(self):
        assert odtc_module._parse_run_data("<foo/>") == [{"raw": "<foo/>"}]
        assert odtc_module._parse_run_data("  ") == []


class TestSimCycleCount:
    def test_loop_number_n_runs_n_plus_one_passes(self):
        # The real unit runs the block once and then LoopNumber more times.
        from hamilton_venus.odtc_protocol import ODTCStep

        for repeats in (1, 2, 3):
            t = _SimODTCTransport(1)
            t.connect("x", "8080", "", True)
            builder = ODTCProtocolBuilder("C")
            builder.add_cycle(
                [ODTCStep(temperature=95, hold_seconds=1), ODTCStep(temperature=60, hold_seconds=1)],
                repeats=repeats,
            )
            t.set_method(render_protocol_xml(builder.build()))
            t.wait_for_end_of_execute_method(t.execute_method("C", 1), 60)
            # each pass reaches the 60 C plateau once (the log records the step number reached)
            passes = sum(
                1 for row in t.get_last_data() if row["step"] == 2 and row["target"] == 60 and row["current"] == 60
            )
            assert passes == repeats + 1, (repeats, passes)


class TestTraceFiles:
    _FILE = (
        "********************************************************\r\n"
        "* ODTC Temperature trace = Trace3Cycle = 2026-09-23T17:24:36Z\r\n"
        "* Firmware: BUILD:1 / Hardware: x\r\n"
        "********************************************************\r\n"
        "Elapsed time [ms];Target temperature [1/100\xb0C];Current temperature [1/100\xb0C];"
        "Lid temperature [1/100\xb0C];PWM\r\n"
        "259;2500;4100;10993;-1000\r\n"
        "460;9500;9410;10990;500\r\n"
        ";End of trace.\r\n"
    )

    def test_parses_header_and_the_four_main_columns(self):
        header, rows = odtc_module.parse_trace_csv(self._FILE)
        assert header == {"methodName": "Trace3Cycle", "startedAt": "2026-09-23T17:24:36Z"}
        assert rows == [
            {"elapsedMs": 259.0, "targetTemperature": 25.0, "currentTemperature": 41.0, "lidTemperature": 109.93},
            {"elapsedMs": 460.0, "targetTemperature": 95.0, "currentTemperature": 94.1, "lidTemperature": 109.9},
        ]

    def test_garbage_gives_no_rows_and_no_error(self):
        assert odtc_module.parse_trace_csv("nothing useful here") == ({"methodName": "", "startedAt": ""}, [])
