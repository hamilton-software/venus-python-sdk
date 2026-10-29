"""Hamilton Heater Shaker (HHS) command methods for StarClient (Device category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    HHSCreateDeviceResponse,
    HHSDeviceIdsResponse,
    HHSPlateLockResponse,
    HHSShakingStartedResponse,
    HHSShakingStoppedResponse,
    HHSStatusResponse,
    HHSTempControlStartedResponse,
    HHSTempControlStoppedResponse,
    MessageResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class HeaterShakerDeviceCommands:
    """Device command group for Hamilton Heater Shaker (HHS)."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def hhs_create_star_device(self, node: int) -> HHSCreateDeviceResponse:
        """Register an HHS connected through a STAR node and return its device id."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.createStarDevice",
                parameters={"node": node},
            )
        )
        return self._parse_response(HHSCreateDeviceResponse, response)

    def hhs_create_usb_device(self, node: int) -> HHSCreateDeviceResponse:
        """Register an HHS connected through USB and return its device id."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.createUsbDevice",
                parameters={"node": node},
            )
        )
        return self._parse_response(HHSCreateDeviceResponse, response)

    def hhs_get_device_ids(self) -> HHSDeviceIdsResponse:
        """Return the registered HHS devices and their connection metadata."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.getDeviceIds",
            )
        )
        return self._parse_response(HHSDeviceIdsResponse, response)

    def hhs_get_status(self) -> HHSStatusResponse:
        """Return the current shaking speed and temperature status of each HHS device."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.getStatus",
            )
        )
        return self._parse_response(HHSStatusResponse, response)

    def hhs_set_plate_lock(self, lock: bool, device_id: int | None = None) -> HHSPlateLockResponse:
        """Lock or unlock the plate on the HHS. Applies to all devices when *device_id* is None."""
        parameters: dict[str, Any] = {"lock": lock}
        if device_id is not None:
            parameters["deviceId"] = device_id
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.setPlateLock",
                parameters=parameters,
            )
        )
        return self._parse_response(HHSPlateLockResponse, response)

    def hhs_start_shaker(
        self,
        speed: int,
        time: int = 0,
        device_id: int | None = None,
    ) -> HHSShakingStartedResponse:
        """Start shaking at *speed* RPM for *time* seconds (0 = indefinite).

        Applies to all devices when *device_id* is None.
        """
        parameters: dict[str, Any] = {"speed": speed, "time": time}
        if device_id is not None:
            parameters["deviceId"] = device_id
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.startShaker",
                parameters=parameters,
            )
        )
        return self._parse_response(HHSShakingStartedResponse, response)

    def hhs_stop_shaker(self, device_id: int | None = None) -> HHSShakingStoppedResponse:
        """Stop shaking. Applies to all devices when *device_id* is None."""
        if device_id is None:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.stopShaker",
                )
            )
        else:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.stopShaker",
                    parameters={"deviceId": device_id},
                )
            )
        return self._parse_response(HHSShakingStoppedResponse, response)

    def hhs_wait_for_shaker(self, device_id: int | None = None) -> HHSShakingStoppedResponse:
        """Block until shaking has stopped. Waits for all devices when *device_id* is None."""
        if device_id is None:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.waitForShaker",
                )
            )
        else:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.waitForShaker",
                    parameters={"deviceId": device_id},
                )
            )
        return self._parse_response(HHSShakingStoppedResponse, response)

    def hhs_start_temp_control(
        self,
        temperature: float,
        device_id: int | None = None,
    ) -> HHSTempControlStartedResponse:
        """Start temperature control targeting *temperature* deg C.

        Applies to all devices when *device_id* is None.
        """
        parameters: dict[str, Any] = {"temperature": temperature}
        if device_id is not None:
            parameters["deviceId"] = device_id
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.startTempControl",
                parameters=parameters,
            )
        )
        return self._parse_response(HHSTempControlStartedResponse, response)

    def hhs_stop_temp_control(self, device_id: int | None = None) -> HHSTempControlStoppedResponse:
        """Stop temperature control. Applies to all devices when *device_id* is None."""
        if device_id is None:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.stopTempControl",
                )
            )
        else:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.stopTempControl",
                    parameters={"deviceId": device_id},
                )
            )
        return self._parse_response(HHSTempControlStoppedResponse, response)

    def hhs_wait_for_temp_control(self, device_id: int | None = None) -> HHSTempControlStoppedResponse:
        """Block until temperature control has stopped. Waits for all devices when *device_id* is None."""
        if device_id is None:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.waitForTempControl",
                )
            )
        else:
            response = self._run(
                self._connected_instrument.venus.send_command(
                    category="Device",
                    action_name="HHS.waitForTempControl",
                    parameters={"deviceId": device_id},
                )
            )
        return self._parse_response(HHSTempControlStoppedResponse, response)

    def hhs_terminate(self) -> MessageResponse:
        """Disconnect all HHS devices and release the connection."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="HHS.terminate",
            )
        )
        return self._parse_response(MessageResponse, response)
