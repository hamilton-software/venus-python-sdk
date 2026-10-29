"""Unit tests for DeckStatusCommandsMixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.mixins.deck_status_commands import DeckStatusCommandsMixin
from hamilton_venus.models import CommandResponse
from hamilton_venus.star_client import StarClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        star = MagicMock()
        star.start = AsyncMock()
        star.stop = AsyncMock()

        venus_mock = MagicMock()
        venus_mock.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            ),
        )
        star.venus = venus_mock
        cls.return_value = star
        yield cls


class TestDeckStatusCommands:
    def test_layout_get_added_carriers(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"totalCarriers": 2, "carriersAdded": ["Carrier1", "Carrier2"]},
            )
        )

        with StarClient(config) as client:
            result = client.get_added_carriers()

        assert result.success is True
        assert result.return_parameters.total_carriers == 2
        assert result.return_parameters.carriers_added == ["Carrier1", "Carrier2"]
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAddedCarriers",
        )

    def test_layout_get_added_plates(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"totalPlates": 1, "platesAdded": ["Plate1"]},
            )
        )

        with StarClient(config) as client:
            result = client.get_added_plates()

        assert result.success is True
        assert result.return_parameters.total_plates == 1
        assert result.return_parameters.plates_added == ["Plate1"]
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAddedPlates",
        )

    def test_layout_get_added_tip_racks(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"totalTipRacks": 1, "tipRacksAdded": ["Rack1"]},
            )
        )

        with StarClient(config) as client:
            result = client.get_added_tip_racks()

        assert result.success is True
        assert result.return_parameters.total_tip_racks == 1
        assert result.return_parameters.tip_racks_added == ["Rack1"]
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAddedTipRacks",
        )

    def test_layout_get_added_reservoirs(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"reservoirsAdded": ["Reservoir1"]},
            )
        )

        with StarClient(config) as client:
            result = client.get_added_reservoirs()

        assert result.success is True
        assert result.return_parameters.reservoirs_added == ["Reservoir1"]
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAddedReservoirs",
        )

    def test_layout_get_available_tracks(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tracksAvailable": [1, 2, 3]},
            )
        )

        with StarClient(config) as client:
            result = client.get_available_tracks()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAvailableTracks",
        )

    def test_layout_get_occupied_tracks(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tracksOccupied": [5, 6]},
            )
        )

        with StarClient(config) as client:
            result = client.get_occupied_tracks()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getOccupiedTracks",
        )

    def test_layout_get_available_carrier_sites(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"availableSites": ["1", "2"]},
            )
        )

        with StarClient(config) as client:
            result = client.get_available_carrier_sites(carrier="Carrier1")

        assert result.success is True
        assert result.return_parameters.available_sites == ["1", "2"]
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getAvailableCarrierSites",
            parameters={"carrier": "Carrier1"},
        )

    def test_layout_get_occupied_carrier_sites(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"usedSites": [{"site": "3", "labwareCount": 1}]},
            )
        )

        with StarClient(config) as client:
            result = client.get_occupied_carrier_sites(carrier="Carrier1")

        assert result.success is True
        assert result.return_parameters.used_sites[0].site == "3"
        assert result.return_parameters.used_sites[0].labware_count == 1
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getOccupiedCarrierSites",
            parameters={"carrier": "Carrier1"},
        )

    def test_layout_get_labware_on_carrier(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "labware": [
                        {"labwareName": "Plate1", "labwareType": "plate"},
                        {"labwareName": "Rack1", "labwareType": "tipRack"},
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_labware_on_carrier(carrier="Carrier1")

        assert result.success is True
        assert result.return_parameters.labware[0].labware_name == "Plate1"
        assert result.return_parameters.labware[1].labware_type == "tipRack"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getLabwareOnCarrier",
            parameters={"carrier": "Carrier1"},
        )

    def test_layout_get_labware_positions(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "test plate": {"count": 2, "positions": ["A1", "B1"]},
                },
            )
        )

        with StarClient(config) as client:
            result = client.get_labware_positions(labware_name="test plate")

        assert result.success is True
        assert result.return_parameters.model_extra == {
            "test plate": {"count": 2, "positions": ["A1", "B1"]},
        }
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getLabwarePositions",
            parameters={"labwareName": "test plate"},
        )

    def test_layout_get_labware_positions_empty_response(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            )
        )

        with StarClient(config) as client:
            result = client.get_labware_positions(labware_name="Plate1")

        assert result.success is True
        assert not result.return_parameters.model_extra

    def test_layout_get_labware_location(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"carrier": "Carrier1", "site": "1"},
            )
        )

        with StarClient(config) as client:
            result = client.get_labware_location(labware_name="Plate1")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getLabwareLocation",
            parameters={"labwareName": "Plate1"},
        )

    def test_layout_get_top_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"labwareId": "Plate1", "type": "plate"},
            )
        )

        with StarClient(config) as client:
            result = client.get_top_labware(carrier_id="Carrier1", site="1")

        assert result.success is True
        assert result.return_parameters.labware_id == "Plate1"
        assert result.return_parameters.type == "plate"
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.getTopLabware",
            parameters={"carrierId": "Carrier1", "site": "1"},
        )

    def test_layout_is_track_occupied(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"isOccupied": True},
            )
        )

        with StarClient(config) as client:
            result = client.is_track_occupied(track_id=5)

        assert result.success is True
        assert result.return_parameters.is_occupied is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.isTrackOccupied",
            parameters={"trackId": 5},
        )

    def test_layout_is_track_occupied_false(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"isOccupied": False},
            )
        )

        with StarClient(config) as client:
            result = client.is_track_occupied(track_id=7)

        assert result.success is True
        assert result.return_parameters.is_occupied is False
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="status.isTrackOccupied",
            parameters={"trackId": 7},
        )


class _DeckStatusClient(DeckStatusCommandsMixin):
    def __init__(self, response: CommandResponse):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(return_value=response)

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)


def test_deck_status_mixin_layout_get_added_carriers():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"totalCarriers": 1, "carriersAdded": ["Carrier1"]},
        )
    )

    result = client.get_added_carriers()

    assert result.success is True
    assert result.return_parameters.total_carriers == 1
    assert result.return_parameters.carriers_added == ["Carrier1"]
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.getAddedCarriers",
    )


def test_deck_status_mixin_layout_get_labware_location():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"carrier": "Carrier1", "site": "1"},
        )
    )

    result = client.get_labware_location("Plate1")

    assert result.success is True
    assert result.return_parameters.carrier == "Carrier1"
    assert result.return_parameters.site == "1"
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.getLabwareLocation",
        parameters={"labwareName": "Plate1"},
    )


def test_deck_status_mixin_get_labware_coordinates_with_well():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"well": "A1", "x": 100.0, "y": 200.0, "z": 245.0, "angle": 0.0},
        )
    )

    result = client.get_labware_coordinates("Plate1", well="a1")

    params = result.return_parameters
    assert result.success is True
    assert (params.well, params.x, params.y, params.z, params.angle) == ("A1", 100.0, 200.0, 245.0, 0.0)
    assert params.origin is None
    assert params.wells is None
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.getLabwareCoordinates",
        parameters={"labwareName": "Plate1", "well": "a1"},
    )


def test_deck_status_mixin_get_labware_coordinates_rack_without_well():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "origin": {"x": 95.5, "y": 63.0, "z": 186.15, "angle": 0.0},
                "wells": [
                    {"well": "A1", "x": 100.0, "y": 200.0, "z": 245.0, "angle": 0.0},
                    {"well": "B1", "x": 100.0, "y": 191.0, "z": 245.0, "angle": 0.0},
                ],
            },
        )
    )

    result = client.get_labware_coordinates("Plate1")

    params = result.return_parameters
    assert (params.origin.x, params.origin.y, params.origin.z, params.origin.angle) == (95.5, 63.0, 186.15, 0.0)
    assert [(w.well, w.x, w.y) for w in params.wells] == [("A1", 100.0, 200.0), ("B1", 100.0, 191.0)]
    # The top-level coordinates are not filled in without a well.
    assert (params.well, params.x, params.y, params.z, params.angle) == (None, None, None, None, None)
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.getLabwareCoordinates",
        parameters={"labwareName": "Plate1"},
    )


def test_deck_status_mixin_get_labware_coordinates_carrier_origin_only():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"origin": {"x": 400.0, "y": 63.0, "z": 100.0, "angle": 0.0}},
        )
    )

    params = client.get_labware_coordinates("PlateCarrier").return_parameters

    assert params.origin.x == 400.0
    assert params.wells is None
    assert params.x is None


def test_deck_status_mixin_layout_get_top_labware():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"labwareId": "Plate1", "type": "plate"},
        )
    )

    result = client.get_top_labware(carrier_id="Carrier1", site="1")

    assert result.success is True
    assert result.return_parameters.labware_id == "Plate1"
    assert result.return_parameters.type == "plate"
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.getTopLabware",
        parameters={"carrierId": "Carrier1", "site": "1"},
    )


def test_deck_status_mixin_layout_is_track_occupied_false():
    client = _DeckStatusClient(
        CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"isOccupied": False},
        )
    )

    result = client.is_track_occupied(track_id=3)

    assert result.success is True
    assert result.return_parameters.is_occupied is False
    client._star.venus.send_command.assert_awaited_once_with(
        category="Deck Layout",
        action_name="status.isTrackOccupied",
        parameters={"trackId": 3},
    )
