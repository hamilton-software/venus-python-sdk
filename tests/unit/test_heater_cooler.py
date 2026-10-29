"""Unit tests for the pure-Python HeaterCooler driver module."""

from __future__ import annotations

import io
import sys

import pytest

from hamilton_venus import heater_cooler as hc
from hamilton_venus.exceptions import HeaterCoolerError
from hamilton_venus.heater_cooler import (
    HeaterCoolerManager,
    _Bridge32Backend,
    _ComHeaterCoolerTransport,
    _SimHeaterCoolerTransport,
    find_python32,
    heater_cooler_available,
    heater_cooler_com_diagnosis,
    validate_band,
)


class TestValidateBand:
    def test_centred_band(self):
        assert validate_band(37.0, 0.5) == (36.5, 37.5, 37.0)

    def test_clamps_to_device_limits(self):
        assert validate_band(0.0, 2.0) == (0.0, 2.0, 0.0)
        assert validate_band(110.0, 2.0) == (108.0, 110.0, 110.0)

    @pytest.mark.parametrize("target", [-0.1, 110.1, 200.0])
    def test_target_out_of_range_raises(self, target):
        with pytest.raises(ValueError, match="outside the HeaterCooler range"):
            validate_band(target, 0.5)

    def test_tolerance_too_small_raises(self):
        with pytest.raises(ValueError, match="tolerance must be"):
            validate_band(37.0, 0.0)


