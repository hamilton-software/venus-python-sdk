"""Tests for hamilton_venus_mcp.script_validator: the static feasibility check.

Every test validates script *text*; nothing here runs a script or needs VENUS.
"""

from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path

from hamilton_venus_mcp.script_validator import validate_source
from hamilton_venus_mcp.scripts_store import sha256_of

_HEADER = """\
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.models import AspirateSettings, DispenseSettings, Position
from hamilton_venus.models.enums import CapacitiveLLD, DispenseMode, WellOrder
"""


def script(body: str, *, header: str = _HEADER, simulate: str = "True") -> str:
    """A script whose *body* runs inside ``with StarClient(...) as star:``."""
    return header + f"\nwith StarClient(simulate={simulate}) as star:\n" + textwrap.indent(textwrap.dedent(body), "    ")


def rules(issues) -> list[str]:
    return [i.rule for i in issues]


class ValidatorTestCase(unittest.TestCase):
    def check(self, source: str):
        return validate_source(source, "test.py")

    def assertHasError(self, report, rule: str, *, containing: str | None = None):
        matches = [i for i in report.errors if i.rule == rule]
        self.assertTrue(matches, f"expected error {rule}; got errors {[(i.rule, i.message) for i in report.errors]}")
        if containing is not None:
            self.assertTrue(
                any(containing in i.message or containing in (i.suggestion or "") for i in matches),
                f"no {rule} mentioning {containing!r}: {[(i.message, i.suggestion) for i in matches]}",
            )
        return matches[0]

    def assertClean(self, report):
        self.assertEqual([(i.rule, i.message) for i in report.errors], [])


class GoodScriptTests(ValidatorTestCase):
    def test_a_valid_script_passes_and_reports_what_it_uses(self):
        report = self.check(
            script(
                """\
                star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="Tips")
                star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_50UL, carrier_id="Tips", site="1", tip_pool="P")
                star.tip_pool_reset_tip_counter(tip_pool="P")
                star.tip_pickup(tip_pool="P")
                star.tip_eject()
                """
            )
        )
        self.assertClean(report)
        self.assertTrue(report.ok)
        info = report.info
        self.assertEqual(info["clients"][0]["class"], "StarClient")
        self.assertIs(info["clients"][0]["simulate_literal"], True)
        self.assertEqual(sorted(info["commands_used"]), ["add_carrier", "add_tip_rack", "tip_eject", "tip_pickup", "tip_pool_reset_tip_counter"])
        self.assertGreater(info["arguments"]["checked"], 0)
        self.assertEqual(report.warnings, [])

    def test_report_is_json_serialisable_and_hashes_the_source(self):
        source = script("star.tip_eject()\n")
        report = self.check(source)
        data = json.loads(json.dumps(report.to_dict()))
        self.assertTrue(data["ok"])
        self.assertEqual(data["sha256"], sha256_of(source.encode("utf-8")))

    def test_repo_mastermix_example_is_clean(self):
        path = Path(__file__).resolve().parents[3] / "example_scripts" / "mastermix_tubes_to_384_plate.py"
        if not path.is_file():
            self.skipTest("mastermix example not present")
        self.assertClean(self.check(path.read_text(encoding="utf-8-sig")))


class SyntaxTests(ValidatorTestCase):
    def test_syntax_error_reports_the_line_and_stops(self):
        report = self.check("x = 1\nif x ==:\n    pass\n")
        error = self.assertHasError(report, "V001")
        self.assertEqual(error.line, 2)
        self.assertEqual(rules(report.errors), ["V001"])


class PolicyTests(ValidatorTestCase):
    def test_forbidden_imports(self):
        for source in (
            "import subprocess\n",
            "import socket\n",
            "import requests\n",
            "import ctypes\n",
            "import urllib.request\n",
            "from subprocess import run\n",
            "from http.client import HTTPConnection\n",
        ):
            with self.subTest(source=source):
                self.assertHasError(self.check(source), "V010")

    def test_harmless_relatives_of_forbidden_modules_are_allowed(self):
        self.assertClean(self.check("import urllib.parse\nimport http\nimport json, math, time\n"))

    def test_forbidden_calls(self):
        for source in (
            "import os\nos.system('dir')\n",
            "import os as o\no.remove('x')\n",
            "from os import system\nsystem('dir')\n",
            "import shutil\nshutil.rmtree('x')\n",
            "eval('1+1')\n",
            "exec('x = 1')\n",
            "__import__('os')\n",
            "import os\nos.execv('a', [])\n",
        ):
            with self.subTest(source=source):
                self.assertHasError(self.check(source), "V011")

    def test_safe_os_use_is_allowed(self):
        self.assertClean(self.check("import os\nprint(os.getcwd(), os.path.join('a', 'b'))\n"))

    def test_gui_and_input_are_refused_as_headless(self):
        for source in (
            "import tkinter\n",
            "from tkinter import messagebox\n",
            "import tkinter.simpledialog as d\n",
            "name = input('who? ')\n",
        ):
            with self.subTest(source=source):
                self.assertHasError(self.check(source), "V012")

    def test_a_shadowed_input_is_not_flagged(self):
        self.assertClean(self.check("def input(prompt):\n    return 1\n\ninput('x')\n"))


