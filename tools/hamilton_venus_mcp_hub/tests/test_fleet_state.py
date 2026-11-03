"""Tests for the hub's fleet view: each spoke's idle / running / error state, the aggregated
list of prompts waiting for a human, and the dashboard's route for answering them.

These use the real SpokeGroup with only its network seam (_open_and_call) replaced by a script
of spoke answers, so the bookkeeping under test is the real code.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from mcp.types import CallToolResult, TextContent

import hamilton_venus_mcp_hub.server as srv
from hamilton_venus_mcp_hub.spokes import STATE_LABELS, SpokeConfig, SpokeGroup, state_label

TOKEN = "hub-side-secret"


def ok(structured: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(structured))], structuredContent=structured, isError=False)


def failed(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)


def spoke_state(state: str = "idle", **extra) -> dict:
    return {
        "state": state,
        "error_kind": None,
        "detail": None,
        "paused": False,
        "run": None,
        "pending_prompts": [],
        "last_run": None,
        "session_active": False,
        "operator_ui": {"listening": True, "url": "http://star1:8765/operator", "error": None},
        **extra,
    }


PROMPT = {
    "prompt_id": "err-1",
    "run_id": "run-1",
    "kind": "operator_error",
    "code": "P1:08/78",
    "title": "Tip Pick Up - Error",
    "options": ["abort", "cancel"],
    "channel_errors": [
        {
            "channels": ["1", "2"],
            "message": "No tip picked up.",
            "detail_uuids": ["d1", "d2"],
            "actions": [{"id": 1026, "name": "Repeat"}],
            "default_action_id": 1026,
        }
    ],
}


class FleetTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.urls = {"star1": "http://star1/mcp", "star2": "http://star2/mcp"}
        self.answers: dict[tuple[str, str], object] = {}  # (url, tool) -> CallToolResult | Exception
        self.calls: list[tuple[str, str, dict | None]] = []

        async def fake_open_and_call(_group, url, tool_name, arguments):
            self.calls.append((url, tool_name, arguments))
            answer = self.answers[(url, tool_name)]
            if callable(answer):  # a function of the call's arguments, for paged answers
                answer = answer(arguments or {})
            if isinstance(answer, Exception):
                raise answer
            return answer

        patcher = mock.patch.object(SpokeGroup, "_open_and_call", fake_open_and_call)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.group = SpokeGroup([SpokeConfig(id=i, url=u) for i, u in self.urls.items()])
        srv.set_spokes(self.group)
        self.addCleanup(srv._activity.clear)
        srv._ui_cache.clear()
        self.addCleanup(srv._ui_cache.clear)
        ttl = mock.patch.object(srv, "_UI_CACHE_TTL_S", 0.0)  # each test asserts on fresh answers
        ttl.start()
        self.addCleanup(ttl.stop)
        env = mock.patch.dict(os.environ, {srv._OPERATOR_TOKEN_ENV: TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def answer(self, spoke: str, tool: str, result) -> None:
        self.answers[(self.urls[spoke], tool)] = result

    def by_id(self) -> dict[str, dict]:
        return {s["id"]: s for s in self.group.status()}


class StateLabelTests(FleetTestCase):
    async def test_labels(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ConnectionError("no route"))
        await srv.poll_spoke_states()
        states = self.by_id()
        self.assertEqual(states["star1"]["state"], "idle")
        self.assertEqual(states["star2"]["state"], "unreachable")
        self.assertIn(states["star2"]["state"], STATE_LABELS)

    async def test_every_state_the_spoke_can_report_is_passed_through(self):
        for reported in ("idle", "running", "error"):
            with self.subTest(reported=reported):
                self.answer("star1", "get_spoke_state", ok(spoke_state(reported)))
                self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
                await srv.poll_spoke_states()
                self.assertEqual(self.by_id()["star1"]["state"], reported)

    async def test_an_older_spoke_without_script_runs_is_unknown_not_an_error(self):
        self.answer("star1", "get_spoke_state", failed("Unknown tool: get_spoke_state"))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        star1 = self.by_id()["star1"]
        self.assertEqual(star1["state"], "unknown")
        self.assertIn("Unknown tool", star1["state_detail"])
        self.assertTrue(star1["connected"])  # it answered; it just cannot say

    async def test_a_state_that_is_not_one_of_the_three_is_unknown(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("exploding")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.assertEqual(self.by_id()["star1"]["state"], "unknown")

    def test_state_label_helper_directly(self):
        conn = self.group._connections["star1"]
        self.assertEqual(state_label(conn), "unreachable")  # never contacted
        conn.connected = True
        self.assertEqual(state_label(conn), "unknown")  # contacted, nothing polled
        conn.state = {"state": "running"}
        self.assertEqual(state_label(conn), "running")

    async def test_a_spoke_that_goes_away_is_unreachable_and_its_old_state_is_dropped(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("error", pending_prompts=[PROMPT])))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.assertEqual(len(self.group.pending_interventions()), 1)
        self.answer("star1", "get_spoke_state", TimeoutError())
        await srv.poll_spoke_states()
        self.assertEqual(self.by_id()["star1"]["state"], "unreachable")
        self.assertEqual(self.group.pending_interventions(), [])  # cannot answer for it any more

    async def test_a_held_command_stream_is_listed_as_a_command_hold(self):
        hold = {"step": 4, "reason": "error", "command": "aspirate", "error_type": "VenusCommandFailedError",
                "message": "Step canceled.", "error_step": 4, "replay_pending": [], "since": 1.0}
        held = {"state": "held", "hold": hold, "last_event_seq": 1}
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", session_active=True, command_control=held)))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle", command_control={"state": "running", "hold": None})))
        (item,) = await srv.list_command_holds()
        self.assertEqual((item["spoke_id"], item["step"], item["command"], item["reason"]), ("star1", 4, "aspirate", "error"))
        self.assertEqual(self.group.pending_interventions(), [])  # no prompt to answer
        self.assertEqual(self.by_id()["star1"]["command_control"], held)

    async def test_state_view_carries_the_running_details(self):
        run = {"run_id": "run-1", "script": "mastermix.py", "simulate": True, "elapsed_s": 12.0}
        self.answer("star1", "get_spoke_state", ok(spoke_state("running", paused=True, run=run, detail="mastermix.py (paused)")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        star1 = self.by_id()["star1"]
        self.assertEqual(star1["run"], run)
        self.assertTrue(star1["paused"])
        self.assertEqual(star1["state_detail"], "mastermix.py (paused)")
        self.assertEqual(star1["operator_ui"]["url"], "http://star1:8765/operator")


class ToolTests(FleetTestCase):
    async def test_fleet_status_counts_and_lists_interventions(self):
        self.answer(
            "star1",
            "get_spoke_state",
            ok(spoke_state("error", error_kind="prompt_pending", detail="Tip Pick Up - Error", pending_prompts=[PROMPT], run={"script": "a.py"})),
        )
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        result = await srv.get_fleet_status()
        self.assertEqual(result["counts"], {"idle": 1, "running": 0, "error": 1, "unreachable": 0, "unknown": 0})
        (intervention,) = result["pending_interventions"]
        self.assertEqual((intervention["spoke_id"], intervention["script"], intervention["prompt_id"]), ("star1", "a.py", "err-1"))
        self.assertEqual(intervention["options"], ["abort", "cancel"])
        self.assertIn("polled_at", result)

    async def test_refresh_false_uses_the_last_poll_without_calling_spokes(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("running")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        calls_before = len(self.calls)
        result = await srv.get_fleet_status(refresh=False)
        self.assertEqual(len(self.calls), calls_before)
        self.assertEqual(result["counts"]["running"], 1)

    async def test_list_pending_interventions(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("error", pending_prompts=[PROMPT], run={"script": "b.py"})))
        (item,) = await srv.list_pending_interventions()
        self.assertEqual(item["spoke_id"], "star2")

    async def test_list_spokes_includes_state(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("running")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        states = {s["id"]: s["state"] for s in await srv.list_spokes()}
        self.assertEqual(states, {"star1": "running", "star2": "idle"})

    async def test_polling_does_not_fill_the_activity_log(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state()))
        self.answer("star2", "get_spoke_state", ok(spoke_state()))
        await srv.poll_spoke_states()
        self.assertEqual(len(srv._activity), 0)

    async def test_a_spoke_removed_mid_poll_is_skipped(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state()))
        self.answer("star2", "get_spoke_state", ok(spoke_state()))
        original = self.group.record_state

        def removed(spoke_id, *args, **kwargs):
            if spoke_id == "star1":
                raise ValueError("Unknown spoke_id")
            return original(spoke_id, *args, **kwargs)

        with mock.patch.object(self.group, "record_state", removed):
            await srv.poll_spoke_states()  # must not raise
        self.assertEqual(self.by_id()["star2"]["state"], "idle")

    async def test_the_poller_survives_a_failed_round(self):
        rounds = []

        async def flaky():
            rounds.append(1)
            if len(rounds) == 1:
                raise RuntimeError("boom")

        with mock.patch.object(srv, "poll_spoke_states", flaky):
            task = asyncio.create_task(srv.run_state_poller(interval_s=0.01))
            await asyncio.sleep(0.2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertGreaterEqual(len(rounds), 2)


class StatusRouteTests(FleetTestCase):
    async def test_status_json_carries_state_and_interventions(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("error", pending_prompts=[PROMPT], run={"script": "a.py"})))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        body = json.loads((await srv.status_json(None)).body)
        self.assertTrue(body["hub"]["operator_gate_configured"])
        self.assertEqual({s["id"]: s["state"] for s in body["spokes"]}, {"star1": "error", "star2": "idle"})
        self.assertEqual(body["pending_interventions"][0]["prompt_id"], "err-1")
        self.assertNotIn(TOKEN, json.dumps(body))

    async def test_gate_flag_reflects_the_hubs_environment(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(srv._OPERATOR_TOKEN_ENV, None)
            body = json.loads((await srv.status_json(None)).body)
        self.assertFalse(body["hub"]["operator_gate_configured"])


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _EventRequest(_Request):
    def __init__(self, body, spoke_id):
        super().__init__(body)
        self.query_params = {"spoke_id": spoke_id}


class SpokeEventPushTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))

    async def test_the_hub_subscribes_itself_to_a_spoke_that_offers_events(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", event_subscriptions=[])))
        self.answer("star1", "subscribe_command_events", ok({"subscriptions": []}))
        with mock.patch.dict(os.environ, {srv.HUB_URL_ENV: "http://hub-pc:8000"}):
            await srv.poll_spoke_states()
            (call,) = [c for c in self.calls if c[1] == "subscribe_command_events"]
            self.assertEqual(call[2], {"url": "http://hub-pc:8000/api/spoke-events?spoke_id=star1"})

            # Already subscribed (the spoke lists the callback): no second subscribe.
            self.answer("star1", "get_spoke_state", ok(spoke_state("idle", event_subscriptions=[call[2]["url"]])))
            await srv.poll_spoke_states()
        self.assertEqual(len([c for c in self.calls if c[1] == "subscribe_command_events"]), 1)

    async def test_an_older_spoke_without_events_is_not_subscribed(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.assertEqual([c for c in self.calls if c[1] == "subscribe_command_events"], [])

    async def test_a_pushed_status_shows_at_once(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", status={"status": "idle"})))
        await srv.poll_spoke_states()
        response = await srv.spoke_events(
            _EventRequest({"kind": "status", "status": "error", "detail": "Step 4 (aspirate) held", "source": "session", "at": 5.0}, "star1")
        )
        self.assertEqual(response.status_code, 200)
        star1 = self.by_id()["star1"]
        self.assertEqual(star1["status"], {"status": "error", "detail": "Step 4 (aspirate) held", "source": "session", "since": 5.0})
        self.assertIsNotNone(star1["status_pushed_at"])

    async def test_a_pushed_hold_refreshes_that_spoke(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        before = len([c for c in self.calls if c[1] == "get_spoke_state"])
        await srv.spoke_events(_EventRequest({"kind": "held", "step": 4}, "star1"))
        await asyncio.sleep(0.05)
        self.assertEqual(len([c for c in self.calls if c[1] == "get_spoke_state"]), before + 1)

    async def test_a_pushed_failure_is_kept_after_the_spoke_recovers(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        failure = {
            "kind": "error",
            "type": "command_error",
            "seq": 7,
            "at": 100.0,
            "session_id": "sess-1",
            "step": 3,
            "command": "tip_pickup",
            "error_type": "VenusCommandFailedError",
            "message": "Z drive: Step lost on Z drive",
        }
        await srv.spoke_events(_EventRequest(failure, "star1"))
        # A status event and a resume are not errors.
        await srv.spoke_events(_EventRequest({"kind": "status", "status": "idle", "at": 101.0}, "star1"))
        await srv.spoke_events(_EventRequest({"kind": "held", "reason": "stop", "step": 4}, "star1"))
        await asyncio.sleep(0.05)
        await srv.poll_spoke_states()  # the spoke is idle again and reports nothing

        (kept,) = self.by_id()["star1"]["recent_errors"]
        self.assertEqual(
            (kept["kind"], kept["command"], kept["step"], kept["session_id"], kept["at"]),
            ("error", "tip_pickup", 3, "sess-1", 100.0),
        )
        self.assertEqual(kept["message"], "Z drive: Step lost on Z drive")
        self.assertEqual(self.by_id()["star2"]["recent_errors"], [])

    async def test_a_held_error_survives_the_hold_clearing_and_is_not_duplicated_by_the_poll(self):
        held = {"kind": "held", "type": "run_hold", "seq": 9, "at": 50.0, "reason": "error", "step": 2,
                "command": "aspirate", "error_type": "VenusCommandFailedError", "message": "insufficient liquid"}
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", recent_errors=[held])))
        await srv.spoke_events(_EventRequest(held, "star1"))
        await asyncio.sleep(0.05)
        await srv.poll_spoke_states()
        await srv.poll_spoke_states()
        (kept,) = self.by_id()["star1"]["recent_errors"]
        self.assertEqual((kept["kind"], kept["command"], kept["held"]), ("held", "aspirate", True))

    async def test_session_operator_prompts_are_listed_until_answered(self):
        prompt = {"type": "operator_prompt", "error_uuid": "u-1", "code": "02/62",
                  "title": "Z drive: Step lost on Z drive", "top_level_actions": ["retry", "abort"],
                  "timestamp": "2026-10-29T12:00:00+00:00"}
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", pending_operator_prompts=[prompt])))
        await srv.spoke_events(_EventRequest({"kind": "operator_prompt", "seq": 5, "at": 10.0, **prompt}, "star1"))
        await asyncio.sleep(0.05)
        star1 = self.by_id()["star1"]
        self.assertEqual([p["error_uuid"] for p in star1["session_prompts"]], ["u-1"])
        (entry,) = star1["recent_errors"]  # the pushed and the polled copy are one record
        self.assertEqual((entry["kind"], entry["code"], entry["message"]), ("operator_prompt", "02/62", "Z drive: Step lost on Z drive"))

        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", pending_operator_prompts=[])))
        await srv.spoke_events(
            _EventRequest({"kind": "operator_prompt_resolved", "error_uuid": "u-1", "action": "retry", "at": 20.0}, "star1")
        )
        await asyncio.sleep(0.05)
        star1 = self.by_id()["star1"]
        self.assertEqual(star1["session_prompts"], [])
        self.assertEqual((star1["recent_errors"][0]["resolved_at"], star1["recent_errors"][0]["resolved_action"]), (20.0, "retry"))

    async def test_a_command_the_instrument_rejected_is_logged_as_an_error_call(self):
        self.answer("star1", "call_sdk_command", ok({"status": "error", "error_type": "VenusCommandFailedError", "message": "x"}))
        payload = await srv._dispatch_hub_call("star1", "call_sdk_command", {"name": "aspirate"}, 5.0)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(list(srv._activity)[-1]["status"], "error")

    async def test_error_history_is_filterable_and_served_over_http_and_as_a_tool(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        for seq, at, kind in ((1, 10.0, "error"), (2, 20.0, "error"), (3, 30.0, "held")):
            await srv.spoke_events(
                _EventRequest({"kind": kind, "seq": seq, "at": at, "command": f"c{seq}", "reason": "error", "message": "m"}, "star1")
            )
        await asyncio.sleep(0.05)

        self.assertEqual([e["command"] for e in srv.get_spoke_errors("star1")], ["c3", "c2", "c1"])
        self.assertEqual([e["command"] for e in srv.get_spoke_errors("star1", since=10.0)], ["c3", "c2"])
        self.assertEqual([e["command"] for e in srv.get_spoke_errors("star1", kind="error", limit=1)], ["c2"])
        with self.assertRaises(ValueError):
            srv.get_spoke_errors("star1", kind="bogus")
        with self.assertRaises(ValueError):
            srv.get_spoke_errors("nope")

        request = _EventRequest({}, "star1")
        request.path_params = {"spoke_id": "star1"}
        request.query_params = {"since": "15", "kind": "error"}
        body = json.loads((await srv.spoke_events_json(request)).body)
        self.assertEqual([e["command"] for e in body["events"]], ["c2"])
        request.query_params = {"limit": "x"}
        self.assertEqual((await srv.spoke_events_json(request)).status_code, 400)
        request.query_params = {"kind": "bogus"}
        self.assertEqual((await srv.spoke_events_json(request)).status_code, 400)
        request.path_params = {"spoke_id": "nope"}
        request.query_params = {}
        self.assertEqual((await srv.spoke_events_json(request)).status_code, 404)

    async def test_each_spoke_row_states_its_instrument_type(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", installed_instrument_type="Vantage")))
        await srv.poll_spoke_states()
        rows = self.by_id()
        self.assertEqual(rows["star1"]["instrument_type"], "Vantage")
        self.assertIsNone(rows["star2"]["instrument_type"])  # an older spoke doesn't say

    async def test_bad_pushes(self):
        self.assertEqual((await srv.spoke_events(_EventRequest({"kind": "status"}, "nope"))).status_code, 404)
        self.assertEqual((await srv.spoke_events(_EventRequest(ValueError("x"), "star1"))).status_code, 400)
        self.assertEqual((await srv.spoke_events(_EventRequest(["list"], "star1"))).status_code, 400)

    async def test_with_a_token_the_callback_is_keyed_and_checked(self):
        with mock.patch.dict(os.environ, {"HAMILTON_MCP_AUTH_TOKEN": "hub-tok", srv.HUB_URL_ENV: "http://hub-pc:8000"}):
            url = srv.hub_callback_url("star1", "http://star1/mcp")
            key = url.split("&key=")[1]
            self.assertEqual(len(key), 32)

            request = _EventRequest({"kind": "status", "status": "idle"}, "star1")
            self.assertEqual((await srv.spoke_events(request)).status_code, 403)  # no key
            request.query_params["key"] = "wrong"
            self.assertEqual((await srv.spoke_events(request)).status_code, 403)
            request.query_params["key"] = key
            self.assertEqual((await srv.spoke_events(request)).status_code, 200)

    async def test_an_older_unkeyed_subscription_is_replaced(self):
        old = "http://hub-pc:8000/api/spoke-events?spoke_id=star1"
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle", event_subscriptions=[old, "http://other/hook"])))
        self.answer("star1", "subscribe_command_events", ok({"subscriptions": []}))
        self.answer("star1", "unsubscribe_command_events", ok({"subscriptions": []}))
        with mock.patch.dict(os.environ, {"HAMILTON_MCP_AUTH_TOKEN": "hub-tok", srv.HUB_URL_ENV: "http://hub-pc:8000"}):
            await srv.poll_spoke_states()
        subscribed = [c[2]["url"] for c in self.calls if c[1] == "subscribe_command_events"]
        removed = [c[2]["url"] for c in self.calls if c[1] == "unsubscribe_command_events"]
        self.assertTrue(subscribed[0].startswith(old + "&key="))
        self.assertEqual(removed, [old])  # the orchestrator's own hook is left alone

    def test_callback_url_without_an_override_uses_this_pcs_address(self):
        os.environ.pop(srv.HUB_URL_ENV, None)
        url = srv.hub_callback_url("star 1", "http://127.0.0.1:8001/mcp")
        self.assertEqual(url, f"http://127.0.0.1:{srv.mcp.settings.port}/api/spoke-events?spoke_id=star%201")


class ResolveRouteTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.answer("star1", "operator_resolve_prompt", ok({"run_id": "run-1", "prompt_id": "err-1", "resolved": True, "action": "abort"}))
        self.answer("star1", "get_spoke_state", ok(spoke_state("running")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))

    def resolve_calls(self):
        return [c for c in self.calls if c[1] == "operator_resolve_prompt"]

    async def test_without_a_hub_token_it_refuses(self):
        os.environ.pop(srv._OPERATOR_TOKEN_ENV, None)
        response = await srv.resolve_intervention_route(_Request({"spoke_id": "star1"}))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.resolve_calls(), [])

    async def test_bad_bodies(self):
        cases = [
            ValueError("not json"),
            {},
            {"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1"},  # no action at all
            {"spoke_id": "star1", "run_id": "run-1", "action": "abort"},  # no prompt
            {"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "channel_actions": ["not", "a", "dict"]},
        ]
        for body in cases:
            with self.subTest(body=body):
                response = await srv.resolve_intervention_route(_Request(body))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.resolve_calls(), [])

    async def test_an_action_is_forwarded_with_the_hubs_token(self):
        response = await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort", "operator": "Sam"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.body)["ok"])
        (call,) = self.resolve_calls()
        self.assertEqual(call[2], {"run_id": "run-1", "prompt_id": "err-1", "action": "abort", "operator": "Sam", "token": TOKEN})
        self.assertNotIn(TOKEN, response.body.decode())

    async def test_per_channel_choices_are_forwarded_instead_of_an_action(self):
        picks = {"d1": 1026, "d2": 1026}
        response = await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "channel_actions": picks})
        )
        self.assertEqual(response.status_code, 200)
        (call,) = self.resolve_calls()
        self.assertEqual(call[2]["channel_actions"], picks)
        self.assertNotIn("action", call[2])
        self.assertEqual(call[2]["operator"], "hub dashboard")  # a default, so every decision is attributed

    async def test_operator_name_is_length_limited(self):
        await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort", "operator": "x" * 500})
        )
        (call,) = self.resolve_calls()
        self.assertEqual(len(call[2]["operator"]), 80)

    async def test_the_spokes_refusal_becomes_a_400_and_the_token_is_masked(self):
        self.answer("star1", "operator_resolve_prompt", failed(f"Wrong operator token {TOKEN}"))
        response = await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort"})
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(TOKEN, response.body.decode())

    async def test_an_unreachable_spoke_is_a_400_not_a_crash(self):
        self.answer("star1", "operator_resolve_prompt", ConnectionError("gone"))
        response = await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort"})
        )
        self.assertEqual(response.status_code, 400)

    async def test_the_spokes_state_is_refreshed_after_an_answer(self):
        await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort"})
        )
        self.assertEqual(self.by_id()["star1"]["state"], "running")

    async def test_the_token_is_never_a_tool_argument_an_agent_could_use(self):
        # The hub's generic call_tool_on cannot supply the token: it is not in any tool result,
        # status output, or activity record the agent can read.
        self.answer("star1", "get_spoke_state", ok(spoke_state("error", pending_prompts=[PROMPT], run={"script": "a.py"})))
        await srv.poll_spoke_states()
        await srv.resolve_intervention_route(
            _Request({"spoke_id": "star1", "run_id": "run-1", "prompt_id": "err-1", "action": "abort"})
        )
        visible = json.dumps(
            {
                "spokes": await srv.list_spokes(),
                "fleet": await srv.get_fleet_status(refresh=False),
                "interventions": await srv.list_pending_interventions(refresh=False),
                "activity": list(srv._activity),
                "status": json.loads((await srv.status_json(None)).body),
            },
            default=str,
        )
        self.assertNotIn(TOKEN, visible)


class _PathRequest:
    def __init__(self, path_params: dict, query_params: dict | None = None) -> None:
        self.path_params = path_params
        self.query_params = query_params or {}


class SpokeDetailRouteTests(FleetTestCase):
    async def test_aggregates_run_runs_and_consumables(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run", ok({"run_id": "r1", "status": "completed", "script": "a.py"}))
        self.answer("star1", "list_runs", ok({"result": [{"run_id": "r1", "script": "a.py", "status": "completed"}]}))
        self.answer("star1", "get_consumables_levels", ok({"result": [{"kind": "tip", "item_key": "P", "level": 90}]}))
        self.answer("star1", "list_low_consumables", ok({"result": []}))

        response = await srv.spoke_detail_json(_PathRequest({"spoke_id": "star1"}))
        body = json.loads(response.body)

        self.assertEqual(body["spoke"]["id"], "star1")
        self.assertEqual(body["run"]["run_id"], "r1")
        self.assertEqual(body["runs"]["result"][0]["run_id"], "r1")
        self.assertEqual(body["consumables"]["levels"]["result"][0]["item_key"], "P")
        self.assertEqual(body["consumables"]["low"]["result"], [])

    async def test_unknown_spoke_is_a_404(self):
        response = await srv.spoke_detail_json(_PathRequest({"spoke_id": "not-a-spoke"}))
        self.assertEqual(response.status_code, 404)

    async def test_survives_an_unreachable_spoke_without_raising(self):
        self.answer("star1", "get_spoke_state", ConnectionError("no route"))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run", ConnectionError("no route"))
        self.answer("star1", "list_runs", ConnectionError("no route"))
        self.answer("star1", "get_consumables_levels", ConnectionError("no route"))
        self.answer("star1", "list_low_consumables", ConnectionError("no route"))

        response = await srv.spoke_detail_json(_PathRequest({"spoke_id": "star1"}))
        body = json.loads(response.body)

        self.assertEqual(body["spoke"]["state"], "unreachable")
        self.assertEqual(body["run"]["status"], "error")


class SpokeRunDetailRouteTests(FleetTestCase):
    async def test_aggregates_run_summary_and_events(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run", ok({"run_id": "r1", "status": "completed", "tips": {}, "reagents": {}, "labware": []}))
        self.answer(
            "star1",
            "get_run_summary",
            ok({"run_id": "r1", "script": "a.py", "summary": {"result": "success", "duration_seconds": 12.5, "step_count": 3, "error_count": 0}}),
        )
        self.answer(
            "star1",
            "get_run_events",
            ok({"run_id": "r1", "status": "completed", "events": [{"seq": 1, "type": "line", "line": 3}], "next_since_seq": 2, "dropped": 0, "finished": True}),
        )

        response = await srv.spoke_run_detail_json(_PathRequest({"spoke_id": "star1", "run_id": "r1"}))
        body = json.loads(response.body)

        self.assertEqual(body["run"]["run_id"], "r1")
        self.assertEqual(body["summary"]["summary"]["result"], "success")
        self.assertEqual(body["events"]["events"][0]["type"], "line")

    async def test_events_are_fetched_beyond_the_first_page(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run", ok({"run_id": "r1", "status": "completed"}))
        self.answer("star1", "get_run_summary", failed("no summary"))
        pages = {
            0: {"events": [{"seq": i} for i in range(1, 1001)], "next_since_seq": 1000, "finished": True},
            1000: {"events": [{"seq": i} for i in range(1001, 1251)], "next_since_seq": 1250, "finished": True},
        }
        self.answer("star1", "get_run_events", lambda args: ok({"run_id": "r1", **pages[args["since_seq"]]}))
        body = json.loads((await srv.spoke_run_detail_json(_PathRequest({"spoke_id": "star1", "run_id": "r1"}))).body)
        self.assertEqual(len(body["events"]["events"]), 1250)

    async def test_unknown_spoke_is_a_404(self):
        response = await srv.spoke_run_detail_json(_PathRequest({"spoke_id": "not-a-spoke", "run_id": "r1"}))
        self.assertEqual(response.status_code, 404)

    async def test_a_run_still_in_progress_has_no_summary_but_still_returns(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("running")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run", ok({"run_id": "r1", "status": "running", "tips": {}, "reagents": {}, "labware": []}))
        self.answer("star1", "get_run_summary", failed("Run r1 is still running; no summary until it finishes."))
        self.answer("star1", "get_run_events", ok({"run_id": "r1", "status": "running", "events": [], "next_since_seq": 0, "dropped": 0, "finished": False}))

        response = await srv.spoke_run_detail_json(_PathRequest({"spoke_id": "star1", "run_id": "r1"}))
        body = json.loads(response.body)

        self.assertEqual(body["run"]["status"], "running")
        self.assertEqual(body["summary"]["status"], "error")


class SpokeCurrentRunEventsRouteTests(FleetTestCase):
    async def test_forwards_since_seq_and_a_short_wait_s(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("running")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer(
            "star1",
            "get_run_events",
            ok({"run_id": "r1", "status": "running", "events": [{"seq": 5, "type": "line", "line": 9}], "next_since_seq": 6, "dropped": 0, "finished": False}),
        )

        response = await srv.spoke_current_run_events_json(_PathRequest({"spoke_id": "star1"}, {"since_seq": "5"}))
        body = json.loads(response.body)

        self.assertEqual(body["events"]["events"][0]["line"], 9)
        call = next(c for c in self.calls if c[1] == "get_run_events")
        self.assertEqual(call[2]["run_id"], None)
        self.assertEqual(call[2]["since_seq"], 5)
        self.assertEqual(call[2]["wait_s"], srv._CURRENT_RUN_EVENTS_WAIT_S)

    async def test_missing_since_seq_defaults_to_zero(self):
        self.answer("star1", "get_spoke_state", ok(spoke_state("idle")))
        self.answer("star2", "get_spoke_state", ok(spoke_state("idle")))
        await srv.poll_spoke_states()
        self.answer("star1", "get_run_events", ok({"run_id": "r1", "status": "idle", "events": [], "next_since_seq": 0, "dropped": 0, "finished": True}))

        await srv.spoke_current_run_events_json(_PathRequest({"spoke_id": "star1"}))
        call = next(c for c in self.calls if c[1] == "get_run_events")
        self.assertEqual(call[2]["since_seq"], 0)

    async def test_unknown_spoke_is_a_404(self):
        response = await srv.spoke_current_run_events_json(_PathRequest({"spoke_id": "not-a-spoke"}))
        self.assertEqual(response.status_code, 404)


class FleetConsumablesTests(FleetTestCase):
    async def test_merges_rows_from_every_spoke_tagged_with_spoke_id(self):
        self.answer(
            "star1",
            "get_consumables_levels",
            ok({"result": [{"kind": "tip", "item_key": "P", "level": 92, "low": False}]}),
        )
        self.answer(
            "star2",
            "get_consumables_levels",
            ok({"result": [{"kind": "reagent", "item_key": "Trough1", "level": 500, "low": True}]}),
        )

        data = await srv.get_fleet_consumables()

        self.assertEqual({i["spoke_id"] for i in data["items"]}, {"star1", "star2"})
        self.assertEqual(len(data["low_items"]), 1)
        self.assertEqual(data["low_items"][0]["spoke_id"], "star2")
        self.assertEqual(data["errors"], {})

    async def test_kind_filter_is_forwarded_to_every_spoke(self):
        self.answer("star1", "get_consumables_levels", ok({"result": []}))
        self.answer("star2", "get_consumables_levels", ok({"result": []}))
        await srv.get_fleet_consumables(kind="tip")
        for call in self.calls:
            if call[1] == "get_consumables_levels":
                self.assertEqual(call[2], {"kind": "tip"})

    async def test_one_spokes_failure_does_not_hide_the_others(self):
        self.answer("star1", "get_consumables_levels", ConnectionError("no route"))
        self.answer("star2", "get_consumables_levels", ok({"result": [{"kind": "tip", "item_key": "P", "low": False}]}))

        data = await srv.get_fleet_consumables()

        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["spoke_id"], "star2")
        self.assertIn("star1", data["errors"])

    async def test_spoke_ids_narrows_the_target_set(self):
        self.answer("star1", "get_consumables_levels", ok({"result": []}))
        data = await srv.get_fleet_consumables(spoke_ids=["star1"])
        self.assertEqual(data["errors"], {})
        self.assertFalse(any(c[1] == "get_consumables_levels" and c[0] == self.urls["star2"] for c in self.calls))

    async def test_dashboard_route_returns_the_same_shape(self):
        self.answer("star1", "get_consumables_levels", ok({"result": [{"kind": "tip", "item_key": "P", "low": True}]}))
        self.answer("star2", "get_consumables_levels", ok({"result": []}))

        response = await srv.fleet_consumables_json(None)
        body = json.loads(response.body)

        self.assertEqual(len(body["low_items"]), 1)
        self.assertIn("polled_at", body)


class SharedCallCacheTests(FleetTestCase):
    async def test_repeated_page_polls_share_one_spoke_call(self):
        self.answer("star1", "get_consumables_levels", ok({"result": []}))
        with mock.patch.object(srv, "_UI_CACHE_TTL_S", 30.0):
            first = await srv._shared_hub_call("star1", "get_consumables_levels", None, 5.0)
            second, third = await asyncio.gather(
                srv._shared_hub_call("star1", "get_consumables_levels", None, 5.0),
                srv._shared_hub_call("star1", "get_consumables_levels", None, 5.0),
            )
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(second["result"], third["result"])
        self.assertEqual(len([c for c in self.calls if c[1] == "get_consumables_levels"]), 1)

    async def test_different_arguments_are_not_shared(self):
        self.answer("star1", "get_consumables_levels", ok({"result": []}))
        with mock.patch.object(srv, "_UI_CACHE_TTL_S", 30.0):
            await srv._shared_hub_call("star1", "get_consumables_levels", {"kind": "tip"}, 5.0)
            await srv._shared_hub_call("star1", "get_consumables_levels", {"kind": "reagent"}, 5.0)
        self.assertEqual(len(self.calls), 2)


class StaticAssetRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_serves_a_known_file(self):
        response = await srv.static_asset(_PathRequest({"path": "hub.css"}))
        self.assertEqual(response.status_code, 200)

    async def test_pages_and_assets_are_revalidated_not_cached_blindly(self):
        for response in (
            await srv.static_asset(_PathRequest({"path": "hub.css"})),
            await srv.dashboard(_PathRequest({})),
            await srv.instrument_page(_PathRequest({"spoke_id": "x"})),
        ):
            self.assertEqual(response.headers["cache-control"], "no-cache")

    async def test_page_links_are_versioned_so_a_stale_stylesheet_cannot_linger(self):
        response = await srv.instrument_page(_PathRequest({"spoke_id": "x"}))
        body = response.body.decode()
        self.assertRegex(body, r'href="/static/hub\.css\?v=\d+"')
        self.assertRegex(body, r'src="/static/trace\.js\?v=\d+"')
        self.assertNotIn('"/static/hub.css"', body)

    async def test_missing_file_is_a_404(self):
        response = await srv.static_asset(_PathRequest({"path": "nope-not-here.css"}))
        self.assertEqual(response.status_code, 404)

    async def test_rejects_path_traversal_outside_the_static_dir(self):
        response = await srv.static_asset(_PathRequest({"path": "../server.py"}))
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
