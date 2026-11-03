"""Stop / Resume / Resume From for call_sdk_command (run_control.py and its server tools).

RunControlTests drive RunControl directly with a scripted executor standing in for
_dispatch_sdk_command, so each test controls exactly which attempt fails and how.
ServerRunControlTests go through the real MCP tool functions with a fake StarClient whose
aspirate raises a real VenusCommandFailedError (a Cancel-answered error) on demand.
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from typing import Any
from unittest.mock import patch

import hamilton_venus_mcp.server as srv
from hamilton_venus_mcp import instrument_guard
from hamilton_venus_mcp.script_validator import validate_bytes
from hamilton_venus_mcp.run_control import HELD, RUNNING, STOP_REQUESTED, RunControl, RunControlError

from hamilton_venus.exceptions import VenusCommandAbortedError, VenusCommandFailedError
from hamilton_venus.models import CommandResponse


def _ok(name: str) -> dict[str, Any]:
    return {"command": name, "status": "success", "result": f"{name}-ok"}


def _cancelled(name: str) -> dict[str, Any]:
    return {"command": name, "status": "error", "error_type": "VenusCommandFailedError", "message": "insufficient liquid"}


def _aborted(name: str) -> dict[str, Any]:
    return {"command": name, "status": "error", "error_type": "VenusCommandAbortedError", "message": "aborted"}


class _ScriptedExecutor:
    """Returns success unless a (name, nth call of that name) is scripted to fail."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[tuple[str, int], Any] = {}

    def fail(self, name: str, nth: int, kind=_cancelled) -> None:
        self.failures[(name, nth)] = kind

    async def __call__(self, name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        nth = self.calls.count(name)
        kind = self.failures.get((name, nth))
        return kind(name) if kind else _ok(name)


class RunControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.rc = RunControl(on_event=self.events.append)
        self.rc.reset(hold_on_error=True)
        self.ex = _ScriptedExecutor()

    async def _held_aspirate_loop(self) -> dict[str, Any]:
        """pickup(1) aspirate(2) dispense(3) aspirate(4, fails) -> held at 4."""
        for name in ("tip_pickup", "aspirate", "dispense"):
            self.assertEqual((await self.rc.submit(name, {}, self.ex))["status"], "success")
        self.ex.fail("aspirate", 2)
        return await self.rc.submit("aspirate", {"volumes": 50}, self.ex)

    async def test_error_without_hold_on_error_is_reported_as_before(self) -> None:
        self.rc.reset(hold_on_error=False)
        self.ex.fail("aspirate", 1)
        result = await self.rc.submit("aspirate", {}, self.ex)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["step"], 1)
        self.assertEqual(self.rc.state, RUNNING)

    async def test_error_without_hold_publishes_a_command_error_event(self) -> None:
        self.rc.reset(hold_on_error=False)
        self.rc.session_id = "sess-1"
        self.ex.fail("tip_pickup", 1)
        await self.rc.submit("tip_pickup", {}, self.ex)
        errors = [e for e in self.events if e["type"] == "command_error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(
            (errors[0]["command"], errors[0]["step"], errors[0]["error_type"], errors[0]["message"], errors[0]["held"]),
            ("tip_pickup", 1, "VenusCommandFailedError", "insufficient liquid", False),
        )
        self.assertEqual(errors[0]["session_id"], "sess-1")
        self.assertEqual(self.rc.recent_errors(), errors)

    async def test_abort_and_executor_exceptions_publish_command_errors(self) -> None:
        self.rc.reset(hold_on_error=False)
        self.ex.fail("aspirate", 1, kind=_aborted)
        await self.rc.submit("aspirate", {}, self.ex)

        async def _boom(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("fixed_height expected 1 entries")

        with self.assertRaises(ValueError):
            await self.rc.submit("dispense", {}, _boom)
        self.assertEqual(
            [(e["command"], e["error_type"]) for e in self.events if e["type"] == "command_error"],
            [("aspirate", "VenusCommandAbortedError"), ("dispense", "ValueError")],
        )

    async def test_a_held_error_is_kept_in_recent_errors_after_the_hold_clears(self) -> None:
        await self._held_aspirate_loop()
        self.assertEqual([e["type"] for e in self.events if e["type"] == "command_error"], [])
        self.rc.release_hold()
        kept = self.rc.recent_errors()
        self.assertEqual([(e["type"], e["command"]) for e in kept], [("run_hold", "aspirate")])
        self.assertIsNone(self.rc.hold)

    async def test_successful_commands_publish_no_error(self) -> None:
        await self.rc.submit("tip_pickup", {}, self.ex)
        self.assertEqual(self.rc.recent_errors(), [])

    async def test_cancel_error_holds_and_await_stays_held(self) -> None:
        held = await self._held_aspirate_loop()
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["step"], 4)
        self.assertEqual(held["hold"]["reason"], "error")
        self.assertEqual(self.rc.state, HELD)
        self.assertEqual((await self.rc.await_step(4, wait_s=0.2))["status"], "held")
        self.assertTrue(any(e["type"] == "run_hold" for e in self.events))

    async def test_abort_is_never_held(self) -> None:
        self.ex.fail("aspirate", 1, kind=_aborted)
        result = await self.rc.submit("aspirate", {}, self.ex)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.rc.state, RUNNING)

    async def test_normal_command_refused_while_held_but_recovery_runs(self) -> None:
        await self._held_aspirate_loop()
        with self.assertRaises(RunControlError):
            await self.rc.submit("dispense", {}, self.ex)
        result = await self.rc.run_recovery("unlock_door", {}, self.ex)
        self.assertEqual(result["status"], "success")
        recovery = [e for e in self.rc.journal() if e["recovery"]]
        self.assertEqual([e["name"] for e in recovery], ["unlock_door"])
        self.assertIsNone(recovery[0]["step"])

    async def test_resume_reruns_held_step_and_releases_waiter(self) -> None:
        await self._held_aspirate_loop()
        waiter = asyncio.create_task(self.rc.await_step(4, wait_s=5))
        await asyncio.sleep(0.05)
        await self.rc.run_recovery("unlock_door", {}, self.ex)
        summary = await self.rc.resume(self.ex)
        self.assertEqual(summary["result"]["status"], "success")
        self.assertEqual((await waiter)["status"], "success")
        self.assertEqual(self.rc.state, RUNNING)
        self.assertEqual(self.ex.calls[-1], "aspirate")

    async def test_resume_that_fails_again_stays_held(self) -> None:
        await self._held_aspirate_loop()
        self.ex.fail("aspirate", 3)
        summary = await self.rc.resume(self.ex)
        self.assertEqual(summary["state"], HELD)
        self.assertEqual((await self.rc.await_step(4, wait_s=0))["status"], "held")
        await self.rc.resume(self.ex)
        self.assertEqual((await self.rc.await_step(4, wait_s=0))["status"], "success")

    async def test_resume_from_replays_successful_steps_in_order_without_recovery(self) -> None:
        await self._held_aspirate_loop()
        await self.rc.run_recovery("tip_eject", {}, self.ex)
        await self.rc.run_recovery("tip_pickup", {}, self.ex)
        self.ex.calls.clear()
        self.ex.failures.clear()  # reservoir refilled
        summary = await self.rc.resume_from(2, self.ex)
        # steps 2 (aspirate) and 3 (dispense) replayed, then held step 4 (aspirate)
        self.assertEqual(self.ex.calls, ["aspirate", "dispense", "aspirate"])
        self.assertEqual(summary["result"]["status"], "success")
        self.assertEqual((await self.rc.await_step(4, wait_s=0))["status"], "success")
        replays = [a for a in self.rc.journal()[2]["attempts"] if a["kind"] == "replay"]
        self.assertEqual(len(replays), 1)  # step 3 (dispense) replayed once

    async def test_replay_failure_reholds_and_resume_continues_from_there(self) -> None:
        await self._held_aspirate_loop()
        self.ex.calls.clear()
        self.ex.failures.clear()
        self.ex.fail("dispense", 1)  # the replay of step 3
        summary = await self.rc.resume_from(2, self.ex)
        self.assertEqual(summary["state"], HELD)
        self.assertEqual(summary["hold"]["step"], 4)
        self.assertEqual(summary["hold"]["replay_pending"], [3])
        await self.rc.resume(self.ex)
        self.assertEqual(self.ex.calls, ["aspirate", "dispense", "dispense", "aspirate"])
        self.assertEqual((await self.rc.await_step(4, wait_s=0))["status"], "success")

    async def test_abort_during_replay_fails_the_held_step(self) -> None:
        await self._held_aspirate_loop()
        self.ex.failures.clear()
        self.ex.calls.clear()
        self.ex.fail("dispense", 1, kind=_aborted)
        await self.rc.resume_from(2, self.ex)
        self.assertEqual(self.rc.state, RUNNING)
        self.assertEqual((await self.rc.await_step(4, wait_s=0))["status"], "error")
        self.assertNotIn("aspirate", self.ex.calls[1:])

    async def test_resume_from_rejects_a_step_after_the_held_one(self) -> None:
        await self._held_aspirate_loop()
        with self.assertRaises(RunControlError):
            await self.rc.resume_from(5, self.ex)

    async def test_stop_holds_the_next_command_before_it_runs(self) -> None:
        await self.rc.submit("tip_pickup", {}, self.ex)
        self.rc.request_stop()
        self.assertEqual(self.rc.state, STOP_REQUESTED)
        held = await self.rc.submit("aspirate", {}, self.ex)
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["hold"]["reason"], "stop")
        self.assertEqual(self.ex.calls, ["tip_pickup"])  # aspirate has not run
        await self.rc.resume(self.ex)
        self.assertEqual(self.ex.calls, ["tip_pickup", "aspirate"])

    async def test_stop_works_without_hold_on_error(self) -> None:
        self.rc.reset(hold_on_error=False)
        self.rc.request_stop()
        self.assertEqual((await self.rc.submit("aspirate", {}, self.ex))["status"], "held")

    async def test_resume_with_stop_but_nothing_held_just_cancels_the_stop(self) -> None:
        self.rc.request_stop()
        await self.rc.resume(self.ex)
        self.assertEqual(self.rc.state, RUNNING)

    async def test_release_hold_fails_the_waiter(self) -> None:
        await self._held_aspirate_loop()
        self.rc.release_hold("operator gave up")
        result = await self.rc.await_step(4, wait_s=0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "HoldReleased")
        self.assertEqual(self.rc.state, RUNNING)

    async def test_resume_with_nothing_held_raises(self) -> None:
        with self.assertRaises(RunControlError):
            await self.rc.resume(self.ex)

    async def test_events_are_numbered_and_kept_across_resets(self) -> None:
        await self._held_aspirate_loop()
        held = [e for e in self.rc.events_since(0) if e["type"] == "run_hold"]
        self.assertEqual(len(held), 1)
        self.assertEqual((held[0]["step"], held[0]["command"], held[0]["reason"]), (4, "aspirate", "error"))
        self.assertEqual(held[0]["message"], "insufficient liquid")
        seq = self.rc.last_event_seq
        await self.rc.resume(self.ex)
        kinds = [e.get("event") for e in self.rc.events_since(seq)]
        self.assertEqual(kinds, ["resuming", "resumed"])
        self.rc.reset()
        self.assertEqual(self.rc.last_event_seq, seq + 2)
        self.assertEqual(self.events, list(self.rc.events_since(0)))  # same events went to on_event

    async def test_hold_brief_trims_the_error(self) -> None:
        self.ex.fail("aspirate", 1, kind=lambda n: {**_cancelled(n), "message": "x" * 5000, "response": {"big": 1}})
        await self.rc.submit("aspirate", {}, self.ex)
        brief = self.rc.hold_brief
        self.assertEqual(len(brief["message"]), 400)
        self.assertNotIn("error", brief)
        self.assertIn("response", self.rc.hold["error"])

    async def test_reset_clears_journal_and_hold(self) -> None:
        await self._held_aspirate_loop()
        self.rc.reset()
        self.assertEqual(self.rc.state, RUNNING)
        self.assertIsNone(self.rc.hold)
        self.assertEqual(self.rc.journal(), [])


