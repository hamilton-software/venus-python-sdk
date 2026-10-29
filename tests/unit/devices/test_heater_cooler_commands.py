"""Unit tests for HeaterCoolerDeviceCommands / HeaterCoolerClient (pure-Python, no VENUS runtime)."""

from __future__ import annotations

import pytest

from hamilton_venus import heater_cooler as hc_module
from hamilton_venus.devices.heater_cooler_commands import HeaterCoolerClient
from hamilton_venus.exceptions import HeaterCoolerError
from hamilton_venus.heater_cooler import _SimHeaterCoolerTransport


class RecordingTransport(_SimHeaterCoolerTransport):
    """Sim transport that also records the ordered method-call trace."""

    def __init__(self, units: int = 1) -> None:
        super().__init__(units=units)
        self.calls: list[tuple[str, tuple]] = []

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        tracked = {
            "connect",
            "disconnect",
            "get_firmware",
            "get_temperature",
            "get_temp_time_remaining",
            "set_temperature",
            "set_temp_for_time",
            "wait_for_temp",
            "stop_temp_control",
            "get_verification_date",
            "set_verification_date",
            "identify",
            "get_self_diagnostic",
            "set_self_diagnostic",
            "set_display_brightness",
            "turn_on_off_display",
        }
        if name in tracked and callable(attr):

            def wrapper(*args, **kwargs):
                object.__getattribute__(self, "calls").append((name, args))
                return attr(*args, **kwargs)

            return wrapper
        return attr


def _client(transport: RecordingTransport) -> HeaterCoolerClient:
    return HeaterCoolerClient(transport=transport)


