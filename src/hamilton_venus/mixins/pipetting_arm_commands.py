"""Pipetting arm command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.models import (
    ArmIdParameters,
    CommandResponse,
    CoordinateMode,
    PipArmMoveToParameters,
    PipArmSpeed,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class PipettingArmCommandsMixin:
    """Mixin providing pipetting arm control commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def pip_arm_get_x_position(self, arm_id: int = 1) -> CommandResponse:
        """Return the raw X-axis position response for the selected pipetting arm."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="pipArm.getXPosition",
                parameters=ArmIdParameters(arm_id=arm_id).model_dump(by_alias=True),
            )
        )

    def pip_arm_park_left(self, arm_id: int = 1) -> CommandResponse:
        """Park the selected pipetting arm at the left side of the deck."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="pipArm.parkLeft",
                parameters=ArmIdParameters(arm_id=arm_id).model_dump(by_alias=True),
            )
        )

    def pip_arm_park_right(self, arm_id: int = 1) -> CommandResponse:
        """Park the selected pipetting arm at the right side of the deck."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="pipArm.parkRight",
                parameters=ArmIdParameters(arm_id=arm_id).model_dump(by_alias=True),
            )
        )

    def pip_arm_move(
        self,
        value: float,
        coordinate_mode: CoordinateMode | None = None,
        arm_id: int = 1,
        speed: PipArmSpeed | None = None,
        *,
        safety_bypass_token: str | None = None,
    ) -> CommandResponse:
        """Move a pipetting arm using absolute or relative coordinates.

        Args:
            value: Target position or distance in mm.
            safety_bypass_token: Optional token to bypass safety checks.
                VENUS runs its normal safety validation when this is
                omitted; pass the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
            coordinate_mode: Absolute or relative coordinate mode.
            arm_id: Arm identifier (default 1).
            speed: Movement speed setting.
        """
        parameters = PipArmMoveToParameters(
            value=value,
            mode=coordinate_mode,
            arm_id=arm_id,
            speed=speed,
            safety_bypass_token=safety_bypass_token,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="pipArm.moveTo",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

