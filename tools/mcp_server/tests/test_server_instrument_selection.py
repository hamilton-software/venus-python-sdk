"""Regression tests for server.py's instrument_type handling: start_session's parsing,
get_session_status/list_sdk_commands/describe_sdk_command/call_sdk_command switching to
the matching CATALOG_BY_INSTRUMENT catalog, and the regenerate_catalog tool reusing the
active session's client instead of opening a second connection.

@mcp.tool() leaves the decorated function directly callable (FastMCP registers it in a
registry without wrapping the callable itself), so these call the tool functions in
server.py exactly as an MCP client's tool-call dispatch would.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import hamilton_venus_mcp.server as srv
from hamilton_venus.models import InstrumentType


class _FakeClient:
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


def _patch_clients():
    return (
        patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient),
        patch("hamilton_workflow_framework.session.VantageClient", _FakeVantageClient),
    )


class ServerInstrumentSelectionTests(unittest.IsolatedAsyncioTestCase):
    """Client selection with no installed-instrument guard in the way (see InstrumentTypeGuardTests
    in test_run_control.py for the guard): these run on a PC of either family."""

    async def asyncSetUp(self) -> None:
        guard = patch.object(srv, "_installed_instrument", lambda: None)
        guard.start()
        self.addCleanup(guard.stop)

    async def asyncTearDown(self) -> None:
        await srv.close_session()

    async def test_start_session_defaults_to_star(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            result = await srv.start_session(simulate=True, blank_deck=True)
        self.assertEqual(result["instrument_type"], "STAR")
        self.assertIsInstance(srv._session.star, _FakeStarClient)

    async def test_start_session_accepts_vantage_case_insensitively(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            result = await srv.start_session(simulate=True, blank_deck=True, instrument_type="vantage")
        self.assertEqual(result["instrument_type"], "Vantage")
        self.assertIsInstance(srv._session.star, _FakeVantageClient)

    async def test_start_session_rejects_unknown_instrument_type(self) -> None:
        with self.assertRaises(ValueError):
            await srv.start_session(simulate=True, blank_deck=True, instrument_type="Nimbus99")

    async def test_get_session_status_reports_instrument_type(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True, instrument_type="Vantage")
        status = srv.get_session_status()
        self.assertEqual(status["instrument_type"], "Vantage")

    async def test_list_sdk_commands_excludes_star_only_commands_in_vantage_mode(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True, instrument_type="Vantage")
        names = {row["name"] for row in srv.list_sdk_commands()}
        # core_5ml_transport is the one command family VantageClient genuinely lacks
        # (no 5mL transport tool on Vantage hardware).
        self.assertNotIn("core_5ml_transport", names)
        self.assertIn("aspirate", names)

    async def test_describe_sdk_command_unknown_in_vantage_mode_for_star_only_command(self) -> None:
        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True, instrument_type="Vantage")
        with self.assertRaises(ValueError):
            srv.describe_sdk_command("core_5ml_transport")

    async def test_regenerate_catalog_reuses_the_active_session_client(self) -> None:
        captured: dict[str, object] = {}

        def _fake_regenerate(client: object) -> dict[str, bool]:
            captured["client"] = client
            return {"labware.py": False, "liquid_classes.py": True, "__init__.py": False}

        p1, p2 = _patch_clients()
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True, instrument_type="Vantage")
        with patch("hamilton_venus_mcp.server._regenerate_local_catalog", _fake_regenerate):
            result = await srv.regenerate_catalog()

        self.assertIs(captured["client"], srv._session.star)
        self.assertEqual(result["changed"], {"labware.py": False, "liquid_classes.py": True, "__init__.py": False})

    async def test_regenerate_catalog_requires_an_active_session(self) -> None:
        with self.assertRaises(RuntimeError):
            await srv.regenerate_catalog()


if __name__ == "__main__":
    unittest.main()
