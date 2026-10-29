"""Protocol defining the instrument-client interface used by compound commands.

Both :class:`~hamilton_venus.star_client.StarClient` and
:class:`~hamilton_venus.vantage_client.VantageClient` satisfy this protocol —
compound commands should accept ``InstrumentClient`` rather than the concrete
class so they work with either instrument.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hamilton_venus._internal._operator_prompts import LiquidReloadPromptCallback, TipReloadPromptCallback
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.command_types import (
        ChannelAspirationResponse,
        ChannelDispenseResponse,
        TipPoolAvailableTipsResponse,
        TipPoolCounterResponse,
        TipTypesResponse,
    )
    from hamilton_venus.models.commands import CommandResponse
    from hamilton_venus.models.enums import EjectMode, WellOrder
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
    from hamilton_venus.models.position import LabwareLayoutSpec, PositionInput


@runtime_checkable
class InstrumentClient(Protocol):
    """Structural protocol satisfied by StarClient and VantageClient.

    Compound-command implementations type their ``client`` parameter as
    ``InstrumentClient`` so they work unchanged with both instruments.
    """

    on_tip_reload_prompt: TipReloadPromptCallback | None
    on_liquid_reload_prompt: LiquidReloadPromptCallback | None

    def get_labware_spec(self, labware_id: str) -> LabwareLayoutSpec: ...

    def register_labware_definition(self, labware_id: str, spec: LabwareLayoutSpec) -> None: ...

    @contextmanager
    def use_error_profile(self, profile: ErrorProfile) -> Iterator[None]: ...

    def tip_pickup(
        self,
        positions: PositionInput | None = None,
        *,
        tip_pool: str | None = None,
        channels: list[int] | None = None,
        optimized_pickup: bool = True,
    ) -> CommandResponse: ...

    def tip_eject(
        self,
        eject_mode: EjectMode = ...,
        positions: PositionInput | None = None,
        *,
        tip_pool: str | None = None,
        channels: list[int] | None = None,
    ) -> CommandResponse: ...

    def aspirate(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        volumes: float | list[float],
        liquid_class: str | list[str],
        settings: AspirateSettings | None = None,
        well_order: WellOrder = ...,
        mad_enabled: bool | None = None,
        mad_threshold: int | None = None,
        adc: bool | None = None,
    ) -> ChannelAspirationResponse: ...

    def dispense(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        volumes: float | list[float],
        settings: DispenseSettings | None = None,
        well_order: WellOrder = ...,
        adc: bool | None = None,
    ) -> ChannelDispenseResponse: ...

    def tip_pool_get_available_tips(self, tip_pool: str) -> TipPoolAvailableTipsResponse: ...

    def tip_pool_get_tip_counter(self, tip_pool: str) -> TipPoolCounterResponse: ...

    def tip_pool_reset_tip_counter(self, tip_pool: str) -> CommandResponse: ...

    def get_tip_types(self) -> TipTypesResponse: ...

    def labware_get_params_from_id(self, labware_name: str) -> CommandResponse: ...
