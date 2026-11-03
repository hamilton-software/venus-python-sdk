"""Unit tests for the child process's error handling: prompt numbering, and asking a person
again when VENUS re-notifies an error their answer did not clear.

The real child is exercised end to end against the VENUS simulator by hand; these use fakes for
the client so the failing-again case, which the simulator cannot be made to produce on demand,
is covered.
"""

from __future__ import annotations

import asyncio
import queue
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from hamilton_venus_mcp.script_runs import child_bootstrap as child


class FakeVenus:
    def __init__(self, sequence):
        self._sequence = list(sequence)  # each call returns the next list of unhandled errors
        self.calls = 0

    async def get_unhandled_errors(self):
        self.calls += 1
        index = min(self.calls - 1, len(self._sequence) - 1)
        return self._sequence[index]


class FakeResolver:
    def __init__(self):
        self.raised = []

    async def on_instrument_error(self, error):
        self.raised.append(error)


class FakeClient:
    def __init__(self, sequence):
        self.venus = FakeVenus(sequence)
        self.resolver = FakeResolver()
        self.listener = SimpleNamespace(
            runtime_status=[],
            error_notification=[],
            on_runtime_status=lambda cb: self.listener.runtime_status.append(cb),
            on_instrument_error_notification=lambda cb: self.listener.error_notification.append(cb),
        )
        self._connected_instrument = SimpleNamespace(venus=self.venus, _error_resolver=self.resolver, _listener=self.listener)
        self.closed = False

    def _run(self, coro):
        if self.closed:
            coro.close()
            raise RuntimeError("Client is not started")
        return asyncio.run(coro)


def error(uuid="err-1"):
    return SimpleNamespace(uuid=uuid, code="P1:08/78", title="Tip Pick Up - Error", message="P1:08/78", detailed_errors=[], recovery_actions=[])