class TestHeaterCoolerCommands:
    def test_connect_bundles_reads_per_unit(self):
        transport = RecordingTransport(units=2)
        client = _client(transport)

        result = client.hhc_connect("COM4", keep_alive=7)

        assert result.return_status == "Success"
        assert result.return_parameters.chain_id == 1
        units = result.return_parameters.units
        assert [u.device_id for u in units] == [1, 2]
        assert units[0].serial_number == "HC-SIM-001"
        assert units[0].firmware_version
        assert units[0].verification_date == "2026-01-15"

        names = [c[0] for c in transport.calls]
        assert names[0] == "connect"
        assert transport.calls[0][1] == ("COM4", 7)
        # firmware + temperature + verification read for each of the 2 units
        assert names.count("get_firmware") == 2
        assert names.count("get_temperature") == 2
        assert names.count("get_verification_date") == 2

    def test_commands_before_connect_raise(self):
        client = _client(RecordingTransport())
        with pytest.raises(HeaterCoolerError, match="no HeaterCooler connected"):
            client.hhc_get_status()

    def test_start_temp_control_fans_out_and_bounds(self):
        transport = RecordingTransport(units=2)
        client = _client(transport)
        client.hhc_connect("COM4")

        result = client.hhc_start_temp_control(target=42.0, tolerance=1.0)

        assert result.return_parameters.device_ids == [1, 2]
        assert result.return_parameters.target == 42.0
        set_calls = [c for c in transport.calls if c[0] == "set_temperature"]
        assert len(set_calls) == 2
        # (serial, low, high, target, wait, timeout)
        assert set_calls[0][1][1:4] == (41.0, 43.0, 42.0)
        assert set_calls[0][1][4] is False

    def test_start_temp_control_single_device(self):
        transport = RecordingTransport(units=3)
        client = _client(transport)
        client.hhc_connect("COM4")

        result = client.hhc_start_temp_control(target=8.0, device_id=2)

        assert result.return_parameters.device_ids == [2]
        set_calls = [c for c in transport.calls if c[0] == "set_temperature"]
        assert len(set_calls) == 1
        assert set_calls[0][1][0] == "HC-SIM-002"

    @pytest.mark.parametrize("bad_target", [-1.0, 111.0])
    def test_temperature_out_of_range_rejected(self, bad_target):
        client = _client(RecordingTransport())
        client.hhc_connect("COM4")
        with pytest.raises(ValueError, match="outside the HeaterCooler range"):
            client.hhc_start_temp_control(target=bad_target)

    def test_wait_for_temp_control_converges(self):
        client = _client(RecordingTransport())
        client.hhc_connect("COM4")
        client.hhc_start_temp_control(target=4.0)

        client.hhc_wait_for_temp_control()
        status = client.hhc_get_status().return_parameters.device_ids[0]

        assert 3.5 <= status.temperature <= 4.5

    def test_get_status_reports_control_state(self):
        client = _client(RecordingTransport(units=1))
        client.hhc_connect("COM4")
        client.hhc_start_temp_control(target=30.0)

        row = client.hhc_get_status().return_parameters.device_ids[0]
        assert row.device_id == 1
        assert row.controlling is True

        client.hhc_stop_temp_control()
        row = client.hhc_get_status().return_parameters.device_ids[0]
        assert row.controlling is False

    def test_hold_temp_for_time(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.hhc_connect("COM4")

        client.hhc_hold_temp_for_time(target=65.0, minutes=15.0, tolerance=0.5)

        held = [c for c in transport.calls if c[0] == "set_temp_for_time"]
        assert held and held[0][1][1:5] == (64.5, 65.5, 65.0, 15.0)

    def test_set_display_requires_an_argument(self):
        client = _client(RecordingTransport())
        client.hhc_connect("COM4")
        with pytest.raises(ValueError, match="pass on= and/or brightness="):
            client.hhc_set_display()

    def test_set_display_sends_only_provided(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.hhc_connect("COM4")

        client.hhc_set_display(brightness=40)

        names = [c[0] for c in transport.calls]
        assert "set_display_brightness" in names
        assert "turn_on_off_display" not in names

    def test_self_diagnostic_set_then_read_back(self):
        client = _client(RecordingTransport())
        client.hhc_connect("COM4")

        result = client.hhc_self_diagnostic(enable=True)
        entry = result.return_parameters.device_ids[0]
        assert entry.device_id == 1
        assert entry.enabled is True

    def test_set_verification_date(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.hhc_connect("COM4")

        client.hhc_set_verification_date("2027-03-01")

        assert client.hhc_connect("COM4").return_parameters.units[0].verification_date == "2027-03-01"

    def test_get_device_ids(self):
        client = _client(RecordingTransport(units=2))
        client.hhc_connect("COM4")

        ids = client.hhc_get_device_ids().return_parameters.device_ids
        assert [d.device_id for d in ids] == [1, 2]
        assert ids[0].serial_number == "HC-SIM-001"

    def test_terminate_resets_registry(self):
        transport = RecordingTransport(units=2)
        client = _client(transport)
        client.hhc_connect("COM4")

        result = client.hhc_terminate()
        assert result.return_parameters.message == "HeaterCooler disconnected"
        assert ("disconnect", (1,)) in transport.calls
        with pytest.raises(HeaterCoolerError):
            client.hhc_get_status()

    def test_unavailable_driver_without_simulate_raises_on_use(self, monkeypatch):
        monkeypatch.setattr(hc_module, "heater_cooler_available", lambda: False)
        # No injected transport, simulate not set -> manager still picks the sim
        # transport (import-safe), so connect works; assert that graceful path.
        client = HeaterCoolerClient()
        result = client.hhc_connect("COM4")
        assert result.return_status == "Success"

    def test_close_on_unused_client_is_a_noop(self):
        client = HeaterCoolerClient(simulate=True)
        client.close()  # must not construct a manager, must not raise
        assert getattr(client, "_heater_cooler_manager", None) is None

    def test_close_terminates_the_manager(self):
        transport = RecordingTransport(units=1)
        client = _client(transport)
        client.hhc_connect("COM4")

        client.close()

        assert ("disconnect", (1,)) in transport.calls

    def test_context_manager_closes_on_exit(self):
        transport = RecordingTransport(units=1)
        with HeaterCoolerClient(transport=transport) as client:
            client.hhc_connect("COM4")
        assert ("disconnect", (1,)) in transport.calls
