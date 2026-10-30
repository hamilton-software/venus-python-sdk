"""Command-group tests for the Hamilton Media Fill Module, through the standalone
``MediaFillClient``."""

from __future__ import annotations

import inspect
import re

import pytest

import hamilton_venus
from hamilton_venus import MediaFillClient, MediaFillError, VenusError
from hamilton_venus import media_fill as mf
from hamilton_venus.devices.media_fill_commands import MediaFillDeviceCommands
from hamilton_venus.media_fill import _ComMediaFillTransport, _SimMediaFillTransport
from hamilton_venus.models import (
    MediaFillConnectResponse,
    MediaFillLiquidLevelSensorStateResponse,
    MediaFillPumpDirectionResponse,
    MediaFillStatusResponse,
    MessageResponse,
    PumpDirection,
)
from hamilton_venus.standalone_devices import STANDALONE_DEVICES, find_standalone_device

# Every public function of the vendor HSL interface (HSLHamiltonMediaFillModule.hsl)
# -> its Python method. The public surface must be exactly these plus the SDK's
# standard get_device_ids / terminate -- nothing the vendor library doesn't have.
HSL_INTERFACE = {
    "Initialize": "media_fill_connect",
    "Disconnect": "media_fill_disconnect",
    "GetPumpDirection": "media_fill_get_pump_direction",
    "SetPumpDirection": "media_fill_set_pump_direction",
    "GetLiquidLevelSensorState": "media_fill_get_liquid_level_sensor_state",
    "FillTrough": "media_fill_fill_trough",
    "WaitForPump": "media_fill_wait_for_pump",
    "GetLastErrorMessage": "media_fill_get_last_error_message",
}
# Vendor COM calls beyond the HSL header: WastePumpNoSensor was dropped from the
# header in 2018 but is still in its .hs_ and in HxMediaFill.dll; 1.3.0 exposes it
# because pumping in *and* out is a requirement.
VENDOR_EXTRA = {"WastePumpNoSensor": "media_fill_waste_pump_no_sensor"}
# Only in the 2.0 library (HxMediaFill.hsl); EmptyLineToSource is 2.0's WastePumpNoSensor.
VENDOR_V2 = {"StopPump": "media_fill_stop_pump", "EmptyLineToSource": "media_fill_waste_pump_no_sensor"}
SDK_STANDARD = {"media_fill_get_device_ids", "media_fill_terminate", "media_fill_get_status"}


def _public_methods() -> set[str]:
    members = inspect.getmembers(MediaFillDeviceCommands, inspect.isfunction)
    return {n for n, _ in members if n.startswith("media_fill_")}


class TestSurface:
    def test_one_method_per_hsl_function_and_nothing_else(self):
        assert _public_methods() == (
            set(HSL_INTERFACE.values()) | set(VENDOR_EXTRA.values()) | set(VENDOR_V2.values()) | SDK_STANDARD
        )

    def test_no_internal_calls_exposed(self):
        # AbortAll is only the HSL's abort handler (it disconnects every module).
        assert not any("abort" in n for n in _public_methods())

    def test_registered_as_standalone_device(self):
        spec = find_standalone_device("media_fill_connect")
        assert spec is not None and spec.client_cls is MediaFillClient
        assert sum(s.prefix == "media_fill_" for s in STANDALONE_DEVICES) == 1

    def test_exports(self):
        assert hamilton_venus.MediaFillClient is MediaFillClient
        assert issubclass(MediaFillError, VenusError)
        from hamilton_venus.devices import MediaFillClient as FromDevices
        from hamilton_venus.mixins.media_fill_commands import MediaFillCommandsMixin

        assert FromDevices is MediaFillClient
        assert MediaFillCommandsMixin is MediaFillDeviceCommands

    def test_simulate_keyword_construction(self):
        # Clients can be built generically as cls(simulate=...)
        client = MediaFillClient(simulate=True)
        assert client._simulate is True


