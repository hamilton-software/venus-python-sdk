"""Tip length vs labware depth: the channel must not go inside a well or tube
(hamilton_venus.tip_reach and the check before pipetting commands)."""

from __future__ import annotations

from typing import Any

import pytest

from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
from hamilton_venus.liquid_class_library import parse_tip_types
from hamilton_venus.models import CommandResponse
from hamilton_venus.tip_reach import assess_tip_reach, container_depth, lowest_tip_heights, rack_tip_type

TIPS = parse_tip_types({
    "22": {"Tip Length": 50.4, "Stop Disk Immersion Depth": 8, "Max Liquid Volume": 50,
           "Liquid Device List": ["1mL Channels", "96 head"], "Tip View Name": "50ul Tip", "Tip Class": "tip"},
    "0": {"Tip Length": 59.9, "Stop Disk Immersion Depth": 8, "Max Liquid Volume": 300,
          "Liquid Device List": ["1mL Channels", "96 head"], "Tip View Name": "300ul Tip", "Tip Class": "tip"},
    "4": {"Tip Length": 95.1, "Stop Disk Immersion Depth": 8, "Max Liquid Volume": 1000,
          "Liquid Device List": ["1mL Channels", "96 head"], "Tip View Name": "1000ul Tip", "Tip Class": "tip"},
    "25": {"Tip Length": 118, "Stop Disk Immersion Depth": 10, "Max Liquid Volume": 5000,
           "Liquid Device List": ["5mL channels"], "Tip View Name": "5ml Tip", "Tip Class": "tip"},
})
TUBE_RACK = {"containerGrids": {"tubes": {"containerDefinition": {"totalDepth": 98.9}}}}
DEEP_WELL = {"containerGrids": {"wells": {"containerDefinition": {"totalDepth": 40.0}}}}
TIP_RACK = {"customAttributes": {"hamilton:rck_properties": {"MlStarTipRack": 22, "MlStarCore96TipRack": 22}}}


def test_depth_and_rack_tip_type_from_definitions():
    assert container_depth(TUBE_RACK) == 98.9
    assert container_depth({}) is None
    assert rack_tip_type(TIP_RACK, "channels_1000ul") == 22
    assert rack_tip_type({}, "channels_1000ul") is None


def test_short_tip_in_a_100mm_tube_is_a_contamination_risk():
    reach = assess_tip_reach(TIPS[22], labware="Tubes", depth=98.9, registered=TIPS)
    assert not reach.ok
    assert reach.tip_length_below_channel == 42.4
    assert reach.channel_inside_mm == 56.5
    assert "Contamination risk" in reach.message
    # With LLD the message says how high the tip must stay: 98.9 - 10 (allowance) - 42.4 = 46.5 mm.
    assert "lower than 46.5 mm above the bottom" in reach.message


def test_with_lld_a_tip_must_reach_half_the_depth():
    # 100 mm tube (98.9 mm deep): 50 µL warns, 300 µL (51.9 mm) and 1000 µL (87.1 mm) don't.
    assert not assess_tip_reach(TIPS[22], labware="Tubes", depth=98.9, registered=TIPS).ok
    assert assess_tip_reach(TIPS[0], labware="Tubes", depth=98.9, registered=TIPS).ok
    assert assess_tip_reach(TIPS[4], labware="Tubes", depth=98.9, registered=TIPS).ok


def test_short_tips_get_longer_suggestions():
    reach = assess_tip_reach(TIPS[22], labware="DeepTubes", depth=120.0, registered=TIPS)
    assert not reach.ok
    # Half of 120 mm is 60: 300 µL (51.9 mm) is too short too; 5 mL tips are for another device.
    assert reach.longer_tips == ["1000ul Tip (87.1 mm)"]


def test_fixed_height_counts():
    assert assess_tip_reach(TIPS[0], labware="Tubes", depth=98.9, lowest_tip_height=50, fixed_height=True).ok
    reach = assess_tip_reach(TIPS[0], labware="Tubes", depth=98.9, lowest_tip_height=20, fixed_height=True)
    assert not reach.ok and "fixed height of 20 mm" in reach.message
    assert "pipette at 37 mm or higher" in reach.message  # 98.9 - 10 - 51.9