class ChildTestCase(unittest.TestCase):
    def setUp(self):
        for name in (
            "_answered",
            "_reasking",
            "_deferred_notified",
            "_prompt_events",
            "_prompt_responses",
            "_status_listener_registered",
            "_tip_thresholds",
            "_reagent_thresholds",
            "_reagent_capacities",
            "_reagent_state",
            "_reagent_below_threshold",
            "_tip_below_threshold",
            "_tip_capacity_cache",
            "_reservoir_logged",
            "_config",
        ):
            getattr(child, name).clear()
        child._geometry = None
        child._line_timeline.clear()
        child._stop_requested.clear()
        child._finished.clear()
        sleeper = mock.patch.object(child.time, "sleep", lambda _s: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.events = []
        # Positional param named "event_type", not "kind" -- several real events (reload,
        # consumable_warning) carry their own "kind" keyword (tip/reagent), which would
        # otherwise collide with a same-named positional parameter here.
        emitter = mock.patch.object(child, "emit", lambda event_type, **data: self.events.append((event_type, data)))
        emitter.start()
        self.addCleanup(emitter.stop)

    def logs(self):
        return [data["message"] for kind, data in self.events if kind == "log"]


class AskAgainTests(ChildTestCase):
    def test_an_error_that_is_still_unhandled_goes_back_to_the_resolver(self):
        pending = error()
        client = FakeClient([[pending]])
        child._answered["err-1"] = 1
        child._reasking.add("err-1")
        child._ask_again_if_still_pending(client, "err-1")
        self.assertEqual(client.resolver.raised, [pending])
        self.assertEqual(client.venus.calls, 5)  # it looked five times before giving up on it clearing
        self.assertTrue(any("asking again" in m for m in self.logs()))
        self.assertNotIn("err-1", child._reasking)

    def test_an_error_that_clears_is_left_alone(self):
        client = FakeClient([[error()], [error()], []])  # gone by the third look
        child._answered["err-1"] = 1
        child._ask_again_if_still_pending(client, "err-1")
        self.assertEqual(client.resolver.raised, [])
        self.assertEqual(client.venus.calls, 3)
        self.assertEqual(self.logs(), [])

    def test_a_different_error_pending_does_not_count(self):
        client = FakeClient([[error("some-other-error")]])
        child._answered["err-1"] = 1
        child._ask_again_if_still_pending(client, "err-1")
        self.assertEqual(client.resolver.raised, [])

    def test_nothing_happens_once_the_run_is_stopping_or_finished(self):
        for flag in (child._stop_requested, child._finished):
            with self.subTest(flag=flag):
                flag.set()
                client = FakeClient([[error()]])
                child._ask_again_if_still_pending(client, "err-1")
                self.assertEqual(client.resolver.raised, [])
                self.assertEqual(client.venus.calls, 0)
                flag.clear()

    def test_a_client_that_closed_meanwhile_is_not_reported_as_a_problem(self):
        client = FakeClient([[error()]])
        client.closed = True
        child._ask_again_if_still_pending(client, "err-1")
        self.assertEqual(self.logs(), [])
        self.assertNotIn("err-1", child._reasking)

    def test_a_failure_to_re_raise_is_reported_not_raised(self):
        client = FakeClient([[error()]])

        async def boom(_error):
            raise ValueError("resolver refused")

        client.resolver.on_instrument_error = boom
        child._ask_again_if_still_pending(client, "err-1")
        self.assertTrue(any("resolver refused" in m for m in self.logs()))


class DoStopClearsErrorHandlerTests(ChildTestCase):
    """instrument_terminate() (STOP's own SDK call) does not unregister this run's client as
    VENUS's error handler -- only a clean __aexit__ does, which may never happen if the script
    is still stuck on something when STOP is requested. _do_stop attempts the same cleanup
    itself, best-effort, so VENUS isn't left unable to show its own operator dialog for a later
    run (confirmed live: exactly this was found stuck on real hardware)."""

    def test_attempts_to_clear_the_error_handler(self):
        with mock.patch("hamilton_venus_mcp.venus_api.clear_error_handler") as clear_error_handler:
            child._do_stop("test")
        clear_error_handler.assert_called_once()

    def test_a_failure_to_clear_is_logged_not_raised(self):
        with mock.patch("hamilton_venus_mcp.venus_api.clear_error_handler", side_effect=RuntimeError("down")):
            child._do_stop("test")  # must not raise
        self.assertTrue(any("clear_error_handler" in m for m in self.logs()))

    def test_a_terminate_that_never_returns_does_not_stop_the_handler_being_cleared(self):
        # Seen live: the SDK's terminate blocked while a command waited on an operator prompt, so the
        # steps after it never ran and VENUS was left with a handler that no longer existed.
        release = threading.Event()
        self.addCleanup(release.set)

        class HangingClient:
            def instrument_terminate(self):
                release.wait(30)

        child._captured_clients.append(HangingClient())
        self.addCleanup(child._captured_clients.clear)
        with mock.patch.object(child, "_TERMINATE_WAIT_S", 0.2), mock.patch(
            "hamilton_venus_mcp.venus_api.clear_error_handler"
        ) as clear_error_handler:
            child._do_stop("test")
        clear_error_handler.assert_called_once()
        self.assertTrue(any("did not return" in m for m in self.logs()))

    def test_every_client_is_terminated(self):
        called = []

        class Client:
            def __init__(self, name):
                self.name = name

            def instrument_terminate(self):
                called.append(self.name)

        child._captured_clients.extend([Client("a"), Client("b")])
        self.addCleanup(child._captured_clients.clear)
        with mock.patch("hamilton_venus_mcp.venus_api.clear_error_handler"):
            child._do_stop("test")
        self.assertEqual(sorted(called), ["a", "b"])


class NotificationHookTests(ChildTestCase):
    def setUp(self):
        super().setUp()
        # These tests exercise the "ask again if still pending" branch specifically; the token
        # is configured so the new deferred-error-reporting branch (DeferredErrorReportingTests)
        # doesn't also fire and spawn a second, unrelated Thread these tests aren't expecting.
        child._config["operator_gate_configured"] = True

    def register(self, client):
        child._register_status_listener(client)
        (handler,) = client.listener.error_notification
        return handler

    def test_both_listeners_are_registered_once(self):
        client = FakeClient([[]])
        child._register_status_listener(client)
        child._register_status_listener(client)
        self.assertEqual((len(client.listener.runtime_status), len(client.listener.error_notification)), (1, 1))

    def test_a_notification_for_an_error_nobody_answered_is_ignored(self):
        client = FakeClient([[error()]])
        handler = self.register(client)
        with mock.patch.object(child.threading, "Thread") as thread:
            asyncio.run(handler("unknown-error"))
        thread.assert_not_called()

    def test_a_notification_for_an_answered_error_starts_one_check(self):
        client = FakeClient([[error()]])
        handler = self.register(client)
        child._answered["err-1"] = 1
        with mock.patch.object(child.threading, "Thread") as thread:
            asyncio.run(handler("err-1 "))  # VENUS's notification text can carry stray whitespace
            asyncio.run(handler("err-1"))  # a repeat while the first check runs
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(thread.call_args.kwargs["args"], (client, "err-1"))

    def test_no_check_is_started_while_stopping(self):
        client = FakeClient([[error()]])
        handler = self.register(client)
        child._answered["err-1"] = 1
        child._stop_requested.set()
        with mock.patch.object(child.threading, "Thread") as thread:
            asyncio.run(handler("err-1"))
        thread.assert_not_called()


class EscalationPromptTests(ChildTestCase):
    def setUp(self):
        super().setUp()
        child._config["operator_gate_configured"] = True  # these tests exercise the "ask a human" path

    def context(self, err):
        return SimpleNamespace(error=err, top_level_actions=[])

    def test_each_ask_gets_its_own_prompt_id_and_attempt_number(self):
        ids = []

        def fake_await(prompt_id, payload):
            ids.append((prompt_id, payload["attempt"]))
            return None  # no answer -> abort

        with mock.patch.object(child, "_await_prompt", fake_await), mock.patch(
            "hamilton_workflow_framework.session._describe_error", return_value=("Title", [])
        ):
            child._on_operator_escalation(self.context(error()))
            child._on_operator_escalation(self.context(error()))
            child._on_operator_escalation(self.context(error("err-2")))
        self.assertEqual(ids, [("err-1", 1), ("err-1#2", 2), ("err-2", 1)])

    def test_abort_is_always_among_the_options(self):
        seen = {}

        def fake_await(prompt_id, payload):
            seen.update(payload)
            return None

        with mock.patch.object(child, "_await_prompt", fake_await), mock.patch(
            "hamilton_workflow_framework.session._describe_error", return_value=("Title", [])
        ), mock.patch("hamilton_workflow_framework.session._known_action_names", return_value=["cancel"]):
            child._on_operator_escalation(self.context(error()))
        self.assertEqual(seen["options"], ["cancel", "abort"])
        self.assertEqual(seen["kind"], "operator_error")

    def test_no_answer_means_abort_to_the_sdk(self):
        with mock.patch.object(child, "_await_prompt", lambda *_a: None), mock.patch(
            "hamilton_workflow_framework.session._describe_error", return_value=("Title", [])
        ):
            self.assertIsNone(child._on_operator_escalation(self.context(error())))


class CommandTimeoutConfigTests(ChildTestCase):
    """The SDK's 300 s per-command limit also runs while a person answers an instrument-error prompt."""

    def _construct(self, *args, **kwargs):
        captured = {}

        class FakeSdkClient:
            def __init__(self, *a, **kw):
                captured.update(kw)

            def __enter__(self):
                return self

            def instrument_connect(self, **kw):
                return None

        child._config.update({"simulate": True, "run_log_dir": "C:\nowhere"})
        child._patch_client_class(FakeSdkClient)
        FakeSdkClient(*args, **kwargs)
        return captured

    def test_the_sdk_config_gets_the_runs_command_timeout(self):
        child._config["command_timeout_s"] = 1800.0
        config = self._construct()["config"]
        self.assertEqual(config.timeouts.command, 1800.0)

    def test_a_script_supplied_config_is_left_alone(self):
        child._config["command_timeout_s"] = 1800.0
        sentinel = object()
        self.assertIs(self._construct(config=sentinel)["config"], sentinel)

    def test_no_setting_means_the_sdk_default(self):
        self.assertNotIn("config", self._construct())


class NoOperatorGateClientPatchTests(ChildTestCase):
    """No operator token configured on this spoke (child._config["operator_gate_configured"]
    left unset/False by ChildTestCase.setUp's clear()) -- nobody remote could ever answer a
    prompt. Confirmed directly against a real run: registering the escalation callback anyway
    and having it *return* a selected_action_id=-1 ErrorRecovery does NOT reproduce "no callback
    registered" -- the SDK's own resolver unconditionally forces selected_action_is_recovery to
    True on any callback-returned ErrorRecovery before submitting it
    (_error_profile_resolver.py's _escalate), and VENUS is left waiting on a decision that was
    never really made, with no dialog ever appearing. The only way to get the SDK's own
    well-formed legacy-dialog fallback is to not register a callback at all -- see
    _patch_client_class's patched_init."""

    def test_kwargs_reflect_the_gate(self):
        captured = {}

        class FakeSdkClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def __enter__(self):
                return self

            def instrument_connect(self, **kwargs):
                return None

        # simulate/run_log_dir are read once, at _patch_client_class call time -- set them first.
        child._config.update({"simulate": True, "run_log_dir": "C:\\nowhere"})
        child._patch_client_class(FakeSdkClient)

        # operator_gate_configured is read fresh inside patched_init on every instantiation, so
        # it can vary per FakeSdkClient() call without re-patching.
        with mock.patch.object(child, "_captured_clients", []):
            child._config["operator_gate_configured"] = False
            FakeSdkClient()
        self.assertIsNone(captured["on_operator_error_escalation"])

        captured.clear()
        with mock.patch.object(child, "_captured_clients", []):
            child._config["operator_gate_configured"] = True
            FakeSdkClient()
        self.assertIs(captured["on_operator_error_escalation"], child._on_operator_escalation)


class DeferredErrorReportingTests(ChildTestCase):
    """The visibility half of the no-token path: _on_error_notification (registered
    unconditionally by _register_status_listener, independent of the escalation callback) looks
    up and reports an error the spoke never tried to decide on its own behalf. The report itself
    runs on a background daemon thread (see _report_deferred_error), so these poll self.events
    briefly instead of asserting immediately after the triggering call returns."""

    def register(self, client):
        child._register_status_listener(client)
        (handler,) = client.listener.error_notification
        return handler

    def wait_for_event(self, kind, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = next((d for k, d in self.events if k == kind), None)
            if match is not None:
                return match
            time.sleep(0.02)
        self.fail(f"no {kind!r} event within {timeout}s; saw {[k for k, _d in self.events]}")

    def test_looks_up_and_reports_an_unhandled_error(self):
        client = FakeClient([[error()]])
        handler = self.register(client)
        with mock.patch.dict(child._config, {"operator_gate_configured": False}, clear=False), mock.patch(
            "hamilton_workflow_framework.session._describe_error", return_value=("Tip Pick Up - Error", [])
        ):
            asyncio.run(handler("err-1"))
            data = self.wait_for_event("operator_error_deferred")
        self.assertEqual(data["code"], "P1:08/78")
        self.assertEqual(data["title"], "Tip Pick Up - Error")

    def test_only_reports_once_per_error_uuid(self):
        client = FakeClient([[error()], [error()]])
        handler = self.register(client)
        with mock.patch.dict(child._config, {"operator_gate_configured": False}, clear=False), mock.patch(
            "hamilton_workflow_framework.session._describe_error", return_value=("Title", [])
        ):
            asyncio.run(handler("err-1"))
            self.wait_for_event("operator_error_deferred")
            asyncio.run(handler("err-1"))
            time.sleep(0.1)  # give a wrongly-spawned second report a chance to show up
        kinds = [k for k, _d in self.events if k == "operator_error_deferred"]
        self.assertEqual(len(kinds), 1)

    def test_does_nothing_when_the_gate_is_configured(self):
        client = FakeClient([[error()]])
        handler = self.register(client)
        with mock.patch.dict(child._config, {"operator_gate_configured": True}, clear=False):
            asyncio.run(handler("err-1"))
            time.sleep(0.1)
        self.assertNotIn("operator_error_deferred", [k for k, _d in self.events])

    def test_reports_something_even_if_already_resolved_by_the_time_we_look(self):
        client = FakeClient([[]])  # nothing unhandled -- VENUS already moved on
        handler = self.register(client)
        with mock.patch.dict(child._config, {"operator_gate_configured": False}, clear=False):
            asyncio.run(handler("err-1"))
            data = self.wait_for_event("operator_error_deferred")
        self.assertIn("err-1", data["title"])


class ReloadPromptTests(ChildTestCase):
    def test_continue_is_true_and_anything_else_is_false(self):
        tip = SimpleNamespace(tip_pool="P", required=8, available=2, command="add_reagent", attempt=1)
        liquid = SimpleNamespace(active_source="Trough@1", sources=("Trough@1",), required=50.0, available=10.0, command="x", attempt=1)
        for handler, context in ((child._on_tip_reload_prompt, tip), (child._on_liquid_reload_prompt, liquid)):
            for response, expected in (({"kind": "continue"}, True), ({"kind": "abort"}, False), (None, False), ({}, False)):
                with self.subTest(handler=handler.__name__, response=response), mock.patch.object(child, "_await_prompt", lambda *_a, r=response: r):
                    self.assertIs(handler(context), expected)

    def test_a_continued_tip_reload_emits_a_reload_event(self):
        tip = SimpleNamespace(tip_pool="P", required=8, available=2, command="add_reagent", attempt=1)
        with mock.patch.object(child, "_await_prompt", lambda *_a: {"kind": "continue"}):
            child._on_tip_reload_prompt(tip)
        (event,) = [e for e in self.events if e[0] == "reload"]
        self.assertEqual(event[1], {"kind": "tip", "item_key": "P", "command": "add_reagent"})

    def test_an_aborted_tip_reload_emits_nothing(self):
        tip = SimpleNamespace(tip_pool="P", required=8, available=2, command="add_reagent", attempt=1)
        with mock.patch.object(child, "_await_prompt", lambda *_a: {"kind": "abort"}):
            child._on_tip_reload_prompt(tip)
        self.assertEqual([e for e in self.events if e[0] == "reload"], [])

    def test_a_continued_liquid_reload_emits_a_reload_event_and_clears_the_estimate(self):
        child._reagent_state["Trough"] = {"remaining_ul": 5.0, "total_ul": 1000.0}
        liquid = SimpleNamespace(active_source="Trough@1", sources=("Trough@1",), required=50.0, available=10.0, command="x", attempt=1)
        with mock.patch.object(child, "_await_prompt", lambda *_a: {"kind": "continue"}):
            child._on_liquid_reload_prompt(liquid)
        (event,) = [e for e in self.events if e[0] == "reload"]
        self.assertEqual(event[1], {"kind": "reagent", "item_key": "Trough", "command": "x"})
        self.assertNotIn("Trough", child._reagent_state)


class ReleaseTests(ChildTestCase):
    def test_stop_releases_every_waiting_prompt_as_no_answer(self):
        waiting = child.threading.Event()
        child._prompt_events["p1"] = waiting
        child._release_waiters()
        self.assertTrue(waiting.is_set())
        self.assertIsNone(child._prompt_responses["p1"])
        self.assertTrue(child._resume_now.is_set())
        child._prompt_events.clear()


class FakeTipCounterParams:
    def __init__(self, available_tips, empty_tips, missing_racks):
        self.available_tips = available_tips
        self.empty_tips = empty_tips
        self.missing_racks = missing_racks


class FakeTipPoolClient:
    def __init__(self, params=None, raises=False):
        self._params = params
        self._raises = raises
        self.calls = 0

    def tip_pool_get_tip_counter(self, _tip_pool):
        self.calls += 1
        if self._raises:
            raise RuntimeError("VENUS unreachable")
        return SimpleNamespace(return_parameters=self._params)


class TipPoolCapacityTests(ChildTestCase):
    def test_capacity_from_a_fresh_pool(self):
        params = FakeTipCounterParams(available_tips=[{"rack1": {"count": 40}}], empty_tips=[{"rack1": {"count": 56}}], missing_racks=[])
        client = FakeTipPoolClient(params)
        self.assertEqual(child._tip_pool_capacity(client, "P"), 96)

    def test_capacity_counts_distinct_racks_across_both_lists(self):
        params = FakeTipCounterParams(
            available_tips=[{"rack1": {"count": 10}}, {"rack2": {"count": 20}}],
            empty_tips=[{"rack1": {"count": 30}}],
            missing_racks=["rack3"],
        )
        client = FakeTipPoolClient(params)
        self.assertEqual(child._tip_pool_capacity(client, "P"), 96 * 3)

    def test_capacity_is_cached_per_pool(self):
        client = FakeTipPoolClient(FakeTipCounterParams([{"r": {"count": 1}}], [], []))
        child._tip_pool_capacity(client, "P")
        child._tip_pool_capacity(client, "P")
        self.assertEqual(client.calls, 1)

    def test_capacity_lookup_failure_is_none_not_raised(self):
        client = FakeTipPoolClient(raises=True)
        self.assertIsNone(child._tip_pool_capacity(client, "P"))

    def test_no_racks_at_all_is_none(self):
        client = FakeTipPoolClient(FakeTipCounterParams([], [], []))
        self.assertIsNone(child._tip_pool_capacity(client, "P"))


class TipThresholdTests(ChildTestCase):
    def test_fires_once_when_crossing_below_and_resets_above(self):
        child._tip_thresholds["P"] = 10
        child._check_tip_threshold("P", 5)
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)
        child._check_tip_threshold("P", 4)  # still low: no second warning
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)
        child._check_tip_threshold("P", 20)  # back above: clears the guard
        child._check_tip_threshold("P", 3)  # low again: fires again
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 2)

    def test_no_threshold_configured_never_fires(self):
        child._check_tip_threshold("Untracked", 0)
        self.assertEqual([e for e in self.events if e[0] == "consumable_warning"], [])


