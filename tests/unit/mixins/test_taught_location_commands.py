"""Unit tests for TaughtLocationCommandsMixin.

These commands are local file I/O only -- they never touch the instrument -- so
the tests drive a client that is never connected or initialized, and point
``_taught_locations_path`` at a temp file.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import CommandResponse
from hamilton_venus.star_client import StarClient
from hamilton_venus.vantage_client import VantageClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        inst = MagicMock()
        inst.start = AsyncMock()
        inst.stop = AsyncMock()
        venus_mock = MagicMock()
        venus_mock.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={}),
        )
        inst.venus = venus_mock
        cls.return_value = inst
        yield cls


@pytest.fixture
def store(tmp_path):
    return tmp_path / "TaughtLocations.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("client_cls", [StarClient, VantageClient])
def test_register_and_lookup_offline(client_cls, config, mock_async_star_class, store):
    with client_cls(config) as client:
        client._taught_locations_path = str(store)

        # Mixed-case input is stored lower-cased, keys included.
        client.register_taught_offset("CAR_1", 3, dx=0.4, dy=-0.2, dz=0.1)
        client.register_taught_position("Plate_01", "CAR_1", 3, x=1.0, y=2.0, z=3.0)
        client.register_taught_position("plate_01", "car_1", 3, x=9.0, y=2.0, z=3.0)
        client.register_taught_position("Plate_01", "CAR_1", 4, x=5.0, y=6.0, z=7.0)

        assert client.get_taught_position("PLATE_01", "CAR_1", 3).x == 9.0  # case-insensitive lookup
        assert set(client.get_taught_positions("Plate_01")) == {"car_1/3", "car_1/4"}
        assert client.get_taught_offset("CAR_1", 3).dz == 0.1
        assert client.resolve_taught_location("Plate_01", "CAR_1", 3).__class__.__name__ == "LabwarePosition"
        assert client.resolve_taught_location("Other", "CAR_1", 3).__class__.__name__ == "CarrierSiteOffset"

        doc = client.get_taught_locations()
        assert set(doc.labware_positions) == {"plate_01"}
        assert set(doc.labware_positions["plate_01"]) == {"car_1/3", "car_1/4"}
        assert set(doc.carrier_site_offsets) == {"car_1/3"}

    # instrument was never initialized / connected
    mock_async_star_class.return_value.venus.send_command.assert_not_awaited()
    assert _load(store)["schemaVersion"] == 1


def test_deck_query_get_labware_positions_still_reachable(config, mock_async_star_class):
    """The taught-location mixin must not shadow the deck-layout query of a similar name."""
    star = mock_async_star_class.return_value
    star.venus.send_command = AsyncMock(
        return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={"Plate1": {}}),
    )
    with StarClient(config) as client:
        client.get_labware_positions("Plate1")
    star.venus.send_command.assert_awaited_once()
    assert star.venus.send_command.call_args.kwargs["action_name"] == "status.getLabwarePositions"


def test_remove_and_clear(config, mock_async_star_class, store):
    with StarClient(config) as client:
        client._taught_locations_path = str(store)
        client.register_taught_offset("CAR_1", 3, dx=0.4, dy=-0.2, dz=0.1)
        client.register_taught_position("Plate_01", "CAR_1", 3, x=1.0, y=2.0, z=3.0)

        assert client.remove_taught_offset("CAR_1", 3) is True
        assert client.remove_taught_offset("CAR_1", 3) is False
        assert client.remove_taught_position("plate_01", "car_1", 3) is True
        assert client.remove_taught_position("Plate_01") is False

        client.register_taught_position("Plate_02", "CAR_1", 4, x=1.0, y=2.0, z=3.0)
        client.clear_taught_locations()

    assert _load(store) == {"schemaVersion": 1, "labwarePositions": {}, "carrierSiteOffsets": {}}
