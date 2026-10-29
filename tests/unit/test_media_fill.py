"""Unit tests for the Hamilton Media Fill Module driver: simulation transport,
manager, COM transport (against a fake backend) and helpers."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hamilton_venus import media_fill as mf
from hamilton_venus.exceptions import MediaFillError
from hamilton_venus.media_fill import (
    MediaFillManager,
    PumpDirection,
    _ComMediaFillTransport,
    _SimMediaFillTransport,
    direction_name,
    direction_value,
    parse_com_port,
)

# The COM calls the vendor HSL implementation (HSLHamiltonMediaFillModule.hs_)
# makes on Hamilton.HxMediaFillModule, with its argument lists -- the transport
# must use exactly these names and argument order.
HS_CALLS = {
    "Initialize": ("ComPortNumber", "Simulation", "rInstrumentId"),
    "GetFirmwareVersion": ("rInstrumentId", "firmwareVersion"),
    "Disconnect": ("InstrumentId",),
    "GetPumpDirection": ("InstrumentId", "PumpId", "rDirection"),
    "SetPumpDirection": ("InstrumentId", "PumpId", "Direction"),
    "GetLiquidLevelSensorState": ("InstrumentId", "PumpId", "rLiquidLevelSensorState"),
    "FillTrough": ("InstrumentId", "PumpId", "Speed", "Timeout"),
    "WastePumpNoSensor": ("InstrumentId", "PumpId", "Speed", "Timeout"),  # in the .hs_, not the header
    "WaitForPump": ("InstrumentId", "PumpId"),
    "GetLastErrorMessage": ("errorMessage",),
    "AbortAll": (),  # only in the HSL's abort handler
}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


class TestParsing:
    @pytest.mark.parametrize("value,expected", [(5, 5), ("5", 5), ("COM5", 5), (" com12 ", 12)])
    def test_com_port(self, value, expected):
        assert parse_com_port(value) == expected

    @pytest.mark.parametrize("value", [0, -1, "COMX", "", True])
    def test_bad_com_port(self, value):
        with pytest.raises(ValueError):
            parse_com_port(value)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, 0),
            (1, 1),
            (2, 2),  # plain ints go to the vendor object unchanged; it rejects anything but 0/1
            (1.0, 1),
            ("1", 1),
            ("cw", 1),
            ("counter-clockwise", 0),
            ("CLOCKWISE", 1),
            (PumpDirection.CLOCKWISE, 1),
        ],
    )
    def test_direction_value(self, value, expected):
        assert direction_value(value) == expected

    @pytest.mark.parametrize("value", ["up", 1.7, True, None])
    def test_bad_direction(self, value):
        with pytest.raises(ValueError):
            direction_value(value)

    def test_direction_name(self):
        assert (direction_name(0), direction_name(1), direction_name(7)) == (
            "counter_clockwise",
            "clockwise",
            "unknown(7)",
        )

    def test_direction_values_match_hsl_constants(self):
        # DIRECTION_COUNTER_CLOCKWISE(0) / DIRECTION_CLOCKWISE(1) in the vendor .hsl
        assert (int(PumpDirection.COUNTER_CLOCKWISE), int(PumpDirection.CLOCKWISE)) == (0, 1)


# --------------------------------------------------------------------------- #
# Simulation transport: documented vendor behaviour                            #
# --------------------------------------------------------------------------- #


class TestSimTransport:
    def test_pumps_start_counter_clockwise(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        assert [sim.get_pump_direction(inst, p) for p in range(1, 5)] == [0, 0, 0, 0]

    def test_fill_is_asynchronous_and_wait_blocks_until_sensor_triggers(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 0
        sim.fill_trough(inst, 1, 50, 60)
        assert sim.is_running(inst, 1)  # FillTrough returned while the pump runs
        sim.wait_for_pump(inst, 1)
        assert not sim.is_running(inst, 1)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 1

    def test_polling_the_sensor_converges_without_waiting(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 2, 50, 60)
        assert [sim.get_liquid_level_sensor_state(inst, 2) for _ in range(5)][-1] == 1

    @pytest.mark.parametrize("pump_id", [0, 5, -1])
    def test_pump_id_must_be_1_to_4(self, pump_id):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_PUMP)):
            sim.fill_trough(inst, pump_id, 50, 60)
        assert sim.get_last_error_message() == mf.VENDOR_BAD_PUMP

    @pytest.mark.parametrize("speed", [29, 101, 0])
    def test_speed_must_be_30_to_100(self, speed):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_SPEED)):
            sim.fill_trough(inst, 1, speed, 60)

    @pytest.mark.parametrize("speed", [30, 100])
    def test_speed_limits_inclusive(self, speed):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, speed, 60)

    def test_direction_must_be_0_or_1(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_DIRECTION)):
            sim.set_pump_direction(inst, 1, 2)
        sim.set_pump_direction(inst, 1, 1)
        assert sim.get_pump_direction(inst, 1) == 1

    def test_disconnect_stops_pumps_and_forgets_instrument(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, 50, 60)
        sim.disconnect(inst)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_UNKNOWN_INSTRUMENT)):
            sim.get_liquid_level_sensor_state(inst, 1)

    def test_fill_on_an_already_triggered_sensor_succeeds_without_pumping(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, 50, 60)
        sim.wait_for_pump(inst, 1)
        sim.fill_trough(inst, 1, 50, 60)  # the vendor returns 0 here, and its last error reads "SENSOR ON"
        assert not sim.is_running(inst, 1)
        assert sim.get_last_error_message() == mf.VENDOR_SENSOR_ON

    def test_fill_that_times_out_before_the_sensor_triggers(self):
        sim = _SimMediaFillTransport(fill_reaches_sensor=False)
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, 50, 60)
        sim.wait_for_pump(inst, 1)
        assert not sim.is_running(inst, 1)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 0

    def test_sensorless_run_ignores_a_wet_sensor_and_leaves_it_alone(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, 50, 60)
        sim.wait_for_pump(inst, 1)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 1
        sim.waste_pump_no_sensor(inst, 1, 30, 5)  # no "SENSOR ON" short-circuit
        assert sim.is_running(inst, 1)
        sim.wait_for_pump(inst, 1)
        assert not sim.is_running(inst, 1)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 1

    def test_sensorless_run_from_a_dry_sensor_never_trips_it(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.waste_pump_no_sensor(inst, 1, 30, 5)
        sim.wait_for_pump(inst, 1)
        assert sim.get_liquid_level_sensor_state(inst, 1) == 0

    @pytest.mark.parametrize("speed", [29, 101])
    def test_sensorless_run_checks_speed_like_fill(self, speed):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_SPEED_NO_SENSOR)) as info:
            sim.waste_pump_no_sensor(inst, 1, speed, 5)
        assert info.value.error_code == 1
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_PUMP)):
            sim.waste_pump_no_sensor(inst, 5, 50, 5)

    def test_abort_all_stops_pumps_and_disconnects_every_instrument(self):
        sim = _SimMediaFillTransport()
        a, b = sim.initialize(5), sim.initialize(6)
        sim.fill_trough(a, 1, 50, 60)
        sim.abort_all()
        for inst in (a, b):
            with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_UNKNOWN_INSTRUMENT)):
                sim.get_firmware_version(inst)

    def test_last_error_message_reads_no_error_until_a_failure_and_then_keeps_it(self):
        sim = _SimMediaFillTransport()
        assert sim.get_last_error_message() == "No error."
        with pytest.raises(MediaFillError):
            sim.get_firmware_version(99)
        inst = sim.initialize(5)
        sim.get_firmware_version(inst)  # a later success doesn't clear it, as with the vendor object
        assert sim.get_last_error_message() == mf.VENDOR_UNKNOWN_INSTRUMENT

    @pytest.mark.parametrize("com_port", [0, -3, 65536])
    def test_com_port_must_be_1_to_65535(self, com_port):
        sim = _SimMediaFillTransport()
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_COM_PORT)):
            sim.initialize(com_port)
        assert sim.initialize(65535) == 1

    def test_a_port_already_open_is_refused_like_the_vendor_object_does(self):
        sim = _SimMediaFillTransport()
        sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_PORT_IN_USE.format(5))):
            sim.initialize(5)

    def test_instrument_ids_are_the_lowest_free_like_the_vendor_object(self):
        sim = _SimMediaFillTransport()
        assert (sim.initialize(5), sim.initialize(6)) == (1, 2)
        sim.disconnect(1)
        assert sim.initialize(7) == 1

    def test_checks_run_in_the_vendor_order(self):
        sim = _SimMediaFillTransport()
        inst = sim.initialize(5)
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_UNKNOWN_INSTRUMENT)):
            sim.fill_trough(99, 0, 0, 60)  # instrument first
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_PUMP)):
            sim.fill_trough(inst, 0, 0, 60)  # then pump, then speed
        with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_PUMP)):
            sim.set_pump_direction(inst, 9, 9)  # then pump, then direction

    def test_error_text_matches_the_com_transport(self):
        sim = _SimMediaFillTransport()
        with pytest.raises(MediaFillError) as info:
            sim.get_firmware_version(3)
        expected = f"MediaFill GetFirmwareVersion failed with return code 1: {mf.VENDOR_UNKNOWN_INSTRUMENT}"
        assert str(info.value) == expected

    def test_vendor_messages_are_verbatim(self):
        # Copied from HxMediaFill.dll (1.1.6911.25472) -- the "Speeed" typo is the vendor's.
        assert mf.VENDOR_BAD_SPEED.startswith("Error, Speeed variable is out of range")
        assert mf.VENDOR_PORT_IN_USE.format(7) == (
            "Error, unable to connect to instrument on COM7; "
            "an instrument under COM7 is already being controlled by HSL."
        )
        actual = (mf.PUMP_IDS, mf.SPEED_MIN_PERCENT, mf.SPEED_MAX_PERCENT, mf.COM_PORT_MAX)
        assert (range(1, 5), 30, 100, 65535) == actual


# --------------------------------------------------------------------------- #
# Manager                                                                      #
# --------------------------------------------------------------------------- #


class TestManager:
    def test_device_ids_lowest_free_first(self):
        mgr = MediaFillManager(simulate=True)
        assert mgr.connect(5)[0] == 1
        assert mgr.connect(6)[0] == 2
        mgr.disconnect(1)
        assert mgr.connect(7)[0] == 1
        assert sorted(d for d, _, _ in mgr.devices()) == [1, 2]

    def test_same_port_twice_rejected(self):
        mgr = MediaFillManager(simulate=True)
        mgr.connect(5)
        with pytest.raises(MediaFillError, match="already connected"):
            mgr.connect(5)

    def test_unknown_device(self):
        mgr = MediaFillManager(simulate=True)
        with pytest.raises(MediaFillError, match="call media_fill_connect first"):
            mgr.instrument_for(1)

    def test_terminate_disconnects_everything(self):
        mgr = MediaFillManager(simulate=True)
        mgr.connect(5)
        mgr.connect(6)
        mgr.terminate()
        assert mgr.devices() == []

    def test_terminate_falls_back_to_abort_all_when_a_disconnect_fails(self):
        class DisconnectFails(_SimMediaFillTransport):
            aborted = False

            def disconnect(self, instrument_id):
                raise MediaFillError("MediaFill Disconnect failed with return code 1: port closed")

            def abort_all(self):
                self.aborted = True
                super().abort_all()

        transport = DisconnectFails()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.fill_trough(1, 1, 50, 60)
        with pytest.raises(MediaFillError, match="fell back to the vendor AbortAll"):
            mgr.terminate()
        assert transport.aborted and mgr.devices() == []

    def test_failed_disconnect_keeps_the_module_for_terminate_to_retry(self):
        class DisconnectFailsOnce(_SimMediaFillTransport):
            failures = 1

            def disconnect(self, instrument_id):
                if self.failures:
                    self.failures -= 1
                    raise MediaFillError("MediaFill Disconnect failed with return code 1: busy")
                super().disconnect(instrument_id)

        mgr = MediaFillManager(transport=DisconnectFailsOnce())
        mgr.connect(5)
        with pytest.raises(MediaFillError, match="busy"):
            mgr.disconnect(1)
        assert [d for d, _, _ in mgr.devices()] == [1]  # still connected as far as the vendor knows
        mgr.terminate()  # retries Disconnect, which now succeeds
        assert mgr.devices() == []

    def test_falls_back_to_simulation_without_driver(self, monkeypatch):
        monkeypatch.setattr(mf, "media_fill_available", lambda: False)
        assert MediaFillManager().simulated

    def test_injected_transport_is_used(self):
        fake = _SimMediaFillTransport()
        assert MediaFillManager(transport=fake).transport is fake

    # -- what HxMediaFill.dll does after a failed Initialize / a lost connection --------

    OPEN_FAILED = (
        "Failed to connect to Media Fill Module. Check physical connection to the module and Windows manager "
        "connections to insure that the module is properly connected and correct COM port number is provided."
    )

    def _open_fails(self):
        test = self

        class OpenFails(_SimMediaFillTransport):
            """COM9 fails to open once. Like the vendor object, a port it failed to open
            stays reserved (a retry is refused) for the life of its process."""

            closed = 0

            def __init__(self):
                super().__init__()
                self.failing, self.reserved = {9}, set()

            def initialize(self, com_port):
                if com_port in self.reserved:
                    raise self._fail("Initialize", mf.VENDOR_PORT_IN_USE.format(com_port))
                if com_port in self.failing:
                    self.failing.discard(com_port)
                    self.reserved.add(com_port)
                    raise self._fail("Initialize", test.OPEN_FAILED)
                return super().initialize(com_port)

            def close(self):  # the worker process ends; the next one starts clean
                self.closed += 1
                self.reserved.clear()

        return OpenFails()

    def test_failed_connect_with_nothing_connected_ends_the_vendor_process(self):
        transport = self._open_fails()
        mgr = MediaFillManager(transport=transport)
        with pytest.raises(MediaFillError) as info:
            mgr.connect(9)
        assert str(info.value) == f"MediaFill Initialize failed with return code 1: {self.OPEN_FAILED}"
        assert transport.closed == 1 and mgr.devices() == []
        assert mgr.connect(9) == (1, 1)  # a fresh vendor process: the retry works

    def test_failed_connect_beside_connected_modules_says_how_to_free_the_port(self):
        transport = self._open_fails()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        match = r"disconnect them, or call media_fill_terminate\(\), then connect again"
        with pytest.raises(MediaFillError, match=match) as info:
            mgr.connect(9)
        assert self.OPEN_FAILED in str(info.value)
        assert transport.closed == 0  # the connected module keeps running
        assert [d for d, _, _ in mgr.devices()] == [1]
        with pytest.raises(MediaFillError, match="already being controlled by HSL"):
            mgr.connect(9)  # what the vendor object answers while COM5 keeps it alive
        mgr.disconnect(1)
        assert mgr.connect(9) == (1, 1)  # nothing connected any more: a fresh vendor object first
        assert transport.closed == 1

    def test_com_port_out_of_range_is_reported_as_is(self):
        class Tracks(_SimMediaFillTransport):
            closed = 0

            def close(self):
                self.closed += 1

        transport = Tracks()
        mgr = MediaFillManager(transport=transport)
        with pytest.raises(MediaFillError) as info:
            mgr.connect(70000)
        assert str(info.value).endswith(mf.VENDOR_BAD_COM_PORT) and transport.closed == 0

    LOST = (
        "Instrument (InstrumentId: 1, COM5) lost connection with the following error message: The port is closed. "
        "Initialize must be called to regain control of the instrument."
    )

    def test_a_module_the_vendor_lost_is_released_and_can_be_connected_again(self):
        test = self

        class Unplugged(_SimMediaFillTransport):
            def get_pump_direction(self, instrument_id, pump_id):
                del self._ports[instrument_id]  # the vendor object forgets it...
                raise self._fail("GetPumpDirection", test.LOST)  # ...and says so once

        transport = Unplugged()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        match = r"device_id 1 is no longer connected; call media_fill_connect\('COM5'\) again"
        with pytest.raises(MediaFillError, match=match):
            mgr.call(1, transport.get_pump_direction, 1)
        assert mgr.devices() == []
        assert mgr.connect(5) == (1, 1)

    def test_a_restarted_vendor_process_releases_its_modules_on_first_use(self):
        transport = _SimMediaFillTransport()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.abort_all()  # stands in for a worker that died and was restarted: it knows no instruments
        with pytest.raises(MediaFillError, match="no longer connected"):
            mgr.call(1, transport.get_firmware_version)
        assert mgr.devices() == []

    def test_other_errors_keep_the_module(self):
        transport = _SimMediaFillTransport()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        with pytest.raises(MediaFillError) as info:
            mgr.call(1, transport.fill_trough, 1, 10, 60)
        assert str(info.value).endswith(mf.VENDOR_BAD_SPEED)  # unchanged, no hint
        assert [d for d, _, _ in mgr.devices()] == [1]

    def test_call_on_an_unknown_device(self):
        mgr = MediaFillManager(simulate=True)
        with pytest.raises(MediaFillError, match="call media_fill_connect first"):
            mgr.call(3, mgr.transport.get_firmware_version)

    def test_disconnecting_a_module_the_vendor_already_dropped_succeeds(self):
        transport = _SimMediaFillTransport()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.disconnect(1)  # gone on the vendor side
        mgr.disconnect(1)
        assert mgr.devices() == []
        mgr.terminate()  # nothing left, nothing raised

    # -- the SDK restarts a 32-bit worker that ended: a new vendor object, ids from 1 again --

    def test_after_a_restart_a_device_id_never_reaches_another_module(self):
        transport = Restartable()
        mgr = MediaFillManager(transport=transport)
        assert mgr.connect(5) == (1, 1) and mgr.connect(6) == (2, 2)
        transport.restart()
        with pytest.raises(MediaFillError, match=r"device_id 2 \(COM6\) is no longer connected"):
            mgr.call(2, transport.get_firmware_version)
        assert mgr.connect(6) == (2, 1)  # COM6 keeps its device_id; the new vendor object says instrument 1
        with pytest.raises(MediaFillError, match=r"device_id 1 \(COM5\) is no longer connected"):
            mgr.call(1, transport.fill_trough, 1, 50, 60)  # must not pump on COM6 (now instrument 1)
        assert not transport.is_running(1, 1)
        assert mgr.devices() == [(2, 6, 1)]
        assert mgr.connect(5) == (1, 2)
        mgr.call(1, transport.fill_trough, 1, 50, 60)
        assert transport.is_running(2, 1) and transport._ports[2] == 5  # really COM5

    def test_a_new_port_after_a_restart_gets_a_new_device_id(self):
        transport = Restartable()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.restart()
        assert mgr.connect(7) == (2, 1)  # device_id 1 stays COM5's until COM5 is connected again
        with pytest.raises(MediaFillError, match="no longer connected"):
            mgr.instrument_for(1)
        mgr.disconnect(1)  # drops the reservation; nothing to tell the vendor
        assert mgr.connect(8) == (1, 2)

    def test_without_a_restart_signal_an_instrument_id_clash_still_expires_the_old_modules(self):
        transport = _SimMediaFillTransport()  # no epoch(): only the vendor's answers tell
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.abort_all()  # stands in for a new vendor object
        assert mgr.connect(7) == (2, 1)
        with pytest.raises(MediaFillError, match="no longer connected"):
            mgr.call(1, transport.get_firmware_version)
        assert mgr.devices() == [(2, 7, 1)]

    def test_reconnecting_a_port_the_vendor_no_longer_has(self):
        transport = _SimMediaFillTransport()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.abort_all()
        assert mgr.connect(5) == (1, 1)  # not "already connected": the vendor object doesn't have it

    def test_terminate_clears_reservations(self):
        transport = Restartable()
        mgr = MediaFillManager(transport=transport)
        mgr.connect(5)
        transport.restart()
        mgr.terminate()
        assert mgr.connect(9) == (1, 1)


class Restartable(_SimMediaFillTransport):
    """Stands in for the SDK's 32-bit worker: restart() is a new worker process, i.e. a
    new vendor object that knows no modules and hands out instrument ids from 1 again."""

    def __init__(self) -> None:
        super().__init__()
        self.generation = 0

    def epoch(self) -> int:
        return self.generation

    def restart(self) -> None:
        self.generation += 1
        self._ports.clear()
        self._pumps.clear()
        self._last_error = mf.VENDOR_NO_ERROR


# --------------------------------------------------------------------------- #
# COM transport against a fake backend                                         #
# --------------------------------------------------------------------------- #


class FakeBackend:
    """Mimics the _com32 backends: returns ``(returnCode, *outputs)``."""

    def __init__(self, fail: set[str] | None = None, error: str = mf.VENDOR_BAD_SPEED) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.fail = fail or set()
        self.error = error
        self.closed = 0

    def close(self):
        self.closed += 1

    def raw_call(self, name, *args):
        self.calls.append((name, args))
        if name == "GetLastErrorMessage":
            return [0, self.error]
        if name in self.fail:
            return [1]
        return {
            "Initialize": [0, 42],
            "GetFirmwareVersion": [0, "2.1.0"],
            "GetPumpDirection": [0, 1],
            "GetLiquidLevelSensorState": [0, 1],
        }.get(name, [0])


class TestComTransport:
    def test_every_call_matches_the_hsl_implementation(self):
        backend = FakeBackend()
        com = _ComMediaFillTransport(backend=backend)
        assert com.initialize(5) == 42
        assert com.get_firmware_version(42) == "2.1.0"
        com.disconnect(42)
        assert com.get_pump_direction(42, 3) == 1
        com.set_pump_direction(42, 3, 0)
        assert com.get_liquid_level_sensor_state(42, 3) == 1
        com.fill_trough(42, 3, 50, 60)
        com.waste_pump_no_sensor(42, 3, 40, 20)
        com.wait_for_pump(42, 3)
        com.get_last_error_message()
        com.abort_all()
        assert [name for name, _ in backend.calls] == list(HS_CALLS)
        for name, args in backend.calls:
            assert len(args) == len(HS_CALLS[name]), name
        calls = dict(backend.calls)
        assert calls["Initialize"] == (5, 0, 0)  # simulation off; out-param placeholder
        assert calls["GetFirmwareVersion"] == (42, "")
        assert calls["FillTrough"] == (42, 3, 50, 60)  # speed/timeout passed through unchanged
        assert calls["WastePumpNoSensor"] == (42, 3, 40, 20)
        assert calls["SetPumpDirection"] == (42, 3, 0)
        assert calls["AbortAll"] == ()

    def test_abort_all_is_void(self):
        class VoidBackend(FakeBackend):
            def raw_call(self, name, *args):
                super().raw_call(name, *args)
                return None  # AbortAll() returns void

        com = _ComMediaFillTransport(backend=VoidBackend())
        com.abort_all()  # must not raise

    def test_nonzero_return_code_carries_the_vendor_error_message(self):
        com = _ComMediaFillTransport(backend=FakeBackend(fail={"FillTrough"}))
        with pytest.raises(MediaFillError) as info:
            com.fill_trough(42, 1, 10, 60)
        assert str(info.value) == f"MediaFill FillTrough failed with return code 1: {mf.VENDOR_BAD_SPEED}"
        assert info.value.error_code == 1

    def test_errors_the_sdk_raises_itself_have_no_error_code(self):
        assert MediaFillError("no such device_id").error_code is None

    def test_close_releases_the_backend(self):
        backend = FakeBackend()
        _ComMediaFillTransport(backend=backend).close()
        assert backend.closed == 1

    def test_failed_initialize_ends_the_worker_so_the_port_is_free_again(self):
        backend = FakeBackend(fail={"Initialize"}, error=TestManager.OPEN_FAILED)
        mgr = MediaFillManager(transport=_ComMediaFillTransport(backend=backend))
        with pytest.raises(MediaFillError, match="Failed to connect to Media Fill Module"):
            mgr.connect(5)
        assert backend.closed == 1

    def test_lost_connection_through_the_com_transport_releases_the_module(self):
        backend = FakeBackend(fail={"WaitForPump"}, error=TestManager.LOST)
        mgr = MediaFillManager(transport=_ComMediaFillTransport(backend=backend))
        assert mgr.connect(5) == (1, 42)
        with pytest.raises(MediaFillError, match=r"lost connection.*no longer connected"):
            mgr.call(1, mgr.transport.wait_for_pump, 1)
        assert mgr.devices() == []

    def test_com_exception_becomes_media_fill_error(self):
        class Boom(FakeBackend):
            def raw_call(self, name, *args):
                raise OSError("RPC server unavailable")

        with pytest.raises(MediaFillError, match="WaitForPump raised"):
            _ComMediaFillTransport(backend=Boom()).wait_for_pump(1, 1)

    def test_void_and_scalar_returns(self):
        assert _ComMediaFillTransport._split(None) == (0, [])
        assert _ComMediaFillTransport._split(0) == (0, [])
        assert _ComMediaFillTransport._split((1, "x")) == (1, ["x"])

    def test_a_missing_output_value_is_an_error_not_zero(self):
        class NoOuts(FakeBackend):
            def raw_call(self, name, *args):
                super().raw_call(name, *args)
                return 0  # only the return code came back

        com = _ComMediaFillTransport(backend=NoOuts())
        for call in (lambda: com.initialize(5), lambda: com.get_firmware_version(1),
                     lambda: com.get_pump_direction(1, 1), lambda: com.get_liquid_level_sensor_state(1, 1)):
            with pytest.raises(MediaFillError, match="returned no output value"):
                call()

    def test_epoch_follows_the_worker_process(self):
        backend = BridgeLike()
        com = _ComMediaFillTransport(backend=backend)
        start = com.epoch()
        com.initialize(5)  # starts worker 1
        assert com.epoch() == start
        backend._proc.dead = True  # the worker crashed
        assert com.epoch() == start + 1
        com.get_firmware_version(42)  # the bridge starts worker 2 on demand
        assert com.epoch() == start + 1
        com.close()
        assert com.epoch() == start + 2

    def test_no_command_reaches_a_restarted_worker_with_an_old_instrument_id(self):
        backend = BridgeLike()
        mgr = MediaFillManager(transport=_ComMediaFillTransport(backend=backend))
        assert mgr.connect(5) == (1, 42)
        backend._proc.dead = True
        backend.calls.clear()
        with pytest.raises(MediaFillError, match=r"device_id 1 \(COM5\) is no longer connected"):
            mgr.call(1, mgr.transport.fill_trough, 1, 50, 60)
        assert backend.calls == []  # refused before anything was sent

    def test_the_sdk_bridge_still_exposes_what_epoch_reads(self):
        # epoch() watches _com32.Bridge32Backend._proc / InProcBackend32._obj; fail loudly if the SDK changes them.
        bridge = mf._com32.Bridge32Backend("python32.exe", "X.Y")
        inproc = mf._com32.InProcBackend32("X.Y")
        assert bridge._proc is None and not hasattr(inproc, "_proc") and inproc._obj is None


class FakeProc:
    def __init__(self) -> None:
        self.dead = False

    def poll(self):
        return 1 if self.dead else None


class BridgeLike(FakeBackend):
    """A FakeBackend that, like _com32.Bridge32Backend, (re)starts its worker on demand."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._proc = None

    def raw_call(self, name, *args):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = FakeProc()
        return super().raw_call(name, *args)

    def close(self):
        super().close()
        self._proc = None


