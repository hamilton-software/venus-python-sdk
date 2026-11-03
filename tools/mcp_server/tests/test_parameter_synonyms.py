"""call_sdk_command accepts the SDK's other spellings of carrier / labware parameters.

A carrier is `carrier` in get_available_carrier_sites, get_labware_on_carrier and the
transports but `carrier_id` in the add_* commands, so agents kept calling
get_available_carrier_sites(carrier_id=...) and failing.
"""

from __future__ import annotations

import dataclasses
import unittest

from hamilton_venus_mcp.catalog import CATALOG
from hamilton_venus_mcp.coercion import ArgumentError, apply_synonyms, coerce_kwargs


class ParameterSynonymTests(unittest.TestCase):
    def test_carrier_id_reaches_a_command_that_takes_carrier(self) -> None:
        spec = CATALOG["get_available_carrier_sites"]
        self.assertEqual(coerce_kwargs(spec, {"carrier_id": "tip_car_480bc_0001"}), {"carrier": "tip_car_480bc_0001"})

    def test_carrier_reaches_a_command_that_takes_carrier_id(self) -> None:
        kwargs = apply_synonyms(CATALOG["add_plate"], {"carrier": "PlateCarrier", "labware_id": "Plate1"})
        self.assertEqual(kwargs["carrier_id"], "PlateCarrier")
        self.assertEqual(kwargs["plate_id"], "Plate1")

    def test_both_spellings_together_still_fail(self) -> None:
        spec = CATALOG["get_available_carrier_sites"]
        with self.assertRaises(ArgumentError):
            coerce_kwargs(spec, {"carrier": "a", "carrier_id": "b"})

    def test_ambiguous_group_is_left_alone(self) -> None:
        spec = CATALOG["get_available_carrier_sites"]
        params = [dataclasses.replace(spec.params[0], name="labware_name"), dataclasses.replace(spec.params[0], name="plate_id")]
        two = dataclasses.replace(spec, params=params)
        self.assertEqual(apply_synonyms(two, {"labware": "x"}), {"labware": "x"})

    def test_real_unknown_parameters_still_fail(self) -> None:
        with self.assertRaises(ArgumentError):
            coerce_kwargs(CATALOG["get_available_carrier_sites"], {"site": "1"})