class TestClientFlows:
    def test_connect_direction_fill_wait_sensor_terminate(self):
        with MediaFillClient(simulate=True) as mfm:
            resp = mfm.media_fill_connect("COM5")
            assert isinstance(resp, MediaFillConnectResponse)
            rp = resp.return_parameters
            assert (rp.device_id, rp.com_port, rp.simulated) == (1, 5, True)
            assert rp.firmware_version

            direction = mfm.media_fill_get_pump_direction(1)
            assert isinstance(direction, MediaFillPumpDirectionResponse)
            assert (direction.return_parameters.direction, direction.return_parameters.direction_name) == (
                0,
                "counter_clockwise",
            )
            assert isinstance(mfm.media_fill_set_pump_direction(1, PumpDirection.CLOCKWISE), MessageResponse)
            assert mfm.media_fill_get_pump_direction(1).return_parameters.direction == 1

            sensor = mfm.media_fill_get_liquid_level_sensor_state(1)
            assert isinstance(sensor, MediaFillLiquidLevelSensorStateResponse)
            assert sensor.return_parameters.liquid_level_sensor_state == 0

            assert "filling" in mfm.media_fill_fill_trough(1, 50, 60).return_parameters.message
            assert "finished" in mfm.media_fill_wait_for_pump(1).return_parameters.message
            assert mfm.media_fill_get_liquid_level_sensor_state(1).return_parameters.liquid_level_sensor_state == 1

            ids = mfm.media_fill_get_device_ids().return_parameters.device_ids
            assert [(d.device_id, d.com_port) for d in ids] == [(1, 5)]

            assert "disconnected" in mfm.media_fill_terminate().return_parameters.message
            with pytest.raises(MediaFillError):
                mfm.media_fill_get_pump_direction(1)

    def test_out_of_range_values_reach_the_vendor_object_and_fail_there(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            assert mfm.media_fill_get_last_error_message().return_parameters.error_message == "No error."
            with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_SPEED)):
                mfm.media_fill_fill_trough(1, 10, 60)
            assert mfm.media_fill_get_last_error_message().return_parameters.error_message == mf.VENDOR_BAD_SPEED
            with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_PUMP)):
                mfm.media_fill_get_liquid_level_sensor_state(5)
            with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_COM_PORT)):
                mfm.media_fill_connect(65536)

    def test_sensorless_run_and_status(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect("COM5")
            mfm.media_fill_set_pump_direction(1, PumpDirection.CLOCKWISE)
            assert "without sensor" in mfm.media_fill_waste_pump_no_sensor(1, 30, 5).return_parameters.message
            mfm.media_fill_wait_for_pump(1)
            status = mfm.media_fill_get_status()
            assert isinstance(status, MediaFillStatusResponse)
            rp = status.return_parameters
            assert (rp.device_id, rp.com_port, rp.simulated) == (1, 5, True) and rp.firmware_version
            assert [p.pump_id for p in rp.pumps] == [1, 2, 3, 4]
            directions = [(p.direction, p.direction_name) for p in rp.pumps[:2]]
            assert directions == [(1, "clockwise"), (0, "counter_clockwise")]
            assert [p.liquid_level_sensor_state for p in rp.pumps] == [0, 0, 0, 0]
            assert rp.last_error_message == "No error."
            with pytest.raises(MediaFillError):
                mfm.media_fill_get_status(device_id=2)

    def test_fill_on_a_full_trough_succeeds_and_reports_sensor_on(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            mfm.media_fill_fill_trough(1, 50, 60)
            mfm.media_fill_wait_for_pump(1)
            mfm.media_fill_fill_trough(1, 50, 60)  # already full: no error, nothing pumped
            assert mfm.media_fill_get_last_error_message().return_parameters.error_message == "SENSOR ON"

    def test_direction_names_and_values_accepted(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            mfm.media_fill_set_pump_direction(2, "cw")
            assert mfm.media_fill_get_pump_direction(2).return_parameters.direction == 1
            mfm.media_fill_set_pump_direction(2, 0)
            assert mfm.media_fill_get_pump_direction(2).return_parameters.direction == 0
            mfm.media_fill_set_pump_direction(2, "1")  # e.g. a value parsed from JSON
            assert mfm.media_fill_get_pump_direction(2).return_parameters.direction == 1
            with pytest.raises(MediaFillError, match=re.escape(mf.VENDOR_BAD_DIRECTION)):
                mfm.media_fill_set_pump_direction(2, 2)  # passed through; the vendor object rejects it
            with pytest.raises(ValueError):
                mfm.media_fill_set_pump_direction(2, "up")

    def test_two_modules(self):
        with MediaFillClient(simulate=True) as mfm:
            assert mfm.media_fill_connect(5).return_parameters.device_id == 1
            assert mfm.media_fill_connect(6).return_parameters.device_id == 2
            mfm.media_fill_fill_trough(1, 50, 60, device_id=2)
            mfm.media_fill_wait_for_pump(1, device_id=2)
            state = lambda d: mfm.media_fill_get_liquid_level_sensor_state(1, device_id=d).return_parameters  # noqa: E731
            assert state(2).liquid_level_sensor_state == 1
            assert state(1).liquid_level_sensor_state == 0
            mfm.media_fill_disconnect(device_id=1)
            assert [d.device_id for d in mfm.media_fill_get_device_ids().return_parameters.device_ids] == [2]

    def test_command_before_connect(self):
        with MediaFillClient(simulate=True) as mfm, pytest.raises(MediaFillError, match="media_fill_connect first"):
            mfm.media_fill_fill_trough(1, 50, 60)

    def test_unknown_device_id(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            with pytest.raises(MediaFillError, match="device_id 3"):
                mfm.media_fill_wait_for_pump(1, device_id=3)

    def test_firmware_failure_on_connect_does_not_leave_module_registered(self):
        class FirmwareFails(_SimMediaFillTransport):
            def get_firmware_version(self, instrument_id):
                raise MediaFillError("MediaFill GetFirmwareVersion failed with return code 1")

        with MediaFillClient(transport=FirmwareFails()) as mfm:
            with pytest.raises(MediaFillError, match="GetFirmwareVersion"):
                mfm.media_fill_connect(5)
            assert mfm.media_fill_get_device_ids().return_parameters.device_ids == []

    def test_a_module_that_lost_its_connection_can_be_connected_again(self):
        lost = (
            "Instrument (InstrumentId: 1, COM5) lost connection with the following error message: The port is "
            "closed. Initialize must be called to regain control of the instrument."
        )

        class Unplugged(_SimMediaFillTransport):
            unplugged = False

            def wait_for_pump(self, instrument_id, pump_id):
                if self.unplugged:
                    self.unplugged = False
                    del self._ports[instrument_id]
                    raise self._fail("WaitForPump", lost)
                super().wait_for_pump(instrument_id, pump_id)

        transport = Unplugged()
        with MediaFillClient(transport=transport) as mfm:
            mfm.media_fill_connect(5)
            mfm.media_fill_fill_trough(1, 50, 60)
            transport.unplugged = True
            with pytest.raises(MediaFillError, match=r"no longer connected; call media_fill_connect\('COM5'\) again"):
                mfm.media_fill_wait_for_pump(1)
            assert mfm.media_fill_get_device_ids().return_parameters.device_ids == []
            assert mfm.media_fill_connect(5).return_parameters.device_id == 1


class TestLifecycle:
    def test_close_on_unused_client_is_noop(self):
        client = MediaFillClient(simulate=True)
        client.close()
        assert getattr(client, "_media_fill_manager", None) is None

    def test_with_block_disconnects_on_exit(self):
        with MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            mfm.media_fill_fill_trough(1, 50, 60)
            manager = mfm._media_fill_manager
        assert manager.devices() == []

    def test_with_block_disconnects_on_error_too(self):
        with pytest.raises(RuntimeError), MediaFillClient(simulate=True) as mfm:
            mfm.media_fill_connect(5)
            manager = mfm._media_fill_manager
            raise RuntimeError("script failed mid-fill")
        assert manager.devices() == []


REAL_FIRMWARE = "Media Fill Module V1.00 94821-01 A"  # read from the real module, 2026-10-15


class FirmwareBackend:
    def __init__(self, firmware=REAL_FIRMWARE):
        self.calls = []
        self.firmware = firmware

    def raw_call(self, name, *args):
        self.calls.append(name)
        return {"Initialize": [0, 7], "GetFirmwareVersion": [0, self.firmware]}.get(name, [0])


class TestOverFakeCom:
    def test_client_over_fake_com_backend(self):
        backend = FirmwareBackend()
        with MediaFillClient(transport=_ComMediaFillTransport(backend=backend)) as mfm:
            rp = mfm.media_fill_connect("COM3").return_parameters
            assert (rp.instrument_id, rp.firmware_version, rp.simulated) == (7, REAL_FIRMWARE, False)
            mfm.media_fill_fill_trough(1, 50, 60)
            mfm.media_fill_wait_for_pump(1)
        assert backend.calls == ["Initialize", "GetFirmwareVersion", "FillTrough", "WaitForPump", "Disconnect"]

    @pytest.mark.parametrize("firmware", ["Tilt Module A.0.0.1.0", "Arduino Uno", ""])
    def test_a_device_that_is_not_a_media_fill_module_is_refused_and_released(self, firmware):
        backend = FirmwareBackend(firmware)
        with MediaFillClient(transport=_ComMediaFillTransport(backend=backend)) as mfm:
            with pytest.raises(MediaFillError, match="not a Media Fill Module"):
                mfm.media_fill_connect("COM3")
            assert mfm.media_fill_get_device_ids().return_parameters.device_ids == []
        assert backend.calls == ["Initialize", "GetFirmwareVersion", "Disconnect"]  # nothing else ever sent

    def test_firmware_identity(self):
        assert mf.is_media_fill_firmware(REAL_FIRMWARE)
        assert mf.is_media_fill_firmware("MEDIA FILL MODULE V2")
        assert not mf.is_media_fill_firmware("A.0.0.1.0 2014-05-14 (SSW)")  # the Tilt Module's firmware


class TestStopPumpAndVendorApi:
    def test_stop_pump_in_simulation(self):
        with MediaFillClient(simulate=True) as mfm:
            rp = mfm.media_fill_connect("COM5").return_parameters
            assert rp.vendor_api == "simulated"
            mfm.media_fill_fill_trough(pump_id=2, speed=50, timeout=60)
            assert mfm.media_fill_stop_pump(pump_id=2).return_parameters.message == "pump 2 stopped"
            assert mfm.media_fill_get_status().return_parameters.vendor_api == "simulated"

    def test_stop_pump_on_the_1_1_library_explains(self):
        with MediaFillClient(transport=_ComMediaFillTransport(backend=FirmwareBackend())) as mfm:
            mfm.media_fill_connect("COM5")
            with pytest.raises(MediaFillError, match="media_fill_disconnect stops every pump"):
                mfm.media_fill_stop_pump(pump_id=1)
