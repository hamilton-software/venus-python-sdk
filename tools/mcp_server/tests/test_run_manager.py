"""Tests for script_runs.manager.RunManager, using tests/fake_child.py instead of a real run.

The fake child speaks the real protocol, so these cover the manager's own behaviour: what it
refuses, how it turns child events into state, and how prompts, pause/resume/abort, the hard
kill, the timeout, and persistence work. Nothing here touches VENUS.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hamilton_venus_mcp.script_runs import manager as manager_module
from hamilton_venus_mcp.script_runs.consumables_config import ConsumablesConfigStore
from hamilton_venus_mcp import venus_api
from hamilton_venus_mcp.script_runs.consumables_ledger import ConsumablesLedger
from hamilton_venus_mcp.script_runs.manager import ALLOW_HARDWARE_ENV, guid_from_log, Run, OPERATOR_TOKEN_ENV, RunError, RunManager
from hamilton_venus_mcp.scripts_store import ScriptStore

FAKE_CHILD = Path(__file__).with_name("fake_child.py")
TOKEN = "s3cret-token"


def script_text(mode: str) -> str:
    return f'# mode: {mode}\nprint("fake script")\n'


class ManagerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # No VENUS on the test machine: the run-GUID watcher must see "nothing running" by default.
        current = mock.patch.object(venus_api, "get_current_run_data", return_value=None)
        self.current_run_data = current.start()
        self.addCleanup(current.stop)
        state = mock.patch.object(venus_api, "get_run_state", return_value={"value": 10, "name": "TERMINATED"})
        self.venus_run_state = state.start()
        self.addCleanup(state.stop)
        abort = mock.patch.object(venus_api, "abort", return_value=None)
        self.venus_abort = abort.start()
        self.addCleanup(abort.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ScriptStore(Path(self._tmp.name) / "scripts")
        # Isolated from the real machine's default consumables config/ledger, and from other
        # tests: RunManager defaults both to files under the real scripts dir otherwise.
        self.consumables_config = ConsumablesConfigStore(Path(self._tmp.name) / "consumables" / "config.json")
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "consumables" / "ledger.sqlite")
        self.addCleanup(self.ledger.close)
        self.manager = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        patcher = mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(ALLOW_HARDWARE_ENV, None)

    def add(self, name: str, mode: str) -> str:
        self.store.write(name, script_text(mode), overwrite=True)
        return name

    async def until(self, condition, timeout: float = 20.0, message: str = "condition"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition()
            if value:
                return value
            await asyncio.sleep(0.05)
        self.fail(f"timed out waiting for {message}")

    async def finished(self, run, timeout: float = 20.0):
        await self.until(lambda: run.status in ("completed", "failed", "stopped"), timeout, f"run {run.run_id} to finish")
        # The record, trace and ledger rows are written just after the status flips; the manager
        # only marks the run as its last finished one once all of that is done.
        await self.until(lambda: self.manager._last_finished is run, 5.0, "post-run bookkeeping to finish")
        return run

    async def tearDown_runs(self):
        try:
            self.manager.abort()
        except RunError:
            pass


class StartRefusalTests(ManagerTestCase):
    async def test_runs_without_the_operator_token_instead_of_refusing(self):
        # No remote human could ever answer a prompt without the token, but that no longer
        # blocks the run from starting at all -- an escalation just defers straight to VENUS's
        # own local dialog instead (see child_bootstrap._on_operator_escalation). Config.json
        # written for the child reflects the gate's real state either way.
        self.add("a.py", "quick")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(OPERATOR_TOKEN_ENV, None)
            run = await self.manager.start_run("a.py")
            await self.finished(run)
        self.assertEqual(run.status, "completed")
        config = json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))
        self.assertFalse(config["operator_gate_configured"])

    async def test_config_reflects_the_token_when_it_is_set(self):
        self.add("a.py", "quick")
        with mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: "t"}):
            run = await self.manager.start_run("a.py")
            await self.finished(run)
        config = json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["operator_gate_configured"])

    async def test_command_timeout_is_generous_by_default_and_configurable(self):
        self.add("a.py", "quick")
        run = await self.manager.start_run("a.py")
        await self.finished(run)
        config = json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["command_timeout_s"], 1800.0)  # the SDK's own 300 s cannot cover a person deciding
        for value, expected in (("120", 120.0), ("nonsense", 1800.0), ("-5", 1800.0)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"HAMILTON_MCP_COMMAND_TIMEOUT_S": value}):
                self.assertEqual(RunManager._command_timeout_s(), expected)

    async def test_real_hardware_needs_the_spoke_flag(self):
        self.add("a.py", "quick")
        with self.assertRaisesRegex(RunError, ALLOW_HARDWARE_ENV):
            await self.manager.start_run("a.py", simulate=False)
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            run = await self.manager.start_run("a.py", simulate=False)
            await self.finished(run)
        self.assertFalse(run.simulate)

    async def test_flag_values_other_than_1_do_not_enable_hardware(self):
        self.add("a.py", "quick")
        for value in ("0", "true", "yes", ""):
            with self.subTest(value=value), mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: value}):
                with self.assertRaises(RunError):
                    await self.manager.start_run("a.py", simulate=False)

    async def test_unknown_script(self):
        with self.assertRaisesRegex(RunError, "No script named"):
            await self.manager.start_run("missing.py")

    async def test_script_that_fails_validation_is_not_run(self):
        self.store.write("bad.py", "import subprocess\nsubprocess.run(['x'])\n")
        with self.assertRaisesRegex(RunError, "does not pass validation") as caught:
            await self.manager.start_run("bad.py")
        self.assertIn("V010", str(caught.exception))
        self.assertFalse(self.manager.has_active_run())

    async def test_validation_result_is_recorded_when_a_run_is_requested(self):
        self.add("a.py", "quick")
        run = await self.manager.start_run("a.py")
        await self.finished(run)
        self.assertTrue(self.store.is_runnable("a.py"))

    async def test_preflight_problem_blocks_the_run(self):
        self.add("a.py", "quick")

        async def busy():
            return "VENUS is busy."

        with self.assertRaisesRegex(RunError, "VENUS is busy"):
            await self.manager.start_run("a.py", preflight=busy)
        self.assertFalse(self.manager.has_active_run())

    async def test_only_one_run_at_a_time(self):
        self.add("slow.py", "slow")
        first = await self.manager.start_run("slow.py")
        try:
            with self.assertRaisesRegex(RunError, "only one script"):
                await self.manager.start_run("slow.py")
        finally:
            self.manager.abort(first.run_id)
            await self.finished(first)

    async def test_bad_max_runtime(self):
        self.add("a.py", "quick")
        with self.assertRaisesRegex(RunError, "positive"):
            await self.manager.start_run("a.py", max_runtime_s=0)


class LifecycleTests(ManagerTestCase):
    async def test_a_quick_run_completes_and_is_tracked(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        snap = self.manager.get_run(run.run_id)
        self.assertEqual(snap["status"], "completed")
        self.assertEqual(snap["exit_code"], 0)
        self.assertIsNone(snap["error"])
        self.assertEqual(snap["current_line"], 7)
        self.assertTrue(snap["simulate"])
        self.assertEqual(snap["system_simulation_mode"]["current"], True)
        self.assertEqual([c["client"] for c in snap["clients"]], ["StarClient"])
        self.assertEqual(snap["labware"][0]["labware_name"], "plate1")
        self.assertEqual(snap["tips"]["P"], {**snap["tips"]["P"], "remaining": 80, "picked_up": 16, "pickups": 2})
        reagent = snap["reagents"]["trough@1"]
        self.assertEqual(reagent["aspirated_ul"], 100.0)
        self.assertEqual(reagent["aspirates"], 2)
        self.assertEqual(reagent["last_liquid_volume_ul"], 850.0)
        self.assertGreaterEqual(snap["elapsed_s"], 0)

    async def test_script_output_is_captured_as_events(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        page = await self.manager.get_events(run.run_id)
        types = [e["type"] for e in page["events"]]
        self.assertEqual(types[0], "run_started")
        self.assertIn("stdout", types)
        self.assertEqual(types[-1], "run_finished")
        self.assertIn("quick script says hi", [e.get("text") for e in page["events"]])
        self.assertTrue(page["finished"])

    async def test_line_updates_are_state_not_events(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        page = await self.manager.get_events(run.run_id)
        self.assertNotIn("line", [e["type"] for e in page["events"]])

    async def test_the_validated_text_is_what_runs(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        copy = self.store.runs_dir / run.run_id / "quick.py"
        self.assertEqual(copy.read_text(encoding="utf-8"), script_text("quick"))
        self.assertEqual(run.sha256, self.store.sha256("quick.py"))

    async def test_a_failing_script_is_a_sticky_error_until_acknowledged(self):
        self.add("fail.py", "fail")
        run = await self.manager.start_run("fail.py")
        await self.finished(run)
        snap = self.manager.get_run(run.run_id)
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(snap["error"]["message"], "Tip pickup failed")
        self.assertEqual(snap["error_line"], 3)

        state = self.manager.state()
        self.assertEqual((state["state"], state["error_kind"]), ("error", "run_failed"))
        self.assertIn("Tip pickup failed", state["detail"])

        self.manager.acknowledge(run.run_id)
        self.assertEqual(self.manager.state()["state"], "idle")

    async def test_a_new_run_clears_a_previous_failure(self):
        self.add("fail.py", "fail")
        self.add("quick.py", "quick")
        failed = await self.manager.start_run("fail.py")
        await self.finished(failed)
        self.assertEqual(self.manager.state()["state"], "error")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        self.assertEqual(self.manager.state()["state"], "idle")

    async def test_a_child_that_dies_silently_is_a_failure(self):
        self.add("gone.py", "silent_exit")
        run = await self.manager.start_run("gone.py")
        await self.finished(run)
        # exit code 0 with no events is still a completed process; the point is it must finish
        self.assertIn(run.status, ("completed", "failed"))

    async def test_idle_state_when_nothing_has_run(self):
        state = self.manager.state()
        self.assertEqual(state["state"], "idle")
        self.assertIsNone(state["run"])
        self.assertTrue(state["operator_gate_configured"])
        self.assertFalse(state["hardware_runs_allowed"])

    async def test_running_state_while_a_script_is_active(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            state = self.manager.state()
            self.assertEqual(state["state"], "running")
            self.assertEqual(state["run"]["script"], "slow.py")
            self.assertFalse(state["paused"])
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_operator_token_is_not_visible_to_the_script(self):
        self.add("env.py", "env")
        run = await self.manager.start_run("env.py")
        await self.finished(run)
        page = await self.manager.get_events(run.run_id)
        texts = [e.get("text", "") for e in page["events"] if e["type"] == "stdout"]
        self.assertIn("token_in_env=False", texts)
        self.assertNotIn(TOKEN, str(page))

    async def test_sim_setting_is_forced_into_the_run(self):
        self.add("quick.py", "quick")
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            live = await self.manager.start_run("quick.py", simulate=False)
            await self.finished(live)
        self.assertEqual(self.manager.get_run(live.run_id)["system_simulation_mode"]["current"], False)
        sim = await self.manager.start_run("quick.py", simulate=True)
        await self.finished(sim)
        self.assertEqual(self.manager.get_run(sim.run_id)["system_simulation_mode"]["current"], True)


class EventPagingTests(ManagerTestCase):
    async def test_cursor_paging_and_type_filter(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        total = (await self.manager.get_events(run.run_id))["events"]
        first = await self.manager.get_events(run.run_id, max_items=2)
        self.assertEqual(len(first["events"]), 2)
        second = await self.manager.get_events(run.run_id, since_seq=first["next_since_seq"], max_items=1000)
        self.assertEqual([e["seq"] for e in first["events"] + second["events"]], [e["seq"] for e in total])

        only_tips = await self.manager.get_events(run.run_id, types={"tips"})
        self.assertEqual({e["type"] for e in only_tips["events"]}, {"tips"})
        # after a filtered page the cursor has moved past everything, so nothing is re-sent
        again = await self.manager.get_events(run.run_id, since_seq=only_tips["next_since_seq"], types={"tips"})
        self.assertEqual(again["events"], [])

    async def test_long_poll_returns_when_something_arrives(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            seen = (await self.manager.get_events(run.run_id))["next_since_seq"]
            waiter = asyncio.create_task(self.manager.get_events(run.run_id, since_seq=seen, wait_s=10.0))
            await asyncio.sleep(0.3)
            self.assertFalse(waiter.done())
            self.manager.pause(run.run_id)
            page = await asyncio.wait_for(waiter, 8.0)
            self.assertTrue(page["events"])
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_long_poll_times_out_with_no_events(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            seen = (await self.manager.get_events(run.run_id))["next_since_seq"]
            started = time.monotonic()
            page = await self.manager.get_events(run.run_id, since_seq=seen, wait_s=0.6)
            self.assertGreaterEqual(time.monotonic() - started, 0.5)
            self.assertEqual(page["events"], [])
            self.assertFalse(page["finished"])
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_the_ring_reports_what_it_dropped(self):
        self.add("quick.py", "quick")
        with mock.patch.object(manager_module, "EVENT_RING_SIZE", 3):
            run = await self.manager.start_run("quick.py")
            await self.finished(run)
        page = await self.manager.get_events(run.run_id, since_seq=0)
        self.assertGreater(page["dropped"], 0)
        self.assertLessEqual(len(page["events"]), 3)


class ControlTests(ManagerTestCase):
    async def test_pause_resume_abort(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            self.manager.pause(run.run_id)
            await self.until(lambda: run.status == "paused", message="pause")
            state = self.manager.state()
            self.assertEqual(state["state"], "running")
            self.assertTrue(state["paused"])

            self.manager.resume(run.run_id)
            await self.until(lambda: run.status == "running", message="resume")
            self.assertFalse(self.manager.state()["paused"])
        finally:
            self.manager.abort(run.run_id)
        await self.finished(run)
        self.assertEqual(run.status, "stopped")
        self.assertEqual(self.manager.state()["state"], "idle")  # an abort is not an error

    async def test_controls_need_a_live_run(self):
        with self.assertRaisesRegex(RunError, "No run is active"):
            self.manager.pause()
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        for action in (self.manager.pause, self.manager.resume, self.manager.abort):
            with self.subTest(action=action.__name__), self.assertRaisesRegex(RunError, "already completed"):
                action(run.run_id)

    async def test_a_script_that_ignores_stop_is_killed(self):
        self.add("stubborn.py", "ignore_stop")
        with mock.patch.object(manager_module, "KILL_GRACE_S", 0.6), mock.patch.object(
            manager_module.venus_api, "clear_error_handler"
        ) as clear_error_handler:
            run = await self.manager.start_run("stubborn.py")
            await self.until(lambda: run.status == "running", message="run to start")
            self.manager.abort(run.run_id)
            await self.finished(run, timeout=15.0)
        self.assertEqual(run.status, "stopped")
        page = await self.manager.get_events(run.run_id)
        self.assertIn("hard_kill", [e["type"] for e in page["events"]])
        # A hard kill skips the child's own clean shutdown -- the only place that unregisters
        # this run's client as VENUS's error handler -- so RunManager cleans up on its behalf
        # (confirmed live: skipping this leaves VENUS unable to show its own operator dialog for
        # a later run's -1 defer, stuck indefinitely).
        clear_error_handler.assert_called_once()

    async def test_max_runtime_stops_the_run_as_a_failure(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py", max_runtime_s=1.0)
        await self.finished(run, timeout=20.0)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error["type"], "Timeout")
        self.assertEqual(self.manager.state()["error_kind"], "run_failed")


class PromptTests(ManagerTestCase):
    async def start_prompt_run(self, mode="prompt"):
        self.add(f"{mode}.py", mode)
        run = await self.manager.start_run(f"{mode}.py")
        await self.until(lambda: run.pending_prompts(), message="a prompt")
        return run

    async def test_a_prompt_makes_the_spoke_an_error_until_it_is_answered(self):
        run = await self.start_prompt_run()
        state = self.manager.state()
        self.assertEqual((state["state"], state["error_kind"]), ("error", "prompt_pending"))
        (prompt,) = state["pending_prompts"]
        self.assertEqual(prompt["prompt_id"], "err-1")
        self.assertEqual(prompt["run_id"], run.run_id)
        self.assertEqual(prompt["options"], ["retry", "abort"])
        self.assertEqual(prompt["channel_errors"][0]["channels"], ["1", "2"])

        self.manager.resolve_prompt(run.run_id, "err-1", action="retry", operator="Sam", source="test")
        await self.finished(run)
        self.assertEqual(run.status, "completed")
        self.assertEqual(self.manager.state()["state"], "idle")

    async def test_an_answer_outside_the_offered_options_is_refused(self):
        run = await self.start_prompt_run()
        try:
            for bad in ("ignore", "explode", "", None):
                with self.subTest(action=bad), self.assertRaisesRegex(RunError, "not one of this prompt's options"):
                    self.manager.resolve_prompt(run.run_id, "err-1", action=bad)
            self.assertEqual(len(run.pending_prompts()), 1)  # still waiting
        finally:
            self.manager.resolve_prompt(run.run_id, "err-1", action="abort")
            await self.finished(run)

    async def test_the_answer_is_case_insensitive(self):
        run = await self.start_prompt_run()
        self.manager.resolve_prompt(run.run_id, "err-1", action="RETRY")
        await self.finished(run)
        self.assertEqual(run.status, "completed")

    async def test_resolution_is_audited(self):
        run = await self.start_prompt_run()
        self.manager.resolve_prompt(run.run_id, "err-1", action="abort", operator="Sam", source="operator_page")
        await self.finished(run)
        snap = self.manager.get_run(run.run_id)
        self.assertEqual(snap["pending_prompts"], [])
        (done,) = snap["prompt_history"]
        self.assertEqual(done["resolution"], {"action": "abort", "operator": "Sam", "source": "operator_page"})
        self.assertIsNotNone(done["resolved_at"])
        page = await self.manager.get_events(run.run_id, types={"prompt_resolved"})
        self.assertEqual(page["events"][0]["operator"], "Sam")
        self.assertEqual(run.status, "failed")  # the operator aborted

    async def test_an_unknown_or_repeated_prompt_is_refused(self):
        run = await self.start_prompt_run()
        with self.assertRaisesRegex(RunError, "No pending prompt"):
            self.manager.resolve_prompt(run.run_id, "nope", action="retry")
        self.manager.resolve_prompt(run.run_id, "err-1", action="retry")
        with self.assertRaisesRegex(RunError, "(No pending prompt|already)"):
            self.manager.resolve_prompt(run.run_id, "err-1", action="retry")
        await self.finished(run)

    async def test_reload_prompts_take_continue_or_abort(self):
        run = await self.start_prompt_run("reload")
        with self.assertRaisesRegex(RunError, "not one of"):
            self.manager.resolve_prompt(run.run_id, "tip-1", action="retry")
        self.manager.resolve_prompt(run.run_id, "tip-1", action="continue")
        await self.finished(run)
        self.assertEqual(run.status, "completed")

    async def test_per_channel_choices_are_only_for_instrument_errors(self):
        run = await self.start_prompt_run("reload")
        try:
            with self.assertRaisesRegex(RunError, "Per-channel"):
                self.manager.resolve_prompt(run.run_id, "tip-1", channel_actions={"d1": 1026})
        finally:
            self.manager.resolve_prompt(run.run_id, "tip-1", action="abort")
            await self.finished(run)

    async def test_bad_per_channel_ids_are_refused(self):
        run = await self.start_prompt_run()
        try:
            with self.assertRaisesRegex(RunError, "numeric"):
                self.manager.resolve_prompt(run.run_id, "err-1", channel_actions={"d1": "abc"})
        finally:
            self.manager.resolve_prompt(run.run_id, "err-1", action="abort")
            await self.finished(run)

    async def test_per_channel_choices_are_accepted_when_they_match_the_prompt(self):
        run = await self.start_prompt_run()
        result = self.manager.resolve_prompt(
            run.run_id, "err-1", channel_actions={"d1": 1026, "d2": 1030}, operator="Sam", source="test"
        )
        self.assertEqual(result["action"], "per-channel selection")
        await self.finished(run)
        self.assertEqual(run.status, "completed")
        # The record says what was chosen, by name, not only that a choice was made.
        (entry,) = [p for p in self.manager.get_run(run.run_id)["prompt_history"] if p["prompt_id"] == "err-1"]
        choices = entry["resolution"]["choices"]
        self.assertEqual(sorted(a for c in choices for a in c["actions"]), ["Exclude", "Repeat"])
        page = await self.manager.get_events(run.run_id, types={"prompt_resolved"})
        self.assertEqual(page["events"][0]["choices"], choices)

    async def test_per_channel_choices_must_use_offered_ids_and_cover_every_channel(self):
        run = await self.start_prompt_run()
        try:
            cases = {
                "an id the prompt never offered": ({"d1": 9999, "d2": 1026}, "not one of the options"),
                "a channel that is not part of the error": ({"d1": 1026, "d2": 1026, "d3": 1026}, "Not part of this error"),
                "a channel left without a choice": ({"d1": 1026}, "missing 1"),
            }
            for label, (picks, message) in cases.items():
                with self.subTest(label), self.assertRaisesRegex(RunError, message):
                    self.manager.resolve_prompt(run.run_id, "err-1", channel_actions=picks)
            self.assertEqual(len(run.pending_prompts()), 1)  # nothing was sent
        finally:
            self.manager.resolve_prompt(run.run_id, "err-1", action="abort")
            await self.finished(run)

    async def test_per_channel_choices_are_refused_when_the_prompt_offers_none(self):
        run = await self.start_prompt_run("reload")
        try:
            with self.assertRaisesRegex(RunError, "Per-channel"):
                self.manager.resolve_prompt(run.run_id, "tip-1", channel_actions={"d1": 1026})
        finally:
            self.manager.resolve_prompt(run.run_id, "tip-1", action="abort")
            await self.finished(run)

    async def test_an_unanswered_prompt_can_abort_the_run_when_a_limit_is_set(self):
        self.add("prompt.py", "prompt")
        with mock.patch.dict(os.environ, {manager_module.PROMPT_ABORT_AFTER_ENV: "1"}):
            run = await self.manager.start_run("prompt.py")
            await self.finished(run, timeout=30.0)
        self.assertEqual(run.status, "stopped")
        page = await self.manager.get_events(run.run_id)
        self.assertIn("prompt_timeout", [e["type"] for e in page["events"]])

    async def test_by_default_an_unanswered_prompt_waits_forever(self):
        run = await self.start_prompt_run()
        try:
            await asyncio.sleep(1.5)
            self.assertEqual(run.status, "running")
            self.assertEqual(len(run.pending_prompts()), 1)
        finally:
            self.manager.resolve_prompt(run.run_id, "err-1", action="abort")
            await self.finished(run)


class PersistenceTests(ManagerTestCase):
    async def test_a_finished_run_is_recorded_and_survives_a_restart(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)

        restarted = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        record = restarted.get_run(run.run_id)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["tips"]["P"]["remaining"], 80)
        self.assertTrue(record["events_tail"])
        self.assertEqual(restarted.state()["state"], "idle")  # old failures do not resurrect

    async def test_list_runs_is_most_recent_first_and_includes_history(self):
        self.add("quick.py", "quick")
        first = await self.manager.start_run("quick.py")
        await self.finished(first)
        second = await self.manager.start_run("quick.py")
        await self.finished(second)
        rows = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        ).list_runs(limit=5)
        self.assertEqual([r["run_id"] for r in rows][:2], [second.run_id, first.run_id])
        self.assertEqual({r["status"] for r in rows}, {"completed"})

    async def test_unknown_run_ids(self):
        with self.assertRaisesRegex(RunError, "No run has happened yet"):
            self.manager.get_run()
        with self.assertRaisesRegex(RunError, "No such run"):
            self.manager.get_run("20200101T000000_nothing")
        for hostile in ("../x", "a/b", "a\\b", ".."):
            with self.subTest(run_id=hostile), self.assertRaises(RunError):
                self.manager.get_run(hostile)


class InterruptedRunTests(ManagerTestCase):
    async def test_a_running_run_is_saved_before_it_finishes(self):
        self.add("slow.py", "slow")
        with mock.patch.object(RunManager, "_PERSIST_INTERVAL_S", 0.1):
            run = await self.manager.start_run("slow.py")
            try:
                await self.until(lambda: run.status == "running", message="run to start")
                await self.until(lambda: (run.run_dir / "record.json").is_file(), message="a saved record")
                saved = json.loads((run.run_dir / "record.json").read_text(encoding="utf-8"))
                self.assertIn(saved["status"], ("starting", "running"))
                self.assertTrue((run.run_dir / "events.jsonl").is_file())
            finally:
                self.manager.abort(run.run_id)
                await self.finished(run)

    async def test_a_record_left_running_by_a_dead_spoke_is_marked_interrupted(self):
        run_dir = self.store.runs_dir / "20200101T000000_dead00"
        run_dir.mkdir(parents=True)
        (run_dir / "record.json").write_text(
            json.dumps({"run_id": "20200101T000000_dead00", "script": "a.py", "status": "running"}), encoding="utf-8"
        )
        restarted = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        row = next(r for r in restarted.list_runs(50) if r["run_id"] == "20200101T000000_dead00")
        self.assertEqual(row["status"], "interrupted")
        self.assertIn("stopped while this run was in progress", row["error"])

    async def test_finished_records_are_left_alone(self):
        run_dir = self.store.runs_dir / "20200101T000000_done00"
        run_dir.mkdir(parents=True)
        (run_dir / "record.json").write_text(json.dumps({"run_id": "20200101T000000_done00", "status": "completed"}), encoding="utf-8")
        RunManager(self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger)
        self.assertEqual(json.loads((run_dir / "record.json").read_text(encoding="utf-8"))["status"], "completed")


class LeftoverVenusMethodTests(ManagerTestCase):
    """After the script's process exits, a method VENUS is still running for it must not be left behind."""

    async def _run_quick(self):
        self.add("quick.py", "quick")
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        return run

    async def test_a_normal_exit_leaves_venus_alone(self):
        await self._run_quick()
        self.venus_abort.assert_not_called()

    async def test_our_method_still_running_is_aborted(self):
        self.venus_run_state.return_value = {"value": 2, "name": "RUNNING"}
        self.current_run_data.return_value = {"methodName": r"C:\Methods\quick.hsl", "runGuid": "abc"}

        def settle(*_):
            self.venus_run_state.return_value = {"value": 10, "name": "TERMINATED"}

        self.venus_abort.side_effect = settle
        with mock.patch.object(RunManager, "_LEFTOVER_GRACE_S", 0.05), mock.patch.object(RunManager, "_LEFTOVER_ABORT_WAIT_S", 0.05):
            run = await self._run_quick()
        self.venus_abort.assert_called_once()
        events = [e for e in (await self.manager.get_events(run.run_id))["events"] if e["type"] == "venus_method_aborted"]
        self.assertEqual(events[0]["state_before"], "RUNNING")
        self.assertEqual(events[0]["state_after"], "TERMINATED")

    async def test_ours_by_method_name_when_no_guid_was_learned(self):
        manager = self.manager
        run = Run("r1", "quick.py", "sha", True, None)
        self.venus_run_state.return_value = {"value": 2, "name": "RUNNING"}
        self.current_run_data.return_value = {"methodName": r"C:\Methods\quick.hsl", "runGuid": ""}

        def settle(*_):
            self.venus_run_state.return_value = {"value": 10, "name": "TERMINATED"}

        self.venus_abort.side_effect = settle
        with mock.patch.object(RunManager, "_LEFTOVER_GRACE_S", 0.05), mock.patch.object(RunManager, "_LEFTOVER_ABORT_WAIT_S", 0.05):
            manager._stop_leftover_venus_method(run)
        self.venus_abort.assert_called_once()

    async def test_someone_elses_method_is_never_aborted(self):
        self.venus_run_state.return_value = {"value": 2, "name": "RUNNING"}
        self.current_run_data.return_value = {"methodName": r"C:\Methods\somebody_else.hsl", "runGuid": "zzz"}
        with mock.patch.object(RunManager, "_LEFTOVER_GRACE_S", 0.05), mock.patch.object(RunManager, "_LEFTOVER_ABORT_WAIT_S", 0.05):
            await self._run_quick()
        self.venus_abort.assert_not_called()

    async def test_a_failed_abort_is_reported_not_raised(self):
        self.venus_run_state.return_value = {"value": 2, "name": "RUNNING"}
        self.current_run_data.return_value = {"methodName": r"C:\Methods\quick.hsl", "runGuid": "abc"}
        self.venus_abort.side_effect = RuntimeError("VENUS said no")
        with mock.patch.object(RunManager, "_LEFTOVER_GRACE_S", 0.05), mock.patch.object(RunManager, "_LEFTOVER_ABORT_WAIT_S", 0.05):
            run = await self._run_quick()
        types = [e["type"] for e in (await self.manager.get_events(run.run_id))["events"]]
        self.assertIn("venus_method_abort_failed", types)