_LIGHT_NAMES = {0: "white", 1: "red", 2: "green", 3: "blue"}


class _FakeStarClient:
    fail_aspirate_times = 0
    abort_aspirate = False
    lights: list[tuple[str, bool, int]] = []

    def __init__(self, **kwargs: object) -> None:
        self._session_id = "fake-session"
        self.calls: list[str] = []

    def __enter__(self) -> _FakeStarClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def instrument_is_idle(self) -> bool:
        self.calls.append("instrument_is_idle")
        return True

    def lock_door(self, *args: object, **kwargs: object) -> None:
        self.calls.append("lock_door")

    def status_light_set_front_light(self, color: object, blink: bool = False, progress: int = 0) -> None:
        _FakeStarClient.lights.append((_LIGHT_NAMES[int(color)], blink, progress))

    def aspirate(self, *args: object, **kwargs: object) -> str:
        self.calls.append("aspirate")
        if _FakeStarClient.abort_aspirate:
            raise VenusCommandAbortedError("method aborted")
        if _FakeStarClient.fail_aspirate_times > 0:
            _FakeStarClient.fail_aspirate_times -= 1
            raise VenusCommandFailedError(
                CommandResponse(action_name="aspirate", return_status="Failed", return_code=3, return_parameters={})
            )
        return "aspirated"


