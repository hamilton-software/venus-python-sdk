"""Unit tests for the pure-Python InhecoTEC driver module."""

from __future__ import annotations

import pytest

from hamilton_venus import inheco_tec as tec
from hamilton_venus.exceptions import InhecoTECError
from hamilton_venus.inheco_tec import (
    InhecoTECManager,
    _SimInhecoTECTransport,
    check_controller_id,
    check_device_id,
    check_shaker_revolutions,
    describe_device_error_code,
    inheco_tec_available,
    inheco_tec_com_diagnosis,
    validate_target_temperature,
)


class TestValidation:
    @pytest.mark.parametrize("value", [0, 4, 7])
    def test_controller_id_in_range(self, value):
        assert check_controller_id(value) == value

    @pytest.mark.parametrize("value", [-1, 8])
    def test_controller_id_out_of_range_raises(self, value):
        with pytest.raises(ValueError, match="controller_id"):
            check_controller_id(value)

    @pytest.mark.parametrize("value", [1, 6])
    def test_device_id_in_range(self, value):
        assert check_device_id(value) == value

    @pytest.mark.parametrize("value", [0, 7])
    def test_device_id_out_of_range_raises(self, value):
        with pytest.raises(ValueError, match="device_id"):
            check_device_id(value)

    def test_device_id_allow_controller(self):
        assert check_device_id(0, allow_controller=True) == 0

    def test_shaker_revolutions_clamp_only_is_allowed(self):
        assert check_shaker_revolutions(0) == 0

    @pytest.mark.parametrize("value", [59, 3001])
    def test_shaker_revolutions_out_of_range_raises(self, value):
        with pytest.raises(ValueError, match="shaker revolutions"):
            check_shaker_revolutions(value)

    def test_target_temperature_in_range(self):
        assert validate_target_temperature(37.0) == 37.0

    @pytest.mark.parametrize("target", [-0.1, 200.0])
    def test_target_temperature_out_of_range_raises(self, target):
        with pytest.raises(ValueError, match="outside the InhecoTEC range"):
            validate_target_temperature(target)

    def test_describe_known_device_error_code(self):
        assert describe_device_error_code("G") == "Device temp not OK"

    def test_describe_unknown_device_error_code(self):
        assert describe_device_error_code("Z") == ""


