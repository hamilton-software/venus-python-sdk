"""Maintenance command methods for StarClient (Instrument category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import CommandResponse, MaintenanceDataResponse

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class MaintenanceCommandsMixin:
    """Mixin providing maintenance commands for instrument maintenance status."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def instrument_get_daily_maintenance_data(self) -> MaintenanceDataResponse:
        """Return the typed daily maintenance status and expiration metadata."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="maintenance.getDailyMaintenanceData",
            )
        )
        return self._parse_response(MaintenanceDataResponse, response)

    def instrument_get_weekly_maintenance_data(self) -> MaintenanceDataResponse:
        """Return the typed weekly maintenance status and expiration metadata."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="maintenance.getWeeklyMaintenanceData",
            )
        )
        return self._parse_response(MaintenanceDataResponse, response)

    def instrument_get_verification_data(self) -> MaintenanceDataResponse:
        """Return the typed verification status and expiration metadata."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="maintenance.getVerificationData",
            )
        )
        return self._parse_response(MaintenanceDataResponse, response)

