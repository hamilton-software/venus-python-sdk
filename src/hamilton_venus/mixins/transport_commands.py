"""Transport command methods for StarClient."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from hamilton_venus.constants import FLUID_MOTION_CHANNEL_TYPE
from hamilton_venus.exceptions import LabwareTiltedError, VenusCommandUnsupportedError
from hamilton_venus.mixins.channel_commands import max_channels_for
from hamilton_venus.mixins.split_well_commands import (
    forget_split_wells,
    hold_split_wells,
    release_held_split_wells,
    split_wells_suspended,
)
from hamilton_venus.models import (
    CommandResponse,
    IswapComplexMovement,
    IswapGetLabwareParameters,
    IswapIsHoldingLabwareResponse,
    IswapMoveLabwareParameters,
    IswapMoveToWasteParameters,
    IswapPresentAndScanParameters,
    IswapPutLabwareParameters,
    MessageResponse,
    TransportHoldLidParameters,
    TransportIsHoldingLabwareResponse,
    TransportParameters,
    TransportPresentAndScanParameters,
    TransportPresentAndScanResponse,
    TransportReturnPlateParameters,
    TransportToWasteParameters,
)
from hamilton_venus.models.enums import CMOrientation, GripInverse, InstrumentType, PlaceRotation

if TYPE_CHECKING:
    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_CORE_GRIP_CHANNEL_SPAN = 2
_QCG_CHANNEL_SPAN = 4

# Each way the iSWAP can face, as a clockwise turn (seen from above) from facing the back of the instrument.
_FACING_DEGREES = {CMOrientation.REAR: 0, CMOrientation.RIGHT: 90, CMOrientation.FRONT: 180, CMOrientation.LEFT: 270}
_PLACE_ROTATION_FOR_TURN = {
    0: PlaceRotation.DEGREES_0,
    90: PlaceRotation.DEGREES_90,
    180: PlaceRotation.DEGREES_180,
    270: PlaceRotation.DEGREES_270,
}
_WIDE_GRIP_MIN_WIDTH = 100.0


def _plain_grip_facing(grip_width: float | None, grip_inverse: GripInverse | None) -> CMOrientation | None:
    """Which way the iSWAP faces after a plain get of labware at rotation 0: a wide
    grip (100 mm or more) faces the back, or the front with ``grip_inverse``; a
    narrow one faces left, or right with ``grip_inverse``. ``None`` when VENUS
    picks the width."""
    if grip_width is None:
        return None
    inverse = grip_inverse is GripInverse.GRIP_FROM_LEFT
    if grip_width >= _WIDE_GRIP_MIN_WIDTH:
        return CMOrientation.FRONT if inverse else CMOrientation.REAR
    return CMOrientation.RIGHT if inverse else CMOrientation.LEFT


def _turn_between(gripped: CMOrientation, placing: CMOrientation) -> PlaceRotation:
    """The place rotation that matches the iSWAP turning from *gripped* to *placing*:
    the held labware turns with it."""
    return _PLACE_ROTATION_FOR_TURN[(_FACING_DEGREES[placing] - _FACING_DEGREES[gripped]) % 360]


class TransportCommandsMixin:
    """Mixin providing plate transport and handling commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def _set_iswap_grip_facing(self, facing: CMOrientation | None) -> None:
        """Remember which way the iSWAP faced when it gripped the labware it holds."""
        vars(self)["_iswap_grip_facing"] = facing

    def _reject_on_vantage(self, method_name: str) -> None:
        """Raise for a STAR-only transport command called on a Vantage."""
        if getattr(self, "_instrument_type", None) is InstrumentType.Vantage:
            raise VenusCommandUnsupportedError(f"{method_name} is not supported on a Vantage (STAR only)")

    def _grip_channel_span(self, action_prefix: str) -> int:
        """Number of channels the CO-RE gripper occupies, counting back from ``front_channel``.

        The QCG (Vantage, or Fluid Motion channels) uses 4; the standard CO-RE gripper uses 2.
        """
        if getattr(self, "_instrument_type", None) is InstrumentType.Vantage:
            return _QCG_CHANNEL_SPAN
        if getattr(self, "_channel_types", {}).get(action_prefix) == FLUID_MOTION_CHANNEL_TYPE:
            return _QCG_CHANNEL_SPAN
        return _CORE_GRIP_CHANNEL_SPAN

    def _validate_front_channel(self, front_channel: int | None, action_prefix: str) -> None:
        """Reject a CO-RE gripper ``front_channel`` that the installed channels cannot support.

        The gripper occupies the front channel and the channels behind it, so the value
        must be at least the gripper's channel span and at most the channel total the
        instrument reported when it connected (the SDK ceiling before that).
        """
        if front_channel is None:
            return
        span = self._grip_channel_span(action_prefix)
        max_channels = max_channels_for(self, action_prefix)
        if not span <= front_channel <= max_channels:
            tool = "QCG" if span == _QCG_CHANNEL_SPAN else "CO-RE gripper"
            raise ValueError(
                f"{action_prefix.replace('channels.', '')} front_channel must be between {span} and "
                f"{max_channels}, got {front_channel} (the {tool} spans {span} channels)"
            )

    def _validate_not_tilted(self, labware_name: str) -> None:
        """Reject transporting labware that ``tilt_labware`` has left tilted."""
        degrees = getattr(self, "_tilted_labware", {}).get(labware_name.lower())
        if degrees:
            raise LabwareTiltedError(
                f"{labware_name!r} is tilted {degrees:g} degrees and cannot be transported; "
                f"call tilt_labware({labware_name!r}, 0) first"
            )

    def core_transport(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        press_distance: float | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        offset_grip: float | None = None,
        check_presence: dict[str, bool] | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Transport a plate to a carrier site using the CO-RE gripper."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.1mL")
        parameters = TransportParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            press_distance=press_distance,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            offset_grip=offset_grip,
            check_presence=check_presence,
            eject_grip=eject_grip,
        )
        with split_wells_suspended(self, [labware_name]):
            return self._run(
                self._connected_instrument.venus.send_command(
                    category="Instrument",
                    action_name="transport.1mL.moveLabware",
                    parameters=parameters.model_dump(by_alias=True, exclude_none=True),
                )
            )

    def core_transport_is_holding_labware(self) -> TransportIsHoldingLabwareResponse:
        """Check whether the CO-RE gripper is currently holding labware."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.isHoldingLabware",
            )
        )
        return TransportIsHoldingLabwareResponse.model_validate(response.model_dump(by_alias=True))

    def core_transport_tracking_clear(self) -> CommandResponse:
        """Clear the transport tracking state."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.clearHeldLabware",
            )
        )

    def core_eject_grips(self) -> CommandResponse:
        """Eject the CO-RE grips."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.ejectGrips",
            )
        )

    def core_transport_return_plate(
        self,
        mode: str = "return",
        carrier: str | None = None,
        site: str | None = None,
        check_presence: dict[str, bool] | None = None,
        grip_z_speed: float | None = None,
        x_acceleration: int | None = None,
        press_distance: float | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Return a held plate to its original position or a new carrier site."""
        parameters = TransportReturnPlateParameters(
            mode=mode,
            carrier=carrier,
            site=site,
            check_presence=check_presence,
            grip_z_speed=grip_z_speed,
            x_acceleration=x_acceleration,
            press_distance=press_distance,
            eject_grip=eject_grip,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.returnLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        release_held_split_wells(self, "1mL")
        return response

    def core_transport_to_waste(
        self,
        labware_name: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        offset_grip: float | None = None,
        check_presence: dict[str, bool] | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Transport a plate to the waste position."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.1mL")
        parameters = TransportToWasteParameters(
            labware_name=labware_name,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            offset_grip=offset_grip,
            check_presence=check_presence,
            eject_grip=eject_grip,
        )
        forget_split_wells(self, [labware_name])
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.moveToWaste",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def core_present_and_scan(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        grip_height_above_bottom: float,
        track: int,
        z_minimal_position: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        eject_grip: bool | None = None,
        check_presence: dict[str, bool] | None = None,
    ) -> TransportPresentAndScanResponse:
        """Transport labware to a scan position and return barcode (STAR only)."""
        self._reject_on_vantage("core_present_and_scan")
        self._validate_not_tilted(labware_name)
        parameters = TransportPresentAndScanParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            track=track,
            z_minimal_position=z_minimal_position,
            grip_force=grip_force,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            eject_grip=eject_grip,
            check_presence=check_presence,
        )
        hold_split_wells(self, labware_name, "1mL")
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.presentAndScan",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return TransportPresentAndScanResponse.model_validate(response.model_dump(by_alias=True))

    def core_hold_lid(
        self,
        labware_name: str,
        grip_height_from_top: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        check_presence: dict[str, bool] | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        x_acceleration: int | None = None,
    ) -> MessageResponse:
        """Grip and hold a lid with the 1 mL transport tool."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.1mL")
        parameters = TransportHoldLidParameters(
            labware_name=labware_name,
            grip_height_from_top=grip_height_from_top,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            check_presence=check_presence,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            x_acceleration=x_acceleration,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.1mL.holdLid",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def core_5ml_transport(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        press_distance: float | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        offset_grip: float | None = None,
        check_presence: dict[str, bool] | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Transport a plate to a carrier site using the 5 mL CO-RE gripper."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.5mL")
        parameters = TransportParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            press_distance=press_distance,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            offset_grip=offset_grip,
            check_presence=check_presence,
            eject_grip=eject_grip,
        )
        with split_wells_suspended(self, [labware_name]):
            return self._run(
                self._connected_instrument.venus.send_command(
                    category="Instrument",
                    action_name="transport.5mL.moveLabware",
                    parameters=parameters.model_dump(by_alias=True, exclude_none=True),
                )
            )

    def core_5ml_transport_is_holding_labware(self) -> TransportIsHoldingLabwareResponse:
        """Check whether the 5 mL CO-RE gripper is currently holding labware."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.isHoldingLabware",
            )
        )
        return TransportIsHoldingLabwareResponse.model_validate(response.model_dump(by_alias=True))

    def core_5ml_transport_tracking_clear(self) -> CommandResponse:
        """Clear the 5 mL transport tracking state."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.clearHeldLabware",
            )
        )

    def core_5ml_eject_grips(self) -> CommandResponse:
        """Eject the 5 mL CO-RE grips."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.ejectGrips",
            )
        )

    def core_5ml_transport_return_plate(
        self,
        mode: str = "return",
        carrier: str | None = None,
        site: str | None = None,
        check_presence: dict[str, bool] | None = None,
        grip_z_speed: float | None = None,
        x_acceleration: int | None = None,
        press_distance: float | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Return a held plate to its original position or a new carrier site using the 5 mL gripper."""
        parameters = TransportReturnPlateParameters(
            mode=mode,
            carrier=carrier,
            site=site,
            check_presence=check_presence,
            grip_z_speed=grip_z_speed,
            x_acceleration=x_acceleration,
            press_distance=press_distance,
            eject_grip=eject_grip,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.returnLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        release_held_split_wells(self, "5mL")
        return response

    def core_5ml_transport_to_waste(
        self,
        labware_name: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        offset_grip: float | None = None,
        check_presence: dict[str, bool] | None = None,
        eject_grip: bool | None = None,
    ) -> CommandResponse:
        """Transport a plate to the waste position using the 5 mL gripper."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.5mL")
        parameters = TransportToWasteParameters(
            labware_name=labware_name,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            offset_grip=offset_grip,
            check_presence=check_presence,
            eject_grip=eject_grip,
        )
        forget_split_wells(self, [labware_name])
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.moveToWaste",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def core_5ml_present_and_scan(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        grip_height_above_bottom: float,
        track: int,
        z_minimal_position: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        x_acceleration: int | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        eject_grip: bool | None = None,
        check_presence: dict[str, bool] | None = None,
    ) -> TransportPresentAndScanResponse:
        """Transport labware to a scan position and return barcode using the 5 mL gripper."""
        self._validate_not_tilted(labware_name)
        parameters = TransportPresentAndScanParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            track=track,
            z_minimal_position=z_minimal_position,
            grip_force=grip_force,
            x_acceleration=x_acceleration,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            eject_grip=eject_grip,
            check_presence=check_presence,
        )
        hold_split_wells(self, labware_name, "5mL")
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.presentAndScan",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return TransportPresentAndScanResponse.model_validate(response.model_dump(by_alias=True))

    def core_5ml_hold_lid(
        self,
        labware_name: str,
        grip_height_from_top: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        tool_id: int | None = None,
        front_channel: int | None = None,
        grip_force: int | None = None,
        check_presence: dict[str, bool] | None = None,
        grip_close_speed: float | None = None,
        grip_z_speed: float | None = None,
        x_acceleration: int | None = None,
    ) -> MessageResponse:
        """Grip and hold a lid with the 5 mL transport tool."""
        self._validate_not_tilted(labware_name)
        self._validate_front_channel(front_channel, "channels.5mL")
        parameters = TransportHoldLidParameters(
            labware_name=labware_name,
            grip_height_from_top=grip_height_from_top,
            grip_width=grip_width,
            grip_open=grip_open,
            tool_id=tool_id,
            front_channel=front_channel,
            grip_force=grip_force,
            check_presence=check_presence,
            grip_close_speed=grip_close_speed,
            grip_z_speed=grip_z_speed,
            x_acceleration=x_acceleration,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.5mL.holdLid",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_transport(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        tolerance: float | None = None,
        grip_inverse: GripInverse | None = None,
        place_rotation: PlaceRotation | None = None,
        offset_grip: float | None = None,
    ) -> MessageResponse:
        """Move labware using the iSWAP transport tool.

        A *grip_width* of 100 mm or more is a wide grip, with the iSWAP facing
        the back of the instrument (the front with ``GRIP_FROM_LEFT``); below
        that, a narrow grip facing left (right with ``GRIP_FROM_LEFT``), for
        labware at rotation 0.
        """
        self._validate_not_tilted(labware_name)
        parameters = IswapMoveLabwareParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            grip_force=grip_force,
            tolerance=tolerance,
            grip_inverse=grip_inverse,
            place_rotation=place_rotation,
            offset_grip=offset_grip,
        )
        with split_wells_suspended(self, [labware_name]):
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Instrument",
                    action_name="transport.iswap.moveLabware",
                    parameters=parameters.model_dump(by_alias=True, exclude_none=True),
                )
            )
        self._set_iswap_grip_facing(None)
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_tracking_clear(self) -> CommandResponse:
        """Clear iSWAP transport tracking state."""
        self._set_iswap_grip_facing(None)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.clearHeldLabware",
            )
        )

    def iswap_is_holding_labware(self) -> IswapIsHoldingLabwareResponse:
        """Return iSWAP held-labware status payload."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.isHoldingLabware",
            )
        )
        return IswapIsHoldingLabwareResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_transport_to_waste(
        self,
        labware_name: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        tolerance: float | None = None,
        grip_inverse: GripInverse | None = None,
        offset_grip: float | None = None,
    ) -> MessageResponse:
        """Move labware to waste using the iSWAP transport tool."""
        self._validate_not_tilted(labware_name)
        parameters = IswapMoveToWasteParameters(
            labware_name=labware_name,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            grip_force=grip_force,
            tolerance=tolerance,
            grip_inverse=grip_inverse,
            offset_grip=offset_grip,
        )
        forget_split_wells(self, [labware_name])
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.moveToWaste",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        self._set_iswap_grip_facing(None)
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_park(self) -> CommandResponse:
        """Park the iSWAP transport tool."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.park",
            )
        )

    def iswap_present_and_scan(
        self,
        labware_name: str,
        carrier: str,
        site: str,
        track: int,
        grip_height_above_bottom: float,
        z_minimal_position: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        tolerance: float | None = None,
        grip_inverse: GripInverse | None = None,
        place_rotation: PlaceRotation | None = None,
    ) -> TransportPresentAndScanResponse:
        """Present labware for barcode scan using iSWAP (STAR only)."""
        self._reject_on_vantage("iswap_present_and_scan")
        self._validate_not_tilted(labware_name)
        parameters = IswapPresentAndScanParameters(
            labware_name=labware_name,
            carrier=carrier,
            site=site,
            track=track,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            z_minimal_position=z_minimal_position,
            grip_force=grip_force,
            tolerance=tolerance,
            grip_inverse=grip_inverse,
            place_rotation=place_rotation,
        )
        hold_split_wells(self, labware_name, "iswap")
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.presentAndScan",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        self._set_iswap_grip_facing(_plain_grip_facing(grip_width, grip_inverse))
        return TransportPresentAndScanResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_get_labware(
        self,
        labware_name: str,
        grip_height_above_bottom: float,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        tolerance: float | None = None,
        grip_inverse: GripInverse | None = None,
        offset_grip: float | None = None,
    ) -> MessageResponse:
        """Pick up labware without placing it using iSWAP.

        A plain get from a carrier site. A *grip_width* of 100 mm or more is a
        wide grip, with the iSWAP facing the back of the instrument (the front
        with ``GRIP_FROM_LEFT``); below that, a narrow grip facing left (right
        with ``GRIP_FROM_LEFT``), for labware at rotation 0. To get from a hotel
        with complex movement, use
        :meth:`iswap_get_labware_complex_movement`.

        With *grip_width* set, the client remembers the grip, so a following
        :meth:`iswap_put_labware_complex_movement` can work out its place rotation.
        """
        self._validate_not_tilted(labware_name)
        parameters = IswapGetLabwareParameters(
            labware_name=labware_name,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            grip_force=grip_force,
            tolerance=tolerance,
            grip_inverse=grip_inverse,
            offset_grip=offset_grip,
        )
        hold_split_wells(self, labware_name, "iswap")
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.getLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        self._set_iswap_grip_facing(_plain_grip_facing(grip_width, grip_inverse))
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_put_labware(
        self,
        carrier: str,
        site: str,
        place_rotation: PlaceRotation | None = None,
    ) -> MessageResponse:
        """Place currently-held labware at a carrier site using iSWAP.

        A plain put to a carrier site. To put into a hotel with complex
        movement, use :meth:`iswap_put_labware_complex_movement`.
        """
        parameters = IswapPutLabwareParameters(
            carrier=carrier,
            site=site,
            place_rotation=place_rotation,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.putLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        release_held_split_wells(self, "iswap")
        self._set_iswap_grip_facing(None)
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_get_labware_complex_movement(
        self,
        labware_name: str,
        grip_height_above_bottom: float,
        retract_distance: float,
        lift_height: float,
        orientation: CMOrientation,
        grip_width: float | None = None,
        grip_open: float | None = None,
        grip_force: int | None = None,
        tolerance: float | None = None,
        offset_grip: float | None = None,
    ) -> MessageResponse:
        """Pick up labware from a hotel with iSWAP complex movement.

        The iSWAP faces *orientation* (front, right, rear or left), toward the
        hotel, reaches *retract_distance* mm into it, and lifts the labware
        *lift_height* mm before retracting. *grip_width* still picks a narrow or
        wide grip (100 mm or more); ``grip_inverse`` has no effect here. Sends the same
        ``transport.iswap.getLabware`` command as :meth:`iswap_get_labware`,
        with a ``complexMovement`` object.
        """
        self._validate_not_tilted(labware_name)
        parameters = IswapGetLabwareParameters(
            labware_name=labware_name,
            grip_height_above_bottom=grip_height_above_bottom,
            grip_width=grip_width,
            grip_open=grip_open,
            grip_force=grip_force,
            tolerance=tolerance,
            offset_grip=offset_grip,
            complex_movement=IswapComplexMovement(
                retract_distance=retract_distance, lift_height=lift_height, orientation=orientation
            ),
        )
        hold_split_wells(self, labware_name, "iswap")
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.getLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        self._set_iswap_grip_facing(orientation)
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

    def iswap_put_labware_complex_movement(
        self,
        carrier: str,
        site: str,
        retract_distance: float,
        lift_height: float,
        orientation: CMOrientation,
        place_rotation: PlaceRotation | None = None,
    ) -> MessageResponse:
        """Place currently-held labware into a hotel with iSWAP complex movement.

        The iSWAP faces *orientation* (front, right, rear or left), toward the
        hotel, reaches *retract_distance* mm into it at *lift_height* mm above
        the site, then lowers the labware. Sends the same
        ``transport.iswap.putLabware`` command as :meth:`iswap_put_labware`,
        with a ``complexMovement`` object.

        The held labware turns with the iSWAP, so when *orientation* differs
        from the way the iSWAP faced when it gripped (see
        :meth:`iswap_get_labware`, or the complex get's orientation),
        VENUS needs the matching place rotation: 180° for the opposite side,
        90° or 270° for a quarter turn. Left as ``None``, *place_rotation* is
        worked out from the last get by this client, when that get set
        *grip_width* or used complex movement; otherwise it is not sent.
        """
        if place_rotation is None:
            gripped = vars(self).get("_iswap_grip_facing")
            if gripped is not None:
                place_rotation = _turn_between(gripped, orientation)
        parameters = IswapPutLabwareParameters(
            carrier=carrier,
            site=site,
            place_rotation=place_rotation,
            complex_movement=IswapComplexMovement(
                retract_distance=retract_distance, lift_height=lift_height, orientation=orientation
            ),
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="transport.iswap.putLabware",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        release_held_split_wells(self, "iswap")
        self._set_iswap_grip_facing(None)
        return MessageResponse.model_validate(response.model_dump(by_alias=True))

