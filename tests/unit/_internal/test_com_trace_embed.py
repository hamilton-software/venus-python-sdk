"""Tests for embedding the VENUS COM trace into the run log.

Exercises `_InstrumentSyncClientBase._snapshot_com_trace` /
`_embed_com_trace` through a real `StarClient` context with the async
instrument client stubbed out (same pattern as test_run_log_integration.py).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hamilton_venus.config import RunLogConfig, SdkConfig


@pytest.fixture()
def config() -> SdkConfig:
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture()
def mock_async_star_class():
    with patch(
        "hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient"
    ) as cls:
        instance = cls.return_value
        instance.start = AsyncMock()
        instance.stop = AsyncMock()
        instance.connection_state = "Connected"
        yield cls


def _final_json(directory: Path) -> dict:
    files = [f for f in directory.glob("*_SdkRunLog.json")]
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _sim_trace_path(directory: Path) -> Path:
    return directory / f"ComTrace_Simulator{date.today():%Y%m%d}.trc"


class TestComTraceEmbed:
    def test_embeds_only_bytes_appended_during_the_session(
        self, config, mock_async_star_class, tmp_path
    ):
        from hamilton_venus.star_client import StarClient

        logs = tmp_path / "logs"
        logs.mkdir()
        trc = _sim_trace_path(logs)
        trc.write_bytes(b"< 09:00:00.000 COM1: BEFORE_1\r\n< 09:00:00.001 COM1: BEFORE_2\r\n")

        rlc = RunLogConfig(
            enabled=True,
            output_dir=str(tmp_path),
            include_com_trace=True,
            com_trace_logfiles_dir=str(logs),
        )
        with StarClient(config, simulate=True, run_log=rlc), trc.open("ab") as fh:
            fh.write(
                b"< 09:00:01.000 COM1: DURING_1\r\n"
                b"> 09:00:01.010 COM1: DURING_2\r\n"
                b"! 09:00:01.020 COM1: DURING_3\r\n"
            )

        data = _final_json(tmp_path)
        types = [e["type"] for e in data["log"]]
        assert "com_trace_snapshot" in types
        assert "com_trace" in types

        embedded: list[str] = []
        for entry in data["log"]:
            if entry["type"] == "com_trace":
                embedded.extend(entry["payload"]["lines"])
        assert embedded == [
            "< 09:00:01.000 COM1: DURING_1",
            "> 09:00:01.010 COM1: DURING_2",
            "! 09:00:01.020 COM1: DURING_3",
        ]

    def test_off_when_include_com_trace_is_false(self, config, mock_async_star_class, tmp_path):
        from hamilton_venus.star_client import StarClient

        logs = tmp_path / "logs"
        logs.mkdir()
        _sim_trace_path(logs).write_bytes(b"< 1\r\n< 2\r\n")

        rlc = RunLogConfig(enabled=True, output_dir=str(tmp_path), include_com_trace=False)
        with StarClient(config, simulate=True, run_log=rlc):
            pass

        data = _final_json(tmp_path)
        assert all(e["type"] not in ("com_trace", "com_trace_snapshot") for e in data["log"])

    def test_capture_failure_never_breaks_the_run(
        self, config, mock_async_star_class, tmp_path
    ):
        from hamilton_venus.star_client import StarClient

        rlc = RunLogConfig(
            enabled=True,
            output_dir=str(tmp_path),
            include_com_trace=True,
            com_trace_logfiles_dir=str(tmp_path / "does" / "not" / "exist"),
        )
        with StarClient(config, simulate=True, run_log=rlc):
            pass

        # Run still finalized cleanly despite the missing trace directory.
        data = _final_json(tmp_path)
        assert data["reason"] == "normal"

    def test_max_bytes_keeps_the_newest_lines(
        self, config, mock_async_star_class, tmp_path
    ):
        from hamilton_venus.star_client import StarClient

        logs = tmp_path / "logs"
        logs.mkdir()
        trc = _sim_trace_path(logs)
        trc.write_bytes(b"")

        rlc = RunLogConfig(
            enabled=True,
            output_dir=str(tmp_path),
            include_com_trace=True,
            com_trace_logfiles_dir=str(logs),
            com_trace_max_bytes=40,  # only the last line or two fit
        )
        with StarClient(config, simulate=True, run_log=rlc), trc.open("ab") as fh:
            for i in range(20):
                fh.write(f"< 09:00:{i:02d}.000 COM1: LINE_{i}\r\n".encode())

        data = _final_json(tmp_path)
        embedded: list[str] = []
        truncated = False
        for entry in data["log"]:
            if entry["type"] == "com_trace":
                embedded.extend(entry["payload"]["lines"])
                truncated = truncated or entry["payload"]["truncated"]
        assert truncated is True
        assert embedded  # kept something
        assert embedded[-1] == "< 09:00:19.000 COM1: LINE_19"
        assert "< 09:00:00.000 COM1: LINE_0" not in embedded