class ShouldTrackReagentTests(ChildTestCase):
    def test_already_tracked_key_is_always_tracked(self):
        child._reagent_state["Trough"] = {"remaining_ul": None, "total_ul": None}
        self.assertTrue(child._should_track_reagent("Trough", "Trough"))

    def test_explicitly_configured_key_is_tracked_before_first_measurement(self):
        child._reagent_thresholds["Tubes@1"] = 0.1
        self.assertTrue(child._should_track_reagent("Tubes@1", "Tubes"))

    def test_reservoir_class_labware_is_auto_tracked(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: SimpleNamespace(labware_class="reservoir", container_grids={}))
        self.assertTrue(child._should_track_reagent("Trough1", "Trough1"))

    def test_unregistered_non_reservoir_is_not_tracked(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: SimpleNamespace(labware_class="plate", container_grids={}))
        self.assertFalse(child._should_track_reagent("Plate1@A1", "Plate1"))

    def test_no_geometry_cache_yet_is_not_tracked_unless_registered(self):
        self.assertIsNone(child._geometry)
        self.assertFalse(child._should_track_reagent("Plate1@A1", "Plate1"))


class UpdateReagentStateTests(ChildTestCase):
    def test_a_registered_capacity_replaces_the_geometry_capacity(self):
        # "60 mL" trough whose geometry works out to ~80 mL: 33 mL must read against what the user set.
        child._reagent_capacities["Trough"] = 60000.0
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 80000.0):
            readings = [{"liquid_level_mm": 29.0, "liquid_volume_ul": 33000.0, "aspirated_ul": 250.0}]
            state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["total_volume_ul"], 60000.0)
        self.assertAlmostEqual(state["percent_full"], 0.55, places=6)

    def test_without_a_registered_capacity_the_geometry_is_used(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 80000.0):
            readings = [{"liquid_level_mm": 29.0, "liquid_volume_ul": 33000.0, "aspirated_ul": 250.0}]
            state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["total_volume_ul"], 80000.0)

    def _geometry_with_capacity(self, capacity):
        return child.LabwareGeometryCache(lambda _l: SimpleNamespace(labware_class="reservoir", container_grids={}) if capacity is None else None)

    def test_first_sighting_seeds_zero_remaining_with_known_capacity(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 1000.0):
            state = child._update_reagent_state(None, "Trough", "Trough", [])
        self.assertEqual(state, {"remaining_volume_ul": 0.0, "total_volume_ul": 1000.0, "percent_full": 0.0})

    def test_measured_reading_overrides_the_estimate(self):
        child._reagent_state["Trough"] = {"remaining_ul": 0.0, "total_ul": 1000.0}
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 1000.0):
            readings = [{"liquid_level_mm": 10.0, "liquid_volume_ul": 800.0, "aspirated_ul": 50.0}]
            state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["remaining_volume_ul"], 800.0)
        self.assertAlmostEqual(state["percent_full"], 0.8, places=6)

    def test_multiple_measured_channels_are_averaged(self):
        child._reagent_state["Trough"] = {"remaining_ul": None, "total_ul": 1000.0}
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 1000.0):
            readings = [
                {"liquid_level_mm": 10.0, "liquid_volume_ul": 600.0, "aspirated_ul": 25.0},
                {"liquid_level_mm": 9.0, "liquid_volume_ul": 800.0, "aspirated_ul": 25.0},
            ]
            state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["remaining_volume_ul"], 700.0)

    def test_no_measurement_decrements_by_aspirated_sum(self):
        child._reagent_state["Trough"] = {"remaining_ul": 500.0, "total_ul": 1000.0}
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        readings = [{"liquid_level_mm": 0.0, "liquid_volume_ul": 0.0, "aspirated_ul": 50.0}]
        state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["remaining_volume_ul"], 450.0)

    def test_decrement_never_goes_negative(self):
        child._reagent_state["Trough"] = {"remaining_ul": 10.0, "total_ul": 1000.0}
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        readings = [{"liquid_level_mm": 0.0, "liquid_volume_ul": 0.0, "aspirated_ul": 999.0}]
        state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(state["remaining_volume_ul"], 0.0)

    def test_no_capacity_at_all_gives_unknown_percent(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        readings = [{"liquid_level_mm": 0.0, "liquid_volume_ul": 0.0, "aspirated_ul": 50.0}]
        state = child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertIsNone(state["percent_full"])
        self.assertIsNone(state["total_volume_ul"])

    def test_threshold_warning_fires_once_and_resets_on_refill(self):
        child._reagent_thresholds["Trough"] = 0.5
        child._reagent_state["Trough"] = {"remaining_ul": 600.0, "total_ul": 1000.0}
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 1000.0):
            low_reading = [{"liquid_level_mm": 1.0, "liquid_volume_ul": 100.0, "aspirated_ul": 500.0}]
            child._update_reagent_state(None, "Trough", "Trough", low_reading)
            self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)
            child._update_reagent_state(None, "Trough", "Trough", low_reading)  # still low: no repeat
            self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)
            refill = [{"liquid_level_mm": 10.0, "liquid_volume_ul": 900.0, "aspirated_ul": 0.0}]
            child._update_reagent_state(None, "Trough", "Trough", refill)
            child._update_reagent_state(None, "Trough", "Trough", low_reading)
            self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 2)

    def test_default_threshold_applies_when_not_configured(self):
        child._reagent_state["Trough"] = {"remaining_ul": 50.0, "total_ul": 1000.0}  # 5% < default 10%
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 1000.0):
            readings = [{"liquid_level_mm": 1.0, "liquid_volume_ul": 50.0, "aspirated_ul": 0.0}]
            child._update_reagent_state(None, "Trough", "Trough", readings)
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)


