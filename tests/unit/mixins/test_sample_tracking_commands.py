"""Unit tests for SampleTrackingCommandsMixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from hamilton_venus.mixins.sample_tracking_commands import SampleTrackingCommandsMixin
from hamilton_venus.models import (
    CommandResponse,
    Position,
    TrackedLabwareType,
    TrackingLabwareBarcodes,
    TrackingLabwareQuery,
    TrackingLabwareVolume,
)
from hamilton_venus.models.position import LabwareLayoutSpec
from hamilton_venus.star_client import StarClient
from hamilton_venus.vantage_client import VantageClient


class _SampleTrackingClient(SampleTrackingCommandsMixin):
    def __init__(self, return_parameters: dict | None = None):
        self._star = MagicMock()
        self._star.venus = MagicMock()
        self._star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters=return_parameters or {},
            )
        )

    @property
    def _connected_instrument(self):
        return self._star

    def _run(self, coro):
        return asyncio.run(coro)

    def get_labware_spec(self, labware_id):
        return LabwareLayoutSpec()


def test_get_barcode_locations():
    client = _SampleTrackingClient(
        {
            "barcodes": [
                {
                    "barcode": "barcode01",
                    "labwareType": "Well",
                    "labwareId": "plate_1",
                    "well": "A1",
                }
            ],
            "notFound": ["barcode02"],
            "totalBarcodesFound": 1,
        }
    )

    result = client.get_barcode_locations(["barcode01", "barcode02"])

    assert result.success is True
    params = result.return_parameters
    assert params.total_barcodes_found == 1
    assert params.not_found == ["barcode02"]
    assert params.barcodes[0].barcode == "barcode01"
    assert params.barcodes[0].labware_id == "plate_1"
    assert params.barcodes[0].well == "A1"
    assert params.barcodes[0].labware_type == "Well"
    client._star.venus.send_command.assert_awaited_once_with(
        category="Sample Tracking",
        action_name="tracking.getBarcodeLocations",
        parameters={"barcodes": ["barcode01", "barcode02"]},
    )


def test_get_labware_details_with_wells():
    client = _SampleTrackingClient(
        {
            "labware": [
                {
                    "labwareId": "plate_1",
                    "barcode": "PlateBarcode",
                    "type": "Rack",
                    "x": 100.0,
                    "y": 200.0,
                    "z": 300.0,
                    "wells": [
                        {
                            "id": "A1",
                            "barcode": "barcode1",
                            "volume": 50.0,
                            "labwareType": "Well",
                            "labwareState": "No Error",
                            "x": 101.0,
                            "y": 201.0,
                            "z": 301.0,
                        }
                    ],
                }
            ]
        }
    )

    result = client.get_labware_details([{"labwareId": "plate_1", "wells": [{"id": "A1"}, "A2"]}])

    labware = result.return_parameters.labware[0]
    assert labware.labware_id == "plate_1"
    assert labware.barcode == "PlateBarcode"
    assert labware.type == "Rack"
    assert labware.wells[0].id == "A1"
    assert labware.wells[0].volume == 50.0
    assert labware.wells[0].labware_state == "No Error"
    client._star.venus.send_command.assert_awaited_once_with(
        category="Sample Tracking",
        action_name="tracking.getLabwareDetails",
        parameters={"labware": [{"labwareId": "plate_1", "wells": [{"id": "A1"}, {"id": "A2"}]}]},
    )


def test_get_labware_details_omits_wells_when_not_given():
    client = _SampleTrackingClient(
        {"labware": [{"labwareId": "plate_2", "message": "not tracked yet"}]}
    )

    result = client.get_labware_details(["plate_1", TrackingLabwareQuery(labware_id="plate_2")])

    assert result.return_parameters.labware[0].message == "not tracked yet"
    assert result.return_parameters.labware[0].wells == []
    client._star.venus.send_command.assert_awaited_once_with(
        category="Sample Tracking",
        action_name="tracking.getLabwareDetails",
        parameters={"labware": [{"labwareId": "plate_1"}, {"labwareId": "plate_2"}]},
    )


def test_set_barcodes():
    client = _SampleTrackingClient({"totalLabwareBarcodesSet": 1, "totalWellBarcodesSet": 2})

    result = client.set_barcodes(
        [
            {
                "labwareId": "plate_1",
                "barcode": "PlateBarcode",
                "wells": [
                    {"id": "A1", "barcode": "barcode1"},
                    {"id": "A2", "barcode": "barcode2"},
                ],
            },
            TrackingLabwareBarcodes(labware_id="plate_2"),
        ]
    )

    assert result.return_parameters.total_labware_barcodes_set == 1
    assert result.return_parameters.total_well_barcodes_set == 2
    client._star.venus.send_command.assert_awaited_once_with(
        category="Sample Tracking",
        action_name="tracking.setBarcodes",
        parameters={
            "labware": [
                {
                    "labwareId": "plate_1",
                    "barcode": "PlateBarcode",
                    "wells": [
                        {"id": "A1", "barcode": "barcode1"},
                        {"id": "A2", "barcode": "barcode2"},
                    ],
                },
                {"labwareId": "plate_2"},
            ]
        },
    )


def test_set_labware_volume():
    client = _SampleTrackingClient()

    result = client.set_labware_volume(
        [
            {"labwareId": "plate_1", "volume": 100.0},
            TrackingLabwareVolume(labware_id="plate_2", wells=[{"id": "A1", "volume": 50.0}]),
        ]
    )

    assert result.success is True
    client._star.venus.send_command.assert_awaited_once_with(
        category="Sample Tracking",
        action_name="tracking.setLabwareVolume",
        parameters={
            "labware": [
                {"labwareId": "plate_1", "volume": 100.0},
                {"labwareId": "plate_2", "wells": [{"id": "A1", "volume": 50.0}]},
            ]
        },
    )


def test_labware_id_is_required():
    client = _SampleTrackingClient()

    with pytest.raises(ValidationError):
        client.set_barcodes([{"barcode": "PlateBarcode"}])

    client._star.venus.send_command.assert_not_awaited()


@pytest.mark.parametrize("client_class", [StarClient, VantageClient])
def test_clients_expose_sample_tracking_commands(client_class):
    assert issubclass(client_class, SampleTrackingCommandsMixin)


def _sent_parameters(client):
    return client._star.venus.send_command.await_args.kwargs["parameters"]


@pytest.mark.parametrize("selector", ["plate_1", "plate_1@all", "plate_1@ALL"])
def test_get_labware_details_whole_labware_selector_omits_wells(selector):
    client = _SampleTrackingClient()

    client.get_labware_details(selector)

    assert _sent_parameters(client) == {"labware": [{"labwareId": "plate_1"}]}


def test_get_labware_details_accepts_pipetting_position_inputs():
    client = _SampleTrackingClient()

    client.get_labware_details(
        [
            "plate_1@A1:B2",
            Position(labware="plate_2", well="C3"),
            {"labwareId": "plate_2", "wellId": "D4"},
            {"labware": "plate_3", "wells": ["A1"]},
        ]
    )

    assert _sent_parameters(client) == {
        "labware": [
            {
                "labwareId": "plate_1",
                "wells": [{"id": "A1"}, {"id": "B1"}, {"id": "A2"}, {"id": "B2"}],
            },
            {"labwareId": "plate_2", "wells": [{"id": "C3"}, {"id": "D4"}]},
            {"labwareId": "plate_3", "wells": [{"id": "A1"}]},
        ]
    }


def test_set_labware_volume_with_selectors():
    client = _SampleTrackingClient()

    client.set_labware_volume(["trough", "plate_1@A1,B1"], 50.0)

    assert _sent_parameters(client) == {
        "labware": [
            {"labwareId": "trough", "volume": 50.0},
            {
                "labwareId": "plate_1",
                "wells": [{"id": "A1", "volume": 50.0}, {"id": "B1", "volume": 50.0}],
            },
        ]
    }


def test_set_barcodes_with_selectors():
    client = _SampleTrackingClient()

    client.set_barcodes(["plate_1", "plate_1@A1,B1"], ["PlateBarcode", "bc1", "bc2"])

    assert _sent_parameters(client) == {
        "labware": [
            {
                "labwareId": "plate_1",
                "barcode": "PlateBarcode",
                "wells": [
                    {"id": "A1", "barcode": "bc1"},
                    {"id": "B1", "barcode": "bc2"},
                ],
            }
        ]
    }


def test_set_barcodes_with_selectors_requires_one_barcode_per_position():
    client = _SampleTrackingClient()

    with pytest.raises(ValueError, match="2 position"):
        client.set_barcodes("plate_1@A1,B1", ["bc1"])

    client._star.venus.send_command.assert_not_awaited()


def test_barcode_locations_to_positions():
    client = _SampleTrackingClient(
        {
            "barcodes": [
                {"barcode": "P1", "labwareType": "Rack", "labwareId": "plate_1", "well": ""},
                {"barcode": "S1", "labwareType": "Well", "labwareId": "plate_1", "well": "A1"},
                {"barcode": "S2", "labwareType": "Reservoir Well", "labwareId": "trough", "well": "1"},
                {"barcode": "C1", "labwareType": "Template", "labwareId": "PlateCarrier", "well": ""},
            ],
            "notFound": ["S3"],
            "totalBarcodesFound": 4,
        }
    )

    result = client.get_barcode_locations(["P1", "S1", "S2", "C1", "S3"])

    assert result.to_positions() == ["plate_1@A1"]
    assert result.to_positions(TrackedLabwareType.RACK) == ["plate_1"]
    assert result.to_positions(TrackedLabwareType.TEMPLATE) == ["PlateCarrier"]
    assert result.to_positions([TrackedLabwareType.WELL, "Reservoir Well"]) == [
        "plate_1@A1",
        "trough@1",
    ]
    assert result.to_positions(None) == ["plate_1", "plate_1@A1", "trough@1", "PlateCarrier"]
    assert result.to_positions(barcodes=["S3", "S1", "P1"]) == ["plate_1@A1"]


def test_tracked_labware_type_values():
    assert [member.value for member in TrackedLabwareType] == [
        "Template",
        "Rack",
        "Well",
        "Tip Rack",
        "Reservoir Rack",
    ]


def test_labware_ids_are_lower_cased_like_the_deck_layout():
    client = _SampleTrackingClient()

    client.get_labware_details(["NuncPlate@A1", {"labwareId": "BufferTrough"}])

    assert _sent_parameters(client) == {
        "labware": [
            {"labwareId": "nuncplate", "wells": [{"id": "A1"}]},
            {"labwareId": "buffertrough"},
        ]
    }


def test_get_labware_details_drops_volume_for_types_venus_does_not_track():
    def well(labware_type):
        return {"id": "1", "volume": 0.0, "labwareType": labware_type}

    client = _SampleTrackingClient(
        {
            "labware": [
                {"labwareId": "trough", "type": "Reservoir Rack", "wells": [well("Reservoir Well")]},
                {"labwareId": "tips", "type": "Tip Rack", "wells": [well("Tip Well")]},
                {"labwareId": "carrier", "type": "Template", "wells": [well("Rack")]},
                {"labwareId": "plate", "type": "Rack", "wells": [well("Well")]},
            ]
        }
    )

    result = client.get_labware_details(["trough", "tips", "carrier", "plate"])

    volumes = [item.wells[0].volume for item in result.return_parameters.labware]
    assert volumes == [None, None, None, 0.0]


def test_get_labware_details_reservoir_wells_have_no_state_or_barcode():
    def well(labware_type):
        return {"id": "1", "barcode": "", "labwareType": labware_type, "labwareState": "Not Used"}

    client = _SampleTrackingClient(
        {
            "labware": [
                {"labwareId": "trough", "type": "Reservoir Rack", "wells": [well("Reservoir Well")]},
                {"labwareId": "plate", "type": "Rack", "wells": [well("Well")]},
            ]
        }
    )

    trough, plate = client.get_labware_details(["trough", "plate"]).return_parameters.labware

    assert (trough.wells[0].barcode, trough.wells[0].labware_state) == (None, None)
    assert (plate.wells[0].barcode, plate.wells[0].labware_state) == ("", "Not Used")


def test_get_labware_details_sorts_wells_x_asc_y_desc_z_desc():
    def well(well_id, x, y, z):
        return {"id": well_id, "labwareType": "Well", "x": x, "y": y, "z": z}

    client = _SampleTrackingClient(
        {
            "labware": [
                {
                    "labwareId": "plate",
                    "type": "Rack",
                    "wells": [
                        well("B2", 109.0, 91.0, 5.0),
                        well("B1", 100.0, 91.0, 5.0),
                        well("A2", 109.0, 100.0, 5.0),
                        well("A1-low", 100.0, 100.0, 1.0),
                        well("A1", 100.0, 100.0, 5.0),
                    ],
                }
            ]
        }
    )

    wells = client.get_labware_details("plate").return_parameters.labware[0].wells

    assert [w.id for w in wells] == ["A1", "A1-low", "B1", "A2", "B2"]
