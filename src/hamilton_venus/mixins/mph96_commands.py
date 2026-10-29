"""MPH96 (96-channel head) command methods for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.models import (
    CommandResponse,
    MPH96AspirateSettings,
    MPH96ClearTipSupportParameters,
    MPH96ClearTipSupportResponse,
    MPH96DetectLiquidLevelParameters,
    MPH96DispenseSettings,
    MPH96GetStatusResponse,
    MPH96LiquidHandlingParameters,
    MPH96MoveAxisParameters,
    MPH96Pattern,
    MPH96TipEjectParameters,
    MPH96TipPickupParameters,
    MPH96TipPickupPartialParameters,
)
from hamilton_venus.models.enums import (
    Axis,
    CapacitiveLLD,
    CoordinateMode,
    EjectMode,
    MPH96PreAirAspirate,
    MphPickupMode,
    MphPickupSide,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient


class MPH96CommandsMixin:
    """Mixin providing MPH96 (96-channel head) commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def tip_pick_up_mph96(
        self,
        labware_id: str | None = None,
        tip_pool: str | None = None,
        pre_air_aspirate: MPH96PreAirAspirate = MPH96PreAirAspirate.DISABLED,
        pre_air_volume: float | None = None,
    ) -> CommandResponse:
        """Pick up a full set of tips with the MPH96 head."""
        parameters = MPH96TipPickupParameters(
            labware_id=labware_id,
            tip_pool=tip_pool,
            pre_air_aspirate=pre_air_aspirate,
            pre_air_volume=pre_air_volume,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.tipPickup",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def tip_pick_up_mph96_partial(
        self,
        mode: MphPickupMode,
        count: int,
        labware_id: str | None = None,
        tip_pool: str | None = None,
        mph_pickup_side: MphPickupSide = MphPickupSide.LEFT,
        pre_air_aspirate: MPH96PreAirAspirate = MPH96PreAirAspirate.DISABLED,
        pre_air_volume: float | None = None,
    ) -> CommandResponse:
        """Pick up a partial subset of tips with the MPH96 head."""
        parameters = MPH96TipPickupPartialParameters(
            labware_id=labware_id,
            tip_pool=tip_pool,
            mode=mode,
            count=count,
            mph_pickup_side=mph_pickup_side,
            pre_air_aspirate=pre_air_aspirate,
            pre_air_volume=pre_air_volume,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.tipPickupPartial",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def tip_eject_mph96(
        self,
        labware_id: str | None = None,
        mph_pattern: MPH96Pattern | None = None,
        mph_selection: list[str] | list[int] | None = None,
        eject_mode: EjectMode = EjectMode.WASTE,
    ) -> CommandResponse:
        """Eject MPH96 tips, optionally targeting a subset selection pattern.

        `mph_selection` is currently retained as an advanced SDK-only extension
        pending product catalog alignment.
        """
        parameters = MPH96TipEjectParameters(
            labware_id=labware_id,
            mph_pattern=mph_pattern,
            mph_selection=mph_selection,
            eject_mode=eject_mode,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.tipEject",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def aspirate_mph96(
        self,
        labware_id: str,
        *,
        mph_pattern: list[str] | list[int] | None = None,
        volume: float,
        liquid_class: str,
        settings: MPH96AspirateSettings | None = None,
    ) -> CommandResponse:
        """Aspirate liquid with the MPH96 head from the specified labware."""
        resolved_settings = settings or MPH96AspirateSettings()
        parameters = MPH96LiquidHandlingParameters(
            labware_id=labware_id,
            mph_pattern=mph_pattern,
            volume=volume,
            liquid_class=liquid_class,
            **resolved_settings.model_dump(),
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.aspirate",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def dispense_mph96(
        self,
        labware_id: str,
        *,
        mph_pattern: list[str] | list[int] | None = None,
        volume: float,
        settings: MPH96DispenseSettings | None = None,
    ) -> CommandResponse:
        """Dispense liquid with the MPH96 head into the specified labware.

        Dispense has no liquid-class parameter of its own — the liquid class
        used is whichever one the head aspirated with.
        """
        resolved_settings = settings or MPH96DispenseSettings()
        parameters = MPH96LiquidHandlingParameters(
            labware_id=labware_id,
            mph_pattern=mph_pattern,
            volume=volume,
            **resolved_settings.model_dump(),
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.dispense",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def mph96_park_back(self) -> CommandResponse:
        """Park the MPH96 head at its rear parking position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.parkBack",
            )
        )

    def mph96_park_front(self) -> CommandResponse:
        """Park the MPH96 head at its front parking position."""
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.parkFront",
            )
        )

    def mph96_move_axis(
        self,
        axis: Axis,
        value: float,
        mode: CoordinateMode = CoordinateMode.ABSOLUTE,
        *,
        safety_bypass_token: str | None = None,
    ) -> CommandResponse:
        """Move the MPH96 head along the selected axis.

        Args:
            axis: The mechanical axis to move (X, Y, or Z).
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
            mode: Absolute or relative coordinate mode.
        """
        parameters = MPH96MoveAxisParameters(
            axis=axis,
            value=value,
            mode=mode,
            safety_bypass_token=safety_bypass_token,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.moveAxis",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def mph96_detect_liquid_level(
        self,
        labware_id: str,
        mph_pattern: list[str] | list[int] | None = None,
        capacitive_lld: CapacitiveLLD = CapacitiveLLD.MAX,
    ) -> CommandResponse:
        """Detect liquid level with the MPH96 head for the selected wells."""
        parameters = MPH96DetectLiquidLevelParameters(
            labware_id=labware_id,
            mph_pattern=mph_pattern,
            capacitive_lld=capacitive_lld,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.detectLiquidLevel",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def get_status_mph96(self) -> MPH96GetStatusResponse:
        """Return the MPH96 head's current X/Y/Z position and tip-loaded status."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.getStatus",
            )
        )
        return MPH96GetStatusResponse.model_validate(response.model_dump(by_alias=True))

    def mph96_clear_tip_support(self, tip_pool: str) -> MPH96ClearTipSupportResponse:
        """Clear a tip support and return remaining tip metadata."""
        parameters = MPH96ClearTipSupportParameters(tip_pool=tip_pool)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="mph96.clearTipSupport",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return MPH96ClearTipSupportResponse.model_validate(response.model_dump(by_alias=True))