class LogReservoirLabwareTests(ChildTestCase):
    def test_writes_once_per_labware(self):
        recorded = []
        client = SimpleNamespace(_run_log=SimpleNamespace(record=lambda *a: recorded.append(a)))
        child._log_reservoir_labware(client, "Trough1")
        child._log_reservoir_labware(client, "Trough1")
        child._log_reservoir_labware(client, "Trough2")
        self.assertEqual(recorded, [("Bootstrap", "Out", "reservoir_labware", {"labware": "Trough1"}), ("Bootstrap", "Out", "reservoir_labware", {"labware": "Trough2"})])

    def test_no_run_log_does_not_raise(self):
        client = SimpleNamespace(_run_log=None)
        child._log_reservoir_labware(client, "Trough1")  # must not raise
        self.assertIn("Trough1", child._reservoir_logged)


class TrackTipPickupTests(ChildTestCase):
    def test_emits_tips_event_and_checks_threshold(self):
        client = FakeTipPoolClient(FakeTipCounterParams([{"r": {"count": 96}}], [], []))
        client._DEFAULT_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
        child._tip_thresholds["P"] = 90
        result = SimpleNamespace(return_parameters={"remainingTips": 5})
        child._track_tip_pickup(client, {"tip_pool": "P", "channels": [1, 2, 3, 4, 5, 6, 7, 8]}, result)
        (tips_event,) = [e for e in self.events if e[0] == "tips"]
        self.assertEqual(tips_event[1], {"tip_pool": "P", "remaining": 5, "capacity": 96, "picked_up": 8})
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)

    def test_no_tip_pool_is_a_no_op(self):
        result = SimpleNamespace(return_parameters={"remainingTips": 5})
        child._track_tip_pickup(SimpleNamespace(), {"tip_pool": None}, result)
        self.assertEqual(self.events, [])


