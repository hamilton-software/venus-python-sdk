"""Shared unit-test fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hamilton_venus._internal._base_instrument_client import _InstrumentSyncClientBase


@pytest.fixture(autouse=True)
def _skip_connect_time_channel_limit_query():
    """Stub the connect-time ``configuration.getConfiguration`` read.

    The per-file mocked clients count ``send_command`` calls, so the extra query
    that ``start()`` issues would break their assertions. Tests of the query
    itself call the real ``_load_instrument_config`` directly.
    """
    with patch.object(_InstrumentSyncClientBase, "_load_instrument_config", new=AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def _no_default_run_log(tmp_path, monkeypatch):
    """Keep mocked clients out of VENUS's LogFiles directory: the run log and its
    COM trace default off here, and a log with no ``output_dir`` goes to a temp
    "LogFiles" directory. Tests of the run log enable it explicitly; tests of
    the defaults remove the variables."""
    monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "0")
    monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", "0")
    monkeypatch.setattr(
        "hamilton_venus._internal._com_trace.registry_logfiles_dir", lambda: str(tmp_path / "LogFiles")
    )


@pytest.fixture(autouse=True)
def _isolate_shared_py32_runtime(tmp_path, monkeypatch):
    """Point PROGRAMDATA at a temp dir so no test sees a real shared 32-bit runtime."""
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "programdata"))
