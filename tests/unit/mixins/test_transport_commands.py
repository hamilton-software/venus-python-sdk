"""Unit tests for TransportCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.exceptions import VenusCommandUnsupportedError
from hamilton_venus.models import CMOrientation, CommandResponse, GripInverse, PlaceRotation
from hamilton_venus.models.enums import InstrumentType
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


class TestTransportCommands:
    def test_core_hold_lid(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Lid held"},
            )
        )

        with StarClient(config) as client:
            result = client.core_hold_lid(
                labware_name="test plate_lid",
                grip_height_from_top=5.0,
                grip_width=80.0,
                grip_open=85.0,
                front_channel=8,
            )

        assert result.success is True
        assert result.return_parameters.message == "Lid held"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.1mL.holdLid"
        assert call_args.kwargs["parameters"]["labwareName"] == "test plate_lid"
        assert call_args.kwargs["parameters"]["gripHeightFromTop"] == 5.0

    def test_iswap_transport(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Moved"},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_transport(
                labware_name="Plate1",
                carrier="SomeShakerCarrier",
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=80.0,
                grip_open=85.0,
                place_rotation=PlaceRotation.DEGREES_0,
            )

        assert result.success is True
        assert result.return_parameters.message == "Moved"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.moveLabware"
        assert call_args.kwargs["parameters"]["placeRotation"] == 1

    def test_iswap_tracking_clear(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.iswap_tracking_clear()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.iswap.clearHeldLabware",
        )

    def test_iswap_is_holding_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        # VENUS's iSWAP controller emits ``isHoldingPlate`` (``isHoldingLabware``
        # is accepted for older executor builds).
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"isHoldingPlate": True},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_is_holding_labware()

        assert result.success is True
        assert result.return_parameters.is_holding_labware is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.iswap.isHoldingLabware",
        )

        # The legacy wire name still parses.
        legacy = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"isHoldingLabware": True},
        )
        star.venus.send_command = AsyncMock(return_value=legacy)
        with StarClient(config) as client:
            assert client.iswap_is_holding_labware().return_parameters.is_holding_labware is True

        # Absent field falls back to the False default.
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={})
        )
        with StarClient(config) as client:
            assert client.iswap_is_holding_labware().return_parameters.is_holding_labware is False

    def test_iswap_transport_to_waste(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Moved to waste"},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_transport_to_waste(
                labware_name="Plate1",
                grip_height_above_bottom=8.0,
                grip_width=80.0,
                grip_open=85.0,
            )

        assert result.success is True
        assert result.return_parameters.message == "Moved to waste"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.moveToWaste"
        assert call_args.kwargs["parameters"]["labwareName"] == "Plate1"

    def test_iswap_park(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.iswap_park()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.iswap.park",
        )

    def test_iswap_present_and_scan(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Scanned", "barcode": "ABC123"},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_present_and_scan(
                labware_name="Plate1",
                carrier="SomeShakerCarrier",
                site="1",
                track=10,
                grip_height_above_bottom=8.0,
                grip_width=80.0,
                grip_open=85.0,
                z_minimal_position=219.0,
                place_rotation=PlaceRotation.DEGREES_0,
            )

        assert result.success is True
        assert result.return_parameters.barcode == "ABC123"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.presentAndScan"
        assert call_args.kwargs["parameters"]["track"] == 10
        assert call_args.kwargs["parameters"]["zMinimalPosition"] == 219.0

    @pytest.mark.parametrize("method_name", ["core_present_and_scan", "iswap_present_and_scan"])
    def test_present_and_scan_rejected_on_vantage(self, config, mock_async_star_class, method_name):
        star = mock_async_star_class.return_value

        with (
            StarClient(config, instrument_type=InstrumentType.Vantage) as client,
            pytest.raises(VenusCommandUnsupportedError, match="not supported on a Vantage"),
        ):
            getattr(client, method_name)(
                labware_name="Plate1",
                carrier="Carrier1",
                site="1",
                track=10,
                grip_height_above_bottom=8.0,
                z_minimal_position=219.0,
            )

        star.venus.send_command.assert_not_awaited()

    def test_core_transport_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once()
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "Instrument"
        assert call_args.kwargs["action_name"] == "transport.1mL.moveLabware"
        assert call_args.kwargs["parameters"]["labwareName"] == "MyPlate"
        assert call_args.kwargs["parameters"]["carrier"] == "PlateCarrier1"

    def test_core_transport_with_optional_params(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
                tool_id=1,
                front_channel=2,
                grip_force=20,
                press_distance=5.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["toolId"] == 1
        assert call_args.kwargs["parameters"]["frontChannel"] == 2
        assert call_args.kwargs["parameters"]["gripForce"] == 20
        assert call_args.kwargs["parameters"]["pressDistance"] == 5.0

    def test_core_transport_is_holding_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        # Channel controllers emit ``isHoldingPlate`` like the iSWAP controller.
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "isHoldingPlate": True,
                    "labwareName": "Plate1",
                    "carrier": "Carrier1",
                    "site": "2",
                    "offsetGrip": 0.0,
                },
            )
        )

        with StarClient(config) as client:
            result = client.core_transport_is_holding_labware()

        assert result.success is True
        assert result.return_parameters.is_holding_labware is True
        assert result.return_parameters.labware_name == "Plate1"
        assert result.return_parameters.carrier == "Carrier1"
        assert result.return_parameters.offset_grip == 0.0
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.1mL.isHoldingLabware",
        )

    def test_core_transport_tracking_clear(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport_tracking_clear()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.1mL.clearHeldLabware",
        )

    def test_core_eject_grips(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.reset_mock()

        with StarClient(config) as client:
            result = client.core_eject_grips()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.1mL.ejectGrips",
        )

    def test_core_transport_return_plate_default_mode(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport_return_plate()

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "Instrument"
        assert call_args.kwargs["action_name"] == "transport.1mL.returnLabware"
        assert call_args.kwargs["parameters"]["mode"] == "return"

    def test_core_transport_return_plate_new_mode(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport_return_plate(
                mode="new",
                carrier="PlateCarrier1",
                site="2",
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["mode"] == "new"
        assert call_args.kwargs["parameters"]["carrier"] == "PlateCarrier1"
        assert call_args.kwargs["parameters"]["site"] == "2"

    def test_core_transport_to_waste(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport_to_waste(
                labware_name="MyPlate",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "Instrument"
        assert call_args.kwargs["action_name"] == "transport.1mL.moveToWaste"
        assert call_args.kwargs["parameters"]["labwareName"] == "MyPlate"

    def test_core_transport_to_waste_with_optional_params(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_transport_to_waste(
                labware_name="MyPlate",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
                tool_id=1,
                grip_force=20,
                x_acceleration=100,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["toolId"] == 1
        assert call_args.kwargs["parameters"]["gripForce"] == 20
        assert call_args.kwargs["parameters"]["xAcceleration"] == 100

    def test_core_present_and_scan(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "message": "Successfully transported plate to scan position",
                    "barcode": "BC123456789",
                },
            )
        )

        with StarClient(config) as client:
            result = client.core_present_and_scan(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
                track=2,
                z_minimal_position=100,
            )

        assert result.success is True
        assert result.return_parameters.message == "Successfully transported plate to scan position"
        assert result.return_parameters.barcode == "BC123456789"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "Instrument"
        assert call_args.kwargs["action_name"] == "transport.1mL.presentAndScan"
        assert call_args.kwargs["parameters"]["labwareName"] == "MyPlate"
        assert call_args.kwargs["parameters"]["carrier"] == "PlateCarrier1"
        assert call_args.kwargs["parameters"]["track"] == 2
        assert call_args.kwargs["parameters"]["zMinimalPosition"] == 100

    def test_core_present_and_scan_with_optional_params(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "message": "Successfully transported plate",
                    "barcode": "BC999888777",
                },
            )
        )

        with StarClient(config) as client:
            result = client.core_present_and_scan(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=8.0,
                grip_width=100.0,
                grip_open=50.0,
                track=1,
                z_minimal_position=150,
                grip_force=25,
                x_acceleration=120,
                grip_close_speed=10.0,
                grip_z_speed=12.0,
                eject_grip=False,
                check_presence={"get": True, "put": True},
            )

        assert result.success is True
        assert result.return_parameters.barcode == "BC999888777"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["gripForce"] == 25
        assert call_args.kwargs["parameters"]["xAcceleration"] == 120
        assert call_args.kwargs["parameters"]["gripCloseSpeed"] == 10.0
        assert call_args.kwargs["parameters"]["gripZSpeed"] == 12.0
        assert call_args.kwargs["parameters"]["ejectGrip"] is False
        assert call_args.kwargs["parameters"]["checkPresence"] == {"get": True, "put": True}

    def test_iswap_get_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Successfully picked up Plate1."},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_get_labware(
                labware_name="Plate1",
                grip_height_above_bottom=8.0,
                grip_width=80.0,
                grip_open=85.0,
                grip_force=5,
                tolerance=5.0,
                grip_inverse=GripInverse.GRIP_FROM_RIGHT,
                offset_grip=0.0,
            )

        assert result.success is True
        assert result.return_parameters.message == "Successfully picked up Plate1."
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.getLabware"
        assert call_args.kwargs["parameters"]["labwareName"] == "Plate1"
        assert call_args.kwargs["parameters"]["gripHeightAboveBottom"] == 8.0
        assert call_args.kwargs["parameters"]["gripWidth"] == 80.0
        assert call_args.kwargs["parameters"]["gripOpen"] == 85.0

    def test_iswap_get_labware_complex_movement(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Successfully picked up Plate1."},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_get_labware_complex_movement(
                labware_name="Plate1",
                grip_height_above_bottom=8.0,
                grip_width=80.0,
                grip_open=85.0,
                retract_distance=150.0,
                lift_height=15.0,
                orientation=CMOrientation.FRONT,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.getLabware"
        assert call_args.kwargs["parameters"] == {
            "labwareName": "Plate1",
            "gripHeightAboveBottom": 8.0,
            "gripWidth": 80.0,
            "gripOpen": 85.0,
            "complexMovement": {"retractDistance": 150.0, "liftHeight": 15.0, "orientation": 1},
        }

    def test_iswap_put_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Successfully placed labware at someshakercarrier [1]."},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_put_labware(
                carrier="SomeShakerCarrier",
                site="1",
                place_rotation=PlaceRotation.DEGREES_0,
            )

        assert result.success is True
        assert result.return_parameters.message == "Successfully placed labware at someshakercarrier [1]."
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.putLabware"
        assert call_args.kwargs["parameters"]["carrier"] == "SomeShakerCarrier"
        assert call_args.kwargs["parameters"]["site"] == "1"
        assert call_args.kwargs["parameters"]["placeRotation"] == 1

    def test_iswap_put_labware_complex_movement(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Successfully placed labware."},
            )
        )

        with StarClient(config) as client:
            result = client.iswap_put_labware_complex_movement(
                carrier="FrontHotel",
                site="1",
                retract_distance=139.0,
                lift_height=35.0,
                orientation=CMOrientation.RIGHT,
                place_rotation=PlaceRotation.DEGREES_180,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.iswap.putLabware"
        assert call_args.kwargs["parameters"] == {
            "carrier": "FrontHotel",
            "site": "1",
            "placeRotation": 3,
            "complexMovement": {"retractDistance": 139.0, "liftHeight": 35.0, "orientation": 2},
        }

    @pytest.mark.parametrize(
        ("get_kwargs", "put_orientation", "expected_rotation"),
        [
            ({"grip_width": 80.0}, CMOrientation.LEFT, 1),  # narrow grip faces left: no turn
            ({"grip_width": 80.0}, CMOrientation.RIGHT, 3),  # opposite side: 180
            ({"grip_width": 80.0}, CMOrientation.FRONT, 4),  # left to front: 270 clockwise
            ({"grip_width": 124.0}, CMOrientation.REAR, 1),  # wide grip faces the back
            ({"grip_width": 124.0}, CMOrientation.FRONT, 3),
            ({"grip_width": 100.0}, CMOrientation.RIGHT, 2),  # 100 mm is already wide: back to right, 90
            ({"grip_width": 80.0, "grip_inverse": GripInverse.GRIP_FROM_LEFT}, CMOrientation.RIGHT, 1),  # faces right
            ({"grip_width": 80.0, "grip_inverse": GripInverse.GRIP_FROM_LEFT}, CMOrientation.LEFT, 3),
            ({"grip_width": 124.0, "grip_inverse": GripInverse.GRIP_FROM_LEFT}, CMOrientation.FRONT, 1),  # faces front
            ({"grip_width": 124.0, "grip_inverse": GripInverse.GRIP_FROM_RIGHT}, CMOrientation.FRONT, 3),
        ],
    )
    def test_complex_put_sends_the_turn_from_the_plain_get(
        self, config, mock_async_star_class, get_kwargs, put_orientation, expected_rotation
    ):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={"message": "ok"})
        )

        with StarClient(config) as client:
            client.iswap_get_labware(labware_name="Plate1", grip_height_above_bottom=7.6, **get_kwargs)
            client.iswap_put_labware_complex_movement(
                carrier="Hotel", site="1", retract_distance=139.0, lift_height=35.0, orientation=put_orientation
            )

        assert star.venus.send_command.call_args.kwargs["parameters"]["placeRotation"] == expected_rotation

    def test_complex_put_after_a_complex_get_turns_between_the_orientations(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={"message": "ok"})
        )
        movement = {"retract_distance": 139.0, "lift_height": 35.0}

        with StarClient(config) as client:
            client.iswap_get_labware_complex_movement(
                labware_name="Plate1", grip_height_above_bottom=7.6, orientation=CMOrientation.RIGHT, **movement
            )
            client.iswap_put_labware_complex_movement(
                carrier="Hotel", site="1", orientation=CMOrientation.LEFT, **movement
            )

        assert star.venus.send_command.call_args.kwargs["parameters"]["placeRotation"] == 3

    def test_complex_put_rotation_explicit_or_unknown(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={"message": "ok"})
        )
        put = {"carrier": "Hotel", "site": "1", "retract_distance": 139.0, "lift_height": 35.0}

        with StarClient(config) as client:
            # An explicit place_rotation wins over the tracked grip.
            client.iswap_get_labware(labware_name="Plate1", grip_height_above_bottom=7.6, grip_width=80.0)
            client.iswap_put_labware_complex_movement(
                orientation=CMOrientation.RIGHT, place_rotation=PlaceRotation.DEGREES_0, **put
            )
            assert star.venus.send_command.call_args.kwargs["parameters"]["placeRotation"] == 1
            # The put released the plate: nothing is tracked for the next one.
            client.iswap_put_labware_complex_movement(orientation=CMOrientation.RIGHT, **put)
            assert "placeRotation" not in star.venus.send_command.call_args.kwargs["parameters"]
            # A get that leaves grip_width to VENUS: the grip is unknown, nothing is sent.
            client.iswap_get_labware(labware_name="Plate1", grip_height_above_bottom=7.6)
            client.iswap_put_labware_complex_movement(orientation=CMOrientation.RIGHT, **put)
            assert "placeRotation" not in star.venus.send_command.call_args.kwargs["parameters"]

    def test_plain_get_and_put_send_no_complex_movement(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={"message": "ok"})
        )

        with StarClient(config) as client:
            client.iswap_get_labware(labware_name="Plate1", grip_height_above_bottom=8.0)
            client.iswap_put_labware(carrier="SomeShakerCarrier", site="1")

        for call in star.venus.send_command.call_args_list:
            keys = set(call.kwargs["parameters"])
            complex_keys = {
                "complexMovement",
                "useComplexMovement",
                "cmRetractDistance",
                "cmLiftHeight",
                "cmOrientation",
            }
            assert not keys & complex_keys

    def test_place_rotation_enum_serializes_to_int(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Placed"},
            )
        )

        rotation_map = {
            PlaceRotation.DEGREES_0: 1,
            PlaceRotation.DEGREES_90: 2,
            PlaceRotation.DEGREES_180: 3,
            PlaceRotation.DEGREES_270: 4,
        }

        for rotation_enum, expected_int in rotation_map.items():
            with StarClient(config) as client:
                client.iswap_put_labware(
                    carrier="SomeShakerCarrier",
                    site="1",
                    place_rotation=rotation_enum,
                )
            call_args = star.venus.send_command.call_args
            assert call_args.kwargs["parameters"]["placeRotation"] == expected_int

    def test_grip_inverse_enum_serializes_to_bool(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Picked up"},
            )
        )

        with StarClient(config) as client:
            client.iswap_get_labware(
                labware_name="Plate1",
                grip_height_above_bottom=8.0,
                grip_inverse=GripInverse.GRIP_FROM_LEFT,
            )
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["gripInverse"] is True

        with StarClient(config) as client:
            client.iswap_get_labware(
                labware_name="Plate1",
                grip_height_above_bottom=8.0,
                grip_inverse=GripInverse.GRIP_FROM_RIGHT,
            )
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["gripInverse"] is False


class TestTransport5mLCommands:
    def test_core_5ml_transport_basic(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=15.5,
                grip_width=80.0,
                grip_open=90.0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once()
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "Instrument"
        assert call_args.kwargs["action_name"] == "transport.5mL.moveLabware"
        assert call_args.kwargs["parameters"]["labwareName"] == "MyPlate"
        assert call_args.kwargs["parameters"]["carrier"] == "PlateCarrier1"

    def test_core_5ml_transport_with_optional_params(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="1",
                grip_height_above_bottom=15.5,
                grip_width=80.0,
                grip_open=90.0,
                front_channel=8,
                grip_force=5,
                press_distance=1.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["frontChannel"] == 8
        assert call_args.kwargs["parameters"]["gripForce"] == 5
        assert call_args.kwargs["parameters"]["pressDistance"] == 1.0

    def test_core_5ml_transport_is_holding_labware(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "isHoldingPlate": True,
                    "labwareName": "Plate1",
                    "carrier": "Carrier1",
                    "site": "2",
                    "offsetGrip": 0.0,
                },
            )
        )

        with StarClient(config) as client:
            result = client.core_5ml_transport_is_holding_labware()

        assert result.success is True
        assert result.return_parameters.is_holding_labware is True
        assert result.return_parameters.labware_name == "Plate1"
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.5mL.isHoldingLabware",
        )

    def test_core_5ml_transport_tracking_clear(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport_tracking_clear()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.5mL.clearHeldLabware",
        )

    def test_core_5ml_eject_grips(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.reset_mock()

        with StarClient(config) as client:
            result = client.core_5ml_eject_grips()

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="transport.5mL.ejectGrips",
        )

    def test_core_5ml_transport_return_plate_default_mode(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport_return_plate()

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.5mL.returnLabware"
        assert call_args.kwargs["parameters"]["mode"] == "return"

    def test_core_5ml_transport_return_plate_new_mode(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport_return_plate(
                mode="new",
                carrier="PlateCarrier1",
                site="2",
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["mode"] == "new"
        assert call_args.kwargs["parameters"]["carrier"] == "PlateCarrier1"
        assert call_args.kwargs["parameters"]["site"] == "2"

    def test_core_5ml_transport_to_waste(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.core_5ml_transport_to_waste(
                labware_name="MyPlate",
                grip_height_above_bottom=15.5,
                grip_width=80.0,
                grip_open=90.0,
            )

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.5mL.moveToWaste"
        assert call_args.kwargs["parameters"]["labwareName"] == "MyPlate"

    def test_core_5ml_present_and_scan(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={
                    "message": "Successfully transported plate to scan position",
                    "barcode": "BC123456789",
                },
            )
        )

        with StarClient(config) as client:
            result = client.core_5ml_present_and_scan(
                labware_name="MyPlate",
                carrier="PlateCarrier1",
                site="3",
                grip_height_above_bottom=7.25,
                track=54,
                z_minimal_position=219,
            )

        assert result.success is True
        assert result.return_parameters.barcode == "BC123456789"
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.5mL.presentAndScan"
        assert call_args.kwargs["parameters"]["track"] == 54
        assert call_args.kwargs["parameters"]["zMinimalPosition"] == 219

    def test_core_5ml_hold_lid(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"message": "Successfully holding test plate_lid."},
            )
        )

        with StarClient(config) as client:
            result = client.core_5ml_hold_lid(
                labware_name="test plate_lid",
                grip_height_from_top=5.0,
                grip_width=80.0,
                grip_open=85.0,
                front_channel=8,
            )

        assert result.success is True
        assert result.return_parameters.message == "Successfully holding test plate_lid."
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["action_name"] == "transport.5mL.holdLid"
        assert call_args.kwargs["parameters"]["labwareName"] == "test plate_lid"
        assert call_args.kwargs["parameters"]["gripHeightFromTop"] == 5.0
