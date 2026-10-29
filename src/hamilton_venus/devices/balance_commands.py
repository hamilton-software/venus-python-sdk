"""WXS Balance command methods for VantageClient (Device category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    MessageResponse,
    WXSGetWeightResponse,
    WXSTareResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class BalanceDeviceCommands:
    """Device command group for WXS Balance."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def wxs_initialize_balance(
        self,
        port: int,
        time_out_seconds: int | None = None,
        trials: int | None = None,
    ) -> MessageResponse:
        """Establish a connection to the balance.

        Parameters
        ----------
        port:
            COM-Port number the device is connected to.
        time_out_seconds:
            Time after which a timeout occurs (optional, 0-60).
        trials:
            Number of trials to establish a connection (optional, 1-10).
        """
        parameters: dict[str, Any] = {"port": port}
        if time_out_seconds is not None:
            parameters["timeOutSeconds"] = time_out_seconds
        if trials is not None:
            parameters["trials"] = trials
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.initializeBalance",
                parameters=parameters,
            )
        )
        return self._parse_response(MessageResponse, response)

    def wxs_reset_scale(self) -> MessageResponse:
        """Reset the scale."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.resetScale",
            )
        )
        return self._parse_response(MessageResponse, response)

    def wxs_set_zero(self, zero_immediately: bool | None = None) -> MessageResponse:
        """Set a new zero point on the scale.

        Clears the tare memory. All weight values (including tare weight) will be
        measured relative to this new zero.

        Parameters
        ----------
        zero_immediately:
            Set a new zero immediately, regardless of balance stability (optional).
        """
        parameters: dict[str, Any] = {}
        if zero_immediately is not None:
            parameters["zeroImmidiately"] = zero_immediately
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.setZero",
                parameters=parameters if parameters else None,
            )
        )
        return self._parse_response(MessageResponse, response)

    def wxs_tare(self, tare_immediately: bool | None = None) -> WXSTareResponse:
        """Tare the scale.

        Note: Call ``wxs_set_zero`` before using this method.
        Having negative weight on the scale may lead to an error.

        Parameters
        ----------
        tare_immediately:
            Tare the balance immediately and independently of balance stability (optional).

        Returns
        -------
        WXSTareResponse
            ``tare_weight``: The tare weight value corresponding to the weight change on the balance.
        """
        parameters: dict[str, Any] = {}
        if tare_immediately is not None:
            parameters["tareImmidiately"] = tare_immediately
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.tare",
                parameters=parameters if parameters else None,
            )
        )
        return self._parse_response(WXSTareResponse, response)

    def wxs_internal_calibration(self) -> MessageResponse:
        """Start an internal adjustment procedure of the scale."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.internalCalibration",
            )
        )
        return self._parse_response(MessageResponse, response)

    def wxs_get_weight(self, weigh_immediately: bool | None = None) -> WXSGetWeightResponse:
        """Get a stable or dynamic weight value from the scale.

        Parameters
        ----------
        weigh_immediately:
            Immediately get the current weight value (optional).

        Returns
        -------
        WXSGetWeightResponse
            ``weight_gramm``: Measured weight value in grams.
            ``weight_stable``: Whether the measured value was stable.
            ``measured_weight``: Raw measured weight from the scale.
            ``measured_unit``: Measured unit from the scale.
        """
        parameters: dict[str, Any] = {}
        if weigh_immediately is not None:
            parameters["weighImmidiately"] = weigh_immediately
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.getWeight",
                parameters=parameters if parameters else None,
            )
        )
        return self._parse_response(WXSGetWeightResponse, response)

    def wxs_set_scale_parameters(
        self,
        weighing_mode: int | None = None,
        vibration: int | None = None,
        stability: int | None = None,
        weight_unit: int | None = None,
        auto_zero: bool | None = None,
    ) -> MessageResponse:
        """Set general scale parameters.

        Parameters
        ----------
        weighing_mode:
            Weighing mode (optional): 0 = Normal, 1 = Dosing.
        vibration:
            Weight value release filter (optional):
            0 = Very fast, 1 = Fast, 2 = Reliable and fast,
            3 = Reliable, 4 = Very reliable.
        stability:
            Ambient condition optimisation (optional):
            0 = Very stable, 1 = Stable, 2 = Standard,
            3 = Unstable, 4 = Very unstable, 5 = Automatic.
        weight_unit:
            Output weighing unit (optional):
            0 = g, 1 = kg, 2 = t, 3 = mg, 4 = µg, 5 = ct, 6 = N,
            7 = lb, 8 = oz, 9 = ozt, 10 = GN, 11 = dwt, 12 = mom,
            13 = msg, 14 = tlh, 15 = tls, 16 = tlt, 17 = tcl,
            18 = tola, 19 = baht, 20 = lb[oz], 21 = ton,
            25 = no unit, 26 = PCS, 27 = %, 28 = cu1, 29 = cu2,
            30 = Currency unit 1, 31 = Currency unit 2.
        auto_zero:
            Enable or disable the auto zero function (optional).
        """
        parameters: dict[str, Any] = {}
        if weighing_mode is not None:
            parameters["weighingMode"] = weighing_mode
        if vibration is not None:
            parameters["vibration"] = vibration
        if stability is not None:
            parameters["stability"] = stability
        if weight_unit is not None:
            parameters["weightUnit"] = weight_unit
        if auto_zero is not None:
            parameters["autoZero"] = auto_zero
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.setScaleParameters",
                parameters=parameters if parameters else None,
            )
        )
        return self._parse_response(MessageResponse, response)

    def wxs_terminate_balance(self) -> MessageResponse:
        """Terminate the connection to the balance."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Device",
                action_name="WXS.terminateBalance",
            )
        )
        return self._parse_response(MessageResponse, response)
