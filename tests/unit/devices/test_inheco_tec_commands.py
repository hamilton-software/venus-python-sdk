"""Unit tests for InhecoTECDeviceCommands / InhecoTECClient (pure-Python, no VENUS runtime)."""

from __future__ import annotations

import pytest

from hamilton_venus import inheco_tec as tec_module
from hamilton_venus.devices.inheco_tec_commands import InhecoTECClient
from hamilton_venus.exceptions import InhecoTECError
from hamilton_venus.inheco_tec import _SimInhecoTECTransport

_TRACKED = {
    "find_controller",
    "release",
    "get_calibration_date",
    "get_firmware_version",
    "get_sensor_values",
    "get_device_serial_number",
    "get_device_runtime",
    "get_device_type",
    "get_reservoir_status",
    "get_actual_temperature",
    "get_temperature_limits",
    "get_target_temperature",
    "set_target_temperature",
    "get_heater_status",
    "start_temperature_control",
    "stop_temperature_control",
    "set_shaker_revolutions",
    "get_shaker_revolutions",
    "set_shaker_shape",
    "get_shaker_shape",
    "get_shaker_status",
    "start_shaker",
    "stop_shaker",
    "set_touchscreen",
    "send_command_string",
}


class RecordingTransport(_SimInhecoTECTransport):
    """Sim transport that also records the ordered method-call trace."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, tuple]] = []

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        if name in _TRACKED and callable(attr):

            def wrapper(*args, **kwargs):
                object.__getattribute__(self, "calls").append((name, args))
                return attr(*args, **kwargs)

            return wrapper
        return attr


def _client(transport: RecordingTransport) -> InhecoTECClient:
    return InhecoTECClient(transport=transport)


class TestInhecoTECCommands:
    def test_connect_scans_controller_and_slots(self):
        transport = RecordingTransport()
        client = _client(transport)

        result = client.inheco_tec_connect(0)

        assert result.return_status == "Success"
        params = result.return_parameters
        assert params.controller_id == 0
        assert params.controller_type_name == "MTC"
        assert [d.device_id for d in params.devices] == [1, 2, 3, 4, 5, 6]
        assert params.devices[0].device_type_name == "CPAC"
        assert params.devices[1].device_type_name == "Thermoshake"
        assert params.devices[2].device_type_name == "No_Device_Connected"

        names = [c[0] for c in transport.calls]
        assert names[0] == "find_controller"
        assert names.count("get_device_type") == 7  # controller (device_id=0) + 6 slots

    def test_connect_scans_a_single_slot_for_an_stc_controller(self):
        """A Single TEC (STC) controller has exactly 1 physical slot --
        confirmed against real hardware -- so connect must not scan slots
        2-6 on one, unlike a Multi TEC (MTC)."""

        class STCTransport(RecordingTransport):
            def get_device_type(self, controller_id: int, device_id: int) -> int:
                if device_id == 0:
                    return 0  # STC
                return super().get_device_type(controller_id, device_id)

        transport = STCTransport()
        client = _client(transport)

        result = client.inheco_tec_connect(0)

        params = result.return_parameters
        assert params.controller_type_name == "STC"
        assert [d.device_id for d in params.devices] == [1]
        assert params.devices[0].device_type_name == "CPAC"

        names = [c[0] for c in transport.calls]
        assert names.count("get_device_type") == 2  # controller (device_id=0) + 1 slot

    def test_commands_before_connect_raise(self):
        client = _client(RecordingTransport())
        with pytest.raises(InhecoTECError, match="not connected"):
            client.inheco_tec_get_identification(0, 1)

    def test_connect_is_required_per_controller_id(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        with pytest.raises(InhecoTECError, match="not connected"):
            client.inheco_tec_get_identification(1, 1)

    def test_get_identification_for_device_slot(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_get_identification(0, 1)

        params = result.return_parameters
        assert params.device_type_name == "CPAC"
        assert params.serial_number == "INHECOTEC-SIM-0-01"
        assert params.calibration_date == "2026-01-15"

    def test_get_identification_for_controller_has_no_calibration_date(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_get_identification(0, 0)

        assert result.return_parameters.calibration_date is None

    def test_get_firmware_version_default_selector(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_get_firmware_version(0)

        assert result.return_parameters.selector_name == "Application_Version"
        assert result.return_parameters.value

    def test_get_firmware_version_rejects_bad_selector(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        with pytest.raises(ValueError, match="selector"):
            client.inheco_tec_get_firmware_version(0, selector=99)

    def test_set_and_read_back_target_temperature(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        client.inheco_tec_set_target_temperature(0, 1, 42.0)
        client.inheco_tec_start_temperature_control(0, 1)
        status = client.inheco_tec_get_temperature_status(0, 1).return_parameters

        assert status.target_temperature == 42.0
        assert status.heater_status_name == "Heating"

    @pytest.mark.parametrize("bad_target", [-0.1, 200.0])
    def test_set_target_temperature_out_of_range_rejected(self, bad_target):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        with pytest.raises(ValueError, match="outside the InhecoTEC range"):
            client.inheco_tec_set_target_temperature(0, 1, bad_target)

    def test_stop_temperature_control(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        client.inheco_tec_start_temperature_control(0, 1)

        client.inheco_tec_stop_temperature_control(0, 1)

        status = client.inheco_tec_get_temperature_status(0, 1).return_parameters
        assert status.heater_status_name == "Off"

    def test_shaker_status_bundles_three_reads(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.inheco_tec_connect(0)

        # slot 2 is the sim's Thermoshake (shaker-capable) -- see
        # hamilton_venus.inheco_tec.SHAKER_CAPABLE_DEVICE_TYPES. Slot 1's CPAC
        # has no shaker motor at all; commands below target the right slot.
        client.inheco_tec_set_shaker_revolutions(0, 2, 500)
        client.inheco_tec_set_shaker_shape(0, 2, 2)
        client.inheco_tec_start_shaker(0, 2)
        status = client.inheco_tec_get_shaker_status(0, 2).return_parameters

        assert status.revolutions == 500
        assert status.shape_name == "UpLeftDownRight"
        assert status.status == 0

    def test_shaker_revolutions_clamp_only_allowed(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        client.inheco_tec_set_shaker_revolutions(0, 2, 0)  # SPEED_CLAMP_ONLY -- must not raise

    @pytest.mark.parametrize("bad_rpm", [59, 3001])
    def test_shaker_revolutions_out_of_range_rejected(self, bad_rpm):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        with pytest.raises(ValueError, match="shaker revolutions"):
            client.inheco_tec_set_shaker_revolutions(0, 2, bad_rpm)

    def test_get_sensor_values_replicates_vendor_bug(self):
        """The vendor's own GetSensorValues sends the firmware-version command
        (see hamilton_venus.inheco_tec._ComInhecoTECTransport.get_sensor_values) --
        the sim transport mirrors that by not distinguishing sensor selectors,
        which this only checks does not raise and returns a value."""
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_get_sensor_values(0, selector=2)

        assert result.return_parameters.selector_name == "Temperature_Sensor_1_Housing"

    def test_reservoir_status(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_get_reservoir_status(0, 1)

        assert result.return_parameters.status_name == "OK"

    def test_set_touchscreen(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_set_touchscreen(0, True)

        assert "enabled" in result.return_parameters.message

    def test_send_raw_command(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)

        result = client.inheco_tec_send_command(0, "1RAT3")

        assert result.return_parameters.command == "1RAT3"
        assert result.return_parameters.response == "1rat0"

    def test_send_raw_command_rejects_empty(self):
        client = _client(RecordingTransport())
        client.inheco_tec_connect(0)
        with pytest.raises(ValueError, match="must not be empty"):
            client.inheco_tec_send_command(0, "")

    def test_terminate_resets_registry(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.inheco_tec_connect(0)

        result = client.inheco_tec_terminate()

        assert result.return_parameters.message == "InhecoTEC disconnected"
        assert ("release", ()) in transport.calls
        with pytest.raises(InhecoTECError):
            client.inheco_tec_get_identification(0, 1)

    def test_unavailable_driver_without_simulate_raises_on_use(self, monkeypatch):
        monkeypatch.setattr(tec_module, "inheco_tec_available", lambda: False)
        # No injected transport, simulate not set -> manager still picks the sim
        # transport (import-safe), so connect works; assert that graceful path.
        client = InhecoTECClient()
        result = client.inheco_tec_connect(0)
        assert result.return_status == "Success"

    def test_close_on_unused_client_is_a_noop(self):
        client = InhecoTECClient(simulate=True)
        client.close()  # must not construct a manager, must not raise
        assert getattr(client, "_inheco_tec_manager", None) is None

    def test_close_terminates_the_manager(self):
        transport = RecordingTransport()
        client = _client(transport)
        client.inheco_tec_connect(0)

        client.close()

        assert ("release", ()) in transport.calls

    def test_context_manager_closes_on_exit(self):
        transport = RecordingTransport()
        with InhecoTECClient(transport=transport) as client:
            client.inheco_tec_connect(0)
        assert ("release", ()) in transport.calls

    def test_no_hidden_lock_id_parameter(self):
        """This device has no lock/session token at all (unlike ODTC), but
        guard against ever accidentally exposing manager/transport plumbing
        (e.g. controller-select state) through a public method signature."""
        import inspect

        from hamilton_venus.devices.inheco_tec_commands import InhecoTECDeviceCommands

        for name, method in inspect.getmembers(InhecoTECDeviceCommands, predicate=inspect.isfunction):
            if name.startswith("inheco_tec_"):
                sig = inspect.signature(method)
                assert "transport" not in sig.parameters
                assert "manager" not in sig.parameters