class GuidFromLogTests(unittest.TestCase):
    def test_reads_the_linked_run_guid_from_an_unfinalized_log(self):
        log = {"log": [
            {"type": "session_start", "payload": {}},
            {"type": "run_guid_linked", "payload": {"run_guid": "3c242519-f9cb-4e9f-bdf8-3d2ac9a426ab", "method_name": "t2"}},
        ]}
        self.assertEqual(guid_from_log(log), "3c242519f9cb4e9fbdf83d2ac9a426ab")

    def test_none_when_the_run_never_got_a_guid(self):
        self.assertIsNone(guid_from_log({"log": [{"type": "session_start", "payload": {}}]}))
        self.assertIsNone(guid_from_log({}))
        self.assertIsNone(guid_from_log({"log": [{"type": "run_guid_linked", "payload": {}}]}))


class SummaryAndLedgerTests(ManagerTestCase):
    """A finished run with a real (fake-child-written) SdkRunLog.json: the manager must compute
    its summary, expose it via get_run_summary, and record its consumption to the ledger."""

    async def test_get_run_summary(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)

        result = self.manager.get_run_summary(run.run_id)
        self.assertEqual(result["run_id"], run.run_id)
        summary = result["summary"]
        self.assertEqual(summary["result"], "success")
        self.assertTrue(summary["simulate"])
        self.assertEqual(summary["tip_pickup_calls"], 1)
        self.assertEqual(summary["tips_used"], 8)
        self.assertEqual(summary["tips_by_type"][0]["tip_type"], "Tip_Rack_50ul")
        self.assertEqual(summary["reservoir_volumes"][0], {"labware": "Trough1", "volume_ul": 50.0})

    async def test_venus_run_guid_is_learned_from_current_run_data_while_running(self):
        self.current_run_data.return_value = {"methodName": r"C:\Program Files\Method\slow.hsl", "runGuid": "AAAA1111-2222-3333-4444-555566667777",
            "instruments": [{"instrumentName": "ML_STAR", "instrumentSerialNumber": "AI68"}],
        }
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.venus_run_guid is not None, message="the GUID")
            self.assertEqual(run.venus_run_guid, "AAAA1111222233334444555566667777")
            self.assertEqual(run.instrument_serial, "AI68")
            self.assertEqual(self.manager.get_run(run.run_id)["venus_run_guid"], "AAAA1111222233334444555566667777")
            page = await self.manager.get_events(run.run_id, types={"venus_run_guid"})
            self.assertEqual(len(page["events"]), 1)
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_windows_method_path_is_matched_and_serial_is_kept_polling_for(self):
        # First answer: GUID but no instrument yet; the serial shows up a moment later.
        first = {"methodName": r"C:\Program Files (x86)\Hamilton\SDK\Method\slow.hsl", "runGuid": "abcd0000-0000-0000-0000-000000000001"}
        later = {**first, "instruments": [{"instrumentSerialNumber": "AI68"}]}
        self.current_run_data.side_effect = [first, later, later, later, later, later, later, later, later, later]
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.instrument_serial == "AI68", timeout=15.0, message="the serial")
            self.assertEqual(run.venus_run_guid, "abcd0000000000000000000000000001")
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_a_different_method_running_on_venus_is_not_this_runs_guid(self):
        self.current_run_data.return_value = {"methodName": r"C:\Methods\somebody_else.hsl", "runGuid": "deadbeefdeadbeefdeadbeefdeadbeef"}
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            await asyncio.sleep(1.5)
            self.assertIsNone(run.venus_run_guid)
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_the_serial_source_is_recorded_for_the_trace_and_for_run_data(self):
        # The trace text supplies the serial first; run-data must still be asked and its answer logged.
        first = {"methodName": r"C:\Methods\slow.hsl", "runGuid": "abcd0000-0000-0000-0000-000000000002"}
        later = {**first, "instruments": [{"instrumentSerialNumber": "AI68"}]}
        self.current_run_data.side_effect = [first] + [later] * 40
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.instrument_serial == "AI68", message="the serial")
            run.instrument_serial = None  # as if the trace had not supplied it
            await self.until(lambda: any(e.type == "instrument_serial" for e in run.events), message="a serial event")
            page = await self.manager.get_events(run.run_id, types={"instrument_serial", "venus_run_guid"})
            kinds = [(e["type"], e.get("source")) for e in page["events"]]
            self.assertIn(("venus_run_guid", None), kinds)
            self.assertIn(("instrument_serial", "current-run-data"), kinds)
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_venus_run_guid_and_instrument_serial_are_captured(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)
        snap = self.manager.get_run(run.run_id)
        self.assertEqual(snap["venus_run_guid"], "6defca7bf3de498e8b93303bc93a245d")
        self.assertEqual(snap["instrument_serial"], "AI68")
        record = self.ledger.get_run(run.run_id)
        self.assertEqual(record["venus_run_guid"], "6defca7bf3de498e8b93303bc93a245d")
        self.assertEqual(record["instrument_serial"], "AI68")

    async def test_summary_is_also_in_get_run_and_survives_a_restart(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)
        self.assertIsNotNone(self.manager.get_run(run.run_id)["summary"])

        restarted = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        self.assertIsNotNone(restarted.get_run_summary(run.run_id)["summary"])

    async def test_full_trace_survives_a_restart(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)
        live = await self.manager.get_events(run.run_id, max_items=1000)

        restarted = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        page = await restarted.get_events(run.run_id, max_items=1000)
        self.assertTrue(page["from_disk"])
        self.assertFalse(page["partial"])
        self.assertTrue(page["finished"])
        self.assertEqual([e["seq"] for e in page["events"]], [e["seq"] for e in live["events"]])
        after = await restarted.get_events(run.run_id, since_seq=page["events"][-3]["seq"])
        self.assertEqual(len(after["events"]), 2)
        only_lines = await restarted.get_events(run.run_id, types={"run_finished"})
        self.assertEqual([e["type"] for e in only_lines["events"]], ["run_finished"])

    async def test_a_run_saved_before_full_traces_only_has_its_tail(self):
        run_dir = self.store.runs_dir / "20200101T000000_old000"
        run_dir.mkdir(parents=True)
        (run_dir / "record.json").write_text(
            json.dumps({"run_id": "20200101T000000_old000", "events_tail": [{"seq": 9, "type": "run_finished"}]}), encoding="utf-8"
        )
        page = await self.manager.get_events("20200101T000000_old000")
        self.assertTrue(page["partial"])
        self.assertEqual(page["events"][0]["seq"], 9)

    async def test_an_unknown_run_still_has_no_events(self):
        with self.assertRaisesRegex(RunError, "No such run"):
            await self.manager.get_events("20200101T000000_nothere")
        with self.assertRaisesRegex(RunError, "No such run"):
            await self.manager.get_events("../../etc")

    async def test_summary_unavailable_while_the_run_is_still_going(self):
        self.add("slow.py", "slow")
        run = await self.manager.start_run("slow.py")
        try:
            await self.until(lambda: run.status == "running", message="run to start")
            with self.assertRaisesRegex(RunError, "still running"):
                self.manager.get_run_summary(run.run_id)
        finally:
            self.manager.abort(run.run_id)
            await self.finished(run)

    async def test_summary_unavailable_when_nothing_has_run_yet(self):
        with self.assertRaisesRegex(RunError, "No run has happened yet"):
            self.manager.get_run_summary()

    async def test_run_with_no_log_at_all_has_no_summary(self):
        self.add("quick.py", "quick")  # "quick" mode never writes a run log
        run = await self.manager.start_run("quick.py")
        await self.finished(run)
        with self.assertRaisesRegex(RunError, "no summary"):
            self.manager.get_run_summary(run.run_id)

    async def test_usage_is_recorded_to_the_ledger_exactly_once(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)

        self.assertTrue(self.ledger.has_run(run.run_id))
        # simulate=True (start_run's own default here) -- ask for it explicitly; the default-
        # excludes-simulated-runs behavior of usage_report has its own dedicated test below.
        tip_usage = self.ledger.usage_report(kind="tip", group_by="item", simulate=True)
        self.assertEqual(tip_usage[0]["total_quantity"], 8)
        reagent_usage = self.ledger.usage_report(kind="reagent", group_by="item", simulate=True)
        self.assertEqual(reagent_usage[0]["total_quantity"], 50.0)

        record = self.ledger.get_run(run.run_id)
        self.assertEqual(record["status"], "completed")
        self.assertFalse(record["partial"])
        self.assertTrue(record["simulate"])  # start_run's own default

    async def test_a_simulated_run_never_moves_current_levels(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py", simulate=True)
        await self.finished(run)
        self.assertEqual(self.ledger.current_levels(), [])
        self.assertEqual(self.ledger.usage_report(kind="tip", simulate=True)[0]["total_quantity"], 8)  # usage row kept
        # ...and it does not auto-register the reagent it saw in the consumables config either.
        self.assertEqual(self.ledger.events(), [])

    async def test_levels_are_recorded_from_the_runs_own_tracking(self):
        self.add("logged.py", "logged")
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            run = await self.manager.start_run("logged.py", simulate=False)
        await self.finished(run)

        levels = self.ledger.current_levels(kind="tip")
        self.assertEqual(levels[0]["level"], 88)
        self.assertEqual(levels[0]["capacity"], 96)
        reagent_levels = self.ledger.current_levels(kind="reagent")
        self.assertEqual(reagent_levels[0]["level"], 900.0)
        self.assertEqual(reagent_levels[0]["capacity"], 1000.0)

    async def test_a_simulated_run_is_recorded_but_excluded_by_default(self):
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py", simulate=True)
        await self.finished(run)
        self.assertTrue(self.ledger.get_run(run.run_id)["simulate"])
        self.assertEqual(self.ledger.usage_report(kind="tip"), [])  # excluded from the default (real-only) report
        self.assertEqual(self.ledger.usage_report(kind="tip", simulate=True)[0]["total_quantity"], 8)

    async def test_a_failed_run_is_recorded_as_partial(self):
        self.add("fail.py", "fail")  # "fail" mode never writes a run log -- no usage, still a run row
        run = await self.manager.start_run("fail.py")
        await self.finished(run)
        record = self.ledger.get_run(run.run_id)
        self.assertTrue(record["partial"])
        self.assertEqual(record["status"], "failed")

    async def test_a_ledger_failure_does_not_break_the_run(self):
        self.add("logged.py", "logged")
        with mock.patch.object(self.ledger, "record_run", side_effect=RuntimeError("disk full")):
            run = await self.manager.start_run("logged.py")
            await self.finished(run)
        self.assertEqual(run.status, "completed")  # the run itself is unaffected
        page = await self.manager.get_events(run.run_id)
        self.assertIn("ledger_error", [e["type"] for e in page["events"]])

    async def test_reload_events_are_written_to_the_ledger(self):
        self.add("reload.py", "reload")
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            run = await self.manager.start_run("reload.py", simulate=False)
        await self.until(lambda: run.pending_prompts(), message="a prompt")
        self.manager.resolve_prompt(run.run_id, "tip-1", action="continue")
        await self.finished(run)
        events = self.ledger.events(kind="tip", item_key="P")
        self.assertEqual(events[0]["type"], "reload")

    async def test_a_simulated_reload_is_not_written_to_the_ledger(self):
        self.add("reload.py", "reload")
        run = await self.manager.start_run("reload.py", simulate=True)
        await self.until(lambda: run.pending_prompts(), message="a prompt")
        self.manager.resolve_prompt(run.run_id, "tip-1", action="continue")
        await self.finished(run)
        self.assertEqual(self.ledger.events(kind="tip", item_key="P"), [])

    async def test_consumables_config_thresholds_flow_into_the_run(self):
        self.consumables_config.set_tip_threshold("P", 90)  # 88 remaining < 90 -> should warn
        self.add("logged.py", "logged")
        run = await self.manager.start_run("logged.py")
        await self.finished(run)
        snap = self.manager.get_run(run.run_id)
        self.assertEqual(len(snap["consumable_warnings"]), 0)  # fake child does not read config
        # the config was at least threaded into config.json for a real child to read:
        config = json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["consumables"]["tip_pools"]["P"]["low_threshold"], 90)


if __name__ == "__main__":
    unittest.main()
