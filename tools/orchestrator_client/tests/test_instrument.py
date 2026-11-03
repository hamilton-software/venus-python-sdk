"""Instrument wraps orchestrator_session.run()/start()/status()/finish() in a typed,
object-oriented interface (see orchestrator_client/instrument.py's module docstring for
the full rationale) -- these tests monkeypatch those four functions directly rather than
standing up a fake MCP server, since Instrument's own job is just argument plumbing on
top of functions that are already exercised directly elsewhere."""

from __future__ import annotations

import unittest
from unittest import mock

# Import via the package, not a flat `import orchestrator_session` -- Instrument.call()
# looks up orchestrator_session.run as a module attribute at call time (`from . import
# orchestrator_session` inside instrument.py), and a flat import here would create a
# SECOND, distinct module object under sys.modules, so mock.patch.object below would
# silently patch a copy Instrument never looks at.
from orchestrator_client import STAR, VANTAGE, Instrument, InstrumentType, orchestrator_session


class InstrumentTests(unittest.TestCase):
    def test_a_generated_method_calls_run_command_with_the_exact_right_name_and_kwargs(self):
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            inst = Instrument("http://spoke", None, connection_id="conn-1")
            result = inst.add_carrier(labware_definition="tip_car_480bc", left_track=1, labware_id="test")

        self.assertEqual(result, {"ok": True})
        fake_run.assert_called_once_with(
            "http://spoke",
            None,
            "add_carrier",
            {"labware_definition": "tip_car_480bc", "left_track": 1, "labware_id": "test"},
            expected_connection_id="conn-1",
            call_timeout_s=60.0,
            recovery=False,
            on_held=None,
            max_hold_s=None,
        )

    def test_call_escape_hatch_dispatches_an_arbitrary_name(self):
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            inst = Instrument("http://spoke", "FM STARlet")
            inst.call("some_not_yet_generated_command", foo=1)

        self.assertEqual(fake_run.call_args.args, ("http://spoke", "FM STARlet", "some_not_yet_generated_command", {"foo": 1}))

    def test_an_sdk_argument_called_name_does_not_collide(self):
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            Instrument("http://spoke").get_liquid_class(name="HighVolume_Water_DispenseJet_Empty")
        self.assertEqual(fake_run.call_args.args[2:], ("get_liquid_class", {"name": "HighVolume_Water_DispenseJet_Empty"}))

    def test_on_held_and_max_hold_s_reach_every_command(self):
        notify = lambda held: None  # noqa: E731
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            Instrument("http://spoke", on_held=notify, max_hold_s=30).tip_eject(channels=[1])
        self.assertIs(fake_run.call_args.kwargs["on_held"], notify)
        self.assertEqual(fake_run.call_args.kwargs["max_hold_s"], 30)

    def test_start_updates_connection_id_from_the_result(self):
        with mock.patch.object(
            orchestrator_session, "start", return_value={"connection_id": "conn-live", "connected": True}
        ):
            inst = Instrument("http://spoke", None)
            result = inst.start(simulate=True)

        self.assertEqual(inst.connection_id, "conn-live")
        self.assertEqual(result["connection_id"], "conn-live")

        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            inst.aspirate(positions="Plate1@A1", volumes=100.0, liquid_class="StandardVolume_Water_DispenseJet_Empty")

        self.assertEqual(fake_run.call_args.kwargs["expected_connection_id"], "conn-live")

    def test_start_passes_every_option_with_its_default(self):
        with mock.patch.object(orchestrator_session, "start", return_value={"connection_id": "c"}) as fake_start:
            Instrument("http://spoke", None).start(
                instrument_type=InstrumentType.VANTAGE, hold_on_error=True, error_profile="cancel_all",
                session_name="Plate prep",
            )

        fake_start.assert_called_once_with(
            "http://spoke",
            None,
            simulate=True,
            deck_name=None,
            load_previous_deck=False,
            instrument_type=InstrumentType.VANTAGE,
            initialize=True,
            connect_timeout_s=200.0,
            hold_on_error=True,
            error_profile="cancel_all",
            session_name="Plate prep",
        )

    def test_session_name_is_only_sent_when_given(self):
        sent = []

        def fake_dispatch(url, spoke_id, tool, arguments, timeout_s):
            sent.append((tool, arguments))
            return {"connection_id": "c"}

        with mock.patch.object(orchestrator_session, "_dispatch", side_effect=fake_dispatch):
            orchestrator_session.start("http://spoke")
            orchestrator_session.start("http://spoke", session_name="Plate prep")
        starts = [arguments for tool, arguments in sent if tool == "start_session"]
        self.assertNotIn("session_name", starts[0])  # an older spoke without it still works
        self.assertEqual(starts[1]["session_name"], "Plate prep")

    def test_instrument_type_constants_are_the_wire_values(self):
        self.assertEqual((InstrumentType.STAR, InstrumentType.VANTAGE), ("STAR", "Vantage"))
        self.assertIs(STAR, InstrumentType.STAR)  # the older names are aliases
        self.assertIs(VANTAGE, InstrumentType.VANTAGE)
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"connection_id": "c"}) as fake:
            orchestrator_session.start("http://spoke", instrument_type=InstrumentType.VANTAGE, initialize=False)
        sent = fake.call_args_list[0].args[3]["instrument_type"]
        self.assertEqual((sent, type(sent)), ("Vantage", str))  # plain JSON string on the wire

    def test_start_leaves_instrument_type_to_the_spoke_unless_given(self):
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"connection_id": "c"}) as fake:
            orchestrator_session.start("http://spoke", initialize=False)
        self.assertNotIn("instrument_type", fake.call_args_list[0].args[3])

    def test_start_rejects_an_unknown_option(self):
        with self.assertRaises(TypeError):
            Instrument("http://spoke", None).start(simulated=True)  # typo caught at the call

    def test_finish_passes_the_current_connection_id(self):
        with mock.patch.object(orchestrator_session, "finish") as fake_finish:
            inst = Instrument("http://spoke", None, connection_id="conn-2")
            inst.finish()

        fake_finish.assert_called_once_with(
            "http://spoke", None, expected_connection_id="conn-2", connect_timeout_s=200.0
        )

    def test_status_delegates_to_orchestrator_session_status(self):
        with mock.patch.object(orchestrator_session, "status", return_value={"session_active": True}) as fake_status:
            inst = Instrument("http://spoke", "FM STARlet")
            result = inst.status()

        fake_status.assert_called_once_with("http://spoke", "FM STARlet", call_timeout_s=60.0)
        self.assertEqual(result, {"session_active": True})


if __name__ == "__main__":
    unittest.main()