async def _fake_connect(initialize: bool = False) -> None:
    srv._session._instrument_connected = True


class ServerRunControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _FakeStarClient.fail_aspirate_times = 0
        _FakeStarClient.abort_aspirate = False
        _FakeStarClient.lights = []
        srv._command_event_webhooks.clear()
        srv._status_light.enabled = True
        srv._status_light.idle_after_s = 0.1
        self._patches = [
            patch("hamilton_workflow_framework.session.StarClient", _FakeStarClient),
            patch("hamilton_workflow_framework.session.VantageClient", _FakeStarClient),
            # Bypass catalog lookup/coercion: the fake client's methods take anything.
            patch.object(srv, "_prepare_sdk_command", lambda name, kwargs: (getattr(srv._resolve_target(name), name), dict(kwargs or {}))),
        ]
        for p in self._patches:
            p.start()
        await srv.start_session(simulate=True, blank_deck=True, hold_on_error=True)
        # The front light belongs to the instrument: only a connected session drives it.
        with patch.object(srv._session, "connect_instrument", _fake_connect):
            await srv.connect_instrument()
        await self._lights_settle("white")
        _FakeStarClient.lights.clear()

    async def asyncTearDown(self) -> None:
        await srv.close_session()
        for p in reversed(self._patches):
            p.stop()

    async def test_held_call_resumes_through_the_tools(self) -> None:
        self.assertEqual((await srv.call_sdk_command("instrument_is_idle"))["step"], 1)
        _FakeStarClient.fail_aspirate_times = 1
        held = await srv.call_sdk_command("aspirate", {"volumes": 10})
        self.assertEqual(held["status"], "held")
        self.assertEqual(srv.get_command_hold()["state"], HELD)

        refused = await srv.call_sdk_command("instrument_is_idle")
        self.assertEqual(refused["error_type"], "CommandHeld")
        recovery = await srv.call_sdk_command("lock_door", recovery=True)
        self.assertEqual(recovery["status"], "success")

        waiter = asyncio.create_task(srv.await_command_step(held["step"], wait_s=5))
        await asyncio.sleep(0.05)
        await srv.resume_commands_from(1)
        result = await waiter
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], "aspirated")
        self.assertEqual(srv._session.star.calls, ["instrument_is_idle", "aspirate", "lock_door", "instrument_is_idle", "aspirate"])

    async def test_abort_is_reported_not_held(self) -> None:
        _FakeStarClient.abort_aspirate = True
        result = await srv.call_sdk_command("aspirate")
        self.assertEqual(result["status"], "error")
        self.assertEqual(srv.get_command_hold()["state"], RUNNING)

    async def test_plain_failure_reaches_subscribers_and_state(self) -> None:
        posted: list[dict[str, Any]] = []

        class _Response:
            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b""

        def _urlopen(request: Any, timeout: float) -> _Response:
            posted.append(json.loads(request.data))
            return _Response()

        srv._run_control.hold_on_error = False
        srv.subscribe_command_events("http://hub.local/events", kinds=["error"])
        _FakeStarClient.abort_aspirate = True
        with patch.object(srv.urllib.request, "urlopen", _urlopen):
            result = await srv.call_sdk_command("aspirate")
            for _ in range(50):
                if posted:
                    break
                await asyncio.sleep(0.02)
        self.assertEqual(result["status"], "error")
        self.assertEqual([(p["kind"], p["command"]) for p in posted], [("error", "aspirate")])
        self.assertEqual(posted[0]["session_id"], srv._session.session_id)
        state = await srv._spoke_state_once()
        self.assertIn("aspirate", [e.get("command") for e in state["recent_errors"]])

    async def test_pending_operator_prompt_is_an_event_a_status_and_state(self) -> None:
        prompt = {
            "type": "operator_prompt",
            "error_uuid": "u-1",
            "code": "02/62",
            "title": "Z drive: Step lost on Z drive",
            "channel_errors": [{"channel": 1}],
            "top_level_actions": ["retry", "abort"],
            "timestamp": "2026-10-29T00:00:00+00:00",
        }
        start_seq = srv._run_control.last_event_seq
        srv._session._pending_prompt_messages["u-1"] = prompt
        srv._session._notify_prompt_listeners(prompt)
        update = await srv.wait_for_command_event(since_seq=start_seq, wait_s=0)
        kinds = [e["kind"] for e in update["events"]]
        self.assertIn("operator_prompt", kinds)
        self.assertEqual(update["status"]["status"], "error")
        self.assertIn("Step lost on Z drive", update["status"]["detail"])
        raised = next(e for e in update["events"] if e["kind"] == "operator_prompt")
        self.assertEqual(raised["channel_error_count"], 1)
        self.assertNotIn("channel_errors", raised)
        state = await srv._spoke_state_once()
        self.assertEqual([p["error_uuid"] for p in state["pending_operator_prompts"]], ["u-1"])

        srv._session._pending_prompt_messages.clear()
        srv._session._notify_prompt_listeners(srv._session._resolved_message("u-1", "retry"))
        update = await srv.wait_for_command_event(since_seq=update["next_since_seq"], wait_s=0)
        self.assertIn("operator_prompt_resolved", [e["kind"] for e in update["events"]])
        self.assertNotEqual(update["status"]["status"], "error")

    async def test_stop_tool_and_release(self) -> None:
        srv.stop_commands()
        held = await srv.call_sdk_command("aspirate")
        self.assertEqual(held["status"], "held")
        srv.release_command_hold()
        self.assertEqual((await srv.await_command_step(held["step"], wait_s=0))["status"], "error")
        with self.assertRaises(ValueError):
            await srv.resume_commands()

    async def test_wait_for_command_event_wakes_on_hold_and_notifies(self) -> None:
        posted: list[dict[str, Any]] = []

        class _Response:
            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b""

        def _urlopen(request: Any, timeout: float) -> _Response:
            posted.append({"url": request.full_url, **json.loads(request.data)})
            return _Response()

        srv.subscribe_command_events("http://orchestrator.local/hold", kinds=["held"])
        start_seq = srv._run_control.last_event_seq
        waiter = asyncio.create_task(srv.wait_for_command_event(since_seq=start_seq, wait_s=10))
        await asyncio.sleep(0.05)
        _FakeStarClient.fail_aspirate_times = 1
        with patch.object(srv.urllib.request, "urlopen", _urlopen):
            t0 = time.monotonic()
            await srv.call_sdk_command("aspirate")
            update = await waiter
            self.assertLess(time.monotonic() - t0, 2.0)
            for _ in range(50):
                if posted and _FakeStarClient.lights:
                    break
                await asyncio.sleep(0.02)
            self.assertIn("held", [e["kind"] for e in update["events"]])
            self.assertEqual(update["hold"]["command"], "aspirate")
            self.assertEqual(posted[0]["url"], "http://orchestrator.local/hold")
            self.assertEqual((posted[0]["kind"], posted[0]["command"]), ("held", "aspirate"))
            await srv.resume_commands()
        self.assertEqual(len(posted), 1)  # subscribed to "held" only

    async def _lights_settle(self, last: str) -> list[str]:
        for _ in range(100):
            if _FakeStarClient.lights and _FakeStarClient.lights[-1][0] == last:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        return [color if progress else "off" for color, _blink, progress in _FakeStarClient.lights]

    async def test_no_light_commands_until_the_instrument_is_connected(self) -> None:
        await srv.close_session()
        _FakeStarClient.lights.clear()
        await srv.start_session(simulate=True, blank_deck=True)
        await srv.call_sdk_command("lock_door")  # e.g. a deck command before connecting
        await asyncio.sleep(0.2)
        await srv.close_session()  # a session that never connected: nothing to turn off
        self.assertEqual(_FakeStarClient.lights, [])

        await srv.start_session(simulate=True, blank_deck=True)
        with patch.object(srv._session, "connect_instrument", _fake_connect):
            await srv.connect_instrument()
        self.assertEqual(await self._lights_settle("white"), ["white"])  # first change once connected

    async def test_status_light_follows_venus_colors(self) -> None:
        with patch.object(srv._session, "connect_instrument", _fake_connect):
            await srv.connect_instrument()
        self.assertEqual(await self._lights_settle("white"), ["white"])  # session connected

        await srv.call_sdk_command("lock_door")
        self.assertEqual(await self._lights_settle("white"), ["white", "green", "white"])  # ran, then idle

        _FakeStarClient.lights.clear()
        _FakeStarClient.fail_aspirate_times = 1
        await srv.call_sdk_command("aspirate")
        self.assertEqual(await self._lights_settle("red"), ["green", "red"])  # held on an error
        await srv.call_sdk_command("lock_door", recovery=True)  # recovery leaves it red
        self.assertEqual(await self._lights_settle("red"), ["green", "red"])
        await srv.resume_commands()
        self.assertEqual(await self._lights_settle("white"), ["green", "red", "green", "white"])

        _FakeStarClient.lights.clear()
        srv.stop_commands()
        self.assertEqual(await self._lights_settle("blue"), ["blue"])  # manual stop
        held = await srv.call_sdk_command("aspirate")
        self.assertEqual(held["status"], "held")
        await srv.resume_commands()
        self.assertEqual(await self._lights_settle("white"), ["blue", "green", "white"])

        _FakeStarClient.lights.clear()
        await srv.close_session()
        self.assertEqual(_FakeStarClient.lights, [("white", False, 0)])  # off
        self.assertTrue(all(blink is False for _c, blink, _p in _FakeStarClient.lights))

    async def test_status_light_uses_the_0_to_5_progress_range(self) -> None:
        await srv.call_sdk_command("lock_door")
        await self._lights_settle("white")
        self.assertTrue(_FakeStarClient.lights)
        self.assertTrue(all(0 <= progress <= 5 for _c, _b, progress in _FakeStarClient.lights))
        self.assertEqual(_FakeStarClient.lights[0][2], 5)

    async def test_a_failing_light_command_is_not_resent_before_every_command(self) -> None:
        attempts = []

        def failing_light(self, color, blink=False, progress=0):
            attempts.append(progress)
            raise RuntimeError("out of range")

        with patch.object(_FakeStarClient, "status_light_set_front_light", failing_light):
            for _ in range(4):
                await srv.call_sdk_command("lock_door")
        self.assertEqual(len(attempts), 1)  # one try for green, not one per command

    async def _statuses_settle(self, last: str, since_seq: int) -> list[str]:
        for _ in range(100):
            statuses = [e["status"] for e in srv._run_control.events_since(since_seq) if e["type"] == "status"]
            if statuses and statuses[-1] == last:
                return statuses
            await asyncio.sleep(0.02)
        return statuses

    async def test_spoke_status_events_follow_the_session(self) -> None:
        seq = srv._run_control.last_event_seq
        srv._publish_status()  # session started in asyncSetUp
        self.assertEqual(srv._status_view()["status"], "idle")

        await srv.call_sdk_command("lock_door")
        self.assertEqual(await self._statuses_settle("idle", seq), ["running", "idle"])

        seq = srv._run_control.last_event_seq
        _FakeStarClient.fail_aspirate_times = 1
        await srv.call_sdk_command("aspirate")
        self.assertEqual(await self._statuses_settle("error", seq), ["running", "error"])
        self.assertIn("aspirate", srv._status_view()["detail"])
        await srv.resume_commands()
        self.assertEqual(await self._statuses_settle("idle", seq), ["running", "error", "running", "idle"])

        seq = srv._run_control.last_event_seq
        srv.stop_commands()
        self.assertEqual(await self._statuses_settle("hold", seq), ["hold"])
        srv.release_command_hold()
        self.assertEqual(await self._statuses_settle("idle", seq), ["hold", "running", "idle"])

        seq = srv._run_control.last_event_seq
        with patch.object(srv.venus_api, "pause", lambda: {"ok": True}), patch.object(srv.venus_api, "resume", lambda: {"ok": True}):
            await srv.venus_pause()
            await srv.venus_resume()
        self.assertEqual(await self._statuses_settle("idle", seq), ["paused", "idle"])

        seq = srv._run_control.last_event_seq
        await srv.close_session()
        self.assertEqual(await self._statuses_settle("terminated", seq), ["terminated"])
        update = await srv.wait_for_command_event(since_seq=seq, wait_s=0)
        event = [e for e in update["events"] if e["kind"] == "status"][-1]
        self.assertEqual((event["status"], event["previous"], event["source"]), ("terminated", "idle", "session"))

    async def test_a_script_run_drives_the_status(self) -> None:
        seq = srv._run_control.last_event_seq
        script_state = {"run": {"run_id": "r1"}, "paused": False, "pending_prompts": [], "state": "running", "detail": "x.py (running)"}
        with patch.object(srv._run_manager, "state", lambda **_: script_state):
            srv._publish_status()
            script_state.update(paused=True, detail="x.py (paused)")
            srv._publish_status()
            script_state.update(paused=False, pending_prompts=[{"title": "Tip Pick Up - Error"}], state="error", detail="Tip Pick Up - Error")
            srv._publish_status()
        statuses = [(e["status"], e["source"]) for e in srv._run_control.events_since(seq) if e["type"] == "status"]
        self.assertEqual(statuses, [("running", "script"), ("paused", "script"), ("error", "script")])
        srv._publish_status()  # run gone again -> back to the session
        self.assertEqual(srv._status_view()["status"], "idle")

    async def test_spoke_state_reports_status_and_subscriptions(self) -> None:
        srv.subscribe_command_events("http://hub.local:8000/api/spoke-events?spoke_id=s1")
        with patch.object(srv.venus_api, "get_run_state", lambda: {"state": "idle"}):
            state = await srv.get_spoke_state()
        self.assertEqual(state["status"]["status"], "idle")
        self.assertEqual(state["event_subscriptions"], ["http://hub.local:8000/api/spoke-events?spoke_id=s1"])

    async def test_a_query_leaves_the_light_and_status_alone(self) -> None:
        seq = srv._run_control.last_event_seq
        for _ in range(3):
            await srv.call_sdk_command("instrument_is_idle")
        await asyncio.sleep(0.2)
        self.assertEqual(_FakeStarClient.lights, [])
        self.assertEqual([e for e in srv._run_control.events_since(seq) if e["type"] == "status"], [])
        await srv.call_sdk_command("lock_door")  # real activity still turns it green
        self.assertEqual(await self._lights_settle("white"), ["green", "white"])

    async def test_status_light_tracking_can_be_turned_off(self) -> None:
        srv.set_status_light_tracking(False)
        await srv.call_sdk_command("lock_door")
        await asyncio.sleep(0.2)
        self.assertEqual(_FakeStarClient.lights, [])

    async def test_wait_for_command_event_flags_a_spoke_restart(self) -> None:
        update = await srv.wait_for_command_event(since_seq=srv._run_control.last_event_seq + 100, wait_s=0)
        self.assertTrue(update["restarted"])

    async def test_subscription_validation(self) -> None:
        with self.assertRaises(ValueError):
            srv.subscribe_command_events("ftp://x")
        with self.assertRaises(ValueError):
            srv.subscribe_command_events("http://x", kinds=["nope"])
        srv.subscribe_command_events("http://x")
        self.assertEqual(srv.list_command_event_subscriptions(), [{"url": "http://x", "kinds": "all"}])
        srv.unsubscribe_command_events("http://x")
        self.assertEqual(srv.list_command_event_subscriptions(), [])

    async def test_session_restart_resets_the_journal(self) -> None:
        await srv.call_sdk_command("instrument_is_idle")
        await srv.start_session(simulate=True, blank_deck=True)
        self.assertEqual(srv.get_command_journal(), [])
        self.assertFalse(srv.get_command_hold()["hold_on_error"])