class TestAvailability:
    def test_force_enable_env(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_INHECO_TEC_FORCE_ENABLE", "1")
        assert inheco_tec_available() is True

    def test_driverless_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_INHECO_TEC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(tec.sys, "platform", "win32")
        monkeypatch.setattr(tec, "_inheco_tec_driver_installed", lambda: False)
        assert inheco_tec_available() is False

    def test_64bit_with_driver_and_py32_is_available(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_INHECO_TEC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(tec.sys, "platform", "win32")
        monkeypatch.setattr(tec, "_IS_64BIT", True)
        monkeypatch.setattr(tec, "_inheco_tec_driver_installed", lambda: True)
        monkeypatch.setattr(tec, "find_python32", lambda: r"C:\py32\python.exe")
        assert inheco_tec_available() is True

    def test_64bit_with_driver_no_py32_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_INHECO_TEC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(tec.sys, "platform", "win32")
        monkeypatch.setattr(tec, "_IS_64BIT", True)
        monkeypatch.setattr(tec, "_inheco_tec_driver_installed", lambda: True)
        monkeypatch.setattr(tec, "find_python32", lambda: None)
        assert inheco_tec_available() is False

    def test_32bit_with_driver_is_available(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_INHECO_TEC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(tec.sys, "platform", "win32")
        monkeypatch.setattr(tec, "_IS_64BIT", False)
        monkeypatch.setattr(tec, "_inheco_tec_driver_installed", lambda: True)
        assert inheco_tec_available() is True

    def test_diagnosis_is_a_string(self):
        assert isinstance(inheco_tec_com_diagnosis(), str)
        assert inheco_tec_com_diagnosis()


class TestSimTransport:
    def test_find_controller_always_true(self):
        transport = _SimInhecoTECTransport()
        assert transport.find_controller(0) is True
        assert transport.find_controller(7) is True

    def test_device_type_slot_one_is_a_cpac(self):
        transport = _SimInhecoTECTransport()
        device_type = transport.get_device_type(0, 1)
        assert tec.DEVICE_TYPE_NAMES[device_type] == "CPAC"
        assert device_type not in tec.SHAKER_CAPABLE_DEVICE_TYPES

    def test_device_type_slot_two_is_a_shaker_capable_thermoshake(self):
        transport = _SimInhecoTECTransport()
        device_type = transport.get_device_type(0, 2)
        assert tec.DEVICE_TYPE_NAMES[device_type] == "Thermoshake"
        assert device_type in tec.SHAKER_CAPABLE_DEVICE_TYPES

    def test_remaining_slots_report_no_device(self):
        transport = _SimInhecoTECTransport()
        for device_id in range(3, 7):
            assert tec.DEVICE_TYPE_NAMES[transport.get_device_type(0, device_id)] == "No_Device_Connected"

    def test_controller_type_is_mtc(self):
        transport = _SimInhecoTECTransport()
        assert tec.CONTROLLER_TYPE_NAMES[transport.get_device_type(0, 0)] == "MTC"

    def test_temperature_control_ramps_toward_target(self):
        transport = _SimInhecoTECTransport()
        transport.set_target_temperature(0, 1, 50.0)
        transport.start_temperature_control(0, 1)
        last = transport.get_actual_temperature(0, 1, 3)
        for _ in range(50):
            current = transport.get_actual_temperature(0, 1, 3)
            assert current >= last - 1e-9  # heating: monotonically non-decreasing
            last = current
        assert abs(last - 50.0) < 0.2

    def test_stop_temperature_control_freezes_current(self):
        transport = _SimInhecoTECTransport()
        transport.set_target_temperature(0, 1, 90.0)
        transport.start_temperature_control(0, 1)
        transport.get_actual_temperature(0, 1, 3)
        transport.stop_temperature_control(0, 1)
        before = transport.get_actual_temperature(0, 1, 3)
        after = transport.get_actual_temperature(0, 1, 3)
        assert before == after

    def test_shaker_start_stop(self):
        transport = _SimInhecoTECTransport()
        # slot 2 is the sim's Thermoshake (shaker-capable) -- see SHAKER_CAPABLE_DEVICE_TYPES
        assert transport.get_shaker_status(0, 2) == 2
        transport.start_shaker(0, 2)
        assert transport.get_shaker_status(0, 2) == 0
        transport.stop_shaker(0, 2)
        assert transport.get_shaker_status(0, 2) == 2

    def test_send_command_string_echoes_success(self):
        transport = _SimInhecoTECTransport()
        assert transport.send_command_string(0, "1RAT3") == "1rat0"


class TestInhecoTECManager:
    def test_connect_marks_controller_connected(self):
        manager = InhecoTECManager(simulate=True)
        manager.connect(0)
        assert manager.connected_controllers() == [0]
        manager.require_connected(0)  # must not raise

    def test_connect_is_idempotent(self):
        manager = InhecoTECManager(simulate=True)
        manager.connect(0)
        manager.connect(0)  # vendor Initialize() is idempotent, not an error
        assert manager.connected_controllers() == [0]

    def test_connect_rejects_out_of_range_id(self):
        manager = InhecoTECManager(simulate=True)
        with pytest.raises(ValueError):
            manager.connect(99)

    def test_require_connected_raises_before_connect(self):
        manager = InhecoTECManager(simulate=True)
        with pytest.raises(InhecoTECError, match="not connected"):
            manager.require_connected(0)

    def test_connect_failure_does_not_register(self):
        class AlwaysFail(_SimInhecoTECTransport):
            def find_controller(self, controller_id: int) -> bool:
                return False

        manager = InhecoTECManager(transport=AlwaysFail())
        with pytest.raises(InhecoTECError, match="failed to find"):
            manager.connect(3)
        assert manager.connected_controllers() == []

    def test_terminate_clears_registry_and_releases(self):
        released = {"count": 0}

        class TrackingTransport(_SimInhecoTECTransport):
            def release(self) -> None:
                released["count"] += 1
                super().release()

        manager = InhecoTECManager(transport=TrackingTransport())
        manager.connect(0)
        manager.connect(1)

        manager.terminate()

        assert manager.connected_controllers() == []
        assert released["count"] == 1
        with pytest.raises(InhecoTECError):
            manager.require_connected(0)

    def test_terminate_stops_all_devices_best_effort(self):
        stopped: list[tuple[int, int]] = []

        class TrackingTransport(_SimInhecoTECTransport):
            def stop_shaker(self, controller_id: int, device_id: int) -> None:
                stopped.append(("shaker", controller_id, device_id))
                super().stop_shaker(controller_id, device_id)

            def stop_temperature_control(self, controller_id: int, device_id: int) -> None:
                stopped.append(("temp", controller_id, device_id))
                super().stop_temperature_control(controller_id, device_id)

        manager = InhecoTECManager(transport=TrackingTransport())
        manager.connect(0)

        manager.terminate(stop_all_devices=True)

        kinds = {s[0] for s in stopped}
        assert kinds == {"shaker", "temp"}
        assert len({s[2] for s in stopped}) == tec.DEVICE_MAX - tec.DEVICE_MIN + 1