class Mph96PickupCountTests(unittest.TestCase):
    def test_full_head_is_96(self):
        self.assertEqual(child._mph96_pickup_count({}, full=True), 96)

    def test_partial_rows_is_12_per_row(self):
        self.assertEqual(child._mph96_pickup_count({"mode": "rows", "count": 2}, full=False), 24)

    def test_partial_columns_is_8_per_column(self):
        self.assertEqual(child._mph96_pickup_count({"mode": "cols", "count": 3}, full=False), 24)

    def test_partial_with_an_enum_mode_value(self):
        from hamilton_venus.models.enums import MphPickupMode

        self.assertEqual(child._mph96_pickup_count({"mode": MphPickupMode.ROWS, "count": 1}, full=False), 12)

    def test_missing_count_is_zero(self):
        self.assertEqual(child._mph96_pickup_count({"mode": "rows"}, full=False), 0)


class TrackTipPickupMph96Tests(ChildTestCase):
    def test_full_head_pickup_emits_tips_event(self):
        client = FakeTipPoolClient(FakeTipCounterParams([{"r": {"count": 96}}], [], []))
        child._tip_thresholds["P"] = 90
        result = SimpleNamespace(return_parameters={"remainingTips": 5})
        child._track_tip_pickup_mph96(full=True)(client, {"tip_pool": "P"}, result)
        (tips_event,) = [e for e in self.events if e[0] == "tips"]
        self.assertEqual(tips_event[1], {"tip_pool": "P", "remaining": 5, "capacity": 96, "picked_up": 96})
        self.assertEqual(len([e for e in self.events if e[0] == "consumable_warning"]), 1)

    def test_partial_pickup_uses_the_mode_aware_count(self):
        client = FakeTipPoolClient(FakeTipCounterParams([{"r": {"count": 96}}], [], []))
        result = SimpleNamespace(return_parameters={"remainingTips": 70})
        child._track_tip_pickup_mph96(full=False)(client, {"tip_pool": "P", "mode": "rows", "count": 2}, result)
        (tips_event,) = [e for e in self.events if e[0] == "tips"]
        self.assertEqual(tips_event[1]["picked_up"], 24)

    def test_no_tip_pool_is_a_no_op(self):
        child._track_tip_pickup_mph96(full=True)(SimpleNamespace(), {"tip_pool": None}, SimpleNamespace())
        self.assertEqual(self.events, [])


