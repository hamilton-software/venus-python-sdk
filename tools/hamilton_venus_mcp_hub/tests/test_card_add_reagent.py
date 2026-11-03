"""card_add_reagent.py (examples/) -- a card built from several chained Instrument
calls rather than card_action.py's single NAME/KWARGS dispatch. Imports the actual
module and runs its main() with orchestrator_session.run_command monkeypatched, the same
technique test_instrument.py uses -- Instrument's own argument plumbing is already
covered there, so this only needs to lock in this card's own step order and output."""

from __future__ import annotations

import importlib
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
if str(_EXAMPLES_DIR) not in sys.path:
    # card_add_reagent.py itself is loaded via importlib below, not a real package --
    # this is unrelated to orchestrator_client, which is now a real installed package.
    sys.path.insert(0, str(_EXAMPLES_DIR))

# Import via the package, not a flat `import orchestrator_session` -- Instrument.call()
# looks up orchestrator_session.run_command as a module attribute at call time, and a flat
# import here would create a SECOND, distinct module object under sys.modules, so
# mock.patch.object below would silently patch a copy card_add_reagent never uses.
from orchestrator_client import orchestrator_session  # noqa: E402


def _reload_card():
    if "card_add_reagent" in sys.modules:
        del sys.modules["card_add_reagent"]
    return importlib.import_module("card_add_reagent")


class CardAddReagentTests(unittest.TestCase):
    def test_runs_tip_pickup_aspirate_dispense_tip_eject_in_order(self):
        calls = []

        def fake_run(url, spoke_id, name, kwargs=None, *, expected_connection_id=None, call_timeout_s=60.0, **_options):
            calls.append((name, kwargs))
            return {"command": name, "status": "success"}

        with mock.patch.object(orchestrator_session, "run_command", fake_run):
            card = _reload_card()
            out = io.StringIO()
            with redirect_stdout(out):
                code = card.main()

        self.assertEqual(code, 0)
        self.assertEqual([name for name, _ in calls], ["tip_pickup", "aspirate", "dispense", "tip_eject"])

        printed = json.loads(out.getvalue())
        self.assertEqual([r["command"] for r in printed], ["tip_pickup", "aspirate", "dispense", "tip_eject"])

    def test_aspirate_and_dispense_use_the_same_channels_and_volume(self):
        calls = []

        def fake_run(url, spoke_id, name, kwargs=None, *, expected_connection_id=None, call_timeout_s=60.0, **_options):
            calls.append((name, kwargs))
            return {"command": name, "status": "success"}

        with mock.patch.object(orchestrator_session, "run_command", fake_run):
            card = _reload_card()
            with redirect_stdout(io.StringIO()):
                card.main()

        by_name = dict(calls)
        self.assertEqual(by_name["aspirate"]["channels"], card.CHANNELS)
        self.assertEqual(by_name["dispense"]["channels"], card.CHANNELS)
        self.assertEqual(by_name["aspirate"]["volumes"], card.VOLUME)
        self.assertEqual(by_name["dispense"]["volumes"], card.VOLUME)

    def test_a_failure_partway_through_stops_the_sequence_and_exits_nonzero(self):
        calls = []

        def fake_run(url, spoke_id, name, kwargs=None, *, expected_connection_id=None, call_timeout_s=60.0, **_options):
            calls.append(name)
            if name == "aspirate":
                raise orchestrator_session.OrchestratorCallError("NO_TIP")
            return {"command": name, "status": "success"}

        with mock.patch.object(orchestrator_session, "run_command", fake_run):
            card = _reload_card()
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = card.main()

        self.assertEqual(code, 1)
        self.assertIn("card_add_reagent failed", err.getvalue())
        # tip_pickup already ran (can't be undone from here); dispense/tip_eject never did.
        self.assertEqual(calls, ["tip_pickup", "aspirate"])


if __name__ == "__main__":
    unittest.main()
