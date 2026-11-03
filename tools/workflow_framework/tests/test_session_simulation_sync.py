"""Regression tests for WorkflowSession's system-wide simulation-mode sync.

StarClient(simulate=...)/VantageClient(simulate=...) only control how VENUS
*executes* a method -- not which instrument (real or simulated) actually answers.
That's a separate, system-wide VENUS setting that start_session() now syncs via
the local Vector API before constructing the client, ported from
python_script_manager_app/backend/script_runner.py's own `_sync_system_simulation_mode`.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.session import WorkflowSession


class _FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = "fake-session"

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeResponse:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeAsyncHttpxClient:
    """Records GET/PUT calls; call_log is shared across instances via a list
    passed in by the test so assertions can inspect it after the `async with` exits."""

    def __init__(self, call_log: list[tuple[str, dict]], get_text: str) -> None:
        self._call_log = call_log
        self._get_text = get_text

    async def __aenter__(self) -> "_FakeAsyncHttpxClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, url: str, headers: dict) -> _FakeResponse:
        self._call_log.append(("GET", {"url": url, "headers": headers}))
        return _FakeResponse(self._get_text)

    async def put(self, url: str, headers: dict, params: dict) -> _FakeResponse:
        self._call_log.append(("PUT", {"url": url, "headers": headers, "params": params}))
        return _FakeResponse()


def _simulation_calls(call_log: list[tuple[str, dict]]) -> list[str]:
    """Methods of the calls to the simulation endpoint only (start_session also GETs the run guid)."""
    return [m for m, call in call_log if call["url"].endswith("/system/configuration/simulation")]


def _make_httpx_module(call_log: list[tuple[str, dict]], get_text: str) -> object:
    class _FakeHttpxModule:
        @staticmethod
        def AsyncClient(timeout: float) -> _FakeAsyncHttpxClient:
            return _FakeAsyncHttpxClient(call_log, get_text)

    return _FakeHttpxModule()


class WorkflowSessionSimulationSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="hwf_session_sim_test_")
        self.addCleanup(shutil.rmtree, self._tmp_dir, True)

    def _config(self, **overrides: object) -> WorkflowBackendConfig:
        return WorkflowBackendConfig(run_log_root=Path(self._tmp_dir), **overrides)

    async def test_puts_new_mode_when_venus_reports_a_mismatch(self) -> None:
        call_log: list[tuple[str, dict]] = []
        fake_httpx = _make_httpx_module(call_log, get_text="false")
        with patch("hamilton_workflow_framework.session.StarClient", _FakeClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeClient
        ), patch.dict("sys.modules", {"httpx": fake_httpx}):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True)
            await session.close()

        self.assertEqual(_simulation_calls(call_log), ["GET", "PUT"])
        self.assertEqual(call_log[1][1]["params"], {"simulationMode": "true"})

    async def test_skips_put_when_venus_already_matches(self) -> None:
        call_log: list[tuple[str, dict]] = []
        fake_httpx = _make_httpx_module(call_log, get_text="true")
        with patch("hamilton_workflow_framework.session.StarClient", _FakeClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeClient
        ), patch.dict("sys.modules", {"httpx": fake_httpx}):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True)
            await session.close()

        self.assertEqual(_simulation_calls(call_log), ["GET"])

    async def test_start_session_still_succeeds_when_sync_raises(self) -> None:
        class _RaisingHttpxModule:
            @staticmethod
            def AsyncClient(timeout: float) -> object:
                raise RuntimeError("VENUS unreachable")

        with patch("hamilton_workflow_framework.session.StarClient", _FakeClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeClient
        ), patch.dict("sys.modules", {"httpx": _RaisingHttpxModule()}):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True)
            self.assertIsInstance(session.star, _FakeClient)
            await session.close()


if __name__ == "__main__":
    unittest.main()
