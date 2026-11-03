"""Regression tests for WorkflowSession's StarClient/VantageClient selection.

WorkflowSession is the single choke point every app (demo_app, sample_transfer_app,
mcp_server) goes through to reach hamilton_venus -- generalizing it to construct either
StarClient or VantageClient (based on instrument_type) is what lets those apps support
Vantage without each reimplementing session lifecycle/escalation handling themselves.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamilton_venus.models import InstrumentType

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.session import WorkflowSession


class _FakeClient:
    """Stands in for StarClient/VantageClient -- start_session() only needs a working
    context-manager protocol and a _session_id attribute (used to build the run-log
    tailing glob); it never actually talks to VENUS in these tests."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = "fake-session"

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeStarClient(_FakeClient):
    pass


class _FakeVantageClient(_FakeClient):
    pass


class WorkflowSessionInstrumentSelectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="hwf_session_test_")
        self.addCleanup(shutil.rmtree, self._tmp_dir, True)

    def _config(self, **overrides: object) -> WorkflowBackendConfig:
        return WorkflowBackendConfig(run_log_root=Path(self._tmp_dir), **overrides)

    async def test_defaults_to_star_client_when_nothing_else_specified(self) -> None:
        with patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeVantageClient
        ):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True)
            self.assertIsInstance(session.star, _FakeStarClient)
            self.assertEqual(session.instrument_type, InstrumentType.STAR)
            await session.close()

    async def test_backend_config_default_instrument_type_is_honored(self) -> None:
        with patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeVantageClient
        ):
            config = self._config(default_instrument_type=InstrumentType.Vantage)
            session = WorkflowSession(config)
            await session.start_session(simulate=True)
            self.assertIsInstance(session.star, _FakeVantageClient)
            self.assertEqual(session.instrument_type, InstrumentType.Vantage)
            await session.close()

    async def test_explicit_instrument_type_overrides_the_backend_config_default(self) -> None:
        with patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeVantageClient
        ):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True, instrument_type=InstrumentType.Vantage)
            self.assertIsInstance(session.star, _FakeVantageClient)
            self.assertEqual(session.instrument_type, InstrumentType.Vantage)
            await session.close()

    async def test_instrument_type_persists_across_a_second_start_session_call_without_it(self) -> None:
        # Mirrors mcp_server: pick Vantage once, then call start_session again (e.g. to
        # restart in a fresh simulate mode) without repeating instrument_type -- it should
        # stay on Vantage rather than silently reverting to the backend config's STAR default.
        with patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient), patch(
            "hamilton_workflow_framework.session.VantageClient", _FakeVantageClient
        ):
            session = WorkflowSession(self._config())
            await session.start_session(simulate=True, instrument_type=InstrumentType.Vantage)
            await session.start_session(simulate=False)
            self.assertIsInstance(session.star, _FakeVantageClient)
            self.assertEqual(session.instrument_type, InstrumentType.Vantage)
            await session.close()

    async def test_star_property_raises_before_any_session_started(self) -> None:
        session = WorkflowSession(self._config())
        with self.assertRaises(RuntimeError):
            _ = session.star


if __name__ == "__main__":
    unittest.main()
