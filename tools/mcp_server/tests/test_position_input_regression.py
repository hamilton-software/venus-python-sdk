"""Regression tests for the PositionInput/Position "not fully defined" bug reported
against the networkTest spoke (http://192.168.86.77:8001/mcp), 2026-09-17.

Symptom: every SDK command with a `positions`-style parameter (aspirate, dispense,
tip_pickup, detect_liquid_level, add_reagent, pool_samples, replicate_samples, ...)
failed immediately on call_sdk_command with:

    TypeAdapter[PositionInput] is not fully defined; you should define `PositionInput`
    and all referenced types, then call `.rebuild()` on the instance.

...regardless of the value passed (including an empty list), before any of the
caller's actual data was inspected.

Two independent root causes, both forward-reference bugs, confirmed by direct source
inspection rather than guessed:

1. hamilton_venus.models.position.PositionInput was defined (as `Union[..., "Position",
   list["Position"]]`) *before* the real `Position` class existed in the file, using a
   quoted forward reference. Nothing in that module ever resolved it afterward (no
   `.model_rebuild()`/`get_type_hints()` call), so pydantic's TypeAdapter machinery
   permanently could not complete this Union's schema. There was no real circularity
   forcing this ordering -- Position doesn't depend on PositionInput -- so the fix
   moves PositionInput's definition to after Position and uses the real class, not a
   string.

2. AddReagentCommand/PoolSamplesCommand/ReplicateSamplesCommand/SerialDilutionCommand's
   own compound-command mixins imported `Position` only under `if TYPE_CHECKING:`, yet
   used it as a real parameter type (e.g. `reagent_source: str | list[str] | Position |
   list[Position]`). Since `from __future__ import annotations` stores annotations as
   plain strings, this "worked" for static type checkers but left `Position` absent
   from these modules' runtime globals entirely -- hamilton_venus_mcp.catalog's
   reflection-based get_type_hints() call for these methods therefore could not resolve
   it, silently falling back to the raw annotation string, which pydantic's TypeAdapter
   could only partially (lazily) resolve and never actually complete. The fix promotes
   `Position` to a real top-level import in each of these four mixins.
"""

from __future__ import annotations

import unittest

from hamilton_venus.models import InstrumentType
from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT
from hamilton_venus_mcp.coercion import coerce_kwargs


class PositionInputTypeAdapterRegressionTests(unittest.TestCase):
    """The exact bug reported: every positions-bearing command failing regardless of
    the value passed, including an empty list."""

    def _spec(self, name: str):
        return CATALOG_BY_INSTRUMENT[InstrumentType.STAR][name]

    def test_aspirate_accepts_an_empty_positions_list(self):
        spec = self._spec("aspirate")
        kwargs = coerce_kwargs(
            spec,
            {"liquid_class": "StandardVolume_Water_DispenseJet_Empty", "positions": [], "volumes": []},
        )
        self.assertEqual(kwargs["positions"], [])

    def test_aspirate_accepts_a_selector_string(self):
        spec = self._spec("aspirate")
        kwargs = coerce_kwargs(
            spec,
            {
                "liquid_class": "StandardVolume_Water_DispenseJet_Empty",
                "positions": "Plate1@A1",
                "volumes": 100.0,
            },
        )
        self.assertEqual(kwargs["positions"], "Plate1@A1")

    def test_tip_pickup_accepts_a_selector_string(self):
        spec = self._spec("tip_pickup")
        kwargs = coerce_kwargs(spec, {"positions": "Plate1@A1"})
        self.assertEqual(kwargs["positions"], "Plate1@A1")

    def test_detect_liquid_level_accepts_a_selector_string(self):
        spec = self._spec("detect_liquid_level")
        kwargs = coerce_kwargs(spec, {"positions": "Plate1@A1"})
        self.assertEqual(kwargs["positions"], "Plate1@A1")

    def test_aspirate_accepts_an_explicit_position_dict(self):
        spec = self._spec("aspirate")
        kwargs = coerce_kwargs(
            spec,
            {
                "liquid_class": "StandardVolume_Water_DispenseJet_Empty",
                "positions": [{"labwareId": "Plate1", "wellId": "A1"}],
                "volumes": 100.0,
            },
        )
        self.assertEqual(kwargs["positions"], [{"labwareId": "Plate1", "wellId": "A1"}])


