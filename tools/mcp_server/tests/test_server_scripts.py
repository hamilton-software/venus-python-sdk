"""Tests for the script tools in server.py: import/validate, run/monitor/control, spoke state,
the human-only prompt path, and the VENUS Web API tools.

The run manager is pointed at tests/fake_child.py and a temporary scripts folder, and VENUS's
Web API is patched out, so nothing here needs an instrument or a running VENUS.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

import hamilton_venus_mcp.server as srv
from hamilton_venus.models import RunState
from hamilton_venus_mcp import venus_api
from hamilton_venus_mcp.script_runs.consumables_config import ConsumablesConfigStore
from hamilton_venus_mcp.script_runs.consumables_ledger import ConsumablesLedger
from hamilton_venus_mcp.script_runs.manager import ALLOW_HARDWARE_ENV, OPERATOR_TOKEN_ENV, RunError, RunManager
from hamilton_venus_mcp.script_runs.operator_gate import OperatorAuthError, OperatorGate
from hamilton_venus_mcp.scripts_store import ScriptStore, ScriptStoreError

FAKE_CHILD = Path(__file__).with_name("fake_child.py")
TOKEN = "s3cret-token"
GOOD = '# mode: quick\nprint("hi")\n'

SDK_SCRIPT = """\
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE

with StarClient(simulate=True) as star:
    star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="Tips")
    star.tip_pickup(tip_pool="P")
