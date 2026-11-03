"""Regression tests for connection_id and the expected_connection_id guard added to
start_session/get_session_status/connect_instrument/call_sdk_command/close_session.

connection_id identifies one specific open StarClient/VantageClient connection (fresh
every start_session() call) -- distinct from the pre-existing session_id, which is fixed
for the whole life of the spoke process and can't tell one session apart from a later,
unrelated one that replaced it. expected_connection_id is the opt-in guard built on top:
when a caller passes it, a mismatch (a different session is active now) raises before
anything else happens, instead of silently acting on the wrong session.
"""

from __future__ import annotations

import itertools
import unittest
from unittest.mock import patch

import hamilton_venus_mcp.server as srv


class _FakeClient:
    """Fresh _session_id per instance, matching the real client (unlike some other test
    files' fixed "fake-session" fake, which doesn't need to distinguish instances)."""

    _counter = itertools.count(1)

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = f"fake-connection-{next(_FakeClient._counter)}"
        self.is_idle_calls = 0

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def instrument_is_idle(self) -> bool:
        self.is_idle_calls += 1
        return True

    def instrument_connect(self, initialize: bool = False) -> None:
        return None


def _patch_clients():
    return (
        patch("hamilton_workflow_framework.session.StarClient", _FakeClient),
        patch("hamilton_workflow_framework.session.VantageClient", _FakeClient),
    )


class ConnectionIdReportingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await srv.close_session()

    async def test_start_session_returns_a_connection_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            result = await srv.start_session(simulate=True, blank_deck=True)
        self.assertIsNotNone(result["connection_id"])

    async def test_get_session_status_matches_start_sessions_own_value(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            started = await srv.start_session(simulate=True, blank_deck=True)
        status = srv.get_session_status()
        self.assertEqual(status["connection_id"], started["connection_id"])

    async def test_get_session_status_connection_id_is_none_before_any_session(self) -> None:
        self.assertIsNone(srv.get_session_status()["connection_id"])

    async def test_a_second_start_session_call_changes_connection_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            first = await srv.start_session(simulate=True, blank_deck=True)
            second = await srv.start_session(simulate=True, blank_deck=True)  # tears down and replaces the first
        self.assertNotEqual(first["connection_id"], second["connection_id"])


class ExpectedConnectionIdGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await srv.close_session()

    async def test_call_sdk_command_succeeds_with_the_matching_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            started = await srv.start_session(simulate=True, blank_deck=True)
            result = await srv.call_sdk_command(
                "instrument_is_idle", expected_connection_id=started["connection_id"]
            )
        self.assertEqual(result["status"], "success")

    async def test_call_sdk_command_refuses_with_a_stale_id_and_does_not_execute_the_command(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True)  # this run's session
            client = srv._session.star
            # A different, later session takes over (a different workflow's start_session):
            await srv.start_session(simulate=True, blank_deck=True)
            with self.assertRaisesRegex(RuntimeError, "Expected connection"):
                await srv.call_sdk_command("instrument_is_idle", expected_connection_id="stale-id")
        self.assertEqual(client.is_idle_calls, 0)  # the stale request's own client, never touched

    async def test_call_sdk_command_with_no_expected_id_is_unaffected(self) -> None:
        """Backward compatibility: every existing caller that never passes
        expected_connection_id keeps working exactly as before."""
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True)
            result = await srv.call_sdk_command("instrument_is_idle")
        self.assertEqual(result["status"], "success")

    async def test_connect_instrument_refuses_with_a_stale_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True)
            with self.assertRaisesRegex(RuntimeError, "Expected connection"):
                await srv.connect_instrument(expected_connection_id="stale-id")
        self.assertFalse(srv.get_session_status()["instrument_connected"])

    async def test_connect_instrument_succeeds_with_the_matching_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            started = await srv.start_session(simulate=True, blank_deck=True)
            result = await srv.connect_instrument(expected_connection_id=started["connection_id"])
        self.assertTrue(result["connected"])

    async def test_close_session_refuses_with_a_stale_id_and_leaves_the_real_session_open(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True)
            with self.assertRaisesRegex(RuntimeError, "Expected connection"):
                await srv.close_session(expected_connection_id="stale-id")
        self.assertTrue(srv.get_session_status()["session_active"])

    async def test_close_session_succeeds_with_the_matching_id(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            started = await srv.start_session(simulate=True, blank_deck=True)
            await srv.close_session(expected_connection_id=started["connection_id"])
        self.assertFalse(srv.get_session_status()["session_active"])


if __name__ == "__main__":
    unittest.main()