class CompoundCommandPositionUnionRegressionTests(unittest.TestCase):
    """add_reagent/pool_samples/replicate_samples/serial_dilution's own directly-typed
    `str | list[str] | Position | list[Position]` unions -- a second, independent
    instance of the same failure mode via TYPE_CHECKING-only Position imports."""

    def _spec(self, name: str):
        return CATALOG_BY_INSTRUMENT[InstrumentType.STAR][name]

    def test_add_reagent_coerces_selector_strings_for_source_and_dest(self):
        spec = self._spec("add_reagent")
        kwargs = coerce_kwargs(
            spec,
            {
                "reagent_source": "Trough1@A1",
                "dest_plate": "Plate1@A1",
                "volume": 100.0,
                "liquid_class": "StandardVolume_Water_DispenseJet_Empty",
                "tip_pool": "tiprack_1",
            },
        )
        self.assertEqual(kwargs["reagent_source"], "Trough1@A1")
        self.assertEqual(kwargs["dest_plate"], "Plate1@A1")

    def test_pool_samples_coerces_selector_strings(self):
        spec = self._spec("pool_samples")
        kwargs = coerce_kwargs(
            spec,
            {
                "source_plate": "Plate1@A1",
                "dest_plate": "Plate2@A1",
                "pool_size": 2,
                "volume_per_source": 50.0,
                "liquid_class": "StandardVolume_Water_DispenseJet_Empty",
                "tip_pool": "tiprack_1",
            },
        )
        self.assertEqual(kwargs["source_plate"], "Plate1@A1")

    def test_replicate_samples_coerces_selector_strings(self):
        spec = self._spec("replicate_samples")
        kwargs = coerce_kwargs(
            spec,
            {
                "source_plate": "Plate1@A1",
                "dest_plate": "Plate2@A1",
                "replicates_per_source": 2,
                "volume_per_replicate": 50.0,
                "liquid_class": "StandardVolume_Water_DispenseJet_Empty",
                "tip_pool": "tiprack_1",
            },
        )
        self.assertEqual(kwargs["dest_plate"], "Plate2@A1")

    def test_serial_dilution_by_volume_coerces_a_selector_string(self):
        spec = self._spec("serial_dilution_by_volume")
        param_names = {p.name for p in spec.params}
        self.assertIn("plate_id", param_names)
        # Full coercion needs many required params unrelated to this bug; confirming
        # the plate_id parameter's own TypeAdapter builds and resolves is the point.
        plate_id_param = next(p for p in spec.params if p.name == "plate_id")
        self.assertIsNotNone(plate_id_param.type_adapter)
        self.assertEqual(plate_id_param.type_adapter.validate_python("Plate1@A1"), "Plate1@A1")


class DescribeSdkCommandSchemaRegressionTests(unittest.TestCase):
    """describe_sdk_command's JSON schema for a positions-bearing param degraded to a
    bare `{"type": "PositionInput"}` fallback when TypeAdapter construction failed
    (catalog.py's _json_schema_for swallows the exception) -- giving an agent no
    structural information at all about what a Position entry looks like. Confirms
    the real, structured schema (including the Position object shape) now comes
    through instead.
    """

    def test_aspirate_positions_schema_includes_the_position_object_shape(self):
        from hamilton_venus_mcp.catalog import describe_command

        spec = CATALOG_BY_INSTRUMENT[InstrumentType.STAR]["aspirate"]
        desc = describe_command(spec)
        positions_param = next(p for p in desc["params"] if p["name"] == "positions")
        schema = positions_param["schema"]
        self.assertIn("$defs", schema, msg=f"schema degraded to {schema!r}")
        self.assertIn("Position", schema["$defs"])
        self.assertEqual(
            set(schema["$defs"]["Position"]["properties"]),
            {"labwareId", "wellId"},
        )


if __name__ == "__main__":
    unittest.main()
