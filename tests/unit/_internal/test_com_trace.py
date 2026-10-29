"""Unit tests for hamilton_venus._internal._com_trace."""

from __future__ import annotations

from datetime import date

import pytest

from hamilton_venus._internal import _com_trace
from hamilton_venus._internal._com_trace import (
    DEFAULT_LOGFILES_DIR,
    ComTraceTailer,
    com_trace_filename,
    com_trace_prefix,
    iter_line_batches,
    resolve_com_trace_path,
    resolve_logfiles_dir,
)
from hamilton_venus.models import InstrumentType


class TestPrefixAndPath:
    def test_prefix_live_star_is_usb(self):
        assert com_trace_prefix(InstrumentType.STAR, simulate=False) == "HxUsbComm"

    def test_prefix_live_vantage_is_tcpip(self):
        assert com_trace_prefix(InstrumentType.Vantage, simulate=False) == "HxTcpIpBdzComm"

    def test_prefix_simulated_is_simulator_regardless_of_instrument(self):
        assert com_trace_prefix(InstrumentType.STAR, simulate=True) == "ComTrace_Simulator"
        assert com_trace_prefix(InstrumentType.Vantage, simulate=True) == "ComTrace_Simulator"

    def test_prefix_live_nimbus_raises(self):
        with pytest.raises(ValueError):
            com_trace_prefix(InstrumentType.Nimbus8, simulate=False)

    def test_filename_uses_the_given_date(self):
        assert (
            com_trace_filename(InstrumentType.STAR, False, date(2025, 5, 9))
            == "HxUsbComm20250509.trc"
        )
        assert (
            com_trace_filename(InstrumentType.Vantage, False, date(2025, 2, 13))
            == "HxTcpIpBdzComm20250213.trc"
        )
        assert (
            com_trace_filename(InstrumentType.STAR, True, date(2026, 8, 28))
            == "ComTrace_Simulator20260828.trc"
        )

    def test_resolve_path_empty_dir_uses_default(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: None)
        path = resolve_com_trace_path("", InstrumentType.STAR, True, date(2026, 8, 28))
        assert str(path).startswith(DEFAULT_LOGFILES_DIR)
        assert path.name == "ComTrace_Simulator20260828.trc"

    def test_resolve_path_uses_given_dir(self, tmp_path):
        path = resolve_com_trace_path(str(tmp_path), InstrumentType.STAR, False, date(2025, 1, 1))
        assert path == tmp_path / "HxUsbComm20250101.trc"


def _tailer(tmp_path, *, when=date(2025, 1, 1), **kw):
    return ComTraceTailer(
        str(tmp_path),
        InstrumentType.STAR,
        simulate=False,
        when=when,
        clock=lambda: when,
        **kw,
    )


