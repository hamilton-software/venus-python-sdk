"""generated_instrument_commands.py must import cleanly with no hamilton_venus/
hamilton_venus_mcp dependency at all -- since it's meant to run on a thin orchestrator
PC that has neither package installed. See orchestrator_client/
generate_instrument_commands.py (the codegen script, tested separately in
mcp_server/tests/ since generation itself needs the SDK) for how this file is produced.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from orchestrator_client import generated_instrument_commands as gen


class ImportAndSignatureTests(unittest.TestCase):
    def test_source_has_no_hamilton_venus_import_statement(self):
        # Prose mentions of "hamilton_venus" are fine (the header explains what this was
        # generated from; some SDK docstrings reference hamilton_venus.* by name) -- only
        # an actual import/from statement would break the no-SDK-dependency guarantee,
        # and this test module having actually imported the generated file above with
        # neither hamilton_venus nor hamilton_venus_mcp installed is the real proof of that.
        source = Path(gen.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("import hamilton_venus", "from hamilton_venus")),
                msg=f"unexpected SDK import: {line!r}",
            )

    def test_generated_commands_class_exists(self):
        self.assertTrue(hasattr(gen, "_GeneratedCommands"))

    def test_add_carrier_has_the_expected_keyword_only_signature(self):
        sig = inspect.signature(gen._GeneratedCommands.add_carrier)
        params = sig.parameters
        self.assertEqual(list(params)[0], "self")
        for name in ("labware_definition", "left_track", "labware_id"):
            self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(params["labware_definition"].annotation, "str")
        self.assertEqual(params["labware_id"].default, None)

    def test_zero_parameter_command_takes_only_self(self):
        sig = inspect.signature(gen._GeneratedCommands.deck_get_saved)
        self.assertEqual(list(sig.parameters), ["self"])


if __name__ == "__main__":
    unittest.main()
