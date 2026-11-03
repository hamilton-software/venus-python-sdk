"""Carriers are placed by their real width (definition's widthAsTracks), and a placement that
overlaps another carrier or runs off the deck is refused before it reaches VENUS."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hamilton_venus_mcp.server as srv
from hamilton_venus_mcp import deck_tracks


def _labware_dir() -> Path:
    root = Path(tempfile.mkdtemp())
    carriers = root / "System" / "carrier"
    carriers.mkdir(parents=True)
    for name, width in (("TIP_CAR_480BC", 6), ("RGT_CAR_5R60", 1), ("PLT_CAR_L5_MTP", 6)):
        (carriers / f"{name}.json").write_text(
            json.dumps({"customAttributes": {"hamilton:star": {"widthAsTracks": width}}}), encoding="utf-8")
    # No width property at all (like PLT_CAR_L4HHC): x / 22.5 mm per track.
    (carriers / "PLT_CAR_L4HHC.json").write_text(
        json.dumps({"dimensions": {"x": 157.5}, "customAttributes": {}}), encoding="utf-8")
    (carriers / "ODD_CAR.json").write_text(json.dumps({"dimensions": {"x": 140.0}}), encoding="utf-8")
    plates = root / "System" / "plate"
    plates.mkdir(parents=True)
    (plates / "NUN_96_FL.json").write_text(json.dumps({"dimensions": {"x": 127.76}}), encoding="utf-8")
    racks = root / "System" / "tube_rack"
    racks.mkdir(parents=True)
    (racks / "SMP_CAR_24C12_15x100.json").write_text(
        json.dumps({"customAttributes": {"hamilton:rck_properties": {"MlStarCarWidthAsT": 1}}}), encoding="utf-8")
    return root


def _layout_dir(spans: dict[str, tuple[int, int]], tracks: int = 54) -> Path:
    root = Path(tempfile.mkdtemp())
    data = {str(t): {"occupied": False, "carrier": ""} for t in range(-3, tracks + 1)}
    for name, (first, last) in spans.items():
        for t in range(first, last + 1):
            data[str(t)] = {"occupied": True, "carrier": name}
    (root / "LayoutTracking.json").write_text(json.dumps(data), encoding="utf-8-sig")
    return root


class DeckTracksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.labware = _labware_dir()

    def test_widths_from_definitions(self) -> None:
        self.assertEqual(deck_tracks.carrier_width("TIP_CAR_480BC", self.labware), 6)
        self.assertEqual(deck_tracks.carrier_width("rgt_car_5r60", self.labware), 1)  # any case
        self.assertEqual(deck_tracks.carrier_width("SMP_CAR_24C12_15X100", self.labware), 1)  # tube carrier
        self.assertIsNone(deck_tracks.carrier_width("NOT_A_CARRIER", self.labware))
        self.assertEqual(deck_tracks.carrier_width("PLT_CAR_L4HHC", self.labware), 7)  # 157.5 / 22.5
        self.assertEqual(deck_tracks.carrier_width("ODD_CAR", self.labware), 7)  # 6.2 tracks takes 7
        self.assertIsNone(deck_tracks.carrier_width("NUN_96_FL", self.labware))  # a plate is no carrier

    def test_occupancy_from_the_layout_file(self) -> None:
        occupied, last = deck_tracks.read_occupancy(_layout_dir({"tipcarrier1": (1, 6)}))
        self.assertEqual((sorted(occupied), last), (list(range(1, 7)), 54))
        self.assertEqual(deck_tracks.read_occupancy(Path(tempfile.mkdtemp())), ({}, None))  # blank deck

    def test_overlap_is_refused_with_where_it_fits(self) -> None:
        layout = _layout_dir({"tipcarrier1": (1, 6), "reagentcarrier1": (11, 11)})
        problem, takes = deck_tracks.check(
            "add_carrier", {"labware_definition": "TIP_CAR_480BC", "left_track": 6}, self.labware, layout)
        self.assertIn("6 track(s) wide", problem)
        self.assertIn("tipcarrier1 (tracks 1-6)", problem)
        self.assertIn("reagentcarrier1 (tracks 11)", problem)  # VENUS let this overlap through
        self.assertIn("fits at or right of 6 is 12", problem)
        self.assertIn("Free tracks now: 7-10, 12-54", problem)
        self.assertEqual(takes["tracks"], "6-11")

    def test_a_free_placement_reports_its_tracks(self) -> None:
        layout = _layout_dir({"tipcarrier1": (1, 6)})
        problem, takes = deck_tracks.check(
            "add_carrier", {"labware_definition": "TIP_CAR_480BC", "left_track": 7}, self.labware, layout)
        self.assertIsNone(problem)
        self.assertEqual(takes, {"width_tracks": 6, "tracks": "7-12", "first_track_after_it": 13})

    def test_off_the_deck_is_refused(self) -> None:
        problem, _ = deck_tracks.check(
            "add_carrier", {"labware_definition": "PLT_CAR_L5_MTP", "left_track": 52}, self.labware, _layout_dir({}))
        self.assertIn("off the deck", problem)

    def test_moving_a_carrier_ignores_its_own_tracks(self) -> None:
        layout = _layout_dir({"mtpcarrier1": (22, 27), "dwpcarrier1": (16, 21)})
        ok, takes = deck_tracks.check("move_carrier", {"labware_name": "MTPCarrier1", "left_track": 23},
                                      self.labware, layout)
        self.assertIsNone(ok)
        self.assertEqual(takes["tracks"], "23-28")
        refused, _ = deck_tracks.check("move_carrier", {"labware_name": "mtpcarrier1", "left_track": 20},
                                       self.labware, layout)
        self.assertIn("dwpcarrier1 (tracks 16-21)", refused)
        # Onto a carrier's site, or an unknown type: not a deck-track placement to check.
        self.assertEqual(deck_tracks.check("move_carrier", {"labware_name": "mtpcarrier1", "left_track": 1, "site": "2"},
                                           self.labware, layout), (None, None))
        self.assertEqual(deck_tracks.check("add_carrier", {"labware_definition": "UNKNOWN", "left_track": 16},
                                           self.labware, layout), (None, None))


class ServerPlacementTests(unittest.TestCase):
    def test_refused_before_it_reaches_venus(self) -> None:
        dispatched = []

        async def dispatch(*args, **kwargs):
            dispatched.append(args)
            return {"status": "success"}

        with patch.object(srv, "_check_connection"), patch.object(srv, "_prepare_sdk_command"), \
                patch.object(srv, "_dispatch_sdk_command", dispatch), \
                patch.object(deck_tracks, "check", return_value=("add_carrier refused: overlap", None)):
            with self.assertRaisesRegex(ValueError, "refused: overlap"):
                asyncio.run(srv.call_sdk_command("add_carrier", {"labware_definition": "X", "left_track": 6}))
        self.assertEqual(dispatched, [])

    def test_search_labware_gives_carrier_widths(self) -> None:
        with patch.object(deck_tracks, "carrier_width", return_value=6):
            results = srv.search_labware(search="TIP_CAR_480BC")
        self.assertEqual(results[0]["width_tracks"], 6)


class InstructionsTests(unittest.TestCase):
    def test_the_essentials_fit_what_clients_pass_on(self) -> None:
        # Clients give the model only the first 4,096 characters of a server's instructions.
        self.assertLess(len(srv._INSTRUCTIONS), 4096)
        for phrase in ("get_usage_guide", "width_tracks", "CO-RE grips are a separate TOOL", "get_transport_tool_ids",
                       "simulate=False", "find_liquid_classes", "operator page"):
            self.assertIn(phrase, srv._INSTRUCTIONS)

    def test_usage_guide_finds_sections(self) -> None:
        tube = srv.get_usage_guide(search="tube carriers")
        self.assertTrue(any("add_tube_carrier" in section for section in tube["sections"]))
        self.assertEqual(srv.get_usage_guide(search="all")["guide"], srv._GUIDE)
        self.assertIn("note", srv.get_usage_guide(search="nothing-like-this"))
        self.assertGreater(len(srv.get_usage_guide()["sections"]), 10)

    def test_configuration_result_says_core_grips_are_not_in_it(self) -> None:
        async def dispatch(name, kwargs):
            return {"command": name, "status": "success", "result": {}}

        with patch.object(srv, "_check_connection"), patch.object(srv, "_prepare_sdk_command"),                 patch.object(srv, "_dispatch_sdk_command", dispatch):
            result = asyncio.run(srv.call_sdk_command("instrument_get_configuration"))
        self.assertIn("CO-RE grips are a separate tool", result["note"])



class NotConnectedHintTests(unittest.TestCase):
    def test_a_command_needing_the_connection_says_to_connect_first(self):
        from hamilton_venus.exceptions import VenusCommandFailedError
        from hamilton_venus.models import CommandResponse

        response = CommandResponse(return_status="Error", return_code=0, return_parameters={
            "message": "Instrument must be connected before calling this command!", "code": 101})
        payload = srv._describe_venus_error(VenusCommandFailedError(response))
        self.assertIn("connect_instrument", payload["hint"])
        other = CommandResponse(return_status="Error", return_code=0, return_parameters={"message": "Something else"})
        self.assertNotIn("hint", srv._describe_venus_error(VenusCommandFailedError(other)))
