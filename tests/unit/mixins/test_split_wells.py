"""Unit tests for split_wells: the VENUS payload, the registry, routing and the lifecycle hooks."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.exceptions import SplitWellCapacityError
from hamilton_venus.mixins.deck_commands import DeckCommandsMixin
from hamilton_venus.mixins.deck_labware_commands import DeckLabwareCommandsMixin
from hamilton_venus.mixins.split_well_commands import (
    SplitWellCommandsMixin,
    route_split_wells,
    split_labware_id,
)
from hamilton_venus.mixins.transport_commands import TransportCommandsMixin
from hamilton_venus.models import (
    CommandResponse,
    LabwareDefinitionSingleResponse,
    Position,
    SplitChannelType,
    SplitWellFit,
    TiltWellPosition,
)
from hamilton_venus.models.position import LabwareLayoutSpec
from hamilton_venus.split_well_geometry import DEFAULT_TIP_PROFILES, TipProfile, compute_split_well_plan
from hamilton_venus.star_client import StarClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "labware"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8-sig"))


PLATE_6 = load("Greiner_Culture_Plate_6")
PLATE_24 = load("Greiner_Culture_Plate_24")
SUCCESS = CommandResponse(return_status="Success", return_code=0, return_parameters={})


def definition_response(definition: dict) -> LabwareDefinitionSingleResponse:
    return LabwareDefinitionSingleResponse.model_validate(
        {"returnParameters": {"labwareName": "Plate6", "definition": definition}}
    )


class _SplitClient(DeckLabwareCommandsMixin, TransportCommandsMixin, DeckCommandsMixin, SplitWellCommandsMixin):
    def __init__(self, definition: dict = PLATE_6):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(return_value=SUCCESS)
        self.labware_get_params_from_id = MagicMock(return_value=definition_response(definition))
        self._spec = LabwareLayoutSpec.from_definition(definition)

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)

    def get_labware_spec(self, labware_id):
        return self._spec


def actions(client) -> list[tuple[str, str]]:
    """(action, labware) of every command sent, in order."""
    sent = []
    for call in client._star.venus.send_command.await_args_list:
        params = call.kwargs.get("parameters") or {}
        name = params.get("splitLabwareName") or params.get("labwareName") or ""
        sent.append((call.kwargs["action_name"], name))
    return sent


def reset(client) -> None:
    client._star.venus.send_command.reset_mock()


class TestSplitWells:
    def test_sends_one_split_site_per_well(self):
        client = _SplitClient()

        sites = client.split_wells("Plate6", "A1")

        assert len(sites) == 1
        site = sites[0]
        assert (site.parent_labware, site.parent_well, site.channel_type) == ("plate6", "A1", SplitChannelType.ONE_ML)
        assert site.split_labware == "plate6_a1_split_1ml_4slots"
        assert site.slot_wells == ["1", "2", "3", "4"]
        call = client._star.venus.send_command.await_args.kwargs
        assert (call["category"], call["action_name"]) == ("Deck Layout", "labware.addSplitWellSite")
        params = call["parameters"]
        assert params["splitLabwareName"] == "plate6_a1_split_1ml_4slots"
        assert params["parentLabwareName"] == "Plate6"
        assert params["parentWell"] == "A1"
        assert [s["deltaY"] for s in params["slots"]] == [13.5, 4.5, -4.5, -13.5]
        assert set(params["slots"][0]) == {"well", "deltaX", "deltaY", "deltaZ"}
        assert [s["well"] for s in params["slots"]] == ["1", "2", "3", "4"]
        grid = params["definition"]["containerGrids"]["default"]
        assert (grid["rows"], grid["columns"], grid["rowPitch"]) == (4, 1, 9.0)
        assert grid["namingConvention"]["rowStyle"] == "numeric"
        assert LabwareLayoutSpec.from_definition(params["definition"]).numeric_addressing
        assert params["rackDeltaY"] == -18.0
        assert client.get_split_wells("PLATE6") == sites

    def test_rack_is_raised_to_slot_one(self):
        # VENUS ignores a Z offset on rack position 1, so the rack itself carries slot 1's Z.
        client = _SplitClient()
        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)

        (site,) = client.split_wells("Plate6", "A2", fit=SplitWellFit.MAX_CHANNELS)

        params = client._star.venus.send_command.await_args.kwargs["parameters"]
        assert site.plan.slots[0].dz > 0
        assert params["rackDeltaZ"] == site.plan.slots[0].dz == params["slots"][0]["deltaZ"]

    def test_slot_coordinates_come_from_the_response(self):
        client = _SplitClient()
        client._star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "splitLabwareName": "plate6_a1_split_1ml_4slots",
                "parentLabwareName": "plate6",
                "parentWell": "A1",
                "slots": [{"well": str(n), "x": 100.0, "y": 200.0 - 9.0 * n, "z": 105.0} for n in range(1, 5)],
            },
        )

        (site,) = client.split_wells("Plate6", "A1")

        assert [(c.well, c.y) for c in site.coordinates] == [("1", 191.0), ("2", 182.0), ("3", 173.0), ("4", 164.0)]

    def test_selector_and_list_pick_wells_once_each(self):
        client = _SplitClient()

        by_range = client.split_wells("Plate6", "A1:B2")
        assert [s.parent_well for s in by_range] == ["A1", "B1", "A2", "B2"]

        again = client.split_wells("Plate6", ["A3", "a3"])
        assert [s.parent_well for s in again] == ["A3"]
        assert len(client.get_split_wells()) == 5

    def test_5ml_channels_use_18_mm(self):
        client = _SplitClient()

        (site,) = client.split_wells("Plate6", "A1", channel_type=SplitChannelType.FIVE_ML)

        assert site.channel_type is SplitChannelType.FIVE_ML
        assert site.split_labware == "plate6_a1_split_5ml_2slots"
        assert [s.dy for s in site.plan.slots] == [9.0, -9.0]

    def test_plain_strings_are_accepted(self):
        client = _SplitClient()

        (site,) = client.split_wells("Plate6", "A1", channel_type="5ml", fit="max_channels")

        assert site.channel_type is SplitChannelType.FIVE_ML
        assert site.request.fit is SplitWellFit.MAX_CHANNELS
        assert site.split_labware == "plate6_a1_split_5ml_2slots"

    def test_wells_that_hold_one_channel_are_skipped(self, caplog):
        client = _SplitClient(PLATE_24)

        with caplog.at_level(logging.WARNING):
            sites = client.split_wells("Plate24", "A1", channel_type=SplitChannelType.FIVE_ML)

        assert sites == []
        client._star.venus.send_command.assert_not_awaited()
        assert "not split" in caplog.text

    def test_splitting_again_replaces_the_split(self):
        client = _SplitClient()
        client.split_wells("Plate6", "A1")
        reset(client)

        client.split_wells("Plate6", "A1", max_channels=2)

        assert actions(client) == [
            ("labware.removeLabware", "plate6_a1_split_1ml_4slots"),
            ("labware.addSplitWellSite", "plate6_a1_split_1ml_2slots"),
        ]
        assert client.get_split_wells()[0].slot_count == 2

    def test_rejects_bad_arguments_before_sending(self):
        client = _SplitClient()

        with pytest.raises(ValueError, match=r"channel_type must be one of SplitChannelType.ONE_ML"):
            client.split_wells("Plate6", "A1", channel_type="300uL")
        with pytest.raises(ValueError, match="fit must be"):
            client.split_wells("Plate6", "A1", fit="most")
        with pytest.raises(ValueError, match="max_channels"):
            client.split_wells("Plate6", "A1", max_channels=0)
        client._star.venus.send_command.assert_not_awaited()

    def test_uses_the_tilt_state(self):
        client = _SplitClient()
        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)
        reset(client)

        (deepest,) = client.split_wells("Plate6", "A1")
        (most,) = client.split_wells("Plate6", "A2", fit=SplitWellFit.MAX_CHANNELS)

        # Aimed at the wall, POSITION is as many channels as fit, as close to the wall as they fit.
        assert deepest.slot_count == most.slot_count == 3
        assert deepest.plan.x_shift_applied == most.plan.x_shift_applied < deepest.plan.requested_x_shift

    def test_uses_the_plates_tip_end_height_and_margins(self):
        client = _SplitClient()
        client.tilt_labware(
            "Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT, tip_end_height_mm=3.0, wall_margin_mm=0.5
        )

        (site,) = client.split_wells("Plate6", "A1", fit=2)

        expected = compute_split_well_plan(
            PLATE_6,
            "A1",
            pitch_mm=9.0,
            max_channels=8,
            tilt_degrees=10,
            well_position=TiltWellPosition.DEEPEST_POINT,
            fit=2,
            tip_end_height_mm=3.0,
            wall_margin_mm=0.5,
        )
        assert site.plan.slots == expected.slots
        assert site.plan.x_shift_applied == expected.x_shift_applied

    def test_its_own_settings_win_and_survive_a_rebuild(self):
        client = _SplitClient()
        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)
        (plate_margins,) = client.split_wells("Plate6", "A1", fit=2)
        (own_margins,) = client.split_wells("Plate6", "A1", fit=2, wall_margin_mm=3.0)

        assert own_margins.plan.x_shift_applied < plate_margins.plan.x_shift_applied - 1.5

        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)
        assert client.get_split_wells()[0].plan == own_margins.plan

    def test_uses_the_measured_angle(self):
        client = _SplitClient()
        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT, measured_tilt_degrees=10.8)

        (site,) = client.split_wells("Plate6", "A1", fit=2)

        expected = compute_split_well_plan(
            PLATE_6,
            "A1",
            pitch_mm=9.0,
            max_channels=8,
            tilt_degrees=10.8,
            well_position=TiltWellPosition.DEEPEST_POINT,
            fit=2,
        )
        assert site.plan.x_shift_applied == expected.x_shift_applied


class TestRemoveSplitWells:
    def test_removes_selected_splits(self):
        client = _SplitClient()
        client.split_wells("Plate6", "A1:A2")
        client.split_wells("Plate6", "A1", channel_type=SplitChannelType.FIVE_ML)
        reset(client)

        removed = client.remove_split_wells("Plate6", "A1", channel_type=SplitChannelType.ONE_ML)

        assert removed == ["plate6_a1_split_1ml_4slots"]
        assert actions(client) == [("labware.removeLabware", "plate6_a1_split_1ml_4slots")]
        assert {s.split_labware for s in client.get_split_wells()} == {
            "plate6_a2_split_1ml_4slots",
            "plate6_a1_split_5ml_2slots",
        }
        assert len(client.remove_split_wells()) == 2
        assert client.get_split_wells() == []

    def test_consolidates_volumes_onto_the_parent(self):
        client = _SplitClient()
        client.split_wells("Plate6", "A1", max_channels=2)
        details = MagicMock()
        details.return_parameters.labware = [
            MagicMock(wells=[MagicMock(volume=-300.0), MagicMock(volume=-200.0)]),
            MagicMock(wells=[MagicMock(volume=2000.0)]),
        ]
        client.get_labware_details = MagicMock(return_value=details)
        client.set_labware_volume = MagicMock()

        client.remove_split_wells("Plate6", consolidate_volumes=True)

        client.get_labware_details.assert_called_once_with(["plate6_a1_split_1ml_2slots", "plate6@A1"])
        client.set_labware_volume.assert_called_once_with("plate6@A1", 1500.0)


class TestLifecycle:
    def split(self, client=None):
        client = client or _SplitClient()
        client.split_wells("Plate6", "A1")
        reset(client)
        return client

    def test_remove_labware_removes_its_splits_first(self):
        client = self.split()

        client.remove_labware("Plate6")

        assert actions(client) == [
            ("labware.removeLabware", "plate6_a1_split_1ml_4slots"),
            ("labware.removeLabware", "Plate6"),
        ]
        assert client.get_split_wells() == []

    def test_removing_a_split_rack_directly_forgets_it(self):
        client = self.split()

        client.remove_labware("plate6_a1_split_1ml_4slots")

        assert actions(client) == [("labware.removeLabware", "plate6_a1_split_1ml_4slots")]
        assert client.get_split_wells() == []

    def test_removing_a_carrier_removes_splits_of_its_labware(self):
        client = self.split()
        on_carrier = MagicMock()
        on_carrier.return_parameters.labware = [MagicMock(labware_name="plate6")]
        client.get_labware_on_carrier = MagicMock(return_value=on_carrier)

        client.remove_labware("Carrier1")

        client.get_labware_on_carrier.assert_called_once_with("Carrier1")
        assert actions(client) == [
            ("labware.removeLabware", "plate6_a1_split_1ml_4slots"),
            ("labware.removeLabware", "Carrier1"),
        ]

    def test_tilt_rebuilds_for_the_new_angle(self):
        client = self.split()

        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT)

        assert actions(client) == [
            ("labware.removeLabware", "plate6_a1_split_1ml_4slots"),
            ("labware.tiltLabware", "Plate6"),
            ("labware.addSplitWellSite", "plate6_a1_split_1ml_3slots"),
        ]
        assert client.get_split_wells()[0].slot_count == 3

    def test_shift_rebuilds(self):
        client = self.split()

        client.shift_labware("Plate6", relative_x=1.0)

        assert [a for a, _ in actions(client)] == [
            "labware.removeLabware",
            "labware.shiftLabware",
            "labware.addSplitWellSite",
        ]

    def test_move_carrier_rebuilds_every_split(self):
        client = self.split()

        client.move_carrier("Carrier1", 10)

        assert [a for a, _ in actions(client)] == [
            "labware.removeLabware",
            "labware.moveCarrier",
            "labware.addSplitWellSite",
        ]

    @pytest.mark.parametrize("method", ["core_transport", "core_5ml_transport"])
    def test_core_transport_rebuilds_at_the_destination(self, method):
        client = self.split()

        getattr(client, method)("Plate6", "Carrier2", "1", 5.0)

        moved = "transport.1mL.moveLabware" if method == "core_transport" else "transport.5mL.moveLabware"
        assert [a for a, _ in actions(client)] == ["labware.removeLabware", moved, "labware.addSplitWellSite"]
        assert len(client.get_split_wells()) == 1

    def test_iswap_transport_rebuilds(self):
        client = self.split()

        client.iswap_transport("Plate6", "Carrier2", "1", 5.0)

        assert [a for a, _ in actions(client)] == [
            "labware.removeLabware",
            "transport.iswap.moveLabware",
            "labware.addSplitWellSite",
        ]

    def test_failed_transport_leaves_them_removed(self):
        client = self.split()
        client._star.venus.send_command.side_effect = [SUCCESS, RuntimeError("grip failed")]

        with pytest.raises(RuntimeError, match="grip failed"):
            client.core_transport("Plate6", "Carrier2", "1", 5.0)

        assert client.get_split_wells() == []

    def test_transport_to_waste_removes_them(self):
        client = self.split()

        client.core_transport_to_waste("Plate6", 5.0)

        assert [a for a, _ in actions(client)] == ["labware.removeLabware", "transport.1mL.moveToWaste"]
        assert client.get_split_wells() == []

    def test_iswap_get_then_put_rebuilds_on_put(self):
        client = self.split()

        client.iswap_get_labware("Plate6", 5.0)
        assert [a for a, _ in actions(client)] == ["labware.removeLabware", "transport.iswap.getLabware"]
        assert client.get_split_wells() == []

        client.iswap_put_labware("Carrier2", "1")
        assert [a for a, _ in actions(client)][-2:] == ["transport.iswap.putLabware", "labware.addSplitWellSite"]
        assert len(client.get_split_wells()) == 1

    def test_present_and_scan_then_return_rebuilds_on_return(self):
        client = self.split()

        client.core_present_and_scan("Plate6", "Carrier2", "1", 5.0, track=1, z_minimal_position=100.0)
        client.core_transport_return_plate()

        assert [a for a, _ in actions(client)] == [
            "labware.removeLabware",
            "transport.1mL.presentAndScan",
            "transport.1mL.returnLabware",
            "labware.addSplitWellSite",
        ]

    def test_other_labware_is_untouched(self):
        client = self.split()

        client.core_transport("Other", "Carrier2", "1", 5.0)
        client.remove_labware("Other")

        assert [a for a, _ in actions(client)] == ["transport.1mL.moveLabware", "labware.removeLabware"]
        assert len(client.get_split_wells()) == 1

    def test_deck_load_forgets_without_commands(self):
        client = self.split()

        client.deck_load("Saved")

        assert [a for a, _ in actions(client)] == ["deck.loadDeck"]
        assert client.get_split_wells() == []


class TestRouteSplitWells:
    @pytest.fixture
    def client(self):
        client = _SplitClient()
        client.split_wells("Plate6", "A1")
        return client

    def route(self, client, wells, channels, prefix="channels.1mL"):
        positions = [Position(labware=labware, well=well) for labware, well in wells]
        return [(p.labware, p.well) for p in route_split_wells(client, positions, channels, prefix)]

    def test_channels_sharing_a_split_well_go_to_its_slots(self, client):
        split = split_labware_id("plate6", "A1", "1mL", 4)

        routed = self.route(client, [("Plate6", "A1")] * 4, [1, 2, 3, 4])

        assert routed == [(split, "1"), (split, "2"), (split, "3"), (split, "4")]

    def test_slots_follow_the_channel_spacing(self, client):
        split = split_labware_id("plate6", "A1", "1mL", 4)

        assert self.route(client, [("plate6", "a1")] * 2, [5, 7]) == [(split, "1"), (split, "3")]

    def test_a_single_channel_keeps_the_well_centre(self, client):
        assert self.route(client, [("Plate6", "A1"), ("Plate6", "B1")], [1, 2]) == [("Plate6", "A1"), ("Plate6", "B1")]

    def test_other_channel_types_are_not_routed(self, client):
        wells = [("Plate6", "A1")] * 2

        assert self.route(client, wells, [1, 2], "channels.5mL") == wells
        assert self.route(client, wells, [1, 2], "channels.MagPip") == wells

    def test_too_many_channels_raise(self, client):
        with pytest.raises(SplitWellCapacityError, match="split into 4 slots"):
            self.route(client, [("Plate6", "A1")] * 5, [1, 2, 3, 4, 5])
        with pytest.raises(SplitWellCapacityError, match=r"\[1, 5\] span 5"):
            self.route(client, [("Plate6", "A1")] * 2, [1, 5])

    def test_nothing_split_is_a_no_op(self):
        positions = [Position(labware="Plate6", well="A1")] * 2

        assert route_split_wells(_SplitClient(), positions, [1, 2], "channels.1mL") is positions


class TestAspirateRouting:
    def test_aspirate_payload_uses_the_slots(self):
        with (
            patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls,
            patch.object(StarClient, "get_labware_spec", return_value=LabwareLayoutSpec.from_definition(PLATE_6)),
            patch.object(StarClient, "labware_get_params_from_id", return_value=definition_response(PLATE_6)),
        ):
            star = MagicMock()
            star.start = AsyncMock()
            star.stop = AsyncMock()
            star.venus.send_command = AsyncMock(return_value=SUCCESS)
            cls.return_value = star

            with StarClient(SdkConfig(base_url="http://test:42400")) as client:
                client.split_wells("Plate6", "A1")
                client.aspirate(channels=[1, 2, 3, 4], positions="Plate6@A1", volumes=100.0, liquid_class="Water")
                aspirate = star.venus.send_command.await_args.kwargs
                client.dispense(channels=[2], positions="Plate6@A1", volumes=100.0)
                dispense = star.venus.send_command.await_args.kwargs

        assert aspirate["action_name"] == "channels.1mL.aspirate"
        assert aspirate["parameters"]["positions"] == [
            {"labwareId": "plate6_a1_split_1ml_4slots", "wellId": well} for well in ("1", "2", "3", "4")
        ]
        assert dispense["parameters"]["positions"] == [{"labwareId": "Plate6", "wellId": "A1"}]


class TestPlateTipProfile:
    def test_a_1ml_split_reuses_the_tilt_tip_profile_and_a_5ml_split_does_not(self):
        narrow = TipProfile(end_radius_mm=0.3, radius_taper=0.05, max_radius_mm=1.0)
        client = _SplitClient()
        client.tilt_labware("Plate6", 10, well_position=TiltWellPosition.DEEPEST_POINT, tip_profile=narrow)

        (one,) = client.split_wells("Plate6", "A1", fit=2)
        (five,) = client.split_wells("Plate6", "A2", channel_type=SplitChannelType.FIVE_ML, fit=2)

        plan = {"pitch_mm": 9.0, "max_channels": 8, "tilt_degrees": 10, "well_position": TiltWellPosition.DEEPEST_POINT}
        assert one.plan.slots == compute_split_well_plan(PLATE_6, "A1", fit=2, tip=narrow, **plan).slots
        assert five.plan.x_shift_applied == compute_split_well_plan(
            PLATE_6,
            "A2",
            fit=2,
            tip=DEFAULT_TIP_PROFILES[SplitChannelType.FIVE_ML],
            parent_x_shift=client.get_tilt_settings("plate6").aim_x_shift,
            **{**plan, "pitch_mm": 18.0},
        ).x_shift_applied