class ErrorProfileToolTests(unittest.TestCase):
    def test_named_and_json_profiles_reach_the_resolver(self) -> None:
        class _Resolver:
            active = None

            def set_active_profile(self, profile: Any) -> None:
                self.active = profile

        resolver = _Resolver()
        fake = type("C", (), {"_connected_instrument": type("I", (), {"error_resolver": resolver})()})()
        with patch.object(srv, "_active_star", lambda: fake):
            self.assertEqual(srv.set_error_profile("cancel_all")["error_profile"], "cancel_all")
            self.assertEqual(resolver.active.default.actions, (srv.RecoveryAction.CANCEL,))
            self.assertEqual(srv.set_error_profile("Standard")["error_profile"], resolver.active.name)
            with self.assertRaises(ValueError):
                srv.set_error_profile("nope")


if __name__ == "__main__":
    unittest.main()


class InstrumentTypeGuardTests(unittest.TestCase):
    """The spoke builds the client for the instrument its VENUS is installed for, and refuses the
    other one -- whatever the calling computer has installed, and with no way for the caller to
    override it."""

    def _installed(self, kind: Any):
        return patch.object(srv, "_installed_instrument", lambda: kind)

    def test_omitted_type_follows_the_install(self) -> None:
        for installed in (srv.InstrumentType.STAR, srv.InstrumentType.Vantage):
            with self._installed(installed):
                self.assertEqual(srv._resolve_instrument_type(None), installed)

    def test_unknown_install_defaults_to_star_and_refuses_nothing(self) -> None:
        with self._installed(None):
            self.assertEqual(srv._resolve_instrument_type(None), srv.InstrumentType.STAR)
            self.assertEqual(srv._resolve_instrument_type("vantage"), srv.InstrumentType.Vantage)

    def test_a_vantage_spoke_refuses_star_with_the_fix(self) -> None:
        with self._installed(srv.InstrumentType.Vantage):
            with self.assertRaises(ValueError) as caught:
                srv._resolve_instrument_type("STAR")
            self.assertIn("installed for Vantage", str(caught.exception))
            self.assertIn("does not accept STAR connections", str(caught.exception))
            self.assertIn("start_session(instrument_type='Vantage')", str(caught.exception))
            self.assertEqual(srv._resolve_instrument_type("vantage"), srv.InstrumentType.Vantage)

    def test_a_star_spoke_refuses_vantage_too(self) -> None:
        with self._installed(srv.InstrumentType.STAR), self.assertRaisesRegex(ValueError, "does not accept Vantage"):
            srv._resolve_instrument_type("Vantage")

    def test_a_caller_cannot_override_it_but_the_spoke_owner_can(self) -> None:
        with self._installed(srv.InstrumentType.STAR):
            self.assertNotIn("allow_instrument_mismatch", srv.start_session.__code__.co_varnames[: srv.start_session.__code__.co_argcount])
            with patch.dict("os.environ", {instrument_guard.ALLOW_MISMATCH_ENV: "1"}):
                self.assertEqual(srv._resolve_instrument_type("Vantage"), srv.InstrumentType.Vantage)

    def test_a_bad_value_is_still_reported_as_unsupported(self) -> None:
        with self._installed(srv.InstrumentType.STAR), self.assertRaisesRegex(ValueError, "Unsupported instrument_type"):
            srv._resolve_instrument_type("Nimbus")

    def test_status_and_instructions_say_what_is_installed(self) -> None:
        with self._installed(srv.InstrumentType.Vantage):
            self.assertEqual(srv.get_session_status()["installed_instrument_type"], "Vantage")
        self.assertLess(len(srv._INSTRUCTIONS), 4096)