class ImportTests(ValidatorTestCase):
    def test_unknown_sdk_name_is_reported_with_a_suggestion(self):
        report = self.check("from hamilton_venus import StarClinet\n")
        self.assertHasError(report, "V020", containing="StarClient")

    def test_unknown_sdk_module(self):
        self.assertHasError(self.check("import hamilton_venus.does_not_exist\n"), "V020")
        self.assertHasError(self.check("from hamilton_venus.nope import x\n"), "V020")

    def test_sdk_submodule_import_by_name(self):
        self.assertClean(self.check("from hamilton_venus import models\nprint(models.Position)\n"))

    def test_uninstalled_module_is_reported(self):
        self.assertHasError(self.check("import definitely_not_installed_pkg_12345\n"), "V014")

    def test_relative_import_is_reported(self):
        self.assertHasError(self.check("from . import helper\n"), "V014")

    def test_stdlib_imports_are_fine(self):
        self.assertClean(self.check("import json, math, time, logging, datetime, pathlib, csv, itertools\n"))


class CommandTests(ValidatorTestCase):
    def test_unknown_command_gets_a_suggestion(self):
        report = self.check(script('star.aspirat(positions="P@A1", volumes=1.0, liquid_class="W")\n'))
        self.assertHasError(report, "V021", containing="aspirate")

    def test_real_client_methods_missing_from_the_catalog_are_allowed(self):
        report = self.check(script('star.get_labware_spec("Plate")\n'))
        self.assertClean(report)
        self.assertIn("get_labware_spec", report.info["unchecked_commands"])

    def test_unknown_keyword_gets_a_suggestion(self):
        report = self.check(script('star.tip_pickup(tip_poool="P")\n'))
        self.assertHasError(report, "V022", containing="tip_pool")

    def test_missing_required_argument(self):
        report = self.check(script('star.aspirate(positions="P@A1")\n'))
        error = self.assertHasError(report, "V022")
        self.assertIn("volumes", error.message)

    def test_too_many_positional_arguments(self):
        report = self.check(script("star.tip_eject([1], 1, 2, 3, 4, 5, 6, 7, 8, 9)\n"))
        self.assertHasError(report, "V022", containing="at most")

    def test_star_arguments_suppress_the_missing_check(self):
        report = self.check(script("kwargs = {}\nstar.aspirate(**kwargs)\n"))
        self.assertClean(report)

    def test_duplicate_value_for_a_parameter(self):
        report = self.check(script('star.tip_pickup([1, 2], channels=[1, 2])\n'))
        self.assertHasError(report, "V022", containing="multiple values")

    def test_client_constructor_arguments_are_checked(self):
        report = self.check(script("pass\n", simulate="True").replace("simulate=True", "simulat=True"))
        self.assertHasError(report, "V022", containing="simulate")

    def test_client_in_a_helper_function_is_recognised(self):
        source = _HEADER + textwrap.dedent(
            """\

            def run(star: StarClient):
                star.aspirat(positions="P@A1", volumes=1.0, liquid_class="W")
            """
        )
        self.assertHasError(self.check(source), "V021")

    def test_client_assigned_without_with_is_recognised(self):
        source = _HEADER + '\nstar = StarClient(simulate=True)\nstar.tip_eject(channels=[])\n'
        self.assertHasError(self.check(source), "V026")

    def test_script_without_a_client_warns(self):
        report = self.check("print('hi')\n")
        self.assertClean(report)
        self.assertIn("W032", rules(report.warnings))