"""


class ServerScriptTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ScriptStore(Path(self._tmp.name) / "scripts")
        self.consumables_config = ConsumablesConfigStore(Path(self._tmp.name) / "consumables" / "config.json")
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "consumables" / "ledger.sqlite")
        self.addCleanup(self.ledger.close)
        self.manager = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        self.gate = OperatorGate(self.manager)
        env = mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: TOKEN})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(ALLOW_HARDWARE_ENV, None)
        for name, value in (("_store", self.store), ("_run_manager", self.manager), ("_operator_gate", self.gate)):
            patcher = mock.patch.object(srv, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (
            mock.patch.object(srv._session, "check_run_state", AsyncMock(return_value=None)),
            mock.patch.object(srv.venus_api, "get_run_state", return_value={"value": 0, "name": "NOT_INITIALIZED"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def until(self, condition, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition()
            if value:
                return value
            await asyncio.sleep(0.05)
        self.fail("timed out")

    async def finished(self, run_id):
        await self.until(lambda: srv.get_run(run_id)["status"] in ("completed", "failed", "stopped"))
        await self.until(lambda: not self.manager.has_active_run())


class ImportAndValidateTests(ServerScriptTestCase):
    def test_import_content_validates_and_stores(self):
        result = srv.import_script(name="sdk.py", content=SDK_SCRIPT)
        self.assertTrue(result["imported"])
        self.assertTrue(result["runnable"], result["validation"]["errors"])
        self.assertTrue(Path(result["path"]).is_file())
        (row,) = srv.list_scripts()["scripts"]
        self.assertEqual((row["name"], row["validation_ok"], row["validation_current"]), ("sdk.py", True, True))

    def test_a_script_with_errors_is_stored_but_not_runnable(self):
        bad = SDK_SCRIPT.replace("tip_pickup(tip_pool=\"P\")", "tip_pickup(channels=[])")
        result = srv.import_script(name="bad.py", content=bad)
        self.assertTrue(result["imported"])
        self.assertFalse(result["runnable"])
        self.assertEqual([e["rule"] for e in result["validation"]["errors"]], ["V026"])
        self.assertEqual(result["validation"]["errors"][0]["line"], 6)
        self.assertFalse(self.store.is_runnable("bad.py"))

    def test_existing_scripts_need_overwrite_and_fixing_makes_them_runnable(self):
        srv.import_script(name="s.py", content=SDK_SCRIPT.replace('tip_pool="P"', "channels=[]"))
        with self.assertRaisesRegex(ScriptStoreError, "already exists"):
            srv.import_script(name="s.py", content=SDK_SCRIPT)
        fixed = srv.import_script(name="s.py", content=SDK_SCRIPT, overwrite=True)
        self.assertTrue(fixed["runnable"])

    def test_exactly_one_of_content_and_source_path(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            srv.import_script(name="x.py")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            srv.import_script(name="x.py", content="x = 1\n", source_path="C:\\a.py")

    def test_content_needs_a_name(self):
        with self.assertRaisesRegex(ValueError, "name is required"):
            srv.import_script(content="x = 1\n")

    def test_import_from_a_file_on_the_spoke(self):
        source = Path(self._tmp.name) / "from_disk.py"
        source.write_bytes(SDK_SCRIPT.encode("utf-8"))
        result = srv.import_script(source_path=str(source))
        self.assertEqual(result["name"], "from_disk.py")
        self.assertTrue(result["runnable"])
        renamed = srv.import_script(name="renamed.py", source_path=str(source))
        self.assertEqual(renamed["name"], "renamed.py")

    def test_only_py_files_can_be_imported_from_disk(self):
        secret = Path(self._tmp.name) / "notes.txt"
        secret.write_text("hunter2")
        with self.assertRaisesRegex(ScriptStoreError, r"\.py"):
            srv.import_script(source_path=str(secret))

    def test_hostile_names_are_refused(self):
        for name in ("../evil.py", "sub/evil.py", "evil.txt", "C:\\evil.py"):
            with self.subTest(name=name), self.assertRaises(ScriptStoreError):
                srv.import_script(name=name, content="x = 1\n")

    def test_a_file_with_a_bom_stays_current_after_validation(self):
        self.store.ensure()
        (self.store.root / "bom.py").write_bytes(b"\xef\xbb\xbf" + SDK_SCRIPT.encode("utf-8"))
        result = srv.validate_script("bom.py")
        self.assertTrue(result["runnable"])
        self.assertTrue(self.store.validation_status("bom.py")["validation_current"])

    def test_non_utf8_content_fails_validation_rather_than_crashing(self):
        self.store.ensure()
        (self.store.root / "latin.py").write_bytes(b"x = '\xe9'\n")
        result = srv.validate_script("latin.py")
        self.assertFalse(result["runnable"])
        self.assertEqual(result["validation"]["errors"][0]["rule"], "V001")

    def test_get_script_returns_text_hash_and_status(self):
        srv.import_script(name="s.py", content=SDK_SCRIPT)
        got = srv.get_script("s.py")
        self.assertEqual(got["content"], SDK_SCRIPT)
        self.assertEqual(got["sha256"], self.store.sha256("s.py"))
        self.assertTrue(got["validation_ok"])

    def test_validate_script_reflects_edits(self):
        srv.import_script(name="s.py", content=SDK_SCRIPT)
        (self.store.root / "s.py").write_text(SDK_SCRIPT + "import subprocess\n")
        self.assertFalse(self.store.validation_status("s.py")["validation_current"])
        result = srv.validate_script("s.py")
        self.assertFalse(result["runnable"])
        self.assertEqual(result["validation"]["errors"][0]["rule"], "V010")


class RunToolTests(ServerScriptTestCase):
    async def test_run_monitor_and_finish(self):
        srv.import_script(name="quick.py", content=GOOD)
        started = await srv.run_script("quick.py")
        self.assertEqual(started["script"], "quick.py")
        self.assertTrue(started["simulate"])
        self.assertIn("get_run_events", started["next"])
        run_id = started["run_id"]

        page = await srv.get_run_events(run_id, since_seq=0, wait_s=10.0)
        self.assertTrue(page["events"])
        await self.finished(run_id)
        page = await srv.get_run_events(run_id)
        self.assertTrue(page["finished"])
        self.assertEqual(page["status"], "completed")
        snap = srv.get_run(run_id)
        self.assertEqual(snap["tips"]["P"]["remaining"], 80)
        self.assertEqual([r["run_id"] for r in srv.list_runs()], [run_id])

    async def test_wait_is_capped_below_the_hubs_call_timeout(self):
        srv.import_script(name="slow.py", content="# mode: slow\nprint('x')\n")
        started = await srv.run_script("slow.py")
        try:
            await self.until(lambda: srv.get_run(started["run_id"])["status"] == "running")
            seen = (await srv.get_run_events(started["run_id"]))["next_since_seq"]
            with mock.patch.object(self.manager, "get_events", wraps=self.manager.get_events) as spy:
                task = asyncio.create_task(srv.get_run_events(started["run_id"], since_seq=seen, wait_s=999))
                await asyncio.sleep(0.2)
                task.cancel()
            self.assertLessEqual(spy.call_args.kwargs["wait_s"], 25.0)
        finally:
            srv.abort_run(started["run_id"])
            await self.finished(started["run_id"])

    async def test_scripts_that_fail_validation_cannot_run(self):
        srv.import_script(name="bad.py", content="import subprocess\n")
        with self.assertRaisesRegex(RunError, "does not pass validation"):
            await srv.run_script("bad.py")

    async def test_unvalidated_edits_are_caught_at_run_time(self):
        srv.import_script(name="a.py", content=GOOD)
        (self.store.root / "a.py").write_text("import socket\n")  # edited after validation
        with self.assertRaisesRegex(RunError, "V010"):
            await srv.run_script("a.py")

    async def test_refused_while_an_interactive_session_is_active(self):
        srv.import_script(name="a.py", content=GOOD)
        with mock.patch.object(srv, "_session_active", return_value=True):
            with self.assertRaisesRegex(RunError, "close_session"):
                await srv.run_script("a.py")

    async def test_refused_while_venus_is_busy(self):
        srv.import_script(name="a.py", content=GOOD)
        with mock.patch.object(srv._session, "check_run_state", AsyncMock(return_value=RunState.RUNNING)):
            with self.assertRaisesRegex(RunError, "silently abort"):
                await srv.run_script("a.py")

    async def test_real_hardware_needs_the_spoke_flag(self):
        srv.import_script(name="a.py", content=GOOD)
        with self.assertRaisesRegex(RunError, ALLOW_HARDWARE_ENV):
            await srv.run_script("a.py", simulate=False)

    async def test_start_session_is_refused_while_a_script_runs(self):
        srv.import_script(name="slow.py", content="# mode: slow\nprint('x')\n")
        started = await srv.run_script("slow.py")
        try:
            with self.assertRaisesRegex(RuntimeError, "script run is active"):
                await srv.start_session(simulate=True, blank_deck=True)
        finally:
            srv.abort_run(started["run_id"])
            await self.finished(started["run_id"])

    async def test_pause_resume_abort_tools(self):
        srv.import_script(name="slow.py", content="# mode: slow\nprint('x')\n")
        run_id = (await srv.run_script("slow.py"))["run_id"]
        await self.until(lambda: srv.get_run(run_id)["status"] == "running")
        srv.pause_run()
        await self.until(lambda: srv.get_run(run_id)["status"] == "paused")
        srv.resume_run(run_id)
        await self.until(lambda: srv.get_run(run_id)["status"] == "running")
        srv.abort_run()
        await self.finished(run_id)
        self.assertEqual(srv.get_run(run_id)["status"], "stopped")


class RunSummaryToolTests(ServerScriptTestCase):
    async def test_get_run_summary(self):
        srv.import_script(name="logged.py", content="# mode: logged\nprint('x')\n")
        run_id = (await srv.run_script("logged.py"))["run_id"]
        await self.finished(run_id)
        result = srv.get_run_summary(run_id)
        self.assertEqual(result["summary"]["tips_used"], 8)

    async def test_no_summary_while_running(self):
        srv.import_script(name="slow.py", content="# mode: slow\nprint('x')\n")
        run_id = (await srv.run_script("slow.py"))["run_id"]
        try:
            await self.until(lambda: srv.get_run(run_id)["status"] == "running")
            with self.assertRaises(RunError):
                srv.get_run_summary(run_id)
        finally:
            srv.abort_run(run_id)
            await self.finished(run_id)


class ConsumablesToolTests(ServerScriptTestCase):
    async def test_configure_tip_threshold_and_register_reagent(self):
        result = srv.set_tip_threshold("P", 15)
        self.assertEqual(result, {"tip_pool": "P", "low_threshold": 15})
        entry = srv.register_reagent("Trough1", "all", label="Water", low_percent=0.2)
        self.assertEqual(entry["key"], "Trough1")
        config = srv.get_consumables_config()
        self.assertEqual(config["tip_pools"]["P"]["low_threshold"], 15)
        self.assertEqual(config["reagents"]["Trough1"]["label"], "Water")
        self.assertTrue(srv.remove_reagent_threshold("Trough1")["removed"])
        self.assertFalse(srv.remove_reagent_threshold("Trough1")["removed"])

    async def test_usage_levels_and_low_items_after_a_run(self):
        srv.import_script(name="logged.py", content="# mode: logged\nprint('x')\n")
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            run_id = (await srv.run_script("logged.py", simulate=False))["run_id"]
        await self.finished(run_id)

        usage = srv.get_consumables_usage(kind="tip")
        self.assertEqual(usage[0]["total_quantity"], 8)
        levels = srv.get_consumables_levels(kind="tip")
        self.assertEqual(levels[0]["level"], 88)
        self.assertEqual(srv.list_low_consumables(kind="tip"), [])  # no threshold configured yet

    async def test_manual_event_needs_the_operator_token(self):
        with self.assertRaises(OperatorAuthError):
            srv.record_consumable_event("tip", "P", "reload", token="wrong")
        result = srv.record_consumable_event("tip", "P", "reload", token=TOKEN, amount=96, operator="Sam")
        self.assertEqual((result["kind"], result["item_key"], result["type"]), ("tip", "P", "reload"))
        (event,) = srv.get_consumables_events(kind="tip", item_key="P")
        self.assertEqual(event["operator"], "Sam")

    async def test_reload_during_a_run_is_visible_in_events_and_usage(self):
        srv.import_script(name="reload.py", content="# mode: reload\nprint('x')\n")
        with mock.patch.dict(os.environ, {ALLOW_HARDWARE_ENV: "1"}):
            run_id = (await srv.run_script("reload.py", simulate=False))["run_id"]
        await self.until(lambda: srv.get_run(run_id)["pending_prompts"])
        srv.operator_resolve_prompt(run_id, "tip-1", token=TOKEN, action="continue")
        await self.finished(run_id)
        events = srv.get_consumables_events(kind="tip", item_key="P")
        self.assertEqual(events[0]["type"], "reload")
        self.assertEqual(events[0]["run_id"], run_id)


class SpokeStateAndPromptTests(ServerScriptTestCase):
    async def test_idle_running_error_idle(self):
        srv.import_script(name="prompt.py", content="# mode: prompt\nprint('x')\n")
        state = await srv.get_spoke_state()
        self.assertEqual(state["state"], "idle")
        self.assertEqual(state["venus_run_state"]["name"], "NOT_INITIALIZED")
        self.assertEqual(state["scripts_dir"], str(self.store.root))
        self.assertIn("operator_ui", state)
        self.assertNotIn(TOKEN, str(state))

        run_id = (await srv.run_script("prompt.py"))["run_id"]
        await self.until(lambda: self.manager.state()["state"] == "error")
        state = await srv.get_spoke_state()
        self.assertEqual((state["state"], state["error_kind"]), ("error", "prompt_pending"))
        (prompt,) = state["pending_prompts"]
        self.assertEqual(prompt["options"], ["retry", "abort"])

        # the agent can see the prompt in the event stream too, but has no token to answer it
        page = await srv.get_run_events(run_id, types=["prompt"])
        self.assertEqual(page["events"][0]["prompt_id"], "err-1")
        self.assertNotIn(TOKEN, str(page))
        with self.assertRaises(OperatorAuthError):
            srv.operator_resolve_prompt(run_id, "err-1", token="", action="retry")
        with self.assertRaises(OperatorAuthError):
            srv.operator_resolve_prompt(run_id, "err-1", token="guess", action="retry")
        self.assertEqual(self.manager.state()["state"], "error")  # still waiting

        answered = srv.operator_resolve_prompt(run_id, "err-1", token=TOKEN, action="retry", operator="Sam")
        self.assertTrue(answered["resolved"])
        await self.finished(run_id)
        self.assertEqual((await srv.get_spoke_state())["state"], "idle")
        (done,) = srv.get_run(run_id)["prompt_history"]
        self.assertEqual(done["resolution"]["source"], "mcp_tool")
        self.assertEqual(done["resolution"]["operator"], "Sam")

    async def test_failed_run_is_an_error_until_acknowledged(self):
        srv.import_script(name="fail.py", content="# mode: fail\nprint('x')\n")
        run_id = (await srv.run_script("fail.py"))["run_id"]
        await self.finished(run_id)
        state = await srv.get_spoke_state()
        self.assertEqual((state["state"], state["error_kind"]), ("error", "run_failed"))
        srv.acknowledge_run_error(run_id)
        self.assertEqual((await srv.get_spoke_state())["state"], "idle")

    async def test_state_survives_venus_being_unreachable(self):
        with mock.patch.object(srv.venus_api, "get_run_state", side_effect=venus_api.VenusApiError("down")):
            state = await srv.get_spoke_state()
        self.assertEqual(state["state"], "idle")

    async def test_state_includes_this_spokes_display_name(self):
        with mock.patch.dict(os.environ, {srv.SPOKE_NAME_ENV: "star3-test"}):
            state = await srv.get_spoke_state()
        self.assertEqual(state["name"], "star3-test")

    async def test_wait_s_returns_well_before_the_deadline_once_the_state_changes(self):
        srv.import_script(name="prompt.py", content="# mode: prompt\nprint('x')\n")
        wait_task = asyncio.create_task(srv.get_spoke_state(wait_s=20))
        await asyncio.sleep(0.1)
        started = time.monotonic()
        run_id = (await srv.run_script("prompt.py"))["run_id"]
        state = await asyncio.wait_for(wait_task, timeout=5.0)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertNotEqual(state["state"], "idle")
        # resolve/finish the run so this test doesn't leave a pending prompt behind for teardown
        await self.until(lambda: self.manager.state()["state"] == "error")
        srv.operator_resolve_prompt(run_id, "err-1", token=TOKEN, action="retry")
        await self.finished(run_id)

    async def test_wait_s_returns_the_unchanged_state_at_the_deadline_when_nothing_happens(self):
        started = time.monotonic()
        state = await srv.get_spoke_state(wait_s=0.5)
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertEqual(state["state"], "idle")

    async def test_wait_s_is_clamped_and_zero_is_immediate(self):
        started = time.monotonic()
        state = await srv.get_spoke_state(wait_s=0)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(state["state"], "idle")


class VenusToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_error_shapes(self):
        with mock.patch.object(srv.venus_api, "get_run_state", return_value={"value": 3, "name": "RUNNING"}):
            result = await srv.get_venus_run_state()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["name"], "RUNNING")

        with mock.patch.object(srv.venus_api, "abort", side_effect=venus_api.VenusApiError("VENUS said no")):
            result = await srv.venus_abort()
        self.assertEqual((result["status"], result["message"]), ("error", "VENUS said no"))

    async def test_history_arguments_are_clamped_and_passed_through(self):
        with mock.patch.object(srv.venus_api, "list_run_history", return_value=[]) as history:
            await srv.list_venus_run_history(limit=99999, offset=-5, run_state="Completed")
        kwargs = history.call_args.kwargs
        self.assertEqual((kwargs["limit"], kwargs["offset"], kwargs["run_state"]), (200, 1, "Completed"))  # VENUS's offset is 1-based

    async def test_pause_resume_detail_trace_and_current_data(self):
        for tool, target, args in (
            (srv.venus_pause, "pause", ()),
            (srv.venus_resume, "resume", ()),
            (srv.get_venus_current_run_data, "get_current_run_data", ()),
            (srv.get_venus_run_detail, "get_run_detail", ("guid-1",)),
            (srv.get_venus_run_trace, "get_run_trace", ()),
        ):
            with self.subTest(tool=target), mock.patch.object(srv.venus_api, target, return_value={"ok": True}):
                result = await tool(*args)
                self.assertEqual(result["status"], "success")


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_new_tools_are_registered(self):
        names = {tool.name for tool in await srv.mcp.list_tools()}
        expected = {
            "list_scripts", "get_script", "import_script", "validate_script", "run_script", "get_run",
            "get_run_summary", "list_runs", "get_run_events", "pause_run", "resume_run", "abort_run",
            "acknowledge_run_error", "get_spoke_state", "operator_resolve_prompt", "get_venus_run_state",
            "get_venus_current_run_data", "list_venus_run_history", "get_venus_run_detail", "get_venus_run_trace",
            "venus_pause", "venus_resume", "venus_abort", "get_consumables_config", "set_tip_threshold",
            "register_reagent", "remove_reagent_threshold", "get_consumables_usage", "get_consumables_levels",
            "list_low_consumables", "get_consumables_events", "record_consumable_event",
        }
        self.assertLessEqual(expected, names)

    async def test_no_tool_advertises_the_token_as_a_default_or_example(self):
        for tool in await srv.mcp.list_tools():
            self.assertNotIn(TOKEN, str(tool))

    def test_instructions_describe_the_script_workflow_and_the_human_gate(self):
        text = srv._GUIDE
        for phrase in (
            "import_script", "run_script", "get_run_events", "WAITS FOR A HUMAN", "operator page",
            "get_spoke_state", "get_run_summary", "get_consumables_usage", "record_consumable_event",
            "HUMAN OPERATORS ONLY",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