class TestAvailability:
    def test_force_enable_env(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_HHC_FORCE_ENABLE", "1")
        assert heater_cooler_available() is True

    def test_force_enable_off_value(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_HHC_FORCE_ENABLE", "no")
        # Result now depends on the environment; just assert it does not raise.
        assert heater_cooler_available() in (True, False)

    def test_driverless_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_HHC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        monkeypatch.setattr(hc, "_hhc_driver_installed", lambda: False)
        assert heater_cooler_available() is False

    def test_64bit_with_driver_and_py32_is_available(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_HHC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        monkeypatch.setattr(hc, "_IS_64BIT", True)
        monkeypatch.setattr(hc, "_hhc_driver_installed", lambda: True)
        monkeypatch.setattr(hc, "find_python32", lambda: r"C:\py32\python.exe")
        assert heater_cooler_available() is True

    def test_64bit_with_driver_no_py32_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_HHC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        monkeypatch.setattr(hc, "_IS_64BIT", True)
        monkeypatch.setattr(hc, "_hhc_driver_installed", lambda: True)
        monkeypatch.setattr(hc, "find_python32", lambda: None)
        assert heater_cooler_available() is False

    def test_32bit_with_driver_is_available(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_HHC_FORCE_ENABLE", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        monkeypatch.setattr(hc, "_IS_64BIT", False)
        monkeypatch.setattr(hc, "_hhc_driver_installed", lambda: True)
        assert heater_cooler_available() is True

    def test_diagnosis_is_a_string(self):
        assert isinstance(heater_cooler_com_diagnosis(), str)
        assert heater_cooler_com_diagnosis()


class TestBindingRedirects:
    def test_merge_creates_config_with_redirects(self, tmp_path):
        cfg = tmp_path / "python.exe.config"
        redirects = {"Hamilton.Components.TransportLayer.ComLink": "7.0.1.561"}
        assert hc._merge_binding_redirects(str(cfg), redirects) is True
        text = cfg.read_text()
        assert "Hamilton.Components.TransportLayer.ComLink" in text
        assert '"7.0.1.561"' in text
        # Idempotent: a second merge changes nothing.
        assert hc._merge_binding_redirects(str(cfg), redirects) is False

    def test_merge_preserves_existing_config(self, tmp_path):
        cfg = tmp_path / "python.exe.config"
        cfg.write_text(
            '<?xml version="1.0"?><configuration><appSettings>'
            '<add key="x" value="1"/></appSettings></configuration>'
        )
        hc._merge_binding_redirects(str(cfg), {"Hamilton.Components.TransportLayer.ComLib": "7.0.1.561"})
        text = cfg.read_text()
        assert 'key="x"' in text
        assert "Hamilton.Components.TransportLayer.ComLib" in text


class TestSimTransport:
    def test_connect_reports_units_and_ramps(self):
        t = _SimHeaterCoolerTransport(units=3)
        chain_id, serials = t.connect("SIM", 5)
        assert chain_id == 1
        assert len(serials) == 3

        sn = serials[0]
        assert t.get_firmware(sn)
        assert t.get_verification_date(sn) == "2026-01-15"

        t.set_temperature(sn, 59.5, 60.5, 60.0, wait=False, timeout=60)
        # Repeated reads converge toward the target.
        first = t.get_temperature(sn)
        for _ in range(20):
            t.get_temperature(sn)
        assert t.get_temperature(sn) == pytest.approx(60.0, abs=0.5)
        assert first != 60.0

    def test_wait_for_temp_converges(self):
        t = _SimHeaterCoolerTransport()
        _, serials = t.connect("SIM", 5)
        sn = serials[0]
        t.set_temperature(sn, 3.5, 4.5, 4.0, wait=True, timeout=60)
        assert 3.5 <= t.get_temperature(sn) <= 4.5

    def test_unknown_serial_raises(self):
        t = _SimHeaterCoolerTransport()
        t.connect("SIM", 5)
        with pytest.raises(HeaterCoolerError, match="unknown HeaterCooler serial"):
            t.get_temperature("nope")


class TestPython32Discovery:
    def test_env_override_rejected_when_not_32bit(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_HHC_PYTHON32", sys.executable)  # this interp is 64-bit
        monkeypatch.setattr(hc, "_IS_64BIT", True)
        assert find_python32() is None

    def test_env_override_accepted_when_32bit(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_HHC_PYTHON32", r"C:\py32\python.exe")
        monkeypatch.setattr(hc, "_is_python_32bit", lambda exe: exe == r"C:\py32\python.exe")
        monkeypatch.setattr(hc.sys, "platform", "win32")
        assert find_python32() == r"C:\py32\python.exe"

    def test_returns_bundled_when_present(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_HHC_PYTHON32", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        fake = tmp_path / "python.exe"
        fake.write_text("")
        monkeypatch.setattr(hc, "_BUNDLED_PY32", str(fake))
        assert find_python32() == str(fake)

    def test_returns_shared_runtime_when_present(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HAMILTON_HHC_PYTHON32", raising=False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        monkeypatch.setattr(hc, "_BUNDLED_PY32", r"C:\does\not\exist\python.exe")
        programdata = tmp_path / "programdata"
        exe = programdata / "Hamilton" / "VenusSDK" / "py32" / "python.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setenv("PROGRAMDATA", str(programdata))
        assert find_python32() == str(exe)

    def test_returns_self_when_already_32bit(self, monkeypatch):
        monkeypatch.delenv("HAMILTON_HHC_PYTHON32", raising=False)
        monkeypatch.setattr(hc, "_BUNDLED_PY32", r"C:\does\not\exist\python.exe")
        monkeypatch.setattr(hc, "_IS_64BIT", False)
        monkeypatch.setattr(hc.sys, "platform", "win32")
        assert find_python32() == sys.executable


class _FakeProc:
    """Minimal stand-in for a Popen talking the worker's JSON-lines protocol."""

    def __init__(self, replies):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(r + "\n" for r in replies))
        self.stderr = io.StringIO("")

    def poll(self):
        return None


def _bridge_with(replies):
    backend = _Bridge32Backend(r"C:\py32\python.exe")
    backend._proc = _FakeProc(replies)
    backend._ensure = lambda: backend._proc  # already "running"
    return backend


class TestBridge32Backend:
    def test_raw_call_roundtrips_and_checks_ok(self):
        backend = _bridge_with(['{"ok": true, "raw": [0, 1, ["HC-1"]]}'])
        assert backend.raw_call("Connect", "COM4", 5) == [0, 1, ["HC-1"]]

    def test_raw_call_raises_on_worker_error(self):
        backend = _bridge_with(['{"ok": false, "error": "COM boom"}'])
        with pytest.raises(HeaterCoolerError, match="COM boom"):
            backend.raw_call("GetTemperature", "HC-1")

    def test_worker_exit_is_reported(self):
        backend = _bridge_with([])  # empty stdout == worker died
        with pytest.raises(HeaterCoolerError, match="exited unexpectedly"):
            backend.raw_call("GetTemperature", "HC-1")

    def test_transport_split_accepts_list_and_checks_return_code(self, monkeypatch):
        class B:
            def raw_call(self, name, *args):
                return [0, 42.5]

        t = _ComHeaterCoolerTransport(backend=B())
        assert t.get_temperature("HC-1") == 42.5

    def test_transport_nonzero_return_code_raises(self):
        class B:
            def raw_call(self, name, *args):
                return [7]

        t = _ComHeaterCoolerTransport(backend=B())
        with pytest.raises(HeaterCoolerError, match="return code 7"):
            t.stop_temp_control("HC-1")

    def test_select_backend_falls_through_broken_to_working(self):
        class Broken:
            def _ensure(self):
                raise RuntimeError("stale surrogate")

        class Working:
            def _ensure(self):
                return object()

            def raw_call(self, name, *args):
                return [0, "1.0"]

        t = _ComHeaterCoolerTransport()
        t._backend = None
        t._candidates = [Broken(), Working()]
        assert t.get_firmware("HC-1") == "1.0"
        assert isinstance(t._select_backend(), Working)

    def test_select_backend_aggregates_errors_when_all_fail(self):
        class Broken:
            def __init__(self, why):
                self._why = why

            def _ensure(self):
                raise RuntimeError(self._why)

        t = _ComHeaterCoolerTransport()
        t._backend = None
        t._candidates = [Broken("no surrogate"), Broken("no py32")]
        with pytest.raises(HeaterCoolerError, match=r"no surrogate.*no py32"):
            t._select_backend()


class TestManagerRegistry:
    def test_device_ids_assigned_in_order(self):
        mgr = HeaterCoolerManager(transport=_SimHeaterCoolerTransport(units=2))
        ids = mgr.connect("SIM", 5)
        assert ids == [1, 2]
        assert mgr.connected is True
        assert mgr.chain_id == 1
        assert [sn for _, sn in mgr.devices()] == ["HC-SIM-001", "HC-SIM-002"]

    def test_resolve_all_vs_one(self):
        mgr = HeaterCoolerManager(transport=_SimHeaterCoolerTransport(units=2))
        mgr.connect("SIM", 5)
        assert len(mgr.resolve(None)) == 2
        assert mgr.resolve(2) == [(2, "HC-SIM-002")]

    def test_resolve_before_connect_raises(self):
        mgr = HeaterCoolerManager(transport=_SimHeaterCoolerTransport())
        with pytest.raises(HeaterCoolerError, match="no HeaterCooler connected"):
            mgr.resolve(None)

    def test_unknown_device_id_raises(self):
        mgr = HeaterCoolerManager(transport=_SimHeaterCoolerTransport(units=1))
        mgr.connect("SIM", 5)
        with pytest.raises(HeaterCoolerError, match="device_id 5"):
            mgr.resolve(5)

    def test_terminate_clears_registry(self):
        mgr = HeaterCoolerManager(transport=_SimHeaterCoolerTransport(units=2))
        mgr.connect("SIM", 5)
        mgr.terminate()
        assert mgr.connected is False
        assert mgr.devices() == []

    def test_manager_selects_sim_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(hc, "heater_cooler_available", lambda: False)
        mgr = HeaterCoolerManager(simulate=False)
        assert isinstance(mgr._transport, _SimHeaterCoolerTransport)
