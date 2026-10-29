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
    WellOrder,
)
from hamilton_venus.models.enums import (
    CapacitiveLLD,
    EjectMode,
    PressureLLD,
)

def max_channels_for(client: object, action_prefix: str, ceiling: int = ...) -> int: ...

class _ChannelCommandsBase:
    def move_axis_relative(
        self,
        channels: list[int] | int,
        *,
        x: float | None = ...,
        y: float | list[float] | None = ...,
        z: float | list[float] | None = ...,
        safety_bypass_token: str | None = ...,
    ) -> ChannelMoveAxisResponse: ...

class ChannelCommandsMixin(_ChannelCommandsBase):
    def move_axis(
        self,
        channels: list[int] | int,
        *,
        x: float | None = ...,
        y: float | list[float] | None = ...,
        z: float | list[float] | None = ...,
        safety_bypass_token: str | None = ...,
    ) -> ChannelMoveAxisResponse: ...
    def get_status(self) -> ChannelGetStatusResponse: ...
    def tip_pickup(
        self,
        channels: list[int] | None = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
        optimized_pickup: bool = ...,
    ) -> CommandResponse: ...
    def tip_eject(
        self,
        channels: list[int] | None = ...,
        eject_mode: EjectMode = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
    ) -> CommandResponse: ...
    def aspirate(
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
    ) -> ChannelAspirationResponse: ...
    def dispense(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        volumes: float | list[float],
        settings: DispenseSettings | None = ...,
        well_order: WellOrder = ...,
        adc: bool | None = ...,
    ) -> ChannelDispenseResponse: ...
    def detect_liquid_level(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        capacitive_lld: CapacitiveLLD = ...,
        pressure_lld: PressureLLD = ...,
        well_order: WellOrder = ...,
    ) -> CommandResponse: ...
    def tip_check(self) -> ChannelTipCheckResponse: ...
    def dispense_on_the_fly(
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
    ) -> CommandResponse: ...

class Channels5mLCommandsMixin(_ChannelCommandsBase):
    def move_axis_5ml(
        self,
        channels: list[int] | int,
        *,
        x: float | None = ...,
        y: float | list[float] | None = ...,
        z: float | list[float] | None = ...,
        safety_bypass_token: str | None = ...,
    ) -> ChannelMoveAxisResponse: ...
    def get_status_5ml(self) -> ChannelGetStatusResponse: ...
    def tip_pickup_5ml(
        self,
        channels: list[int] | None = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
        optimized_pickup: bool = ...,
    ) -> CommandResponse: ...
    def tip_eject_5ml(
        self,
        channels: list[int] | None = ...,
        eject_mode: EjectMode = ...,
        positions: PositionInput | None = ...,
        well_order: WellOrder = ...,
        tip_pool: str | None = ...,
    ) -> CommandResponse: ...
    def aspirate_5ml(
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
    ) -> ChannelAspirationResponse: ...
    def dispense_5ml(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        volumes: float | list[float],
        settings: DispenseSettings | None = ...,
        well_order: WellOrder = ...,
        adc: bool | None = ...,
    ) -> ChannelDispenseResponse: ...
    def detect_liquid_level_5ml(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = ...,
        capacitive_lld: CapacitiveLLD = ...,
        pressure_lld: PressureLLD = ...,
        well_order: WellOrder = ...,
    ) -> CommandResponse: ...
    def tip_check_5ml(self) -> ChannelTipCheckResponse: ...
    def dispense_on_the_fly_5ml(
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
    ) -> CommandResponse: ...