# --------------------------------------------------------------------------- #
# Discovery / setup (non-Windows paths are deterministic)                      #
# --------------------------------------------------------------------------- #


class TestDiscovery:
    def test_force_enable(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_MEDIA_FILL_FORCE_ENABLE", "1")
        assert mf.media_fill_available() is True

    def test_not_available_off_windows(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(mf.sys, "platform", "linux")
        assert mf.media_fill_available() is False
        assert "not Windows" in mf.media_fill_com_diagnosis()
        assert mf.configure_media_fill() == (True, "not Windows; nothing to configure")

    def test_availability_never_raises(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(mf.sys, "platform", "win32")

        def boom():
            raise RuntimeError("registry exploded")

        monkeypatch.setattr(mf, "_driver_installed", boom)
        assert mf.media_fill_available() is False

    def test_codebase_registration_gives_the_vendor_folder(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_BIN_DIR", raising=False)
        dll = tmp_path / "Vendor Bin" / "HxMediaFill.dll"  # as_uri() percent-encodes the space
        monkeypatch.setattr(
            mf, "_registration", lambda: {"clsid": "{X}", "server": "mscoree.dll", "codebase": dll.as_uri()}
        )
        assert Path(mf._registered_dll()) == dll
        assert Path(mf._vendor_bin_dir()) == dll.parent

    def test_bin_dir_override(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_MEDIA_FILL_BIN_DIR", "/opt/vendor")
        assert mf._vendor_bin_dir() == "/opt/vendor"

    def test_native_registration_uses_the_server_path(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_BIN_DIR", raising=False)
        dll = tmp_path / "HxMediaFill.dll"
        monkeypatch.setattr(mf, "_registration", lambda: {"clsid": "{X}", "server": str(dll)})
        assert mf._registered_dll() == str(dll)
        assert Path(mf._vendor_bin_dir()) == tmp_path

    def test_registration_without_codebase_has_no_folder(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_BIN_DIR", raising=False)
        monkeypatch.setattr(mf, "_registration", lambda: dict(VENDOR_REGISTRATION))
        assert "without a CodeBase" in mf._registered_dll()
        assert mf._vendor_bin_dir() is None

    @pytest.mark.parametrize("progid", [mf.PROGID_V1, mf.PROGID_V2])
    def test_no_transport_layer_redirects(self, monkeypatch, progid):
        # Neither vendor DLL references Hamilton's TransportLayer, so the shared
        # 32-bit host must never get TransportLayer redirects on its behalf.
        seen = {}
        monkeypatch.setattr(mf._com32, "candidate_backends", lambda **kw: seen.update(kw) or [])
        monkeypatch.setattr(mf, "_vendor_bin_dir", lambda: r"C:\Program Files (x86)\Hamilton\Bin")
        mf._candidate_backends(progid)
        assert seen["tl_bin_dir"] is None and seen["progid"] == progid

    # -- CodeBase: HxMediaFill.dll isn't strong-named ---------------------------------

    def test_codebase_problem_when_registered_without_one(self):
        problem = mf._codebase_problem(dict(VENDOR_REGISTRATION))
        assert "without a CodeBase" in problem and "--register-codebase" in problem

    @pytest.mark.parametrize(
        "change",
        [
            {"codebase": "file:///C:/Program Files (x86)/Hamilton/Bin/HxMediaFill.dll"},  # has one
            {"assembly": "HxMediaFill, Version=1.1.6911.25472, Culture=neutral, PublicKeyToken=0123456789abcdef"},
            {"server": r"C:\Vendor\native.dll"},  # not a .NET registration
        ],
    )
    def test_no_codebase_problem(self, change):
        assert mf._codebase_problem({**VENDOR_REGISTRATION, **change}) is None

    def test_no_codebase_problem_when_not_registered(self, monkeypatch):
        monkeypatch.setattr(mf, "_registration", lambda: None)
        assert mf._codebase_problem() is None

    def test_diagnosis_names_the_codebase_problem_first(self, monkeypatch):
        monkeypatch.setattr(mf.sys, "platform", "win32")
        monkeypatch.setattr(mf, "_registration", lambda: dict(VENDOR_REGISTRATION))
        assert "--register-codebase" in mf.media_fill_com_diagnosis()

    def test_vendor_dll_lookup(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_BIN_DIR", raising=False)
        monkeypatch.setattr(mf, "_registration", lambda: dict(VENDOR_REGISTRATION))
        monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
        monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf64"))
        assert mf._vendor_dll() is None
        default = tmp_path / "Hamilton" / "Bin" / "HxMediaFill.dll"
        default.parent.mkdir(parents=True)
        default.write_bytes(b"MZ")
        assert mf._vendor_dll() == str(default)
        override = tmp_path / "elsewhere" / "HxMediaFill.dll"
        override.parent.mkdir()
        override.write_bytes(b"MZ")
        monkeypatch.setenv("HAMILTON_MEDIA_FILL_BIN_DIR", str(override.parent))
        assert mf._vendor_dll() == str(override)

    def test_register_codebase_off_windows(self, monkeypatch):
        monkeypatch.setattr(mf.sys, "platform", "linux")
        assert mf.register_codebase() == (False, "not Windows")

    # -- .NET runtime: HxMediaFill.dll is a .NET 2.0 assembly -------------------------

    def test_runtime_problem_without_net35_or_the_host_setting(self, monkeypatch, tmp_path):
        py32 = str(tmp_path / "python.exe")
        monkeypatch.setattr(mf, "_registration", lambda: dict(VENDOR_REGISTRATION))
        monkeypatch.setattr(mf, "_net35_installed", lambda: False)
        assert "NET Framework 3.5" in mf._runtime_problem(py32)
        mf.ensure_host_config(py32)
        assert mf._runtime_problem(py32) is None  # hosted on .NET 4, like VENUS
        monkeypatch.setattr(mf, "_net35_installed", lambda: True)
        assert mf._runtime_problem(str(tmp_path / "other.exe")) is None

    def test_no_runtime_problem_for_a_net4_registration(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mf, "_registration", lambda: {**VENDOR_REGISTRATION, "runtimeversion": "v4.0.30319"})
        monkeypatch.setattr(mf, "_net35_installed", lambda: False)
        assert mf._runtime_problem(str(tmp_path / "python.exe")) is None


# Values regasm writes under CLSID\{...}\InprocServer32 for the vendor class (lower-cased names, as read back).
VENDOR_REGISTRATION = {
    "clsid": "{00000000-0000-0000-0000-000000000000}",
    "server": "mscoree.dll",
    "class": "Hamilton.HxMediaFillModule",
    "assembly": "HxMediaFill, Version=1.1.6911.25472, Culture=neutral, PublicKeyToken=null",
    "runtimeversion": "v2.0.50727",
    "threadingmodel": "Both",
}


class TestHostConfig:
    """``ensure_host_config``: VENUS's ``<startup>`` setting for the 32-bit COM host."""

    @staticmethod
    def _read(py32: str) -> str:
        return Path(py32 + ".config").read_bytes().decode("utf-8")

    def test_creates_the_config(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        ok, msg = mf.ensure_host_config(py32)
        assert ok, msg
        text = self._read(py32)
        root = ET.fromstring(text.encode())
        startup = root.find("startup")
        assert startup.get("useLegacyV2RuntimeActivationPolicy") == "true"
        assert startup.find("supportedRuntime").get("version") == "v4.0"
        assert mf.HOST_CONFIG_BLOCK in text and mf._host_runs_v2_on_clr4(py32)

    def test_keeps_another_drivers_binding_redirects_and_is_idempotent(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        hhc = (
            '<?xml version="1.0" encoding="utf-8"?>\r\n<configuration>\r\n  <runtime>\r\n'
            '  <!-- hamilton-com32 TransportLayer redirects: X -->\r\n'
            '  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">\r\n  </assemblyBinding>\r\n'
            "  </runtime>\r\n</configuration>\r\n"
        )
        Path(py32 + ".config").write_bytes(hhc.encode())
        assert mf.ensure_host_config(py32)[0]
        text = self._read(py32)
        assert text.replace(mf.HOST_CONFIG_BLOCK.replace("\n", "\r\n"), "") == hhc  # only the block was added
        assert "\n" not in text.replace("\r\n", "")  # in the file's own line endings
        ET.fromstring(text.encode())
        ok, msg = mf.ensure_host_config(py32)
        assert ok and "already" in msg and self._read(py32) == text

    def test_goes_after_config_sections(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        cfg = (
            "<configuration>\n  <configSections>\n    <section name=\"x\" type=\"y\"/>\n  </configSections>\n"
            "</configuration>\n"
        )
        Path(py32 + ".config").write_bytes(cfg.encode())
        assert mf.ensure_host_config(py32)[0]
        root = ET.fromstring(self._read(py32))
        assert [child.tag for child in root] == ["configSections", "startup"]

    def test_leaves_a_config_with_its_own_startup_alone(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        cfg = (
            "<configuration>\n  <startup>\n"
            '    <supportedRuntime version="v2.0.50727"/>\n  </startup>\n</configuration>\n'
        )
        Path(py32 + ".config").write_bytes(cfg.encode())
        ok, msg = mf.ensure_host_config(py32)
        assert not ok and "left unchanged" in msg and self._read(py32) == cfg

    def test_leaves_a_file_that_is_not_a_config_alone(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        Path(py32 + ".config").write_bytes(b"hello\n")
        assert mf.ensure_host_config(py32)[0] is False
        assert self._read(py32) == "hello\n"

    @pytest.mark.parametrize(
        "cfg",
        [
            '<?xml version="1.0"?>\n<configuration/>\n',  # no element to put it in
            '<?xml version="1.0"?><configuration><runtime/></configuration>\n',  # all on one line
        ],
    )
    def test_refuses_an_edit_that_would_not_be_valid_xml(self, tmp_path, cfg):
        py32 = str(tmp_path / "python.exe")
        Path(py32 + ".config").write_bytes(cfg.encode())
        ok, msg = mf.ensure_host_config(py32)
        assert not ok and "left unchanged" in msg and self._read(py32) == cfg

    def test_unreadable_encoding_is_reported_not_raised(self, tmp_path):
        py32 = str(tmp_path / "python.exe")
        Path(py32 + ".config").write_bytes("<configuration></configuration>".encode("utf-16"))
        ok, msg = mf.ensure_host_config(py32)
        assert not ok and "could not read" in msg

    def test_unwritable_folder_is_reported_not_raised(self, tmp_path):
        ok, msg = mf.ensure_host_config(str(tmp_path / "missing" / "python.exe"))
        assert not ok and "could not write" in msg

    def test_configure_sets_up_the_bundled_host(self, monkeypatch, tmp_path):
        py32 = tmp_path / "_com32_py32" / "python.exe"
        py32.parent.mkdir()
        py32.write_bytes(b"MZ")
        monkeypatch.setattr(mf.sys, "platform", "win32")
        monkeypatch.setattr(mf, "_BUNDLED_PY32", str(py32))
        monkeypatch.setattr(mf, "_registration", lambda: {**VENDOR_REGISTRATION, "codebase": "file:///C:/x.dll"})
        ok, msg = mf.configure_media_fill()
        assert ok, msg
        assert mf._host_runs_v2_on_clr4(str(py32))
        assert "bindingRedirect" not in (py32.parent / "python.exe.config").read_text()  # no TransportLayer redirects

    def test_configure_reports_a_missing_codebase(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mf.sys, "platform", "win32")
        monkeypatch.setattr(mf, "_BUNDLED_PY32", str(tmp_path / "absent" / "python.exe"))
        monkeypatch.setattr(mf, "_registration", lambda: dict(VENDOR_REGISTRATION))
        ok, msg = mf.configure_media_fill()
        assert not ok and "--register-codebase" in msg

    def test_configure_never_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mf.sys, "platform", "win32")
        monkeypatch.setattr(mf, "_BUNDLED_PY32", str(tmp_path / "absent" / "python.exe"))  # never the SDK's own

        def boom():
            raise RuntimeError("registry exploded")

        monkeypatch.setattr(mf, "_driver_installed", boom)
        ok, msg = mf.configure_media_fill()
        assert not ok and "registry exploded" in msg


# --------------------------------------------------------------------------- #
# Finding the module on USB / bring-up CLI                                     #
# --------------------------------------------------------------------------- #

#: Replies read from the real module on COM5, 2026-10-15 (raw read-only probe).
REAL_REPLIES = {
    b":11;\n": b":0,Media Fill Module V1.00 94821-01 A;\r\n",
    b":7;\n": b":0,1;\r\n",
    b":10;\n": b":0,1,0,0,0,0;\r\n",
    b":13;\n": b":0,0,0,0,0;\r\n",
}


class FakeSerial:
    """Stands in for pywin32's ``win32file``: answers each written frame from *replies*."""

    def __init__(self, replies):
        self.replies, self.sent, self.pending, self.closed, self.settings = replies, [], b"", False, {}

    def install(self, monkeypatch):
        import types

        dcb = types.SimpleNamespace()
        w = types.ModuleType("win32file")
        w.GENERIC_READ, w.GENERIC_WRITE, w.OPEN_EXISTING = 1, 2, 3
        w.NOPARITY, w.ONESTOPBIT, w.DTR_CONTROL_DISABLE, w.RTS_CONTROL_DISABLE = 0, 0, 0, 0
        w.PURGE_RXCLEAR, w.PURGE_TXCLEAR = 8, 4
        w.CreateFile = lambda *a: "handle"
        w.GetCommState = lambda h: dcb

        def set_state(h, d):
            self.settings = {k: getattr(d, k) for k in ("BaudRate", "ByteSize", "fDtrControl", "fRtsControl")}

        w.SetCommState = set_state
        w.SetCommTimeouts = w.PurgeComm = lambda *a: None

        def write(h, data):
            self.sent.append(data)
            self.pending += self.replies.get(data, b"")

        def read(h, n):
            chunk, self.pending = self.pending[:n], self.pending[n:]
            return 0, chunk

        w.WriteFile, w.ReadFile = write, read
        w.CloseHandle = lambda h: setattr(self, "closed", True)
        pwt = types.ModuleType("pywintypes")
        pwt.error = OSError
        monkeypatch.setitem(sys.modules, "win32file", w)
        monkeypatch.setitem(sys.modules, "pywintypes", pwt)


class TestPortsAndCli:
    # Win32_PnPEntity lines as seen on the bring-up laptop (2026-10-15), plus a second id and noise.
    PNP = (
        "USB\\VID_2341&PID_0043\\754393332353519041C0\tUSB Serial Device (COM5)\n"
        "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\tStandard Serial over Bluetooth link (COM4)\n"
        "USB\\VID_16D0&PID_0613\\1\tRuggeduino (COM12)\n"
        "USB\\VID_2341&PID_0043\\X\tUSB Serial Device\n"  # no COM port in the name: not a port
    )

    def test_parse_keeps_only_media_fill_usb_ids_sorted_numerically(self):
        assert mf._parse_pnp_ports(self.PNP) == [
            ("COM5", "USB Serial Device (COM5)  serial 754393332353519041C0"),
            ("COM12", "Ruggeduino (COM12)  serial 1"),
        ]

    def test_identical_modules_are_told_apart_by_serial(self):
        two = ("USB\\VID_2341&PID_0043\\AAA\tUSB Serial Device (COM5)\n"
               "USB\\VID_2341&PID_0043\\BBB\tUSB Serial Device (COM7)\n")
        assert [(p, d.rsplit(" ", 1)[-1]) for p, d in mf._parse_pnp_ports(two)] == [("COM5", "AAA"), ("COM7", "BBB")]

    def test_the_real_modules_usb_id_is_listed(self):
        assert "VID_2341&PID_0043" in mf.USB_IDS

    def test_find_ports_is_empty_off_windows(self, monkeypatch):
        monkeypatch.setattr(mf.os, "name", "posix")
        assert mf.find_media_fill_ports() == []

    def test_list_ports_cli(self, monkeypatch, capsys):
        monkeypatch.setattr(mf, "find_media_fill_ports", lambda: [("COM5", "USB Serial Device (COM5)")])
        assert mf.main(["--list-ports"]) == 0
        assert "COM5  USB Serial Device (COM5)" in capsys.readouterr().out
        monkeypatch.setattr(mf, "find_media_fill_ports", lambda: [])
        assert mf.main(["--list-ports"]) == 1
        assert "no Media Fill Module found" in capsys.readouterr().out

    def test_raw_queries_are_parsed_and_decoded(self, monkeypatch):
        port = FakeSerial(REAL_REPLIES)
        port.install(monkeypatch)
        monkeypatch.setattr(mf, "_usb_lookup", lambda: [("COM5", "USB Serial Device (COM5)")])
        st = mf.raw_status("COM5")
        assert port.sent == [b":11;\n", b":7;\n", b":10;\n", b":13;\n"]  # the four queries, nothing else
        assert st["firmware"] == "Media Fill Module V1.00 94821-01 A" and st["is_media_fill_module"]
        assert st["sensors"] == {1: 0, 2: 1, 3: 1, 4: 1}  # mask 1: bit 0 set = pump 1 dry; S2-S4 unplugged
        assert st["pump_status"] == {1: 0, 2: 0, 3: 0, 4: 0} and st["pump_status_field0"] == 1
        assert st["directions"] == {1: 0, 2: 0, 3: 0, 4: 0}
        assert port.closed and port.settings == {"BaudRate": 9600, "ByteSize": 8, "fDtrControl": 0, "fRtsControl": 0}

    @pytest.mark.parametrize("command", [5, 6, 8, 9, 12, 14, 15])
    def test_raw_query_refuses_anything_that_is_not_a_pure_query(self, command):
        with pytest.raises(ValueError, match="refusing"):
            mf.raw_query("COM5", [mf.QUERY_FIRMWARE, command])

    @pytest.mark.parametrize("reply,match", [
        (b":0,Tilt Module A.0.0.1.0;\r\n", "not a Media Fill Module"),
        (b"", "no Media Fill reply"),
        (b"garbage\r\n", "no Media Fill reply"),
        (b":1,UNKNOWN COMMAND;\r\n", "answered status 1"),
    ])
    def test_raw_identify_rejects_other_devices(self, monkeypatch, reply, match):
        port = FakeSerial({b":11;\n": reply})
        port.install(monkeypatch)
        monkeypatch.setattr(mf, "_usb_lookup", lambda: None)  # lookup unavailable: firmware check only
        with pytest.raises(MediaFillError, match=match):
            mf.raw_identify("COM9", timeout=0.05)
        assert port.sent == [b":11;\n"] and port.closed

    def test_connect_checks_identity_before_the_vendor_initialize(self):
        class Checked(FakeBackend):
            pass

        backend = Checked()
        com = _ComMediaFillTransport(backend=backend)
        seen = []

        def not_an_mfm(port):
            seen.append(port)
            raise MediaFillError(f"COM{port} answered 'Arduino', which is not a Media Fill Module")

        com.identify = not_an_mfm
        from hamilton_venus import MediaFillClient

        with MediaFillClient(transport=com) as mfm, pytest.raises(MediaFillError, match="not a Media Fill Module"):
            mfm.media_fill_connect("COM8")
        assert seen == [8] and "Initialize" not in [name for name, _ in backend.calls]

    def test_a_port_without_the_usb_id_is_refused_unopened(self, monkeypatch):
        port = FakeSerial(REAL_REPLIES)
        port.install(monkeypatch)
        monkeypatch.setattr(mf, "_usb_lookup", lambda: [("COM5", "USB Serial Device (COM5)")])
        for call in (lambda: mf.raw_identify("COM3"), lambda: mf.raw_status("COM3")):
            with pytest.raises(MediaFillError, match="not a Media Fill Module's USB device"):
                call()
        assert port.sent == []  # never opened, nothing written

    def test_injected_backends_skip_the_raw_check(self):
        assert _ComMediaFillTransport(backend=FakeBackend()).identify(5) is None

    def test_probe_cli_reports_and_never_raises(self, monkeypatch, capsys):
        monkeypatch.setattr(mf, "probe", lambda port: (False, f"probe FAILED on {port}: boom"))
        assert mf.main(["--probe", "COM7"]) == 1
        assert "probe FAILED on COM7" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Vendor library 2.0 (HxMediaFill.HxMediaFillCOM)                              #
# --------------------------------------------------------------------------- #

# The COM calls the 2.0 HSL library (HxMediaFill.hsl) makes on HxMediaFill.HxMediaFillCOM.
HS_CALLS_V2 = {
    "Initialize": ("ComPortNumber", "Simulation", "rInstrumentId"),
    "GetPumpDirection": ("InstrumentId", "PumpId", "rDirection"),
    "Disconnect": ("InstrumentId",),
    "SetPumpDirection": ("InstrumentId", "PumpId", "Direction"),
    "GetLiquidLevelSensorState": ("InstrumentId", "PumpId", "rLiquidLevelSensorState"),
    "FillTrough": ("InstrumentId", "PumpId", "Speed", "Timeout"),
    "EmptyLineToSource": ("InstrumentId", "PumpId", "Speed", "Timeout"),
    "WaitForPump": ("InstrumentId", "PumpId"),
    "StopPump": ("InstrumentId", "PumpId"),
    "GetLastErrorMessage": ("errorMessage",),
    "Abort": (),
}


class FakeBackendV2(FakeBackend):
    """The 2.0 object: Initialize hands out the COM port as the instrument id, no GetFirmwareVersion."""

    def __init__(self, codes: dict[str, int] | None = None, error: str = "") -> None:
        super().__init__(error=error)
        self.codes = codes or {}

    def raw_call(self, name, *args):
        self.calls.append((name, args))
        if name == "GetFirmwareVersion":
            raise AttributeError(f"HxMediaFill.HxMediaFillCOM.{name}")
        if name == "GetLastErrorMessage":
            return [0, self.error]
        if name in self.codes:
            return [self.codes[name], 0]
        if name == "Initialize":
            return [0, args[0]]
        return {
            "GetPumpDirection": [0, 0],
            "GetLiquidLevelSensorState": [0, 1],
        }.get(name, [0])


class TestVendorSelection:
    def _registered(self, monkeypatch, *progids):
        monkeypatch.delenv("HAMILTON_MEDIA_FILL_PROGID", raising=False)
        monkeypatch.setattr(mf, "_registration_for", lambda p: {"clsid": "{X}"} if p in progids else None)

    def test_prefers_the_2_0_library(self, monkeypatch):
        self._registered(monkeypatch, mf.PROGID_V1, mf.PROGID_V2)
        assert mf._progid() == mf.PROGID_V2 and mf.vendor_api() == "2.0"

    def test_falls_back_to_1_1(self, monkeypatch):
        self._registered(monkeypatch, mf.PROGID_V1)
        assert mf._progid() == mf.PROGID_V1 and mf.vendor_api() == "1.1"

    def test_environment_override(self, monkeypatch):
        self._registered(monkeypatch, mf.PROGID_V1, mf.PROGID_V2)
        monkeypatch.setenv("HAMILTON_MEDIA_FILL_PROGID", mf.PROGID_V1)
        assert mf._progid() == mf.PROGID_V1

    def test_nothing_registered_names_both(self, monkeypatch):
        self._registered(monkeypatch)
        monkeypatch.setattr(mf.sys, "platform", "win32")
        assert not mf._driver_installed()
        diagnosis = mf.media_fill_com_diagnosis()
        assert mf.PROGID_V1 in diagnosis and mf.PROGID_V2 in diagnosis

    def test_injected_backend_speaks_1_1_unless_told(self):
        assert _ComMediaFillTransport(backend=FakeBackend()).api == "1.1"
        assert _ComMediaFillTransport(backend=FakeBackendV2(), progid=mf.PROGID_V2).api == "2.0"


class TestComTransportV2:
    def _com(self, backend=None):
        return _ComMediaFillTransport(backend=backend or FakeBackendV2(), progid=mf.PROGID_V2)

    def test_every_call_matches_the_2_0_hsl(self):
        backend = FakeBackendV2()
        com = self._com(backend)
        com._firmware_by_port[7] = "Media Fill Module V1.00 94821-01 A"  # what identify() read on COM7
        assert com.initialize(7) == 7  # 2.0: the instrument id is the COM port
        assert com.get_firmware_version(7) == "Media Fill Module V1.00 94821-01 A"
        com.disconnect(7)
        com.set_pump_direction(7, 3, 0)
        assert com.get_liquid_level_sensor_state(7, 3) == 1
        com.fill_trough(7, 3, 50, 60)
        com.waste_pump_no_sensor(7, 3, 40, 20)
        com.wait_for_pump(7, 3)
        com.stop_pump(7, 3)
        com.get_last_error_message()
        com.abort_all()
        assert [name for name, _ in backend.calls] == list(HS_CALLS_V2)
        for name, args in backend.calls:
            assert len(args) == len(HS_CALLS_V2[name]), name
        calls = dict(backend.calls)
        assert calls["EmptyLineToSource"] == (7, 3, 40, 20)  # pump out: same arguments as WastePumpNoSensor
        assert calls["GetPumpDirection"] == (7, 1, 0)  # the liveness check behind get_firmware_version
        assert "GetFirmwareVersion" not in calls

    def test_firmware_unknown_without_the_serial_query(self):
        com = self._com()
        com.initialize(7)
        assert com.get_firmware_version(7) == ""

    def test_return_code_is_named(self):
        backend = FakeBackendV2(
            codes={"Initialize": 4}, error="The device is already in the collection of connected devices."
        )
        with pytest.raises(MediaFillError, match=r"return code 4 \(GeneralError\): The device is already") as info:
            self._com(backend).initialize(7)
        assert info.value.error_code == 4

    def test_stop_pump_needs_2_0(self):
        with pytest.raises(MediaFillError, match=r"StopPump needs the Media Fill 2.0 library"):
            _ComMediaFillTransport(backend=FakeBackend()).stop_pump(42, 1)

    def test_a_module_the_vendor_no_longer_has_expires_alone(self):
        backend = FakeBackendV2(error=f"The device {mf._VENDOR_NOT_CONNECTED_V2}.")
        mgr = MediaFillManager(transport=self._com(backend))
        first, _ = mgr.connect(5)
        second, _ = mgr.connect(6)
        backend.codes["FillTrough"] = 1
        with pytest.raises(MediaFillError, match="no longer connected"):
            mgr.call(first, mgr.transport.fill_trough, 1, 50, 10)
        assert [d for d, _p, _i in mgr.devices()] == [second]  # the other module is untouched


class TestSimStopPump:
    def test_stops_a_running_pump(self):
        sim = mf._SimMediaFillTransport()
        inst = sim.initialize(5)
        sim.fill_trough(inst, 1, 50, 60)
        assert sim.is_running(inst, 1)
        sim.stop_pump(inst, 1)
        assert not sim.is_running(inst, 1)