def test_a_few_mm_of_channel_in_the_tube_is_allowed():
    # 1000 µL tip at 5 mm in a 100 mm tube: the channel is 6.8 mm inside -- within the 10 mm allowance.
    reach = assess_tip_reach(TIPS[4], labware="Tubes", depth=98.9, lowest_tip_height=5, fixed_height=True)
    assert reach.ok and reach.channel_inside_mm == 6.8
    # A 50 µL tip there gets the 1000 µL tip suggested.
    short = assess_tip_reach(TIPS[22], labware="Tubes", depth=98.9, lowest_tip_height=5, fixed_height=True,
                             registered=TIPS)
    assert not short.ok
    assert short.longer_tips == ["1000ul Tip (87.1 mm)"]


def test_lowest_heights_per_channel():
    heights = lowest_tip_heights({"fixedHeight": [30, 5], "capacitiveLLD": [0, 1]}, 2)
    assert heights == [(30.0, True), (0.0, False)]  # LLD can follow the liquid to the bottom
    assert lowest_tip_heights({}, 1) == [(0.0, False)]


class _Venus:
    def __init__(self):
        self.calls: list[str] = []

    async def send_command(self, category: str, action_name: str, parameters: dict[str, Any] | None = None):
        self.calls.append(action_name)
        if action_name == "tipPool.getTipCounter":
            rp = {"tipType": 22}
        elif action_name == "liquidClass.getTipTypes":
            rp = {"tipTypes": {"22": {"Tip Length": 50.4, "Stop Disk Immersion Depth": 8, "Max Liquid Volume": 50,
                                      "Liquid Device List": ["1mL Channels"], "Tip View Name": "50ul Tip",
                                      "Tip Class": "tip"}}}
        else:  # labware.getLabwareParamsFromID
            rp = {"definition": TIP_RACK if parameters["labwareName"] == "Rack" else TUBE_RACK}
        return CommandResponse(return_status="Success", return_parameters=rp)


def _client() -> _AsyncInstrumentClient:
    client = object.__new__(_AsyncInstrumentClient)
    client._venus = _Venus()
    client._run_log = None
    client._channel_tips, client._pool_tip_types, client._labware_definitions = {}, {}, {}
    client._registered_tips, client._command_warnings = None, []
    return client


ASPIRATE = {"channels": [1, 2],
            "positions": [{"labwareId": "Tubes", "wellId": "1"}, {"labwareId": "Tubes", "wellId": "2"}],
            "capacitiveLLD": [1, 1]}


@pytest.mark.asyncio
async def test_pickup_then_aspirate_in_deep_tubes_warns_once():
    client = _client()
    await client._track_tips_and_check_reach("channels.1mL.tipPickup", {"channels": [1, 2], "tipPool": "Tips50"})
    await client._track_tips_and_check_reach("channels.1mL.aspirate", ASPIRATE)
    warnings = client.pop_command_warnings()
    assert len(warnings) == 1  # same tip, labware and height on both channels
    assert "Contamination risk" in warnings[0] and "Tubes" in warnings[0]
    assert client.pop_command_warnings() == []
    # The pool's tip type and the tube definition are looked up once, then cached.
    await client._track_tips_and_check_reach("channels.1mL.aspirate", ASPIRATE)
    assert client._venus.calls.count("tipPool.getTipCounter") == 1
    assert client._venus.calls.count("labware.getLabwareParamsFromID") == 1


@pytest.mark.asyncio
async def test_rack_pickup_is_tracked_and_eject_clears_it():
    client = _client()
    await client._track_tips_and_check_reach(
        "channels.1mL.tipPickup", {"channels": [1], "positions": [{"labwareId": "Rack", "wellId": "A1"}]})
    assert client._channel_tips == {("channels_1000ul", 1): 22}
    await client._track_tips_and_check_reach("channels.1mL.tipEject", {"channels": [1]})
    await client._track_tips_and_check_reach("channels.1mL.aspirate", {**ASPIRATE, "channels": [1]})
    assert client.pop_command_warnings() == []  # no tip known on that channel any more
