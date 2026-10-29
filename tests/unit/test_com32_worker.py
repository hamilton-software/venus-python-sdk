"""Unit tests for the generic 32-bit COM worker (hamilton_venus._com32_worker).

Parametrized over both ProgIDs the SDK drives through this worker today
(Hamilton Heater Cooler, Inheco ODTC) to prove the worker really is
ProgID-agnostic rather than accidentally still HHC-shaped.
"""

from __future__ import annotations

import io

import pytest

from hamilton_venus import _com32_worker

_PROGIDS = [
    "HamiltonHeaterCoolerCOM.HamiltonHeaterCoolerHSLCOM",
    "Inheco.ODTCInterface",
]


class TestParseArgs:
    def test_progid_and_bin_dirs(self):
        progid, bin_dirs, tl_bin_dir, selftest = _com32_worker._parse_args(
            ["Some.ProgId", "--bin-dir", "C:\\a", "--bin-dir", "C:\\b", "--tl-bin-dir", "C:\\tl"]
        )
        assert progid == "Some.ProgId"
        assert bin_dirs == ["C:\\a", "C:\\b"]
        assert tl_bin_dir == "C:\\tl"
        assert selftest is False

    def test_selftest_flag(self):
        _progid, _bin_dirs, _tl, selftest = _com32_worker._parse_args(["Some.ProgId", "--selftest"])
        assert selftest is True

    def test_no_tl_bin_dir_is_none(self):
        _progid, _bin_dirs, tl_bin_dir, _selftest = _com32_worker._parse_args(["Some.ProgId"])
        assert tl_bin_dir is None


@pytest.mark.parametrize("progid", _PROGIDS)
class TestWorkerLoop:
    def test_worker_loop_dispatches_and_reports(self, monkeypatch, progid):
        class FakeCom:
            def __init__(self, _progid, _bin_dirs):
                pass

            def call(self, name, args):
                assert name == "GetTemperature"
                return [0, 21.0]

        monkeypatch.setattr(_com32_worker, "_Com", FakeCom)
        monkeypatch.setattr(
            _com32_worker.sys,
            "stdin",
            io.StringIO('{"call": "GetTemperature", "args": ["X-1"]}\n{"call": "__shutdown__"}\n'),
        )
        out = io.StringIO()
        monkeypatch.setattr(_com32_worker.sys, "stdout", out)
        assert _com32_worker.main([progid]) == 0
        assert '"ok": true' in out.getvalue()
        assert "21.0" in out.getvalue()

    def test_worker_reports_exceptions(self, monkeypatch, progid):
        class BoomCom:
            def __init__(self, _progid, _bin_dirs):
                pass

            def call(self, name, args):
                raise RuntimeError("no device")

        monkeypatch.setattr(_com32_worker, "_Com", BoomCom)
        monkeypatch.setattr(_com32_worker.sys, "stdin", io.StringIO('{"call": "Connect", "args": []}\n'))
        out = io.StringIO()
        monkeypatch.setattr(_com32_worker.sys, "stdout", out)
        _com32_worker.main([progid])
        assert '"ok": false' in out.getvalue()
        assert "no device" in out.getvalue()

    def test_ping_creates_com_object_without_dispatch(self, monkeypatch, progid):
        created = []

        class TrackingCom:
            def __init__(self, _progid, _bin_dirs):
                created.append(_progid)

            def _ensure(self):
                return object()

        monkeypatch.setattr(_com32_worker, "_Com", TrackingCom)
        monkeypatch.setattr(
            _com32_worker.sys, "stdin", io.StringIO('{"call": "__ping__"}\n{"call": "__shutdown__"}\n')
        )
        out = io.StringIO()
        monkeypatch.setattr(_com32_worker.sys, "stdout", out)
        assert _com32_worker.main([progid]) == 0
        assert created == [progid]
        assert '"ok": true' in out.getvalue()


class TestMainRequiresProgid:
    def test_missing_progid_returns_error(self, capsys):
        assert _com32_worker.main([]) == 2
        assert "usage" in capsys.readouterr().err