class TrackAspirateMph96Tests(ChildTestCase):
    def test_pooled_reservoir_is_tracked_by_bare_labware_key(self):
        child._geometry = child.LabwareGeometryCache(
            lambda _l: SimpleNamespace(labware_class="reservoir", container_grids={})
        )
        client = SimpleNamespace(_run_log=None)
        result = SimpleNamespace(return_parameters={"liquidLevel_mm": 10.0, "liquidVolume_uL": 8000.0})
        with mock.patch.object(child.LabwareGeometryCache, "max_volume_ul", lambda self, _l: 10000.0):
            child._track_aspirate_mph96(client, {"labware_id": "Trough1", "volume": 100.0}, result)
        (aspirate_event,) = [e for e in self.events if e[0] == "aspirate"]
        (reading,) = aspirate_event[1]["readings"]
        self.assertEqual(reading["labware"], "Trough1")
        self.assertEqual(reading["well"], "all")
        self.assertEqual(reading["key"], "Trough1")
        self.assertEqual(reading["aspirated_ul"], 9600.0)  # 96 channels x 100uL
        self.assertAlmostEqual(reading["percent_full"], 0.8, places=6)

    def test_non_reservoir_labware_is_not_tracked_unless_registered(self):
        child._geometry = child.LabwareGeometryCache(lambda _l: None)
        client = SimpleNamespace(_run_log=None)
        result = SimpleNamespace(return_parameters={"liquidLevel_mm": 0.0, "liquidVolume_uL": 0.0})
        child._track_aspirate_mph96(client, {"labware_id": "Plate1", "volume": 5.0}, result)
        self.assertEqual([e for e in self.events if e[0] == "aspirate"], [])

    def test_no_labware_id_is_a_no_op(self):
        child._track_aspirate_mph96(SimpleNamespace(), {"labware_id": None}, SimpleNamespace())
        self.assertEqual(self.events, [])


