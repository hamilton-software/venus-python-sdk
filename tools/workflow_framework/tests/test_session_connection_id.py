"""Regression tests for WorkflowSession.connection_id.

Distinct from self.session_id (fixed for the WorkflowSession object's whole process
lifetime, used elsewhere) -- connection_id reflects the specific currently-open
StarClient/VantageClient connection, and must change every time start_session() opens a
new one, so a caller (see mcp_server.hamilton_venus_mcp.server's expected_connection_id
guard) can tell "the session I started" apart from a later, unrelated one that replaced
it.
"""

from __future__ import annotations

import itertools
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.session import WorkflowSession


class _FakeClient:
    """Stands in for StarClient/VantageClient. Unlike the other tests' fixed
    "fake-session" _session_id, this one is fresh per *instance* -- matching the real
    client (_base_instrument_client.py sets a new uuid4().hex in __init__ every time),
    since these tests are specifically about that freshness."""

    _counter = itertools.count(1)

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = f"fake-connection-{next(_FakeClient._counter)}"

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class ConnectionIdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="hwf_connection_id_test_")
        self.addCleanup(shutil.rmtree, self._tmp_dir, True)
        self._patches = (
            patch("hamilton_workflow_framework.session.StarClient", _FakeClient),
            patch("hamilton_workflow_framework.session.VantageClient", _FakeClient),
        )
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _config(self) -> WorkflowBackendConfig:
        return WorkflowBackendConfig(run_log_root=Path(self._tmp_dir))

    async def test_none_before_any_session(self) -> None:
        session = WorkflowSession(self._config())
        self.assertIsNone(session.connection_id)

    async def test_matches_the_open_clients_own_session_id_once_started(self) -> None:
        session = WorkflowSession(self._config())
        await session.start_session(simulate=True)
        self.assertEqual(session.connection_id, session.star._session_id)  # noqa: SLF001
        self.assertIsNotNone(session.connection_id)
        await session.close()

    async def test_changes_on_a_second_start_session_call(self) -> None:
        session = WorkflowSession(self._config())
        await session.start_session(simulate=True)
        first = session.connection_id
        await session.start_session(simulate=True)  # tears down and replaces the first
        second = session.connection_id
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        await session.close()

    async def test_none_again_after_close(self) -> None:
        session = WorkflowSession(self._config())
        await session.start_session(simulate=True)
        await session.close()
        self.assertIsNone(session.connection_id)

    async def test_self_session_id_is_unaffected_and_stays_constant(self) -> None:
        """connection_id is new/additive; session.session_id keeps its existing,
        unrelated, process-lifetime-constant behavior."""
        session = WorkflowSession(self._config())
        before = session.session_id
        await session.start_session(simulate=True)
        after_start = session.session_id
        await session.start_session(simulate=True)
        after_second_start = session.session_id
        self.assertEqual(before, after_start)
        self.assertEqual(after_start, after_second_start)
        await session.close()


if __name__ == "__main__":
    unittest.main()
