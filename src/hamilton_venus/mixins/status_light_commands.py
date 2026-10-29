"""Status light command methods for StarClient and VantageClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.models import (
    CommandResponse,
    StatusLightSetFrontLightParameters,
    StatusLightSetInteriorLightParameters,
)
from hamilton_venus.models.enums import InteriorLightState, LightColor

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class StatusLightCommandsMixin:
    """Mixin providing status light control commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def status_light_set_front_light(
        self,
        color: LightColor,
        blink: bool = False,
        progress: int = 0,
    ) -> CommandResponse:
        """Set color, blink, and discrete progress level in one command."""
        parameters = StatusLightSetFrontLightParameters(color=color, blink=blink, progress=progress)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="statusLight.setFrontLight",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def status_light_set_interior_light(
        self,
        light_state: InteriorLightState,
        light_intensity: int | None = None,
        blink_interval: int | None = None,
        white: int = 0,
        red: int = 0,
        green: int = 0,
        blue: int = 0,
    ) -> CommandResponse:
        """Set the Vantage interior light state, intensity, blink interval, and color mix.

        ``light_intensity`` (0-100) and ``colors`` are only used when ``light_state`` is
        ``ON`` or ``BLINK``. ``blink_interval`` (1-10000 ms) is only used when
        ``light_state`` is ``BLINK`` or ``RAINBOW_DASH``. Omit optional parameters to
        let the instrument use its own defaults.
        """
        from hamilton_venus.models.command_types import InteriorLightColors

        colors = InteriorLightColors(white=white, red=red, green=green, blue=blue)
        parameters = StatusLightSetInteriorLightParameters(
            light_state=light_state,
            light_intensity=light_intensity,
            blink_interval=blink_interval,
            colors=colors,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="statusLight.setInteriorLight",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

