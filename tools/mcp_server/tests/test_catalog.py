"""Regression tests for hamilton_venus_mcp.catalog's reflection-based schema building.

Covers a real bug found in the field: EjectMode "return" (and every other eject
mode) errored out on call_sdk_command("tip_eject", ...) regardless of value.

Root cause -- confirmed by direct source inspection, not guessed -- was that
_build_catalog() called get_type_hints() once per method and discarded *every*
resolved type for that method on any single exception. tip_eject's own
`positions: PositionInput` parameter carries a forward reference ("Position")
that only resolves inside models/position.py's own namespace, not the importing
module's, so get_type_hints() raised NameError for the whole method and every
other parameter -- including eject_mode -- silently degraded from its real
EjectMode annotation to the bare unresolved string "EjectMode". That broke both
its JSON schema and its TypeAdapter-based coercion in coerce_kwargs, regardless
of which EjectMode value was actually supplied.

A second, independent bug in describe_command() put raw Enum defaults (e.g.
EjectMode.WASTE) directly into the returned dict, which isn't JSON-serializable
-- so describe_sdk_command itself would have crashed before an agent could ever
see which eject modes were valid.

Also covers CATALOG_BY_INSTRUMENT: a separate catalog is built per instrument type
(StarClient vs VantageClient) since Vantage lacks 5mL channels, transport, and
compound commands -- these tests confirm that split is actually enforced, and that
the enum-schema sweep above holds for the Vantage catalog too, not just STAR's.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import unittest
from enum import Enum
from unittest import mock

from pydantic import TypeAdapter

from hamilton_venus.models import InstrumentType
from hamilton_venus_mcp.catalog import CATALOG, CATALOG_BY_INSTRUMENT, describe_command
from hamilton_venus_mcp.coercion import coerce_kwargs


class EjectModeRegressionTests(unittest.TestCase):
    """The exact bug reported: eject_mode="return" (and every other value) failing."""

    def test_tip_eject_variants_expose_the_full_eject_mode_enum(self):
        for name in ("tip_eject", "tip_eject_5ml", "tip_eject_mph96"):
            spec = CATALOG[name]
            desc = describe_command(spec)
            param = next(p for p in desc["params"] if p["name"] == "eject_mode")
            self.assertEqual(
                sorted(param["schema"]["enum"]),
                sorted(["waste", "return", "positions", "tipPool"]),
                msg=f"{name}: eject_mode schema degraded to {param['schema']!r}",
            )

    def test_every_eject_mode_value_coerces_to_the_matching_enum_member(self):
        from hamilton_venus.models.enums import EjectMode

        for name in ("tip_eject", "tip_eject_5ml"):
            spec = CATALOG[name]
            for value, expected in [
                ("waste", EjectMode.WASTE),
                ("return", EjectMode.RETURN),
                ("positions", EjectMode.POSITIONS),
                ("tipPool", EjectMode.TIP_POOL),
            ]:
                kwargs = coerce_kwargs(spec, {"channels": [1], "eject_mode": value})
                self.assertIs(kwargs["eject_mode"], expected, msg=f"{name}: eject_mode={value!r}")

    def test_describe_command_is_json_serializable_for_every_catalog_command(self):
        for name, spec in CATALOG.items():
            with self.subTest(command=name):
                json.dumps(describe_command(spec))  # raises TypeError if a raw Enum default leaks through


class TypeAdapterCachingTests(unittest.TestCase):
    """coerce_kwargs should reuse the TypeAdapter catalog.py's _build_catalog already
    built once at import time (ParamInfo.type_adapter) instead of constructing a fresh one
    on every call -- these confirm the cache is actually wired up and that coercion
    behavior itself is unchanged (same values, same errors) either way.
    """

    def test_coerce_kwargs_reuses_the_cached_type_adapter(self):
        spec = CATALOG["tip_eject"]
        param = next(p for p in spec.params if p.name == "eject_mode")
        self.assertIsNotNone(param.type_adapter, "eject_mode should have a pre-built TypeAdapter")

        with mock.patch("hamilton_venus_mcp.coercion.TypeAdapter") as mock_type_adapter:
            kwargs = coerce_kwargs(spec, {"channels": [1], "eject_mode": "waste"})

        mock_type_adapter.assert_not_called()
        from hamilton_venus.models.enums import EjectMode

        self.assertIs(kwargs["eject_mode"], EjectMode.WASTE)

    def test_falls_back_to_constructing_an_adapter_when_none_was_cached(self):
        spec = CATALOG["tip_eject"]
        param = next(p for p in spec.params if p.name == "eject_mode")
        uncached = dataclasses.replace(param, type_adapter=None)
        spec_without_cache = dataclasses.replace(spec, params=[uncached, *(p for p in spec.params if p is not param)])

        kwargs = coerce_kwargs(spec_without_cache, {"channels": [1], "eject_mode": "waste"})

        from hamilton_venus.models.enums import EjectMode

        self.assertIs(kwargs["eject_mode"], EjectMode.WASTE)

    def test_every_catalog_parameter_with_no_annotation_has_no_cached_adapter(self):
        for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
            for name, spec in catalog.items():
                for param in spec.params:
                    if param.annotation is inspect.Signature.empty:
                        with self.subTest(instrument=instrument_type, command=name, param=param.name):
                            self.assertIsNone(param.type_adapter)


class EnumCatalogWideRegressionTests(unittest.TestCase):
    """The broader sweep: every enum-typed SDK parameter, not just eject_mode --
    checked against both the STAR and Vantage catalogs."""

    @classmethod
    def setUpClass(cls):
        enums_mod = importlib.import_module("hamilton_venus.models.enums")
        cls.known_enums = {
            n: getattr(enums_mod, n)
            for n in dir(enums_mod)
            if isinstance(getattr(enums_mod, n), type) and issubclass(getattr(enums_mod, n), Enum)
        }

    def test_no_enum_parameter_schema_is_silently_degraded(self):
        for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
            for name, spec in catalog.items():
                desc = describe_command(spec)
                for p_desc in desc["params"]:
                    base_name = p_desc["type"].split(" ")[0].split("|")[0].strip()
                    if base_name not in self.known_enums:
                        continue
                    with self.subTest(instrument=instrument_type.value, command=name, param=p_desc["name"]):
                        self.assertIn(
                            "enum",
                            p_desc["schema"],
                            msg=f"{name}.{p_desc['name']}: schema degraded to {p_desc['schema']!r}",
                        )

    def test_every_enum_parameter_accepts_every_one_of_its_own_member_values(self):
        for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
            for name, spec in catalog.items():
                for p_spec in spec.params:
                    base_name = (
                        getattr(p_spec.annotation, "__name__", str(p_spec.annotation)).split(" ")[0].split("|")[0].strip()
                    )
                    enum_cls = self.known_enums.get(base_name)
                    if enum_cls is None:
                        continue
                    for member in enum_cls:
                        with self.subTest(
                            instrument=instrument_type.value, command=name, param=p_spec.name, value=member.value
                        ):
                            result = TypeAdapter(p_spec.annotation).validate_python(member.value)
                            self.assertEqual(result, member)


class DualInstrumentCatalogTests(unittest.TestCase):
    """CATALOG_BY_INSTRUMENT actually enforces the STAR/Vantage command split."""

    def test_catalog_alias_points_at_the_star_catalog(self):
        self.assertIs(CATALOG, CATALOG_BY_INSTRUMENT[InstrumentType.STAR])

    def test_vantage_catalog_excludes_core_5ml_transport_commands(self):
        # The only methods VantageClient genuinely lacks: CO-RE 5mL transport
        # (no 5mL transport tool on Vantage hardware).
        vantage_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.Vantage])
        for excluded in (
            "core_5ml_transport",
            "core_5ml_transport_is_holding_labware",
            "core_5ml_transport_tracking_clear",
            "core_5ml_eject_grips",
            "core_5ml_transport_return_plate",
            "core_5ml_transport_to_waste",
            "core_5ml_present_and_scan",
            "core_5ml_hold_lid",
        ):
            with self.subTest(command=excluded):
                self.assertNotIn(excluded, vantage_names)

    def test_vantage_catalog_excludes_present_and_scan(self):
        vantage_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.Vantage])
        star_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.STAR])
        for name in ("core_present_and_scan", "iswap_present_and_scan"):
            with self.subTest(command=name):
                self.assertNotIn(name, vantage_names)
                self.assertIn(name, star_names)

    def test_star_catalog_excludes_vantage_only_commands(self):
        star_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.STAR])
        for excluded in ("load_tray_lower", "load_tray_raise", "status_light_set_interior_light"):
            with self.subTest(command=excluded):
                self.assertNotIn(excluded, star_names)

    def test_vantage_catalog_includes_5ml_channel_transport_and_compound_commands(self):
        # These used to be StarClient-exclusive; the SDK build that added
        # LoadTrayCommandsMixin/interior-light support also composed
        # Channels5mLCommandsMixin/TransportCommandsMixin/CompoundCommandsMixin
        # into VantageClient, so they're shared now.
        vantage_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.Vantage])
        for included in (
            "aspirate_5ml",
            "dispense_5ml",
            "tip_pickup_5ml",
            "tip_eject_5ml",
            "iswap_get_labware",
            "iswap_put_labware",
            "add_reagent",
            "copy_plate",
            "hit_picking",
            "pool_samples",
            "replicate_samples",
            "serial_dilution_by_volume",
            "serial_dilution_by_dilution_factor",
        ):
            with self.subTest(command=included):
                self.assertIn(included, vantage_names)

    def test_vantage_catalog_includes_shared_channel_and_liquid_class_commands(self):
        vantage_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.Vantage])
        for included in ("aspirate", "dispense", "tip_pickup", "tip_eject", "get_liquid_classes"):
            with self.subTest(command=included):
                self.assertIn(included, vantage_names)

    def test_vantage_catalog_includes_its_own_exclusive_commands(self):
        vantage_names = set(CATALOG_BY_INSTRUMENT[InstrumentType.Vantage])
        for included in ("load_tray_lower", "load_tray_raise", "status_light_set_interior_light"):
            with self.subTest(command=included):
                self.assertIn(included, vantage_names)


class TaughtLocationCatalogTests(unittest.TestCase):
    """The TaughtLocationCommandsMixin methods (local file I/O, no VENUS round-trip)
    are reflection-discovered like every other mixin -- lock that in so a future
    _EXCLUDED_METHODS change or a rename can't silently drop them from the MCP."""

    _COMMANDS = (
        "register_taught_offset",
        "register_taught_position",
        "get_taught_locations",
        "get_taught_offset",
        "get_taught_positions",
        "get_taught_position",
        "resolve_taught_location",
        "remove_taught_offset",
        "remove_taught_position",
        "clear_taught_locations",
    )

    def test_present_in_both_catalogs_under_the_taughtlocation_category(self):
        for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
            for name in self._COMMANDS:
                with self.subTest(instrument=instrument_type.value, command=name):
                    self.assertIn(name, catalog)
                    self.assertEqual(catalog[name].category, "TaughtLocation")

    def test_register_taught_offset_param_schema(self):
        spec = CATALOG["register_taught_offset"]
        required = {p.name for p in spec.params if p.required}
        optional = {p.name for p in spec.params if not p.required}
        self.assertEqual(required, {"carrier", "site", "dx", "dy", "dz"})
        self.assertEqual(optional, {"d_angle", "note"})

    def test_register_taught_position_coerces_plain_json(self):
        spec = CATALOG["register_taught_position"]
        kwargs = coerce_kwargs(
            spec,
            {"labware": "Plate1", "carrier": "CarA", "site": 1, "x": 1.0, "y": 2.0, "z": 3.0},
        )
        self.assertEqual(kwargs["site"], 1)  # str | int -> left as int, SDK stringifies
        self.assertEqual(kwargs["labware"], "Plate1")


