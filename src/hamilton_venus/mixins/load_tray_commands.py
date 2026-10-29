"""Load tray command methods for VantageClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.models import CommandResponse

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class LoadTrayCommandsMixin:
    """Mixin providing load tray control commands (Vantage only)."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def load_tray_lower(self) -> CommandResponse:
        """Lower the Vantage load tray to the loading position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="loadTray.lowerTray",
                parameters={},
            )
        )

    def load_tray_raise(self) -> CommandResponse:
        """Raise the Vantage load tray to the operational position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="loadTray.raiseTray",
                parameters={},
            )
        )
