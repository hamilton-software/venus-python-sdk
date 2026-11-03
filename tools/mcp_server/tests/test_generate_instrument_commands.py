"""Tests for orchestrator_client/generate_instrument_commands.py -- the codegen script
that turns hamilton_venus_mcp.catalog.CATALOG_BY_INSTRUMENT into
generated_instrument_commands.py's typed _GeneratedCommands mixin (see instrument.py).

Lives here, not under orchestrator_client/tests/, because the generator itself needs
hamilton-venus-sdk + hamilton-venus-mcp to run (reads the catalog directly) -- this is
the one of the packages that already depends on both. Its generated OUTPUT has no such
dependency; orchestrator_client/tests/test_generated_instrument_commands.py checks that
half separately, importing the committed, already-installed package.
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

_GENERATOR_PATH = (
    Path(__file__).resolve().parents[2] / "orchestrator_client" / "generate_instrument_commands.py"
)
_OUTPUT_PATH = _GENERATOR_PATH.parent / "orchestrator_client" / "generated_instrument_commands.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_instrument_commands", _GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_generator()
        cls.rendered = cls.module.render()

    def test_add_carrier_renders_a_keyword_only_signature_matching_the_sdk(self):
        self.assertIn(
            'def add_carrier(self, *, labware_definition: str, left_track: int, '
            "labware_id: str | None = None) -> Any:",
            self.rendered,
        )
        self.assertIn(
            'return self.call("add_carrier", labware_definition=labware_definition, '
            "left_track=left_track, labware_id=labware_id)",
            self.rendered,
        )

    def test_zero_parameter_command_has_no_bare_star(self):
        # def foo(self, *) is a SyntaxError -- the bare `*` must be omitted entirely
        # when a command takes no parameters (66 real commands do).
        self.assertIn("def deck_get_saved(self) -> Any:", self.rendered)
        self.assertNotIn("def deck_get_saved(self, *)", self.rendered)

    def test_enum_parameter_renders_as_a_literal_of_its_wire_values(self):
        self.assertIn(
            "eject_mode: Literal['waste', 'return', 'positions', 'tipPool'] = 'waste'",
            self.rendered,
        )

    def test_required_keyword_only_param_may_follow_an_optional_one(self):
        # aspirate's real signature: optional `channels` before required `volumes`/
        # `liquid_class`, all keyword-only -- legal Python, unlike positional params.
        match = re.search(r"def aspirate\(self, \*, (.*?)\) -> Any:", self.rendered)
        self.assertIsNotNone(match)
        self.assertIn("channels: list[int] | None = None", match.group(1))
        self.assertIn("volumes: float | list[float]", match.group(1))

    def test_unresolved_string_annotation_falls_back_to_any_with_a_docstring_note(self):
        match = re.search(r"def add_reagent\(self, \*, (.*?)\) -> Any:", self.rendered)
        self.assertIsNotNone(match)
        self.assertIn("aspirate_settings: Any = None", match.group(1))
        self.assertIn(
            "aspirate_settings: real type is 'AspirateSettings | None'",
            self.rendered,
        )

    def test_star_only_and_vantage_only_commands_are_noted_in_their_docstring(self):
        star_only = re.search(r'def core_5ml_transport\(.*?-> Any:\n        """(.*?)"""', self.rendered, re.DOTALL)
        self.assertIsNotNone(star_only)
        self.assertIn("STAR only", star_only.group(1))

        vantage_only = re.search(r'def load_tray_lower\(self\) -> Any:\n        """(.*?)"""', self.rendered, re.DOTALL)
        self.assertIsNotNone(vantage_only)
        self.assertIn("Vantage only", vantage_only.group(1))

    def test_rendered_output_has_no_hamilton_venus_import_statement(self):
        # Prose mentions of "hamilton_venus" are fine (the header explains what this was
        # generated from; some SDK docstrings reference hamilton_venus.* by name) -- only
        # an actual import/from statement would break the no-SDK-dependency guarantee.
        for line in self.rendered.splitlines():
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("import hamilton_venus", "from hamilton_venus")),
                msg=f"unexpected SDK import: {line!r}",
            )

    def test_render_is_idempotent(self):
        self.assertEqual(self.rendered, self.module.render())


class FreshnessTests(unittest.TestCase):
    """The committed generated_instrument_commands.py must match what the generator
    produces right now -- catches drift if the SDK's commands change without
    re-running the generator and committing the diff."""

    def test_committed_file_matches_the_catalog_right_now(self):
        module = _load_generator()
        fresh = module.render().replace("\r\n", "\n")
        committed = _OUTPUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(
            fresh,
            committed,
            msg="generated_instrument_commands.py is stale -- re-run "
            "generate_instrument_commands.py and commit the diff",
        )


if __name__ == "__main__":
    unittest.main()
