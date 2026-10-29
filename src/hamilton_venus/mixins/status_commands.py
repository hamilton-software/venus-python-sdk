"""Status command methods for StarClient (Instrument category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    StatusConnectResponse,
    StatusInitResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class StatusCommandsMixin:
    """Mixin class providing status/connection command support to StarClient."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def _load_instrument_config(self) -> Coroutine[Any, Any, None]: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def instrument_is_connected(self) -> bool:
        """Return whether the instrument runtime is connected and responding."""
        return self._run(self._connected_instrument.status_is_connected())

    def instrument_is_idle(self) -> bool:
        """Return whether the instrument runtime is idle (no commands running)."""
        return self._run(self._connected_instrument.status_is_idle())

    def instrument_init(self, force_init: bool = False) -> StatusInitResponse:
        """Initialize the instrument, optionally forcing re-initialization.

        Args:
            force_init: If True, force re-initialization even if already initialized.

        Returns:
            StatusInitResponse with success status and any error details.
        """
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="status.init",
                parameters={"forceInit": force_init},
            )
        )
        return self._parse_response(StatusInitResponse, response)

    def instrument_connect(self, initialize: bool = True) -> StatusConnectResponse:
        """Connect the instrument runtime, optionally initializing the instrument."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="status.connect",
                parameters={"initialize": initialize},
            )
        )
        self._run(self._load_instrument_config())
        return self._parse_response(StatusConnectResponse, response)

    def instrument_terminate(self) -> CommandResponse:
        """Terminate the current method execution."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="status.terminate",
            )
        )