class TestComTraceTailer:
    def test_reads_only_bytes_appended_after_construction(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"< 10:00:00.000 X: PRE\r\n")
        tailer = _tailer(tmp_path)  # start_offset defaults to current size
        assert tailer.read_new_lines() == []
        with trc.open("ab") as fh:
            fh.write(b"< 10:00:00.001 X: A\r\n> 10:00:00.002 X: B\r\n")
        assert tailer.read_new_lines() == ["< 10:00:00.001 X: A", "> 10:00:00.002 X: B"]

    def test_start_offset_zero_reads_whole_file(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"< a\r\n< b\r\n< c\r\n")
        tailer = _tailer(tmp_path, start_offset=0)
        assert tailer.read_new_lines() == ["< a", "< b", "< c"]

    def test_partial_trailing_line_is_buffered_until_newline(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"")
        tailer = _tailer(tmp_path)
        with trc.open("ab") as fh:
            fh.write(b"< 10:00:00.001 X: HELLO")  # no newline yet
        assert tailer.read_new_lines() == []
        with trc.open("ab") as fh:
            fh.write(b"\r\n> 10:00:00.002 X: WORLD\r\n")
        assert tailer.read_new_lines() == [
            "< 10:00:00.001 X: HELLO",
            "> 10:00:00.002 X: WORLD",
        ]

    def test_flush_partial_returns_the_unterminated_tail(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"< a\r\n< partial")
        tailer = _tailer(tmp_path, start_offset=0)
        assert tailer.read_new_lines(flush_partial=True) == ["< a", "< partial"]

    def test_missing_file_then_appears(self, tmp_path):
        tailer = _tailer(tmp_path)
        assert tailer.read_new_lines() == []
        (tmp_path / "HxUsbComm20250101.trc").write_bytes(b"< 1\r\n< 2\r\n")
        assert tailer.read_new_lines() == ["< 1", "< 2"]

    def test_truncation_resets_offset(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"< a\r\n< b\r\n< c\r\n")
        tailer = _tailer(tmp_path, start_offset=0)
        assert len(tailer.read_new_lines()) == 3
        trc.write_bytes(b"< x\r\n")  # rewritten shorter
        assert tailer.read_new_lines() == ["< x"]

    def test_non_utf8_bytes_do_not_raise(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"> 10:00:00.003 X: \x80\xff\r\n")
        tailer = _tailer(tmp_path, start_offset=0)
        lines = tailer.read_new_lines()
        assert len(lines) == 1

    def test_midnight_rollover_drains_old_then_follows_new_file(self, tmp_path):
        current = {"day": date(2025, 1, 5)}
        (tmp_path / "HxUsbComm20250105.trc").write_bytes(b"< day1a\r\n")
        tailer = ComTraceTailer(
            str(tmp_path),
            InstrumentType.STAR,
            simulate=False,
            start_offset=0,
            clock=lambda: current["day"],
        )
        assert tailer.path.name == "HxUsbComm20250105.trc"
        assert tailer.read_new_lines() == ["< day1a"]

        with (tmp_path / "HxUsbComm20250105.trc").open("ab") as fh:
            fh.write(b"< day1b\r\n")
        current["day"] = date(2025, 1, 6)
        (tmp_path / "HxUsbComm20250106.trc").write_bytes(b"< day2a\r\n< day2b\r\n")

        assert tailer.read_new_lines() == ["< day1b", "< day2a", "< day2b"]
        assert tailer.path.name == "HxUsbComm20250106.trc"

    def test_pinned_when_never_rolls_over(self, tmp_path):
        (tmp_path / "HxUsbComm20250101.trc").write_bytes(b"< a\r\n")
        # clock is "today" but `when` is pinned -> stays on the pinned file.
        tailer = ComTraceTailer(
            str(tmp_path),
            InstrumentType.STAR,
            simulate=False,
            when=date(2025, 1, 1),
            start_offset=0,
            clock=lambda: date(2030, 6, 1),
        )
        assert tailer.read_new_lines() == ["< a"]
        assert tailer.path.name == "HxUsbComm20250101.trc"

    def test_max_bytes_bounds_a_single_read(self, tmp_path):
        trc = tmp_path / "HxUsbComm20250101.trc"
        trc.write_bytes(b"< aaaa\r\n< bbbb\r\n< cccc\r\n")
        tailer = _tailer(tmp_path, start_offset=0)
        first = tailer.read_new_lines(max_bytes=8)  # only "< aaaa\r\n"
        assert first == ["< aaaa"]
        rest = tailer.read_new_lines()
        assert rest == ["< bbbb", "< cccc"]


class TestResolveLogfilesDir:
    def test_explicit_dir_wins(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "fetch_logfiles_dir", lambda *a, **k: "D:\\from-api")
        assert resolve_logfiles_dir("D:\\explicit", "http://localhost:42400") == "D:\\explicit"

    def test_falls_back_to_api(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "fetch_logfiles_dir", lambda url, **k: "D:\\from-api")
        assert resolve_logfiles_dir("", "http://localhost:42400") == "D:\\from-api"

    def test_falls_back_to_the_registry_when_api_fails(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "fetch_logfiles_dir", lambda *a, **k: None)
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: "E:\\VENUS\\Logfiles")
        assert resolve_logfiles_dir("", "http://localhost:42400") == "E:\\VENUS\\Logfiles"

    def test_default_when_no_base_url_and_no_registry(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: None)
        assert resolve_logfiles_dir("") == DEFAULT_LOGFILES_DIR


class TestIterLineBatches:
    def test_line_cap(self):
        lines = [f"l{i}" for i in range(10)]
        batches = list(iter_line_batches(lines, max_bytes=0, max_lines=3))
        assert [len(b) for b in batches] == [3, 3, 3, 1]

    def test_byte_cap(self):
        lines = ["ab", "cd", "ef", "gh"]  # 3 bytes each incl. newline
        batches = list(iter_line_batches(lines, max_bytes=6, max_lines=0))
        assert [len(b) for b in batches] == [2, 2]

    def test_oversized_line_emitted_alone(self):
        big = "x" * 200_000
        batches = list(iter_line_batches(["a", big, "b"], max_bytes=64 * 1024, max_lines=400))
        assert batches == [["a"], [big], ["b"]]

    def test_empty_input(self):
        assert list(iter_line_batches([], max_bytes=10, max_lines=10)) == []

    def test_both_caps_disabled_is_one_batch(self):
        lines = [f"l{i}" for i in range(5)]
        assert list(iter_line_batches(lines, max_bytes=0, max_lines=0)) == [lines]