class ValueTests(ValidatorTestCase):
    def test_wrong_type_fails_pydantic_validation(self):
        report = self.check(script('star.aspirate(positions="P@A1", volumes="lots", liquid_class="W")\n'))
        self.assertHasError(report, "V023", containing="volumes")

    def test_valid_values_pass(self):
        report = self.check(script('star.aspirate(positions="P@A1", volumes=75.0, liquid_class="W")\n'))
        self.assertClean(report)

    def test_module_constants_are_followed(self):
        report = self.check(
            _HEADER
            + 'VOLUME = "lots"\n'
            + 'with StarClient(simulate=True) as star:\n'
            + '    star.aspirate(positions="P@A1", volumes=VOLUME, liquid_class="W")\n'
        )
        self.assertHasError(report, "V023", containing="volumes")

    def test_constants_assigned_twice_are_not_trusted(self):
        report = self.check(
            _HEADER
            + 'VOLUME = "lots"\nVOLUME = 5.0\n'
            + 'with StarClient(simulate=True) as star:\n'
            + '    star.aspirate(positions="P@A1", volumes=VOLUME, liquid_class="W")\n'
        )
        self.assertClean(report)
        self.assertGreater(report.info["arguments"]["unverified"], 0)

    def test_arithmetic_and_fstrings_on_constants_are_followed(self):
        report = self.check(
            _HEADER
            + 'PER_WELL = 5.0\nWELLS = 8\nPLATE = "DWP"\n'
            + 'with StarClient(simulate=True) as star:\n'
            + '    star.aspirate(positions=f"{PLATE}@A1", volumes=PER_WELL * WELLS, liquid_class="W")\n'
        )
        self.assertClean(report)
        self.assertEqual(report.info["arguments"]["unverified"], 0)

    def test_sdk_models_are_constructed_and_checked(self):
        bad = self.check(
            script(
                """\
                settings = AspirateSettings(capacitive_lld="not-a-level")
                star.aspirate(positions="P@A1", volumes=1.0, liquid_class="W", settings=AspirateSettings(capacitive_lld="not-a-level"))
                """
            )
        )
        self.assertHasError(bad, "V023", containing="AspirateSettings")
        good = self.check(
            script(
                'star.aspirate(positions="P@A1", volumes=1.0, liquid_class="W", '
                "settings=AspirateSettings(capacitive_lld=CapacitiveLLD.MAX, submerge_depth=2.0))\n"
            )
        )
        self.assertClean(good)

    def test_unknown_enum_and_catalog_attributes(self):
        report = self.check(script("star.tip_pickup(well_order=WellOrder.COL_ASCENDING)\n"))
        self.assertHasError(report, "V025", containing="COL_ASC")
        report = self.check(script("star.add_carrier(labware_definition=LABWARE.CARRIER.NOT_A_REAL_CARRIER, left_track=1)\n"))
        self.assertHasError(report, "V025")

    def test_real_catalog_attributes_resolve(self):
        report = self.check(
            script(
                "star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1)\n"
                "star.tip_pickup(well_order=WellOrder.COL_ASC)\n"
            )
        )
        self.assertClean(report)

    def test_unresolvable_values_are_counted_not_failed(self):
        report = self.check(script("width = len('ab') + 6\nstar.tip_pickup(channels=list(range(1, width)))\n"))
        self.assertClean(report)

    def test_empty_channel_list_is_an_error(self):
        for call in ("star.tip_pickup(channels=[])", "star.tip_eject(channels=list())", "star.tip_pickup([], tip_pool='P')"):
            with self.subTest(call=call):
                self.assertHasError(self.check(script(call + "\n")), "V026")

    def test_non_empty_channels_pass(self):
        for call in ("star.tip_pickup(channels=[1, 2, 3])", "star.tip_pickup(channels=list(range(1, 9)))"):
            with self.subTest(call=call):
                self.assertClean(self.check(script(call + "\n")))


class SelectorAndStringTests(ValidatorTestCase):
    def test_valid_selectors(self):
        for selector in ("Plate", "Plate@all", "Plate@All", "Plate@A1", "Plate@A1,B1", "Plate@A1:C3", "Plate@col:1,3:5", "Plate@row:A,C:E", "Rack@1:12"):
            with self.subTest(selector=selector):
                report = self.check(script(f'star.aspirate(positions="{selector}", volumes=1.0, liquid_class="W")\n'))
                self.assertClean(report)

    def test_selector_that_does_not_parse(self):
        for selector in ("Plate@row2", "Plate@col1", "Plate@", "Plate@A1:", "@A1"):
            with self.subTest(selector=selector):
                report = self.check(script(f'star.aspirate(positions="{selector}", volumes=1.0, liquid_class="W")\n'))
                self.assertHasError(report, "V027")

    def test_value_wrapped_in_literal_quotes_warns(self):
        report = self.check(script("""star.aspirate(positions="P@A1", volumes=1.0, liquid_class='"Water"')\n"""))
        self.assertClean(report)
        self.assertIn("W034", rules(report.warnings))


