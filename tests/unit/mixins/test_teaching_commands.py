"""Unit tests for TeachingCommandsMixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from hamilton_venus.mixins.teaching_commands import TeachingCommandsMixin
from hamilton_venus.models import (
    CommandResponse,
    LabwareCoordinatesResponse,
    LabwareDefinitionSingleResponse,
    TeachingDirection,
    TeachingMeasureStatus,
)
from hamilton_venus.star_client import StarClient
from hamilton_venus.taught_locations import LabwarePosition
from hamilton_venus.teaching import TeachingError
from hamilton_venus.vantage_client import VantageClient

_STATUS_NAMES = {0: "WALL_NOT_FOUND", 1: "WALL_FOUND", 2: "FOUND_EARLY"}


def _status(code: int) -> dict:
    return {"code": code, "name": _STATUS_NAMES[code]}


class _TeachingClient(TeachingCommandsMixin):
    def __init__(self, return_parameters: dict | None = None):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters=return_parameters or {}
            )
        )
        self.registered: list[tuple] = []

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)

    @property
    def sent(self):
        return self._star.venus.send_command.await_args

    def get_labware_coordinates(self, labware_name, well=None):
        # Origin and first position differ, so registering against the wrong one shows up.
        return LabwareCoordinatesResponse(
            return_parameters={
                "origin": {"x": 186.0, "y": 75.5, "z": 116.8, "angle": 0.0},
                "wells": [
                    {"well": "A1", "x": 200.0, "y": 150.0, "z": 120.0, "angle": 0.0},
                    {"well": "B1", "x": 200.0, "y": 141.0, "z": 120.0, "angle": 0.0},
                ],
            }
        )

    def labware_definition_get_params_from_id(self, labware_name):
        return LabwareDefinitionSingleResponse(
            return_parameters={
                "labwareName": labware_name,
                "definition": {
                    "containerGrids": {
                        "default": {"containerDefinition": {"openingDimensions": {"shape": "circle", "diameter": 6.9}}}
                    }
                },
            }
        )

    def register_taught_position(self, labware, carrier, site, *, x, y, z, angle=0.0, note=None):
        self.registered.append((labware, carrier, site, x, y, z, angle, note))
        return LabwarePosition(labware=labware, carrier=carrier, site=str(site), x=x, y=y, z=z, angle=angle, note=note)


class _SimulatedWell:
    """Answers teaching commands for one round well whose true position differs from the definition."""

    def __init__(
        self,
        *,
        center=(101.2, 199.5),
        radius=3.45,
        entrance_z=150.0,
        bottom_z=139.6,
        expected=(100.0, 200.0, 139.1),
        depth=10.9,
        statuses=None,
        bottom_status=1,
        needle=True,
    ):
        self.center = center
        self.radius = radius
        self.entrance_z = entrance_z
        self.bottom_z = bottom_z
        self.expected = expected
        self.depth = depth
        self.statuses = statuses or {}
        self.bottom_status = bottom_status
        self.needle = needle
        self.position = [0.0, 0.0, 245.0]
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, *, category, action_name, parameters):
        assert category == "Teaching"
        action = action_name.removeprefix("teaching.1mL.")
        self.calls.append((action, dict(parameters)))
        handler = {
            "isNeedlePickedUp": self._is_needle_picked_up,
            "getLabwareDimensions": self._get_labware_dimensions,
            "moveChannelToPosition": self._move_channel,
            "measureXY": self._measure_xy,
            "measureZHeight": self._measure_z,
        }[action]
        return CommandResponse(
            category=category, action_name=action_name, return_status="Success", return_parameters=handler(parameters)
        )

    def _is_needle_picked_up(self, _):
        return {"isNeedlePickedUp": self.needle}

    def _get_labware_dimensions(self, parameters):
        ex, ey, ez = self.expected
        return {
            "labware": {
                "labwareId": parameters["labwareName"],
                "center": {"x": 150.0, "y": 180.0},
                "bottomZ": 135.0,
                "height": 14.4,
            },
            "well": {
                "positionId": parameters.get("well", "A1").upper(),
                "center": {"x": ex, "y": ey},
                "bottomZ": ez,
                "depth": self.depth,
            },
        }

    def _move_channel(self, parameters):
        for index, key in enumerate("xyz"):
            if key in parameters:
                self.position[index] = parameters[key]
        return dict(zip("xyz", self.position, strict=True))

    def _measure_xy(self, parameters):
        direction = TeachingDirection(parameters["direction"])
        code = self.statuses.get(direction, 1)
        axis = 0 if direction in (TeachingDirection.PLUS_X, TeachingDirection.MINUS_X) else 1
        sign = 1 if direction in (TeachingDirection.PLUS_X, TeachingDirection.PLUS_Y) else -1
        wall = round(self.center[axis] + sign * (self.radius - 0.15), 2)
        self.position[axis] = wall
        entrance = self.entrance_z + {1: 0.1, 2: -0.1, 3: 0.2, 4: 0.0}[int(direction)]
        return {
            "wall": ["+X", "-X", "+Y", "-Y"][int(direction) - 1],
            "status": _status(code),
            "measured": {"axis": "xy"[axis], "wallCoordinate": wall, "entranceZ": entrance},
        }

    def _measure_z(self, parameters):
        return {"measuredZ": self.bottom_z, "status": _status(self.bottom_status)}

    def actions(self):
        return [action for action, _ in self.calls]


def _client_for(well: _SimulatedWell) -> _TeachingClient:
    client = _TeachingClient()
    client._star.venus.send_command = AsyncMock(side_effect=well)
    return client


# --- single commands ----------------------------------------------------------------


def test_set_channel_payload():
    client = _TeachingClient({"channel": 4})
    result = client.teaching_set_channel(4)
    assert result.return_parameters.channel == 4
    assert client.sent.kwargs == {
        "category": "Teaching",
        "action_name": "teaching.1mL.setTeachingChannel",
        "parameters": {"channel": 4},
    }


def test_set_channel_rejects_zero():
    with pytest.raises(ValidationError):
        _TeachingClient().teaching_set_channel(0)


@pytest.mark.parametrize(
    ("method", "action"),
    [
        ("teaching_get_channel", "getTeachingChannel"),
        ("teaching_pickup_needle", "pickupTeachingNeedle"),
        ("teaching_eject_needle", "ejectTeachingNeedle"),
    ],
)
def test_no_parameter_commands(method, action):
    client = _TeachingClient({"channel": 8})
    getattr(client, method)()
    assert client.sent.kwargs == {"category": "Teaching", "action_name": f"teaching.1mL.{action}", "parameters": {}}


def test_is_needle_picked_up():
    assert (
        _TeachingClient({"isNeedlePickedUp": True}).teaching_is_needle_picked_up().return_parameters.is_needle_picked_up
        is True
    )
    assert (
        _TeachingClient({"isNeedlePickedUp": False})
        .teaching_is_needle_picked_up()
        .return_parameters.is_needle_picked_up
        is False
    )


def test_get_labware_dimensions():
    client = _TeachingClient(
        {
            "labware": {"labwareId": "plate_1", "center": {"x": 245.3, "y": 146.05}, "bottomZ": 102.5, "height": 14.35},
            "well": {"positionId": "A1", "center": {"x": 196.3, "y": 177.55}, "bottomZ": 103.6, "depth": 10.9},
        }
    )
    result = client.teaching_get_labware_dimensions("Plate_1", "A1").return_parameters
    assert client.sent.kwargs["parameters"] == {"labwareName": "Plate_1", "well": "A1"}
    assert result.labware.center.x == 245.3
    assert result.labware.height == 14.35
    assert result.well.position_id == "A1"
    assert result.well.entrance_z == pytest.approx(114.5)


def test_get_labware_dimensions_without_well_omits_it():
    client = _TeachingClient({})
    client.teaching_get_labware_dimensions("Plate_1")
    assert client.sent.kwargs["parameters"] == {"labwareName": "Plate_1"}


def test_move_channel_sends_only_given_axes():
    client = _TeachingClient({"x": 100.0, "y": 200.0, "z": 150.0})
    result = client.teaching_move_channel(x=100.0, z=150.0, z_traverse=245.0)
    assert client.sent.kwargs["parameters"] == {"x": 100.0, "z": 150.0, "zTraverse": 245.0}
    assert result.return_parameters.z == 150.0


def test_move_channel_rejects_z_out_of_range():
    with pytest.raises(ValidationError):
        _TeachingClient().teaching_move_channel(z=250.0)


def test_measure_z_payload_and_status():
    client = _TeachingClient({"measuredZ": 139.6, "status": _status(1)})
    result = client.teaching_measure_z(150.0, 134.1).return_parameters
    assert client.sent.kwargs["parameters"] == {"zStart": 150.0, "zMin": 134.1, "zEnd": -1.0}
    assert result.measured_z == 139.6
    assert result.status.measure_status == TeachingMeasureStatus.FOUND


def test_measure_z_slow():
    client = _TeachingClient({"measuredZ": 0.0, "status": _status(0)})
    client.teaching_measure_z(150.0, 134.1, slow=True)
    assert client.sent.kwargs["parameters"]["useSlowSpeed"] is True


def test_measure_wall_payload_and_response():
    client = _TeachingClient(
        {"wall": "-Y", "status": _status(1), "measured": {"axis": "y", "wallCoordinate": 196.2, "entranceZ": 150.1}}
    )
    result = client.teaching_measure_wall(
        TeachingDirection.MINUS_Y, safe_height=155.0, min_search_z=147.0, well_width=6.9
    ).return_parameters
    assert client.sent.kwargs["action_name"] == "teaching.1mL.measureXY"
    assert client.sent.kwargs["parameters"] == {
        "safeHeight": 155.0,
        "minSearchZ": 147.0,
        "wellWidth": 6.9,
        "direction": 4,
    }
    assert result.measured is not None
    assert result.measured.wall_coordinate == 196.2
    assert result.status.measure_status == TeachingMeasureStatus.FOUND


def test_measure_wall_rejects_step_out_of_range():
    with pytest.raises(ValidationError):
        _TeachingClient().teaching_measure_wall(
            TeachingDirection.PLUS_X, safe_height=155.0, min_search_z=147.0, well_width=6.9, step_distance=3.0
        )


# --- teach_well -----------------------------------------------------------------------


def test_teach_well_finds_center_and_bottom():
    well = _SimulatedWell()
    client = _client_for(well)

    result = client.teach_well("Plate_1", "a1", well_width=6.9)

    assert result.well == "A1"
    assert [wall.wall for wall in result.walls] == ["+X", "-X", "+Y", "-Y"]
    assert result.center.x == pytest.approx(101.2)
    assert result.center.y == pytest.approx(199.5)
    assert result.entrance_z == pytest.approx(150.1)
    assert result.measured_bottom_z == pytest.approx(139.6)
    assert result.bottom_z == pytest.approx(139.6)
    assert result.offset.x == pytest.approx(1.2)
    assert result.offset.y == pytest.approx(-0.5)
    assert result.offset.z == pytest.approx(0.5)
    assert result.taught_position is None
    assert well.actions() == [
        "isNeedlePickedUp",
        "getLabwareDimensions",
        "moveChannelToPosition",  # over the expected well at its entrance
        "measureXY",  # +X
        "moveChannelToPosition",
        "measureXY",  # -X
        "moveChannelToPosition",
        "measureXY",  # +Y
        "moveChannelToPosition",
        "measureXY",  # -Y
        "moveChannelToPosition",
        "measureZHeight",
        "moveChannelToPosition",  # lift
    ]


def test_teach_well_move_and_search_parameters():
    well = _SimulatedWell()
    client = _client_for(well)
    client.teach_well("Plate_1", "A1", well_width=6.9)
    calls = well.calls

    assert calls[2][1] == {"x": 100.0, "y": 200.0, "z": 150.0, "zTraverse": 245.0}
    assert calls[3][1] == {
        "safeHeight": 155.0,
        "minSearchZ": 147.0,
        "wellWidth": 6.9,
        "direction": 1,
        "stepDistance": 0.6,
    }
    # second X wall starts 0.75 * width back from the +X wall, along the start Y
    plus_x = round(101.2 + 3.45 - 0.15, 2)
    assert calls[4][1] == {"x": round(plus_x - 0.75 * 6.9, 1), "y": 200.0, "z": 155.0, "zTraverse": 155.0}
    assert calls[5][1]["direction"] == 2
    assert calls[6][1] == {"x": 101.2, "y": 200.0, "z": 155.0, "zTraverse": 155.0}
    assert calls[7][1]["direction"] == 3
    assert calls[9][1]["direction"] == 4
    assert calls[10][1] == {"x": 101.2, "y": 199.5, "z": 155.0, "zTraverse": 155.0}
    # bottom search from the measured entrance to depth + 5 mm below it
    assert calls[11][1] == {"zStart": 150.1, "zMin": round(150.1 - 10.9 - 5.0, 1), "zEnd": -1.0}
    assert calls[12][1] == {"z": 245.0}


def test_teach_well_z_offset():
    client = _client_for(_SimulatedWell())
    result = client.teach_well("Plate_1", "A1", well_width=6.9, z_offset=0.5)
    assert result.measured_bottom_z == pytest.approx(139.6)
    assert result.bottom_z == pytest.approx(140.1)
    assert result.offset.z == pytest.approx(1.0)


def test_teach_well_per_axis_widths_and_definition_default():
    well = _SimulatedWell()
    _client_for(well).teach_well("Plate_1", "A1", well_width=(8.0, 7.0))
    assert [params["wellWidth"] for action, params in well.calls if action == "measureXY"] == [8.0, 8.0, 7.0, 7.0]

    well = _SimulatedWell()
    _client_for(well).teach_well("Plate_1", "A1")
    assert {params["wellWidth"] for action, params in well.calls if action == "measureXY"} == {6.9}


def test_teach_well_z_only():
    well = _SimulatedWell()
    result = _client_for(well).teach_well("Plate_1", "A1", teach_z_only=True)
    assert "measureXY" not in well.actions()
    assert result.walls == []
    assert (result.center.x, result.center.y) == (100.0, 200.0)
    assert result.entrance_z == 150.0
    assert result.offset.x == 0.0


def test_teach_well_from_current_position():
    well = _SimulatedWell()
    well.position = [100.5, 199.0, 150.0]
    _client_for(well).teach_well("Plate_1", "A1", well_width=6.9, move_to_well=False)
    assert well.calls[2] == ("moveChannelToPosition", {})


def test_teach_well_requires_needle():
    well = _SimulatedWell(needle=False)
    with pytest.raises(TeachingError, match="no teaching needle"):
        _client_for(well).teach_well("Plate_1", "A1", well_width=6.9)
    assert well.actions() == ["isNeedlePickedUp"]


@pytest.mark.parametrize(
    ("status", "message"),
    [(TeachingMeasureStatus.NOT_FOUND, "was not found"), (TeachingMeasureStatus.FOUND_EARLY, "unexpected Z stall")],
)
def test_teach_well_wall_failure_lifts_and_raises(status, message):
    well = _SimulatedWell(statuses={TeachingDirection.MINUS_X: int(status)})
    with pytest.raises(TeachingError, match=message) as excinfo:
        _client_for(well).teach_well("Plate_1", "A1", well_width=6.9)
    assert excinfo.value.wall == "-X"
    assert excinfo.value.status == status
    assert well.calls[-1] == ("moveChannelToPosition", {"z": 245.0})
    assert "measureZHeight" not in well.actions()


def test_teach_well_bottom_not_found_lifts_and_raises():
    well = _SimulatedWell(bottom_status=0)
    with pytest.raises(TeachingError, match="well bottom was not found"):
        _client_for(well).teach_well("Plate_1", "A1", well_width=6.9)
    assert well.calls[-1] == ("moveChannelToPosition", {"z": 245.0})


def test_teach_well_failed_lift_does_not_mask_error():
    well = _SimulatedWell(bottom_status=0)
    original = well._move_channel

    def failing_lift(parameters):
        if parameters == {"z": 245.0}:
            raise RuntimeError("lift failed")
        return original(parameters)

    well._move_channel = failing_lift
    with pytest.raises(TeachingError):
        _client_for(well).teach_well("Plate_1", "A1", well_width=6.9)


def test_teach_well_register():
    # Registers the first position (A1: 200.0, 150.0, 120.0) + offset, not the origin + offset:
    # VENUS applies the taught position as the first position's coordinates.
    client = _client_for(_SimulatedWell())
    result = client.teach_well("Plate_1", "A1", well_width=6.9, register=True, carrier="PltCar_1", site=2)
    assert client.registered == [("Plate_1", "PltCar_1", 2, 201.2, 149.5, 120.5, 0.0, "auto-teach A1")]
    assert result.taught_position is not None
    assert result.taught_position.x == 201.2


def test_teach_well_register_without_positions_raises():
    client = _client_for(_SimulatedWell())
    client.get_labware_coordinates = lambda labware_name, well=None: LabwareCoordinatesResponse(
        return_parameters={"origin": {"x": 186.0, "y": 75.5, "z": 116.8, "angle": 0.0}}
    )
    with pytest.raises(TeachingError, match="no position coordinates"):
        client.teach_well("Plate_1", "A1", well_width=6.9, register=True, carrier="PltCar_1", site=2)
    assert client.registered == []


def test_teach_well_register_needs_carrier_and_site():
    well = _SimulatedWell()
    with pytest.raises(ValueError, match="carrier and site"):
        _client_for(well).teach_well("Plate_1", "A1", well_width=6.9, register=True)
    assert well.calls == []


@pytest.mark.parametrize("client_class", [StarClient, VantageClient])
def test_clients_include_teaching_mixin(client_class):
    assert issubclass(client_class, TeachingCommandsMixin)
