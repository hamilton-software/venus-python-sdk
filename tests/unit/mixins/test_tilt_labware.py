"""Unit tests for tilt_labware and the transport guard on tilted labware."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.exceptions import LabwareTiltedError
from hamilton_venus.mixins.deck_labware_commands import DeckLabwareCommandsMixin
from hamilton_venus.mixins.transport_commands import TransportCommandsMixin
from hamilton_venus.models import (
    CommandResponse,
    LabwareDefinitionSingleResponse,
    LayoutTiltLabwareResponse,
    TiltPivotPoint,
    TiltWellPosition,
)
from hamilton_venus.star_client import StarClient
from hamilton_venus.tilt_clearance import TipClearance, TipProfile
from hamilton_venus.tilt_geometry import compute_tilt_well_deltas, well_aim_x_shift

LABWARE_DIR = Path(__file__).resolve().parents[3] / "sdk_method_structure" / "Labware" / "System"


def load(relative: str) -> dict:
    return json.loads((LABWARE_DIR / relative).read_text(encoding="utf-8-sig"))


COS_96_FL = load("plate/Cos_96_Fl.json")
COS_96_PCR = load("plate/Cos_96_PCR.json")
PLATE_6 = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "labware" / "Greiner_Culture_Plate_6.json").read_text(
        encoding="utf-8-sig"
    )
)
#: Small enough for the 6 mm wells of a 96-well plate to take one tilted tip.
NARROW_TIP = TipProfile(end_radius_mm=0.3, radius_taper=0.05, max_radius_mm=1.0)
SUCCESS = CommandResponse(return_status="Success", return_code=0, return_parameters={})


class _TiltClient(DeckLabwareCommandsMixin, TransportCommandsMixin):
    def __init__(self, definition: dict = COS_96_FL):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(return_value=SUCCESS)
        self.labware_get_params_from_id = MagicMock(
            return_value=LabwareDefinitionSingleResponse.model_validate(
                {"returnParameters": {"labwareName": "Plate_1", "definition": definition}}
            )
        )

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)


def sent_parameters(client) -> dict:
    return client._star.venus.send_command.await_args.kwargs["parameters"]


class TestTiltLabware:
    def test_sends_per_well_deltas(self):
        client = _TiltClient()

        result = client.tilt_labware("Plate_1", 7)

        assert isinstance(result, LayoutTiltLabwareResponse)
        client.labware_get_params_from_id.assert_called_once_with("Plate_1")
        call = client._star.venus.send_command.await_args.kwargs
        assert call["category"] == "Deck Layout"
        assert call["action_name"] == "labware.tiltLabware"
        params = call["parameters"]
        assert {k: v for k, v in params.items() if k != "wells"} == {
            "labwareName": "Plate_1",
            "tiltDegrees": 7,
            "pivotPoint": "LeftEdge",
            "pivotXOffset": 0.0,
            "pivotZOffset": 0.0,
            "wellPosition": "Center",
        }
        assert len(params["wells"]) == 96
        a1, h12 = params["wells"][0], params["wells"][-1]
        assert a1["well"] == "A1" and h12["well"] == "H12"
        assert set(a1) == {"well", "deltaX", "deltaY", "deltaZ"}
        assert a1["deltaY"] == 0.0
        assert a1["deltaX"] == pytest.approx(-0.5394, abs=1e-4)
        assert a1["deltaZ"] == pytest.approx(5.2496, abs=1e-4)
        assert h12["deltaZ"] == pytest.approx(17.3146, abs=1e-4)

    def test_zero_degrees_sends_nominal_wells_at_the_center(self):
        client = _TiltClient()

        client.tilt_labware("Plate_1", 0, TiltPivotPoint.CENTER, well_position=TiltWellPosition.DEEPEST_POINT)

        params = sent_parameters(client)
        assert params["pivotPoint"] == "Center"
        assert params["wellPosition"] == "Center"  # 0 degrees always returns to the well centre
        assert all(w["deltaX"] == 0.0 and w["deltaZ"] == 3.57 for w in params["wells"])

    @pytest.mark.parametrize(
        ("position", "wire"),
        [(TiltWellPosition.DEEPEST_POINT, "DeepestPoint"), (TiltWellPosition.HIGHEST_POINT, "HighestPoint")],
    )
    def test_options_are_passed_through(self, position, wire):
        client = _TiltClient()

        client.tilt_labware(
            "Plate_1",
            5,
            TiltPivotPoint.CENTER,
            pivot_x_offset_mm=1.5,
            pivot_z_offset_mm=2.0,
            well_position=position,
            tip_profile=NARROW_TIP,
            wall_margin_mm=0.3,
            high_wall_margin_mm=0.3,
        )

        params = sent_parameters(client)
        assert (params["pivotXOffset"], params["pivotZOffset"], params["wellPosition"]) == (1.5, 2.0, wire)

    def test_measured_angle_drives_the_offsets_but_venus_gets_the_commanded_one(self):
        client = _TiltClient(PLATE_6)

        client.tilt_labware("Plate_1", 10, well_position=TiltWellPosition.DEEPEST_POINT, measured_tilt_degrees=10.8)

        params = sent_parameters(client)
        assert params["tiltDegrees"] == 10
        expected = compute_tilt_well_deltas(PLATE_6, 10.8, well_position=TiltWellPosition.DEEPEST_POINT)
        assert [w["deltaZ"] for w in params["wells"]] == pytest.approx([d.dz for d in expected])
        settings = client.get_tilt_settings("PLATE_1")
        assert (settings.tilt_degrees, settings.angle_degrees) == (10, 10.8)
        assert client.get_tilted_labware() == {"plate_1": 10}

    def test_fractional_degrees_are_sent(self):
        client = _TiltClient()

        client.tilt_labware("Plate_1", 7.5)

        assert sent_parameters(client)["tiltDegrees"] == 7.5
        assert client.get_tilted_labware() == {"plate_1": 7.5}

    def test_measured_angle_needs_a_tilt(self):
        client = _TiltClient()

        with pytest.raises(ValueError, match="measured_tilt_degrees needs tilt_degrees > 0"):
            client.tilt_labware("Plate_1", 0, measured_tilt_degrees=1.0)
        with pytest.raises(ValueError, match="measured_tilt_degrees 16 out of range"):
            client.tilt_labware("Plate_1", 10, measured_tilt_degrees=16)
        client._star.venus.send_command.assert_not_awaited()

    def test_clearance_settings_are_kept_for_the_plate(self):
        client = _TiltClient(PLATE_6)

        client.tilt_labware(
            "Plate_1",
            10,
            well_position=TiltWellPosition.HIGHEST_POINT,
            tip_end_height_mm=2.0,
            wall_margin_mm=1.5,
            high_wall_margin_mm=2.5,
        )

        settings = client.get_tilt_settings("plate_1")
        clearance = TipClearance(tip_end_height_mm=2.0, wall_margin_mm=1.5, high_wall_margin_mm=2.5)
        assert settings.clearance == clearance
        assert settings.tip_profile is None
        assert settings.aim_x_shift == well_aim_x_shift(PLATE_6, 10, TiltWellPosition.HIGHEST_POINT, clearance)

        client.tilt_labware("Plate_1", 0)
        assert client.get_tilt_settings("plate_1") is None

    def test_no_room_for_a_tip_raises_before_sending(self):
        client = _TiltClient(COS_96_PCR)

        with pytest.raises(ValueError, match="a single tip does not fit"):
            client.tilt_labware("Plate_1", 10, well_position=TiltWellPosition.DEEPEST_POINT)
        client._star.venus.send_command.assert_not_awaited()
        assert client.get_tilted_labware() == {}

    def test_rejects_non_plate_without_sending(self):
        client = _TiltClient(load("reservoir/Ham_DW_Rgt.json"))

        with pytest.raises(ValueError, match="only plates"):
            client.tilt_labware("Trough_1", 5)
        client._star.venus.send_command.assert_not_awaited()

    def test_rejects_bad_angle_before_any_lookup(self):
        client = _TiltClient()

        with pytest.raises(ValueError):
            client.tilt_labware("Plate_1", 11)
        client.labware_get_params_from_id.assert_not_called()
        client._star.venus.send_command.assert_not_awaited()


class TestTiltTracking:
    def test_tilt_and_untilt_are_tracked_case_insensitively(self):
        client = _TiltClient()

        client.tilt_labware("Plate_1", 7)
        assert client.is_labware_tilted("plate_1")
        assert client.get_tilted_labware() == {"plate_1": 7}

        client.tilt_labware("PLATE_1", 0)
        assert not client.is_labware_tilted("Plate_1")
        assert client.get_tilted_labware() == {}

    def test_failed_command_does_not_mark_tilted(self):
        client = _TiltClient()
        client._star.venus.send_command.side_effect = RuntimeError("VENUS rejected it")

        with pytest.raises(RuntimeError):
            client.tilt_labware("Plate_1", 7)
        assert not client.is_labware_tilted("Plate_1")

    def test_remove_labware_clears_tilt(self):
        client = _TiltClient()
        client.tilt_labware("Plate_1", 7)

        client.remove_labware("Plate_1")

        assert not client.is_labware_tilted("Plate_1")


GUARDED_TRANSPORTS = [
    ("core_transport", {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0}),
    ("core_transport_to_waste", {"grip_height_above_bottom": 3.0}),
    (
        "core_present_and_scan",
        {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0, "track": 1, "z_minimal_position": 0.0},
    ),
    ("core_hold_lid", {"grip_height_from_top": 3.0}),
    ("core_5ml_transport", {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0}),
    ("core_5ml_transport_to_waste", {"grip_height_above_bottom": 3.0}),
    (
        "core_5ml_present_and_scan",
        {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0, "track": 1, "z_minimal_position": 0.0},
    ),
    ("core_5ml_hold_lid", {"grip_height_from_top": 3.0}),
    ("iswap_transport", {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0}),
    ("iswap_transport_to_waste", {"grip_height_above_bottom": 3.0}),
    (
        "iswap_present_and_scan",
        {"carrier": "C", "site": "1", "grip_height_above_bottom": 3.0, "track": 1, "z_minimal_position": 0.0},
    ),
    ("iswap_get_labware", {"grip_height_above_bottom": 3.0}),
]


class TestTransportGuard:
    @pytest.mark.parametrize(("method", "kwargs"), GUARDED_TRANSPORTS)
    def test_tilted_labware_cannot_be_transported(self, method, kwargs):
        client = _TiltClient()
        client.tilt_labware("Plate_1", 5)
        client._star.venus.send_command.reset_mock()

        with pytest.raises(LabwareTiltedError, match="tilt_labware"):
            getattr(client, method)(labware_name="PLATE_1", **kwargs)
        client._star.venus.send_command.assert_not_awaited()

    def test_transport_works_again_after_untilt(self):
        client = _TiltClient()
        client.tilt_labware("Plate_1", 5)
        client.tilt_labware("Plate_1", 0)
        client._star.venus.send_command.reset_mock()

        client.core_transport("Plate_1", "C", "1", 3.0)

        assert client._star.venus.send_command.await_args.kwargs["action_name"] == "transport.1mL.moveLabware"

    def test_other_labware_is_not_blocked(self):
        client = _TiltClient()
        client.tilt_labware("Plate_1", 5)

        client.iswap_transport("Plate_2", "C", "1", 3.0)


def test_star_client_tilt_then_transport_is_blocked():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        star = MagicMock()
        star.start = AsyncMock()
        star.stop = AsyncMock()
        star.venus = MagicMock()
        star.venus.send_command = AsyncMock(
            side_effect=[
                CommandResponse(
                    return_status="Success",
                    return_code=0,
                    return_parameters={"labwareName": "plate_1", "definition": COS_96_FL},
                ),
                CommandResponse(
                    return_status="Success",
                    return_code=0,
                    return_parameters={
                        "labwareName": "plate_1",
                        "tiltDegrees": 4.0,
                        "wells": [{"well": "A1", "x": 275.5, "y": 146.0, "z": 105.37}],
                    },
                ),
            ]
        )
        cls.return_value = star

        with StarClient(SdkConfig(base_url="http://test:42400")) as client:
            result = client.tilt_labware("Plate_1", 4)
            assert result.return_parameters.tilt_degrees == 4.0
            assert result.return_parameters.wells[0].well == "A1"
            assert result.return_parameters.wells[0].z == pytest.approx(105.37)
            with pytest.raises(LabwareTiltedError):
                client.iswap_transport("Plate_1", "C", "1", 3.0)

        assert star.venus.send_command.await_count == 2
