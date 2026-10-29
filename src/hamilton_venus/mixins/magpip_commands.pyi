from hamilton_venus.mixins.channel_commands import _ChannelCommandsBase
from hamilton_venus.models import (
    AspirateSettings,
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelGetStatusResponse,
    ChannelMoveAxisResponse,
    ChannelTipCheckResponse,
    CommandResponse,
    DispenseSettings,
    PositionInput,
    TadmSettings,
    WellOrder,
)
from hamilton_venus.models.enums import (
    CapacitiveLLD,
    EjectMode,
    PressureLLD,
)

class ChannelsMagPipCommandsMixin(_ChannelCommandsBase):
    def tip_pickup_magpip(
        self,
        channels: list[int] | None = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
        optimized_pickup: bool = ...,
    ) -> CommandResponse: ...
    def tip_eject_magpip(
        self,
        channels: list[int] | None = ...,
        eject_mode: EjectMode = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
    ) -> CommandResponse: ...
    def detect_liquid_level_magpip(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        capacitive_lld: CapacitiveLLD = ...,
        pressure_lld: PressureLLD = ...,
        well_order: WellOrder = ...,
    ) -> CommandResponse: ...
    def tip_check_magpip(self) -> ChannelTipCheckResponse: ...
    def aspirate_magpip(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        volumes: float | list[float],
        liquid_class: str | list[str],
        settings: AspirateSettings | None = ...,
        well_order: WellOrder = ...,
        mad_enabled: bool | None = ...,
        mad_threshold: int | None = ...,
        adc: bool | None = ...,
        tadm: TadmSettings | None = ...,
    ) -> ChannelAspirationResponse: ...
    def dispense_magpip(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        volumes: float | list[float],
        settings: DispenseSettings | None = ...,
        well_order: WellOrder = ...,
        adc: bool | None = ...,
        tadm: TadmSettings | None = ...,
    ) -> ChannelDispenseResponse: ...
    def dispense_on_the_fly_magpip(
        self,
        channels: list[int],
        labware_name: str,
        volumes: float | list[float],
        labware_surface_distance: float,
        start_x_offset: float = ...,
        x_speed: float = ...,
        x_acceleration_distance: float = ...,
        dispense_direction: int = ...,
        excluded_positions: list[str] | None = ...,
        *,
        adc: bool | None = ...,
        tadm: TadmSettings | None = ...,
    ) -> CommandResponse: ...
    def move_axis_magpip(
        self,
        channels: list[int] | int,
        *,
        x: float | None = ...,
        y: float | list[float] | None = ...,
        z: float | list[float] | None = ...,
        safety_bypass_token: str | None = ...,
    ) -> ChannelMoveAxisResponse: ...
    def get_status_magpip(self) -> ChannelGetStatusResponse: ...
    def move_axis_relative_magpip(
        self,
        channels: list[int] | int,
        *,
        x: float | None = ...,
        y: float | list[float] | None = ...,
        z: float | list[float] | None = ...,
        safety_bypass_token: str | None = ...,
    ) -> ChannelMoveAxisResponse: ...
