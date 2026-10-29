"""Front cover command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import CommandResponse, FrontCoverIsClosedResponse, FrontCoverIsLockedResponse

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class FrontCoverCommandsMixin:
    """Mixin providing front cover control commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def front_cover_is_closed(self) -> FrontCoverIsClosedResponse:
        """Return the typed front-cover closed-state response."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="frontCover.isClosed",
            )
        )
        return self._parse_response(FrontCoverIsClosedResponse, response)

    def front_cover_is_locked(self) -> FrontCoverIsLockedResponse:
        """Return the typed front-cover lock-state response."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="frontCover.isLocked",
            )
        )
        return self._parse_response(FrontCoverIsLockedResponse, response)

    def front_cover_lock(self) -> CommandResponse:
        """Lock the front cover through the system command channel."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="frontCover.lock",
            )
        )

    def front_cover_unlock(self) -> CommandResponse:
        """Unlock the front cover through the system command channel."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="frontCover.unlock",
            )
        )