class WrongFamilyScriptTests(unittest.TestCase):
    """run_script is the other network path to a client: a script for the other family is refused."""

    SCRIPT = b"""from hamilton_venus import StarClient, VantageClient
with {cls}(simulate=True) as c:
    pass
"""

    def _validate(self, cls: str, installed: Any):
        with patch.object(instrument_guard, "installed_instrument", lambda: installed):
            return validate_bytes(self.SCRIPT.replace(b"{cls}", cls.encode()), "t.py")

    def test_the_other_family_is_an_error(self) -> None:
        report = self._validate("StarClient", srv.InstrumentType.Vantage)
        self.assertIn("V028", [i.rule for i in report.errors])
        self.assertIn("does not accept STAR connections", " ".join(i.message for i in report.errors))
        report = self._validate("VantageClient", srv.InstrumentType.STAR)
        self.assertIn("V028", [i.rule for i in report.errors])

    def test_the_installed_family_and_an_unknown_install_pass(self) -> None:
        for cls, installed in (("StarClient", srv.InstrumentType.STAR), ("VantageClient", srv.InstrumentType.Vantage),
                               ("StarClient", None), ("VantageClient", None)):
            self.assertNotIn("V028", [i.rule for i in self._validate(cls, installed).errors], (cls, installed))

    def test_the_owner_override_lifts_it(self) -> None:
        with patch.dict("os.environ", {instrument_guard.ALLOW_MISMATCH_ENV: "1"}):
            self.assertNotIn("V028", [i.rule for i in self._validate("StarClient", srv.InstrumentType.Vantage).errors])

    def test_the_script_runner_refuses_it_even_if_validation_was_skipped(self) -> None:
        with patch.object(instrument_guard, "installed_instrument", lambda: srv.InstrumentType.Vantage):
            self.assertIn("Use VantageClient", instrument_guard.wrong_client_message("StarClient") or "")
            self.assertIsNone(instrument_guard.wrong_client_message("VantageClient"))