class DispenseMph96AndFlyTests(ChildTestCase):
    def test_dispense_mph96_emits_a_whole_head_reading(self):
        child._track_dispense_mph96(SimpleNamespace(), {"labware_id": "Plate1", "volume": 50.0}, SimpleNamespace())
        (event,) = [e for e in self.events if e[0] == "dispense"]
        (reading,) = event[1]["readings"]
        self.assertEqual(reading, {"labware": "Plate1", "well": "all", "channel": "mph96", "dispensed_ul": 4800.0})

    def test_dispense_mph96_with_a_partial_pattern(self):
        bound = {"labware_id": "Plate1", "volume": 50.0, "mph_pattern": ["A1", "B1"]}
        child._track_dispense_mph96(SimpleNamespace(), bound, SimpleNamespace())
        (event,) = [e for e in self.events if e[0] == "dispense"]
        self.assertEqual(event[1]["readings"][0]["dispensed_ul"], 100.0)

    def test_no_labware_id_is_a_no_op(self):
        child._track_dispense_mph96(SimpleNamespace(), {"labware_id": None}, SimpleNamespace())
        self.assertEqual(self.events, [])

    def test_dispense_on_the_fly_scalar_volume(self):
        bound = {"labware_name": "Plate1", "channels": [1, 2, 3, 4], "volumes": 25.0}
        child._track_dispense_on_the_fly(SimpleNamespace(), bound, SimpleNamespace())
        (event,) = [e for e in self.events if e[0] == "dispense"]
        self.assertEqual(event[1]["readings"], [{"labware": "Plate1", "well": None, "channel": "fly", "dispensed_ul": 100.0}])

    def test_dispense_on_the_fly_per_channel_volumes(self):
        bound = {"labware_name": "Plate1", "channels": [1, 2], "volumes": [10.0, 20.0]}
        child._track_dispense_on_the_fly(SimpleNamespace(), bound, SimpleNamespace())
        (event,) = [e for e in self.events if e[0] == "dispense"]
        self.assertEqual(event[1]["readings"][0]["dispensed_ul"], 30.0)

    def test_no_labware_name_is_a_no_op(self):
        child._track_dispense_on_the_fly(SimpleNamespace(), {"labware_name": None}, SimpleNamespace())
        self.assertEqual(self.events, [])


