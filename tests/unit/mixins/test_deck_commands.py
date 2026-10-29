"""Unit tests for DeckCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
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


class TestDeckCommands:
    def test_deck_get_previous(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"isAvailable": True},
            )
        )

        with StarClient(config) as client:
            result = client.deck_get_previous()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.getPreviousDeck",
        )

    def test_deck_get_saved(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"savedDecks": ["deck1", "deck2"]},
            )
        )

        with StarClient(config) as client:
            result = client.deck_get_saved()

        assert result.success is True
        assert result.return_parameters.saved_decks == ["deck1", "deck2"]

    def test_deck_load(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.deck_load(deck_name="my_deck")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.loadDeck",
            parameters={"deck": "my_deck", "previous": False},
        )

    def test_deck_load_previous_true(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.deck_load(previous=True)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.loadDeck",
            parameters={"previous": True},
        )

    def test_deck_save(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.deck_save(deck_name="my_deck")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.saveDeck",
            parameters={"name": "my_deck", "overwrite": False},
        )

    def test_deck_save_overwrite_true(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.deck_save(deck_name="my_deck", overwrite=True)

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.saveDeck",
            parameters={"name": "my_deck", "overwrite": True},
        )

    def test_deck_delete_saved(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.deck_delete_saved(deck_name="my_deck")

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.deleteSavedDeck",
            parameters={"name": "my_deck"},
        )

    def test_deck_import(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "carriersAdded": [
                        {
                            "labwareName": "Carrier_1",
                            "leftTrack": 10,
                            "x": 1.0,
                            "y": 2.0,
                            "z": 3.0,
                            "angle": 4.0,
                        }
                    ]
                },
            )
        )

        with StarClient(config) as client:
            result = client.deck_import(path="C:\\Layouts\\layout.lay")

        assert result.success is True
        assert result.return_parameters.carriers_added[0].labware_name == "Carrier_1"
        assert result.return_parameters.carriers_added[0].left_track == 10
        star.venus.send_command.assert_awaited_once_with(
            category="Deck Layout",
            action_name="deck.importDeck",
            parameters={"path": "C:\\Layouts\\layout.lay"},
        )

    def test_deck_get_rack_ids_from_deck(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "racksFound": {
                        "LiquidWaste_0001": {
                            "file": "C:\\Users\\User\\Documents\\LiquidWaste.rck",
                            "x": 1332,
                            "y": 341,
                            "z": 187,
                            "angle": 0,
                        },
                        "Ham_ComfortLid_Waste": {
                            "file": "C:\\Users\\User\\Documents\\Ham_1_NB_Lid_ODTC_V1.0.rck",
                            "x": 1415,
                            "y": 300,
                            "z": 265,
                            "angle": 180,
                        },
                    }
                },
            )
        )

        with StarClient(config) as client:
            result = client.deck_get_rack_ids_from_deck(
                path="C:\\Layouts\\layout.lay",
                carrier_filter=["SomeCarrier"],
                only_floating_racks=True,
            )

        assert result.success is True
        assert "LiquidWaste_0001" in result.return_parameters.racks_found
        rack_file = result.return_parameters.racks_found["LiquidWaste_0001"].file
        assert rack_file == "C:\\Users\\User\\Documents\\LiquidWaste.rck"
        assert result.return_parameters.racks_found["LiquidWaste_0001"].x == 1332
        assert "Ham_ComfortLid_Waste" in result.return_parameters.racks_found
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "deck.GetRackIdsFromDeck"
        assert call_args.kwargs["parameters"]["path"] == "C:\\Layouts\\layout.lay"
        assert call_args.kwargs["parameters"]["carrierFilter"] == ["SomeCarrier"]
        assert call_args.kwargs["parameters"]["onlyFloatingRacks"] is True

    def test_deck_get_rack_ids_from_deck_minimal(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"racksFound": {}},
            )
        )

        with StarClient(config) as client:
            result = client.deck_get_rack_ids_from_deck(path="C:\\Layouts\\layout.lay")

        assert result.success is True
        assert len(result.return_parameters.racks_found) == 0
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "deck.GetRackIdsFromDeck"
        assert call_args.kwargs["parameters"]["path"] == "C:\\Layouts\\layout.lay"

    def test_deck_import_rack_as_site(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"siteAdded": "plate sealer"},
            )
        )

        with StarClient(config) as client:
            result = client.deck_import_rack_as_site(
                path="C:\\Layouts\\layout.lay",
                target_labware_name="sealer",
                site_name="plate sealer",
            )

        assert result.success is True
        assert result.return_parameters.site_added == "plate sealer"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "deck.importRackAsSite"
        assert call_args.kwargs["parameters"]["path"] == "C:\\Layouts\\layout.lay"
        assert call_args.kwargs["parameters"]["targetLabwareName"] == "sealer"
        assert call_args.kwargs["parameters"]["siteName"] == "plate sealer"

    def test_deck_import_rack_as_site_minimal(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"siteAdded": "sealer"},
            )
        )

        with StarClient(config) as client:
            result = client.deck_import_rack_as_site(
                path="C:\\Layouts\\layout.lay",
                target_labware_name="sealer",
            )

        assert result.success is True
        assert result.return_parameters.site_added == "sealer"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "deck.importRackAsSite"
        assert call_args.kwargs["parameters"]["path"] == "C:\\Layouts\\layout.lay"
        assert call_args.kwargs["parameters"]["targetLabwareName"] == "sealer"
        assert "siteName" not in call_args.kwargs["parameters"]