class TeachingCatalogTests(unittest.TestCase):
    """The TeachingCommandsMixin methods (teaching.1mL.* plus teach_well) reach both
    MCP catalogs under the Teaching category."""

    _COMMANDS = (
        "teaching_set_channel",
        "teaching_get_channel",
        "teaching_pickup_needle",
        "teaching_eject_needle",
        "teaching_is_needle_picked_up",
        "teaching_get_labware_dimensions",
        "teaching_move_channel",
        "teaching_measure_z",
        "teaching_measure_wall",
        "teach_well",
    )

    def test_present_in_both_catalogs_under_the_teaching_category(self):
        for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
            for name in self._COMMANDS:
                with self.subTest(instrument=instrument_type.value, command=name):
                    self.assertIn(name, catalog)
                    self.assertEqual(catalog[name].category, "Teaching")

    def test_measure_wall_coerces_direction_and_teach_well_widths(self):
        kwargs = coerce_kwargs(
            CATALOG["teaching_measure_wall"],
            {"direction": 2, "safe_height": 155.0, "min_search_z": 147.0, "well_width": 6.9},
        )
        self.assertEqual(kwargs["direction"], 2)
        kwargs = coerce_kwargs(CATALOG["teach_well"], {"labware_name": "Plate_1", "well_width": [8.0, 7.0]})
        self.assertEqual(tuple(kwargs["well_width"]), (8.0, 7.0))


if __name__ == "__main__":
    unittest.main()
