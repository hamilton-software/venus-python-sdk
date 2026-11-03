"""Unit tests for server.py's hub tools (list_spokes/call_tool_on/broadcast_tool_call) and
the /api/status.json dashboard route, against a fake SpokeGroup -- real spoke connectivity
is exercised by the manual multi-process smoke test instead (see the plan's Part 2
verification section), the same split test_server_polling.py uses on the spoke side.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, ListResourcesResult, ReadResourceResult, TextContent

import hamilton_venus_mcp_hub.server as srv


class _FakeSpokeGroup:
    """Responses keyed by spoke_id: a CallToolResult to return, or an Exception to raise."""

    def __init__(
        self,
        responses: dict[str, object],
        statuses: list[dict],
        resource_responses: dict[str, object] | None = None,
        resource_list_responses: dict[str, object] | None = None,
    ) -> None:
        self._responses = responses
        self._statuses = statuses
        self._resource_responses = resource_responses or {}
        self._resource_list_responses = resource_list_responses or {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.resource_reads: list[tuple[str, str]] = []
        self.resource_lists: list[str] = []
        self.added: list[tuple[str, str]] = []
        self.removed: list[str] = []

    @property
    def ids(self) -> list[str]:
        return [s["id"] for s in self._statuses]

    def status(self) -> list[dict]:
        return self._statuses

    def pending_interventions(self) -> list[dict]:
        return []

    def command_holds(self) -> list[dict]:
        return []

    async def call_tool(
        self, spoke_id: str, tool_name: str, arguments: dict | None, *, timeout_s: float | None = None
    ) -> CallToolResult:
        self.calls.append((spoke_id, tool_name, arguments))
        response = self._responses[spoke_id]
        if isinstance(response, Exception):
            raise response
        return response

    async def read_resource(self, spoke_id: str, uri: str, *, timeout_s: float | None = None) -> ReadResourceResult:
        self.resource_reads.append((spoke_id, uri))
        response = self._resource_responses[spoke_id]
        if isinstance(response, Exception):
            raise response
        return response

    async def list_resources(self, spoke_id: str, *, timeout_s: float | None = None) -> ListResourcesResult:
        self.resource_lists.append(spoke_id)
        response = self._resource_list_responses[spoke_id]
        if isinstance(response, Exception):
            raise response
        return response

    async def add_spoke(self, spoke_id: str, url: str) -> None:
        if any(s["id"] == spoke_id for s in self._statuses):
            raise ValueError(f"Spoke {spoke_id!r} already exists.")
        self.added.append((spoke_id, url))
        self._statuses.append({"id": spoke_id, "url": url, "connected": True, "last_seen": None, "last_error": None})

    def remove_spoke(self, spoke_id: str) -> None:
        if not any(s["id"] == spoke_id for s in self._statuses):
            raise ValueError(f"Unknown spoke_id {spoke_id!r}.")
        self.removed.append(spoke_id)
        self._statuses = [s for s in self._statuses if s["id"] != spoke_id]


class _FakeJsonRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


class _FakePathRequest:
    def __init__(self, path_params: dict) -> None:
        self.path_params = path_params


def _ok_result(structured: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(structured))], structuredContent=structured, isError=False)


def _error_result(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)


def _text_resource_result(text: str, uri: str = "docs://hamilton-venus/getting-started") -> ReadResourceResult:
    from mcp.types import TextResourceContents

    return ReadResourceResult(contents=[TextResourceContents(uri=uri, text=text)])


def _resource_list_result(uri: str = "docs://hamilton-venus/getting-started", name: str = "getting started") -> ListResourcesResult:
    from mcp.types import Resource

    return ListResourcesResult(resources=[Resource(uri=uri, name=name)])


class HubServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        srv._activity.clear()  # noqa: SLF001 - test-owned module state

    async def test_list_spokes_returns_the_spoke_groups_status_verbatim(self) -> None:
        statuses = [{"id": "star1", "url": "http://star1/mcp", "connected": True, "last_seen": 1.0, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({}, statuses))

        self.assertEqual(await srv.list_spokes(), statuses)

    async def test_call_tool_on_passes_through_structured_content_and_stamps_a_timestamp(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({"star1": _ok_result({"status": "success", "result": 42.0})}, statuses)
        srv.set_spokes(group)

        result = await srv.call_tool_on("star1", "call_sdk_command", {"name": "odtc_get_temperature"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], 42.0)
        self.assertIn("timestamp", result)
        self.assertEqual(group.calls, [("star1", "call_sdk_command", {"name": "odtc_get_temperature"})])

    async def test_call_tool_on_surfaces_a_tool_level_error_without_raising(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({"star1": _error_result("Unknown SDK command: bogus")}, statuses))

        result = await srv.call_tool_on("star1", "call_sdk_command", {"name": "bogus"})

        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown SDK command", result["message"])

    async def test_call_tool_on_surfaces_a_connection_failure_without_raising(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": False, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({"star1": ConnectionError("spoke unreachable")}, statuses))

        result = await srv.call_tool_on("star1", "call_sdk_command", {"name": "odtc_get_temperature"})

        self.assertEqual(result, {"status": "error", "message": "spoke unreachable", "timestamp": result["timestamp"]})

    async def test_call_tool_on_records_activity(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({"star1": _ok_result({"status": "success"})}, statuses))

        await srv.call_tool_on("star1", "instrument_is_idle", None)

        self.assertEqual(len(srv._activity), 1)  # noqa: SLF001
        entry = srv._activity[0]  # noqa: SLF001
        self.assertEqual(entry["spoke_id"], "star1")
        self.assertEqual(entry["tool_name"], "instrument_is_idle")
        self.assertEqual(entry["status"], "success")

    async def test_broadcast_tool_call_compiles_results_keyed_by_spoke_id_and_survives_one_failure(self) -> None:
        statuses = [
            {"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None},
            {"id": "star2", "url": "u2", "connected": True, "last_seen": None, "last_error": None},
        ]
        group = _FakeSpokeGroup(
            {
                "star1": _ok_result({"status": "success", "result": {"blockTemperature": 25.0}}),
                "star2": ConnectionError("offline"),
            },
            statuses,
        )
        srv.set_spokes(group)

        result = await srv.broadcast_tool_call("call_sdk_command", {"name": "odtc_get_temperature"})

        self.assertEqual(set(result), {"star1", "star2"})
        self.assertEqual(result["star1"]["status"], "success")
        self.assertEqual(result["star2"], {"status": "error", "message": "offline", "timestamp": result["star2"]["timestamp"]})
        self.assertEqual({c[0] for c in group.calls}, {"star1", "star2"})

    async def test_broadcast_tool_call_respects_an_explicit_spoke_id_subset(self) -> None:
        statuses = [
            {"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None},
            {"id": "star2", "url": "u2", "connected": True, "last_seen": None, "last_error": None},
        ]
        group = _FakeSpokeGroup(
            {"star1": _ok_result({"status": "success"}), "star2": _ok_result({"status": "success"})}, statuses
        )
        srv.set_spokes(group)

        result = await srv.broadcast_tool_call("instrument_is_idle", None, spoke_ids=["star1"])

        self.assertEqual(set(result), {"star1"})
        self.assertEqual([c[0] for c in group.calls], ["star1"])

    async def test_add_spoke_tool_registers_via_the_spoke_group(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses)
        srv.set_spokes(group)

        result = await srv.add_spoke("star2", "http://star2/mcp")

        self.assertEqual(group.added, [("star2", "http://star2/mcp")])
        self.assertEqual(result["id"], "star2")
        self.assertEqual(result["url"], "http://star2/mcp")

    async def test_add_spoke_tool_propagates_a_duplicate_id_error(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({}, statuses))

        with self.assertRaises(ValueError):
            await srv.add_spoke("star1", "http://somewhere-else/mcp")

    async def test_remove_spoke_tool_drops_via_the_spoke_group(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses)
        srv.set_spokes(group)

        result = await srv.remove_spoke("star1")

        self.assertEqual(group.removed, ["star1"])
        self.assertEqual(result, {"removed": "star1"})

    async def test_add_spoke_route_registers_on_valid_body(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses)
        srv.set_spokes(group)

        response = await srv.add_spoke_route(_FakeJsonRequest({"id": "star2", "url": "http://star2/mcp"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(group.added, [("star2", "http://star2/mcp")])

    async def test_add_spoke_route_rejects_a_missing_field(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses)
        srv.set_spokes(group)

        response = await srv.add_spoke_route(_FakeJsonRequest({"id": "star2"}))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(group.added, [])

    async def test_add_spoke_route_surfaces_a_duplicate_id_as_400(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({}, statuses))

        response = await srv.add_spoke_route(_FakeJsonRequest({"id": "star1", "url": "http://dup/mcp"}))

        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", json.loads(response.body)["error"])

    async def test_remove_spoke_route_removes_a_known_id(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses)
        srv.set_spokes(group)

        response = await srv.remove_spoke_route(_FakePathRequest({"spoke_id": "star1"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(group.removed, ["star1"])

    async def test_remove_spoke_route_reports_an_unknown_id_as_404(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({}, statuses))

        response = await srv.remove_spoke_route(_FakePathRequest({"spoke_id": "not-a-spoke"}))

        self.assertEqual(response.status_code, 404)

    async def test_read_resource_on_returns_the_text_content(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup(
            {}, statuses, resource_responses={"star1": _text_resource_result("guide text")}
        )
        srv.set_spokes(group)

        result = await srv.read_resource_on("star1", "docs://hamilton-venus/getting-started")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["text"], "guide text")
        self.assertIn("timestamp", result)
        self.assertEqual(group.resource_reads, [("star1", "docs://hamilton-venus/getting-started")])

    async def test_read_resource_on_surfaces_a_connection_failure_without_raising(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": False, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses, resource_responses={"star1": ConnectionError("spoke unreachable")})
        srv.set_spokes(group)

        result = await srv.read_resource_on("star1", "docs://hamilton-venus/getting-started")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "spoke unreachable")

    async def test_list_resources_on_returns_the_resource_list(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": True, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses, resource_list_responses={"star1": _resource_list_result()})
        srv.set_spokes(group)

        result = await srv.list_resources_on("star1")

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["resources"]), 1)
        self.assertEqual(result["resources"][0]["uri"], "docs://hamilton-venus/getting-started")
        self.assertEqual(result["resources"][0]["name"], "getting started")
        self.assertEqual(group.resource_lists, ["star1"])

    async def test_list_resources_on_surfaces_a_connection_failure_without_raising(self) -> None:
        statuses = [{"id": "star1", "url": "u", "connected": False, "last_seen": None, "last_error": None}]
        group = _FakeSpokeGroup({}, statuses, resource_list_responses={"star1": ConnectionError("offline")})
        srv.set_spokes(group)

        result = await srv.list_resources_on("star1")

        self.assertEqual(result, {"status": "error", "message": "offline", "timestamp": result["timestamp"]})

    async def test_status_json_route_reports_hub_spokes_and_recent_activity(self) -> None:
        statuses = [{"id": "star1", "url": "u1", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({"star1": _ok_result({"status": "success"})}, statuses))
        await srv.call_tool_on("star1", "instrument_is_idle", None)

        response = await srv.status_json(None)
        body = json.loads(response.body)

        self.assertIn("uptime_s", body["hub"])
        self.assertEqual(body["spokes"], statuses)
        self.assertEqual(len(body["recent_activity"]), 1)
        self.assertEqual(body["recent_activity"][0]["spoke_id"], "star1")

    async def test_discover_spokes_tool_filters_out_already_connected_urls(self) -> None:
        statuses = [{"id": "star1", "url": "http://star1/mcp", "connected": True, "last_seen": None, "last_error": None}]
        srv.set_spokes(_FakeSpokeGroup({}, statuses))

        found = [
            srv.discovery.DiscoveredSpoke(url="http://star1/mcp", name="already-connected"),
            srv.discovery.DiscoveredSpoke(url="http://star2/mcp", name="star2"),
        ]
        with patch.object(srv.discovery, "scan", AsyncMock(return_value=found)):
            result = await srv.discover_spokes()

        self.assertEqual(result, [{"url": "http://star2/mcp", "name": "star2"}])

    async def test_discover_spokes_route_returns_the_same_shape(self) -> None:
        srv.set_spokes(_FakeSpokeGroup({}, []))
        found = [srv.discovery.DiscoveredSpoke(url="http://star2/mcp", name="star2")]

        with patch.object(srv.discovery, "scan", AsyncMock(return_value=found)):
            response = await srv.discover_spokes_route(None)

        self.assertEqual(json.loads(response.body), {"spokes": [{"url": "http://star2/mcp", "name": "star2"}]})


if __name__ == "__main__":
    unittest.main()
