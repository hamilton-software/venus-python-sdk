"""Unit tests for spokes.py: HAMILTON_MCP_SPOKES parsing and SpokeGroup's per-call
connection-state bookkeeping (connected/last_seen/last_error), patching _open_and_call --
the one seam that actually touches the network -- rather than faking the transport itself.
Real end-to-end connectivity (including the dead-spoke crash this design was changed to
avoid) is exercised by the manual multi-process smoke test instead (see the plan's Part 2
verification section).
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from mcp.types import ListResourcesResult, ReadResourceResult, Resource, TextResourceContents

from hamilton_venus_mcp_hub.spokes import SpokeConfig, SpokeGroup, parse_spokes, spokes_from_env


class ParseSpokesTests(unittest.TestCase):
    def test_parses_multiple_entries(self) -> None:
        result = parse_spokes("star1=http://192.168.1.11:8000/mcp,star2=http://192.168.1.12:8000/mcp")
        self.assertEqual(
            result,
            [
                SpokeConfig(id="star1", url="http://192.168.1.11:8000/mcp"),
                SpokeConfig(id="star2", url="http://192.168.1.12:8000/mcp"),
            ],
        )

    def test_tolerates_whitespace_and_trailing_comma(self) -> None:
        result = parse_spokes(" star1 = http://a:1/mcp , star2=http://b:2/mcp, ")
        self.assertEqual([s.id for s in result], ["star1", "star2"])

    def test_rejects_entry_without_equals(self) -> None:
        with self.assertRaises(ValueError):
            parse_spokes("star1-http://a:1/mcp")

    def test_rejects_empty_value(self) -> None:
        with self.assertRaises(ValueError):
            parse_spokes("")

    def test_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            parse_spokes("star1=http://a:1/mcp,star1=http://b:2/mcp")


class SpokesFromEnvTests(unittest.TestCase):
    """HAMILTON_MCP_SPOKES is optional -- a hub with none pre-configured is the expected
    startup state when spokes are meant to be added later from the dashboard (e.g. a hub
    started from the installer's "Start MCP Hub.bat", which sets no spokes at all)."""

    def test_unset_returns_empty_list(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HAMILTON_MCP_SPOKES", None)
            self.assertEqual(spokes_from_env(), [])

    def test_blank_returns_empty_list(self) -> None:
        with patch.dict(os.environ, {"HAMILTON_MCP_SPOKES": "   "}):
            self.assertEqual(spokes_from_env(), [])

    def test_set_value_is_parsed(self) -> None:
        with patch.dict(os.environ, {"HAMILTON_MCP_SPOKES": "star1=http://a:1/mcp"}):
            self.assertEqual(spokes_from_env(), [SpokeConfig(id="star1", url="http://a:1/mcp")])

    def test_malformed_value_still_raises(self) -> None:
        # Unset is fine (opt in later); a value that IS set but doesn't parse is still a
        # mistake worth failing loudly on, not silently downgrading to "no spokes".
        with patch.dict(os.environ, {"HAMILTON_MCP_SPOKES": "not-a-valid-entry"}):
            with self.assertRaises(ValueError):
                spokes_from_env()


def _fake_open_and_call(responses: dict[str, object], calls: list[tuple[str, str, dict]]):
    """Builds a replacement for SpokeGroup._open_and_call keyed by url. A response of an
    Exception instance is raised; True triggers an unset-event hang (simulates a dead spoke
    that never replies); anything else is returned as the call's result.
    """

    async def _open_and_call(self, url: str, tool_name: str, arguments: dict) -> object:
        calls.append((url, tool_name, arguments))
        response = responses[url]
        if response is True:
            await asyncio.Event().wait()
        if isinstance(response, Exception):
            raise response
        return response

    return _open_and_call


class SpokeGroupTests(unittest.IsolatedAsyncioTestCase):
    def _group(self, ids: list[str] = ("star1", "star2")) -> SpokeGroup:
        return SpokeGroup([SpokeConfig(id=i, url=f"http://{i}/mcp") for i in ids])

    async def test_call_tool_raises_for_unknown_spoke(self) -> None:
        group = self._group()
        with self.assertRaises(ValueError):
            await group.call_tool("not-a-spoke", "list_spokes", None)

    async def test_constructs_with_zero_spokes(self) -> None:
        group = SpokeGroup([])
        self.assertEqual(group.ids, [])
        self.assertEqual(group.status(), [])
        self.assertEqual(group.pending_interventions(), [])
        await group.connect_all()  # nothing to probe -- must not raise
        await group.aclose()

    async def test_add_spoke_works_starting_from_zero(self) -> None:
        group = SpokeGroup([])
        fake = _fake_open_and_call({"http://star1/mcp": "ok"}, [])
        with patch.object(SpokeGroup, "_open_and_call", fake):
            await group.add_spoke("star1", "http://star1/mcp")
        self.assertEqual(group.ids, ["star1"])
        self.assertTrue(group.status()[0]["connected"])

    async def test_successful_call_updates_connection_state(self) -> None:
        group = self._group()
        calls: list[tuple[str, str, dict]] = []
        fake = _fake_open_and_call({"http://star1/mcp": "ok"}, calls)

        with patch.object(SpokeGroup, "_open_and_call", fake):
            result = await group.call_tool("star1", "call_sdk_command", {"name": "instrument_is_idle"})

        self.assertEqual(result, "ok")
        self.assertEqual(calls, [("http://star1/mcp", "call_sdk_command", {"name": "instrument_is_idle"})])
        status = {s["id"]: s for s in group.status()}
        self.assertTrue(status["star1"]["connected"])
        self.assertIsNotNone(status["star1"]["last_seen"])
        self.assertIsNone(status["star1"]["last_error"])

    async def test_failed_call_marks_only_that_spoke_disconnected(self) -> None:
        group = self._group()
        calls: list[tuple[str, str, dict]] = []
        fake = _fake_open_and_call(
            {"http://star1/mcp": ConnectionError("boom"), "http://star2/mcp": "fine"}, calls
        )

        with patch.object(SpokeGroup, "_open_and_call", fake):
            with self.assertRaises(ConnectionError):
                await group.call_tool("star1", "call_sdk_command", {})
            await group.call_tool("star2", "call_sdk_command", {})

        status = {s["id"]: s for s in group.status()}
        self.assertFalse(status["star1"]["connected"])
        self.assertEqual(status["star1"]["last_error"], "boom")
        self.assertTrue(status["star2"]["connected"])
        self.assertIsNone(status["star2"]["last_error"])

    async def test_a_hung_spoke_times_out_instead_of_blocking_forever(self) -> None:
        # Caught during manual multi-process testing: a killed spoke's in-flight call didn't
        # fail promptly and hung well past two minutes with no timeout in place -- this is
        # the regression test for the fix (asyncio.wait_for around the network round trip).
        group = self._group()
        calls: list[tuple[str, str, dict]] = []
        fake = _fake_open_and_call({"http://star1/mcp": True}, calls)

        with patch.object(SpokeGroup, "_open_and_call", fake):
            with self.assertRaises(TimeoutError):
                await group.call_tool("star1", "call_sdk_command", {}, timeout_s=0.05)

        status = {s["id"]: s for s in group.status()}
        self.assertFalse(status["star1"]["connected"])
        self.assertIn("timed out", status["star1"]["last_error"])

    async def test_connect_all_probes_every_spoke_and_records_status_without_raising(self) -> None:
        group = self._group()
        calls: list[tuple[str, str, dict]] = []
        fake = _fake_open_and_call(
            {"http://star1/mcp": "ok", "http://star2/mcp": ConnectionError("offline")}, calls
        )

        with patch.object(SpokeGroup, "_open_and_call", fake):
            await group.connect_all()  # must not raise even though star2 fails

        status = {s["id"]: s for s in group.status()}
        self.assertTrue(status["star1"]["connected"])
        self.assertFalse(status["star2"]["connected"])
        self.assertEqual(status["star2"]["last_error"], "offline")
        self.assertEqual({c[1] for c in calls}, {"get_session_status"})

    async def test_add_spoke_registers_and_probes_it(self) -> None:
        group = self._group(ids=["star1"])
        calls: list[tuple[str, str, dict]] = []
        fake = _fake_open_and_call({"http://star1/mcp": "ok", "http://star3/mcp": "ok"}, calls)

        with patch.object(SpokeGroup, "_open_and_call", fake):
            await group.add_spoke("star3", "http://star3/mcp")

        self.assertIn("star3", group.ids)
        status = {s["id"]: s for s in group.status()}
        self.assertEqual(status["star3"]["url"], "http://star3/mcp")
        self.assertTrue(status["star3"]["connected"])  # probed immediately, not left blank
        self.assertEqual({c[1] for c in calls if c[0] == "http://star3/mcp"}, {"get_session_status"})

    async def test_add_spoke_rejects_a_duplicate_id(self) -> None:
        group = self._group(ids=["star1"])
        with self.assertRaises(ValueError):
            await group.add_spoke("star1", "http://somewhere-else/mcp")

    async def test_remove_spoke_drops_it_without_affecting_others(self) -> None:
        group = self._group(ids=["star1", "star2"])

        group.remove_spoke("star1")

        self.assertEqual(group.ids, ["star2"])
        with self.assertRaises(ValueError):
            await group.call_tool("star1", "call_sdk_command", {})

    async def test_remove_spoke_rejects_an_unknown_id(self) -> None:
        group = self._group(ids=["star1"])
        with self.assertRaises(ValueError):
            group.remove_spoke("not-a-spoke")

    async def test_read_resource_raises_for_unknown_spoke(self) -> None:
        group = self._group()
        with self.assertRaises(ValueError):
            await group.read_resource("not-a-spoke", "docs://hamilton-venus/getting-started")

    async def test_read_resource_returns_the_result_and_updates_connection_state(self) -> None:
        group = self._group()
        expected = ReadResourceResult(
            contents=[TextResourceContents(uri="docs://hamilton-venus/getting-started", text="guide text")]
        )

        async def fake_open_and_read_resource(self, url: str, uri: str) -> ReadResourceResult:
            self._captured = (url, uri)  # noqa: SLF001 - test-owned attribute on the instance
            return expected

        with patch.object(SpokeGroup, "_open_and_read_resource", fake_open_and_read_resource):
            result = await group.read_resource("star1", "docs://hamilton-venus/getting-started")

        self.assertIs(result, expected)
        status = {s["id"]: s for s in group.status()}
        self.assertTrue(status["star1"]["connected"])
        self.assertIsNone(status["star1"]["last_error"])

    async def test_read_resource_marks_the_spoke_disconnected_on_failure(self) -> None:
        group = self._group()

        async def fake_open_and_read_resource(self, url: str, uri: str) -> ReadResourceResult:
            raise ConnectionError("boom")

        with patch.object(SpokeGroup, "_open_and_read_resource", fake_open_and_read_resource):
            with self.assertRaises(ConnectionError):
                await group.read_resource("star1", "docs://hamilton-venus/getting-started")

        status = {s["id"]: s for s in group.status()}
        self.assertFalse(status["star1"]["connected"])
        self.assertEqual(status["star1"]["last_error"], "boom")

    async def test_list_resources_raises_for_unknown_spoke(self) -> None:
        group = self._group()
        with self.assertRaises(ValueError):
            await group.list_resources("not-a-spoke")

    async def test_list_resources_returns_the_result_and_updates_connection_state(self) -> None:
        group = self._group()
        expected = ListResourcesResult(
            resources=[Resource(uri="docs://hamilton-venus/getting-started", name="getting started")]
        )

        async def fake_open_and_list_resources(self, url: str) -> ListResourcesResult:
            return expected

        with patch.object(SpokeGroup, "_open_and_list_resources", fake_open_and_list_resources):
            result = await group.list_resources("star1")

        self.assertIs(result, expected)
        status = {s["id"]: s for s in group.status()}
        self.assertTrue(status["star1"]["connected"])


class SpokeGroupPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """SpokeGroup(spokes_file=...) write-through -- see spokes.py's SpokeGroup._save."""

    def _group(self, ids: list[str] = (), *, spokes_file=None, env_ids=frozenset()) -> SpokeGroup:
        return SpokeGroup(
            [SpokeConfig(id=i, url=f"http://{i}/mcp") for i in ids], spokes_file=spokes_file, env_ids=env_ids
        )

    async def test_default_construction_never_touches_the_filesystem(self) -> None:
        group = self._group(ids=["star1"])  # spokes_file=None, the default
        with patch("hamilton_venus_mcp_hub.spokes.spoke_store.save") as fake_save:
            fake = _fake_open_and_call({"http://star3/mcp": "ok"}, [])
            with patch.object(SpokeGroup, "_open_and_call", fake):
                await group.add_spoke("star3", "http://star3/mcp")
            group.remove_spoke("star1")
        fake_save.assert_not_called()

    async def test_add_spoke_persists_when_a_spokes_file_is_given(self) -> None:
        group = self._group(spokes_file="C:\\fake\\spokes.json")
        fake = _fake_open_and_call({"http://star3/mcp": "ok"}, [])
        with patch("hamilton_venus_mcp_hub.spokes.spoke_store.save") as fake_save:
            with patch.object(SpokeGroup, "_open_and_call", fake):
                await group.add_spoke("star3", "http://star3/mcp")
        fake_save.assert_called_once_with([{"id": "star3", "url": "http://star3/mcp"}], "C:\\fake\\spokes.json")

    async def test_remove_spoke_persists_the_remaining_roster(self) -> None:
        group = self._group(ids=["star1", "star2"], spokes_file="C:\\fake\\spokes.json")
        with patch("hamilton_venus_mcp_hub.spokes.spoke_store.save") as fake_save:
            group.remove_spoke("star1")
        fake_save.assert_called_once_with([{"id": "star2", "url": "http://star2/mcp"}], "C:\\fake\\spokes.json")

    async def test_env_sourced_spokes_are_never_persisted(self) -> None:
        # star1 came from HAMILTON_MCP_SPOKES (env_ids); adding star2 at runtime must only
        # ever write star2 to the file -- star1 must never "leak" into spokes.json, or it
        # would silently outlive being removed from the env var.
        group = self._group(ids=["star1"], spokes_file="C:\\fake\\spokes.json", env_ids=frozenset({"star1"}))
        fake = _fake_open_and_call({"http://star2/mcp": "ok"}, [])
        with patch("hamilton_venus_mcp_hub.spokes.spoke_store.save") as fake_save:
            with patch.object(SpokeGroup, "_open_and_call", fake):
                await group.add_spoke("star2", "http://star2/mcp")
        fake_save.assert_called_once_with([{"id": "star2", "url": "http://star2/mcp"}], "C:\\fake\\spokes.json")


if __name__ == "__main__":
    unittest.main()
