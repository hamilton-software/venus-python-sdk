"""run() waits through a spoke-side hold (stop / hold_on_error) via await_command_step, and
Instrument.recovery() marks calls as recovery commands. _dispatch is patched, so these test
only the client's own loop and argument plumbing."""

from __future__ import annotations

import unittest
from unittest import mock

from orchestrator_client import Instrument, OrchestratorCallError, orchestrator_session


class RunHoldTests(unittest.TestCase):
    def test_run_waits_through_held_until_the_final_result(self):
        replies = [
            {"command": "aspirate", "status": "held", "step": 4, "hold": {"reason": "error"}},
            {"command": "aspirate", "status": "held", "step": 4},
            {"command": "aspirate", "status": "success", "step": 4, "result": "ok"},
        ]
        seen = []
        with mock.patch.object(orchestrator_session, "_dispatch", side_effect=replies) as fake:
            result = orchestrator_session.run("http://spoke", None, "aspirate", on_held=seen.append, volumes=5)

        self.assertEqual(result["result"], "ok")
        self.assertEqual(len(seen), 1)
        tools = [c.args[2] for c in fake.call_args_list]
        self.assertEqual(tools, ["call_sdk_command", "await_command_step", "await_command_step"])
        self.assertEqual(fake.call_args_list[1].args[3]["step"], 4)
        self.assertNotIn("recovery", fake.call_args_list[0].args[3])

    def test_max_hold_s_gives_up_waiting(self):
        held = {"command": "aspirate", "status": "held", "step": 1}
        with mock.patch.object(orchestrator_session, "_dispatch", return_value=held):
            with self.assertRaises(OrchestratorCallError):
                orchestrator_session.run("http://spoke", None, "aspirate", max_hold_s=0)

    def test_run_passes_an_sdk_argument_called_name(self):
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"status": "success"}) as fake:
            orchestrator_session.run("http://spoke", None, "get_liquid_class", name="HighVolume")
        self.assertEqual(fake.call_args.args[3]["name"], "get_liquid_class")
        self.assertEqual(fake.call_args.args[3]["kwargs"], {"name": "HighVolume"})

    def test_recovery_flag_is_sent(self):
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"status": "success"}) as fake:
            orchestrator_session.recovery_call("http://spoke", None, "tip_eject", channels=[1])
        self.assertTrue(fake.call_args.args[3]["recovery"])
        self.assertEqual(fake.call_args.args[3]["kwargs"], {"channels": [1]})

    def test_recovery_handle_uses_the_typed_sdk_methods(self):
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            inst = Instrument("http://spoke", "FM STARlet", connection_id="conn-1", call_timeout_s=30.0)
            recover = inst.recovery()
            recover.tip_eject(channels=[1, 2], eject_mode="waste")
            recover.front_cover_unlock()
            inst.aspirate(positions="Trough@all", volumes=50.0, liquid_class="lc")

        eject, unlock, aspirate = fake_run.call_args_list
        self.assertEqual(eject.args[:3], ("http://spoke", "FM STARlet", "tip_eject"))
        self.assertEqual((eject.args[3]["channels"], eject.args[3]["eject_mode"]), ([1, 2], "waste"))
        self.assertEqual((eject.kwargs["recovery"], eject.kwargs["expected_connection_id"], eject.kwargs["call_timeout_s"]), (True, "conn-1", 30.0))
        self.assertTrue(unlock.kwargs["recovery"])
        self.assertFalse(aspirate.kwargs["recovery"])  # the instrument itself is unchanged

    def test_recovery_block_still_works(self):
        with mock.patch.object(orchestrator_session, "run_command", return_value={"ok": True}) as fake_run:
            inst = Instrument("http://spoke", None)
            with inst.recovery() as recover:
                inst.tip_eject(channels=[1])
                recover.tip_pickup(channels=[1], tip_pool="tips")
            inst.call("aspirate")

        flags = [c.kwargs["recovery"] for c in fake_run.call_args_list]
        self.assertEqual(flags, [True, True, False])

    def test_control_functions_call_the_right_tools(self):
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={}) as fake:
            orchestrator_session.stop("u")
            orchestrator_session.resume("u")
            orchestrator_session.resume_from("u", None, 3)
            orchestrator_session.release_hold("u")
        tools = [c.args[2] for c in fake.call_args_list]
        self.assertEqual(tools, ["stop_commands", "resume_commands", "resume_commands_from", "release_command_hold"])
        self.assertEqual(fake.call_args_list[2].args[3], {"step": 3})


if __name__ == "__main__":
    unittest.main()