class LabwareTests(ValidatorTestCase):
    def test_labware_used_but_never_added_warns(self):
        report = self.check(
            script(
                """\
                star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="Tips")
                star.aspirate(positions="Trough@all", volumes=1.0, liquid_class="W")
                """
            )
        )
        warned = [w for w in report.warnings if w.rule == "W030"]
        self.assertEqual(len(warned), 1)
        self.assertIn("Trough", warned[0].message)

    def test_labware_added_by_the_script_does_not_warn(self):
        report = self.check(
            script(
                """\
                star.add_carrier(labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD, left_track=1, labware_id="Plates")
                star.add_plate(labware_definition=LABWARE.PLATE.COS_96_RD, carrier_id="Plates", site="1", plate_id="DWP")
                star.aspirate(positions="DWP@A1", volumes=1.0, liquid_class="W")
                """
            )
        )
        self.assertNotIn("W030", rules(report.warnings))
        self.assertEqual(report.info["labware"]["added"], ["DWP", "Plates"])

    def test_no_labware_warning_when_a_deck_may_supply_it(self):
        source = _HEADER + textwrap.dedent(
            """\

            with StarClient(simulate=True, deck_name="Saved") as star:
                star.aspirate(positions="Trough@all", volumes=1.0, liquid_class="W")
            """
        )
        self.assertNotIn("W030", rules(self.check(source).warnings))

    def test_no_labware_warning_when_some_labware_is_auto_named(self):
        report = self.check(
            script(
                """\
                star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1)
                star.aspirate(positions="Trough@all", volumes=1.0, liquid_class="W")
                """
            )
        )
        self.assertNotIn("W030", rules(report.warnings))

    def test_compound_add_commands_are_not_labware(self):
        report = self.check(
            script(
                'star.add_reagent(reagent_source="Trough", dest_plate="Plate", volume=5.0, tip_pool="P", liquid_class="W")\n'
            )
        )
        self.assertClean(report)
        self.assertEqual(report.info["labware"]["added"], [])


class SimulateTests(ValidatorTestCase):
    def test_hard_coded_simulate_false_warns_but_is_not_an_error(self):
        report = self.check(script("star.tip_eject()\n", simulate="False"))
        self.assertClean(report)
        self.assertIn("W033", rules(report.warnings))
        self.assertIs(report.info["clients"][0]["simulate_literal"], False)


class TipCounterTests(ValidatorTestCase):
    RACKS = """star.add_carrier(labware_definition=LABWARE.CARRIER.TIP_CAR_480BC, left_track=1, labware_id="Tips")
star.add_tip_rack(labware_definition=LABWARE.TIP_RACK.TIP_RACK_300UL, carrier_id="Tips", site="1", tip_pool="P")
"""

    def test_picking_up_tips_without_setting_up_the_counters_warns(self):
        report = self.check(script(self.RACKS + 'star.tip_pickup(tip_pool="P")\nstar.tip_eject()\n'))
        self.assertClean(report)
        self.assertIn("W035", rules(report.warnings))

    def test_reset_or_show_by_simulate_is_enough(self):
        body = self.RACKS + """if star.simulate:
    star.tip_pool_reset_tip_counter(tip_pool="P")
else:
    star.tip_pool_show_tip_counters(tip_pools=["P"])
star.tip_pick_up_mph96(tip_pool="P")
star.tip_eject_mph96()
"""
        self.assertNotIn("W035", rules(self.check(script(body)).warnings))


class PipettingSettingsTests(ValidatorTestCase):
    def test_aspirate_and_dispense_without_settings_warn(self):
        body = """star.aspirate_mph96(labware_id="Trough", volume=100, liquid_class="LC")
star.dispense_mph96(labware_id="Plate", volume=100)
"""
        warned = [w for w in self.check(script(body)).warnings if w.rule == "W036"]
        self.assertEqual([w.line for w in warned], [7, 8])
        self.assertIn("aspirate_mph96", warned[0].message)

    def test_settings_passed_do_not_warn(self):
        body = """asp = AspirateSettings(capacitive_lld=CapacitiveLLD.MAX)
star.aspirate(positions="Trough@all", volumes=100, liquid_class="LC", settings=asp)
"""
        self.assertNotIn("W036", rules(self.check(script(body)).warnings))

    def test_liquid_following_without_lld_warns(self):
        # Follows down from the fixed height into the bottom: insufficient liquid level.
        header = _HEADER + (
            "from hamilton_venus.models import MPH96AspirateSettings\n"
            "ASP = MPH96AspirateSettings(capacitive_lld=CapacitiveLLD.OFF, liquid_following=True, fixed_height=2.0)\n"
        )
        body = 'star.aspirate_mph96(labware_id="Trough", volume=100, liquid_class="LC", settings=ASP)\n'
        self.assertIn("W037", rules(self.check(script(body, header=header)).warnings))

    def test_liquid_following_with_clld_or_fixed_height_without_following_is_fine(self):
        for settings in ("AspirateSettings(capacitive_lld=CapacitiveLLD.MAX, liquid_following=True)",
                         "AspirateSettings(fixed_height=3.0)"):
            with self.subTest(settings=settings):
                body = f'star.aspirate(positions="Trough@all", volumes=100, liquid_class="LC", settings={settings})\n'
                self.assertNotIn("W037", rules(self.check(script(body)).warnings))


if __name__ == "__main__":
    unittest.main()