class TrackDispenseTests(ChildTestCase):
    def test_emits_dispense_readings_per_channel(self):
        client = SimpleNamespace(
            _DEFAULT_CHANNELS=[1, 2],
            _CHANNEL_PITCH_MM=None,  # keeps normalize_positions on the deck-free path for wire-format dicts
            get_labware_spec=lambda _l: None,
        )
        bound = {
            "channels": [1, 2],
            "positions": [{"labwareId": "Plate1", "wellId": "A1"}, {"labwareId": "Plate1", "wellId": "B1"}],
        }
        channel_data = [
            SimpleNamespace(channel=1, dispensed_volume=50.0),
            SimpleNamespace(channel=2, dispensed_volume=60.0),
        ]
        result = SimpleNamespace(return_parameters=SimpleNamespace(channels=channel_data))
        child._track_dispense(client, bound, result)
        (event,) = [e for e in self.events if e[0] == "dispense"]
        self.assertEqual(len(event[1]["readings"]), 2)
        self.assertEqual(event[1]["readings"][0]["dispensed_ul"], 50.0)
        self.assertEqual(event[1]["readings"][0]["labware"], "Plate1")

    def test_no_channel_data_is_a_no_op(self):
        result = SimpleNamespace(return_parameters=SimpleNamespace(channels=None))
        child._track_dispense(SimpleNamespace(), {}, result)
        self.assertEqual(self.events, [])


class LineTimelineTests(unittest.TestCase):
    """Only lines that ran long enough to matter go into the summary's line timeline -- keeping
    every executed line meant hundreds of thousands of samples for a simple loop -- and each is
    stored with its own start time so the command-to-line lookup stays exact."""

    def setUp(self):
        self.now = 1000.0
        clock = mock.patch.object(child.time, "time", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        for name, value in (("_line_timeline", []), ("_current_line", 0), ("_line_started_at", 0.0)):
            patcher = mock.patch.object(child, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _line(self, lineno, seconds):
        child._on_script_line(lineno)
        self.now += seconds

    def test_fast_lines_are_left_out_and_slow_ones_kept_with_their_start_time(self):
        for _ in range(100):
            self._line(10, 0.0001)
            self._line(11, 0.0001)
        started = self.now
        self._line(12, 0.5)  # e.g. an instrument command
        self._line(13, 0.0001)
        child._finish_line_timeline()
        self.assertEqual(child._line_timeline, [(started, 12), (started + 0.5, 13)])


_DETACH_CHILD = textwrap.dedent(
    """
    import subprocess, sys, threading
    from hamilton_venus_mcp.script_runs import child_bootstrap as child

    control = child._detach_control_channel()
    got = threading.Event()

    def reader():
        for line in control:
            print("got", line.strip(), flush=True)
            got.set()

    threading.Thread(target=reader, daemon=True).start()
    # numpy's native extension hangs in its C runtime startup, which inspects the std handles. A
    # child Python inheriting stdin does the same at startup; with the control read still pending
    # on stdin, this blocked until the next control line.
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    print("subprocess done", flush=True)
    got.wait(20)
    """
)


@unittest.skipUnless(sys.platform == "win32", "the pending-read handle lock is Windows behaviour")
class ControlChannelTests(unittest.TestCase):
    """The control pipe must not be the process's stdin: a blocking read pending on it hung any
    library call that touched the standard handles (numpy/pandas imports) until the parent sent
    the next control line -- in practice the STOP, which then stopped the run."""

    def test_library_calls_do_not_wait_on_the_control_pipe_and_control_lines_still_arrive(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", _DETACH_CHILD],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line.strip()) for line in proc.stdout], daemon=True).start()
        try:
            try:
                self.assertEqual(lines.get(timeout=20), "subprocess done")
            except queue.Empty:
                self.fail("the library call waited on the control pipe")
            proc.stdin.write("STOP\n")
            proc.stdin.flush()
            self.assertEqual(lines.get(timeout=20), "got STOP")
            proc.wait(timeout=20)
        finally:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    unittest.main()
