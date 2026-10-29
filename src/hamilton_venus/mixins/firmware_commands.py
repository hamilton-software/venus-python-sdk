"""Firmware command methods for StarClient (Instrument category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import CommandResponse, FirmwareCommandParameters, FirmwareCommandResponse

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class FirmwareCommandsMixin:
    """Mixin providing raw firmware command access.

    These commands send firmware instructions directly to the instrument and are
    intended for advanced use only. Prefer the typed command mixins when a
    dedicated SDK helper exists.
    """

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def firmware_debug_mode(self, enable: bool) -> CommandResponse:
        """Enable or disable firmware debug mode on the instrument.

        Parameters
        ----------
        enable:
            ``True`` to enable debug mode, ``False`` to disable it.
        """
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="firmware.debugMode",
                parameters={"enable": enable},
            )
        )

    def firmware_command(
        self,
        command: str,
        parameters: str = "",
        *,
        safety_bypass_token: str,
    ) -> FirmwareCommandResponse:
        """Send a raw firmware command to the instrument.

        This is an advanced, low-level command that bypasses the typed SDK
        helpers. Prefer a dedicated command mixin whenever one exists.

        Parameters
        ----------
        command:
            Firmware command: the module and command code, sent upper case. On
            a STAR that is 4 characters, for example ``"C0AS"``; on a Vantage
            6 to 8, for example ``"A1PMRF"``.
        parameters:
            Firmware command parameters, for example ``"tm1 1 1 1 1 1 1 1"``.
            VENUS sends them lower case, so they cannot carry any part of the
            command code.
        safety_bypass_token:
            Security token required to override instrument safety checks. Pass
            the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS` to
            bypass safety validation -- it is not an arbitrary flag, and any
            other string is rejected with a firmware error. Unlike the other
            movement commands, VENUS requires this token for every firmware
            command regardless of whether it actually needs to bypass anything.

            .. warning::

               Bypassing safety checks risks collisions that can damage hardware
               or cause injury. Using this token waives vendor liability for any
               resulting damage.

        Returns
        -------
        FirmwareCommandResponse
            Typed response exposing the raw firmware ``return`` value.
        """
        request = FirmwareCommandParameters(
            command=command,
            parameters=parameters,
            safety_bypass_token=safety_bypass_token,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="firmware.command",
                parameters=request.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(FirmwareCommandResponse, response)
