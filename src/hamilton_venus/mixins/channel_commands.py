"""Channel command methods for StarClient.

Provides both 1mL and 5mL channel command mixins via a shared factory pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML, CHANNEL_PITCH_MM_5ML, MAX_CHANNELS
from hamilton_venus.mixins.split_well_commands import route_split_wells
from hamilton_venus.models import (
    AspirateParameters,
    AspirateSettings,
    ChannelAspirationResponse,
    ChannelDispenseOnTheFlyParameters,
    ChannelDispenseResponse,
    ChannelGetStatusResponse,
    ChannelMoveAxisParameters,
    ChannelMoveAxisResponse,
    ChannelTipCheckResponse,
    CommandResponse,
    DetectLiquidLevelParameters,
    DispenseParameters,
    DispenseSettings,
    PositionInput,
    TipEjectParameters,
    TipPickupParameters,
    WellOrder,
)
from hamilton_venus.models.enums import (
    CapacitiveLLD,
    EjectMode,
    PressureLLD,
)
from hamilton_venus.models.position import normalize_positions

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ChannelValueT = TypeVar("_ChannelValueT")


def max_channels_for(client: object, action_prefix: str, ceiling: int = MAX_CHANNELS) -> int:
    """Return the channel count *client*'s instrument reported for *action_prefix*.

    Falls back to *ceiling* until the instrument configuration has been read.
    """
    return getattr(client, "_channel_limits", {}).get(action_prefix, ceiling)


class _ChannelCommandsBase:
    """Base mixin providing parameterized channel (pipetting) commands."""

    _CHANNEL_PITCH_MM: float
    _DEFAULT_CHANNELS: list[int]
    _MAX_CHANNELS: int
    _ACTION_PREFIX: str

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    @staticmethod
    def _validate_per_channel(
        value: _ChannelValueT | list[_ChannelValueT],
        channel_count: int,
        field_name: str,
    ) -> _ChannelValueT | list[_ChannelValueT]:
        if isinstance(value, list) and len(value) != channel_count:
            raise ValueError(
                f"{field_name} expected {channel_count} entries for {channel_count} channels, got {len(value)}"
            )
        return value

    @staticmethod
    def _expand_per_channel(
        value: _ChannelValueT | list[_ChannelValueT],
        channel_count: int,
        field_name: str,
    ) -> list[_ChannelValueT]:
        if isinstance(value, list):
            if len(value) != channel_count:
                raise ValueError(
                    f"{field_name} expected {channel_count} entries for {channel_count} channels, got {len(value)}"
                )
            return value
        return [value] * channel_count

    def _validate_channel_count(self, channels: list[int]) -> None:
        """Validate that the channel count and channel numbers fit the installed channels.

        The limit is the channel total the instrument reported in its configuration
        when it connected; before that (or if the query failed) it is the SDK ceiling.

        Args:
            channels: List of channel numbers.

        Raises:
            ValueError: If no channels were given, the channel count exceeds the
                maximum, or a channel number is outside ``1..maximum``.
        """
        if not channels:
            raise ValueError("channels must not be empty (omit `channels` to use the default channels)")
        max_channels = max_channels_for(self, self._ACTION_PREFIX, self._MAX_CHANNELS)
        channel_type = self._ACTION_PREFIX.replace("channels.", "")
        if len(channels) > max_channels:
            raise ValueError(
                f"{channel_type} support a maximum of {max_channels} channels, "
                f"but {len(channels)} were specified: {channels}"
            )
        invalid = [ch for ch in channels if ch < 1 or ch > max_channels]
        if invalid:
            raise ValueError(
                f"{channel_type} channel numbers must be between 1 and {max_channels}, but got: {invalid}"
            )

    def _tip_pickup_impl(
        self,
        channels: list[int] | None = None,
        positions: PositionInput | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        tip_pool: str | None = None,
        optimized_pickup: bool = True,
    ) -> CommandResponse:
        """Pick up tips (implementation method).

        Supports two picking modes:

        1. **Manual mode**: Pick tips from explicit positions.
           ``tip_pickup(channels=[1,2,3], positions="TipRack@col:1")``

        2. **TipPool mode**: Pick tips from a managed pool.
           ``tip_pickup(channels=[1,2,3], tip_pool="TransferTips", optimized_pickup=True)``

        When using manual mode, the SDK accepts position selector DSL inputs
        (e.g., "TipRack@col:1") and normalizes them into concrete ``labwareId``/``wellId``
        entries.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
        """
        if channels is None:
            channels = self._DEFAULT_CHANNELS
        self._validate_channel_count(channels)
        normalized_positions = (
            normalize_positions(
                positions,
                well_order=well_order,
                channel_count=len(channels),
                get_spec=self.get_labware_spec,
                channel_pitch_mm=self._CHANNEL_PITCH_MM,
            )
            if positions is not None
            else None
        )
        parameters = TipPickupParameters(
            channels=channels,
            positions=normalized_positions,
            tip_pool=tip_pool,
            optimized_pickup=optimized_pickup if tip_pool is not None else None,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.tipPickup",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def _tip_eject_impl(
        self,
        channels: list[int] | None = None,
        eject_mode: EjectMode = EjectMode.WASTE,
        positions: PositionInput | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        tip_pool: str | None = None,
    ) -> CommandResponse:
        """Eject tips (implementation method).

        Supports multiple ejection modes:

        1. **Waste mode** (default): Eject to default waste location.
           ``tip_eject(channels=[1,2,3])``

        2. **Return mode**: Return tips to pickup positions.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.RETURN)``

        3. **Explicit positions mode**: Eject to specific locations.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.POSITIONS, positions="TipRack@col:1")``

        4. **TipPool mode**: Return tips to an empty slot in a managed pool.
           ``tip_eject(channels=[1,2,3], eject_mode=EjectMode.TIP_POOL, tip_pool="TransferTips")``

        When positions are provided, the SDK accepts position selector DSL inputs
        and normalizes them into concrete wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
        """
        if channels is None:
            channels = self._DEFAULT_CHANNELS
        self._validate_channel_count(channels)
        normalized_positions = (
            normalize_positions(
                positions,
                well_order=well_order,
                channel_count=len(channels),
                get_spec=self.get_labware_spec,
                channel_pitch_mm=self._CHANNEL_PITCH_MM,
            )
            if positions is not None
            else None
        )

        parameters = TipEjectParameters(
            channels=channels,
            eject_mode=eject_mode,
            positions=normalized_positions,
            tip_pool=tip_pool,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.tipEject",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def _aspirate_impl(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        volumes: float | list[float],
        liquid_class: str | list[str],
        settings: AspirateSettings | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        mad_enabled: bool | None = None,
        mad_threshold: int | None = None,
        adc: bool | None = None,
    ) -> ChannelAspirationResponse:
        """Aspirate liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        concrete ``LabwareWell[]`` entries required by the wire contract.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Aspirate volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            liquid_class: Liquid class name. Scalar or per-channel list.
            settings: Reusable :class:`AspirateSettings` object controlling
                LLD, mixing, submerge depth, touch-off, and other behaviors.
            well_order: Well expansion order for selector inputs.
            mad_enabled: Enable Monitored Air Displacement. Single value for
                all channels (not per-channel). ``None`` (default) omits the
                field from the wire call, so VENUS applies its own default
                (disabled).
            mad_threshold: MAD pressure threshold. Range 1-1023. Single value
                for all channels. ``None`` (default) omits the field, so
                VENUS applies its own default (``30``).
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels. ``None`` (default) omits the field,
                so VENUS applies its own default (disabled).
        """
        if channels is None:
            channels = self._DEFAULT_CHANNELS
        self._validate_channel_count(channels)
        resolved_settings = settings or AspirateSettings()
        channel_count = len(channels)
        parameters = AspirateParameters(
            channels=channels,
            positions=route_split_wells(
                self,
                normalize_positions(
                    positions,
                    well_order=well_order,
                    channel_count=channel_count,
                    get_spec=self.get_labware_spec,
                    channel_pitch_mm=self._CHANNEL_PITCH_MM,
                ),
                channels,
                self._ACTION_PREFIX,
            ),
            volumes=self._validate_per_channel(volumes, channel_count, "volumes"),
            liquid_class=self._validate_per_channel(liquid_class, channel_count, "liquid_class"),
            aspirate_mode=self._validate_per_channel(
                resolved_settings.aspirate_mode,
                channel_count,
                "aspirate_mode",
            ),
            capacitive_lld=self._validate_per_channel(
                resolved_settings.capacitive_lld,
                channel_count,
                "capacitive_lld",
            ),
            pressure_lld=self._validate_per_channel(
                resolved_settings.pressure_lld,
                channel_count,
                "pressure_lld",
            ),
            liquid_following=self._validate_per_channel(
                resolved_settings.liquid_following,
                channel_count,
                "liquid_following",
            ),
            tip_tracking_factor=resolved_settings.tip_tracking_factor,
            submerge_depth=self._validate_per_channel(
                resolved_settings.submerge_depth,
                channel_count,
                "submerge_depth",
            ),
            fixed_height=self._validate_per_channel(
                resolved_settings.fixed_height,
                channel_count,
                "fixed_height",
            ),
            max_lld_difference=self._validate_per_channel(
                resolved_settings.max_lld_difference,
                channel_count,
                "max_lld_difference",
            ),
            mix_cycles=self._validate_per_channel(
                resolved_settings.mix_cycles,
                channel_count,
                "mix_cycles",
            ),
            mix_position=self._validate_per_channel(
                resolved_settings.mix_position,
                channel_count,
                "mix_position",
            ),
            mix_volume=self._validate_per_channel(
                resolved_settings.mix_volume,
                channel_count,
                "mix_volume",
            ),
            air_transport_retract_dist=self._validate_per_channel(
                resolved_settings.air_transport_retract_dist,
                channel_count,
                "air_transport_retract_dist",
            ),
            touch_off=self._validate_per_channel(
                resolved_settings.touch_off,
                channel_count,
                "touch_off",
            ),
            touch_off_height=self._validate_per_channel(
                resolved_settings.touch_off_height,
                channel_count,
                "touch_off_height",
            ),
            mad_enabled=mad_enabled,
            mad_threshold=mad_threshold,
            adc=adc,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.aspirate",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return ChannelAspirationResponse.model_validate(response.model_dump())

    def _dispense_impl(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        volumes: float | list[float],
        settings: DispenseSettings | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        adc: bool | None = None,
    ) -> ChannelDispenseResponse:
        """Dispense liquid with channels (implementation method).

        The SDK accepts flexible ``positions`` input (selector DSL strings,
        ``Position`` objects, or wire-format dicts) and normalizes them into
        the vector-style payload compatible with the current VENUS helper path.

        Dispense has no liquid-class parameter of its own — the liquid class
        used is whichever one the tip aspirated with.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.  Examples: ``"Plate1@col:1"``, ``"Plate1@A1,B1"``.
            volumes: Dispense volume(s) in uL. Scalar applies uniformly;
                a list must match the number of channels.
            adc: Enable Aspiration/Dispense Control (TADM-based). Single
                value for all channels (not per-channel). ``None`` (default)
                omits the field from the wire call, so VENUS applies its own
                default (disabled).
            settings: Reusable :class:`DispenseSettings` object controlling
                dispense mode, LLD, mixing, touch-off, and side-touch.
            well_order: Well expansion order for selector inputs.
        """
        if channels is None:
            channels = self._DEFAULT_CHANNELS
        self._validate_channel_count(channels)
        resolved_settings = settings or DispenseSettings()
        channel_count = len(channels)
        parameters = DispenseParameters(
            channels=channels,
            positions=route_split_wells(
                self,
                normalize_positions(
                    positions,
                    well_order=well_order,
                    channel_count=channel_count,
                    get_spec=self.get_labware_spec,
                    channel_pitch_mm=self._CHANNEL_PITCH_MM,
                ),
                channels,
                self._ACTION_PREFIX,
            ),
            volumes=self._validate_per_channel(volumes, channel_count, "volumes"),
            dispense_mode=self._validate_per_channel(
                resolved_settings.dispense_mode,
                channel_count,
                "dispense_mode",
            ),
            capacitive_lld=self._validate_per_channel(
                resolved_settings.capacitive_lld,
                channel_count,
                "capacitive_lld",
            ),
            liquid_following=self._validate_per_channel(
                resolved_settings.liquid_following,
                channel_count,
                "liquid_following",
            ),
            tip_tracking_factor=resolved_settings.tip_tracking_factor,
            submerge_depth=self._validate_per_channel(
                resolved_settings.submerge_depth,
                channel_count,
                "submerge_depth",
            ),
            fixed_height=self._validate_per_channel(
                resolved_settings.fixed_height,
                channel_count,
                "fixed_height",
            ),
            mix_cycles=self._validate_per_channel(
                resolved_settings.mix_cycles,
                channel_count,
                "mix_cycles",
            ),
            mix_position=self._validate_per_channel(
                resolved_settings.mix_position,
                channel_count,
                "mix_position",
            ),
            mix_volume=self._validate_per_channel(
                resolved_settings.mix_volume,
                channel_count,
                "mix_volume",
            ),
            air_transport_retract_dist=self._validate_per_channel(
                resolved_settings.air_transport_retract_dist,
                channel_count,
                "air_transport_retract_dist",
            ),
            touch_off=self._validate_per_channel(
                resolved_settings.touch_off,
                channel_count,
                "touch_off",
            ),
            touch_off_height=self._validate_per_channel(
                resolved_settings.touch_off_height,
                channel_count,
                "touch_off_height",
            ),
            use_side_touch=resolved_settings.use_side_touch,
            adc=adc,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.dispense",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return ChannelDispenseResponse.model_validate(response.model_dump())

    def _move_axis_impl(
        self,
        channels: list[int] | int,
        *,
        x: float | None = None,
        y: float | list[float] | None = None,
        z: float | list[float] | None = None,
        safety_bypass_token: str | None = None,
    ) -> ChannelMoveAxisResponse:
        """Move channels directly to absolute X/Y/Z coordinates (implementation method).

        Args:
            channels: Channel number(s) to move.
            x: Target absolute X position in mm. Shared by all channels
                (the gantry moves as one unit in X); a single value only.
            y: Target absolute Y position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            z: Target absolute Z position(s) in mm. A single value applies to
                every channel; a list must match the number of channels.
            safety_bypass_token: Optional token to bypass safety checks. VENUS
                runs its normal safety validation when this is omitted; pass
                the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
        """
        parameters = ChannelMoveAxisParameters(
            channels=channels,
            x=x,
            y=y,
            z=z,
            safety_bypass_token=safety_bypass_token,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.moveAxis",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return ChannelMoveAxisResponse.model_validate(response.model_dump(by_alias=True))

    def _get_status_impl(self) -> ChannelGetStatusResponse:
        """Return the current X/Y/Z position and tip-loaded status for every channel (implementation method)."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.getStatus",
            )
        )
        return ChannelGetStatusResponse.model_validate(response.model_dump(by_alias=True))

    def move_axis_relative(
        self,
        channels: list[int] | int,
        *,
        x: float | None = None,
        y: float | list[float] | None = None,
        z: float | list[float] | None = None,
        safety_bypass_token: str | None = None,
    ) -> ChannelMoveAxisResponse:
        """Move 1 mL channels by a relative X/Y/Z offset.

        VENUS's ``channels.1mL.moveAxis`` only accepts absolute coordinates —
        there is no relative mode. This first calls :meth:`get_status` for
        each requested channel's current position, adds the requested offset
        to each coordinate, and issues :meth:`move_axis` with the resolved
        absolute values.

        Args:
            channels: Channel number(s) to move.
            x: Offset to apply to the shared X position in mm. A single
                value only (X is shared by all channels).
            y: Offset(s) to apply to each channel's Y position in mm. A
                single value applies to every channel; a list must match the
                number of channels.
            z: Offset(s) to apply to each channel's Z position in mm. A
                single value applies to every channel; a list must match the
                number of channels.
            safety_bypass_token: Optional token to bypass safety checks. VENUS
                runs its normal safety validation when this is omitted; pass
                the exact literal :data:`hamilton_venus.OVERRIDE_SAFETY_CHECKS`
                to bypass it. It is not an arbitrary flag -- any other string
                is rejected.

                .. warning::

                   Bypassing safety checks risks collisions that can damage hardware
                   or cause injury. Using this token waives vendor liability for any
                   resulting damage.
        """
        channel_list = [channels] if isinstance(channels, int) else list(channels)
        channel_count = len(channel_list)
        current = self.get_status()
        positions_by_channel = {status.channel: status for status in current.return_parameters.channel_status}

        missing = [ch for ch in channel_list if ch not in positions_by_channel]
        if missing:
            raise ValueError(
                f"move_axis_relative: channel(s) {missing} not present in get_status() response "
                f"(channels reported: {sorted(positions_by_channel)})"
            )

        new_x: float | None = None
        if x is not None:
            new_x = positions_by_channel[channel_list[0]].x + x

        new_y: float | list[float] | None = None
        if y is not None:
            y_deltas = self._expand_per_channel(y, channel_count, "y")
            new_y = [positions_by_channel[ch].y + dy for ch, dy in zip(channel_list, y_deltas, strict=True)]

        new_z: float | list[float] | None = None
        if z is not None:
            z_deltas = self._expand_per_channel(z, channel_count, "z")
            new_z = [positions_by_channel[ch].z + dz for ch, dz in zip(channel_list, z_deltas, strict=True)]

        return self.move_axis(
            channel_list,
            x=new_x,
            y=new_y,
            z=new_z,
            safety_bypass_token=safety_bypass_token,
        )

    def _detect_liquid_level_impl(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        capacitive_lld: CapacitiveLLD = CapacitiveLLD.MAX,
        pressure_lld: PressureLLD = PressureLLD.OFF,
        well_order: WellOrder = WellOrder.COL_ASC,
    ) -> CommandResponse:
        """Detect liquid level with channels (implementation method).

        Perform capacitive and/or pressure-based liquid-level detection at
        the specified positions.  ``positions`` may be passed as selector
        DSL input and is normalized to explicit wire-format positions.

        Args:
            channels: Channel numbers to use. Defaults to all 8 channels ``[1, 2, 3, 4, 5, 6, 7, 8]``.
            positions: Target positions as selector DSL, explicit wells, or
                dicts.
            capacitive_lld: Capacitive LLD sensitivity. Defaults to
                ``CapacitiveLLD.MAX``.
            pressure_lld: Pressure LLD sensitivity. Defaults to
                ``PressureLLD.OFF``.
            well_order: Well expansion order for selector inputs.
        """
        if channels is None:
            channels = self._DEFAULT_CHANNELS
        self._validate_channel_count(channels)
        parameters = DetectLiquidLevelParameters(
            channels=channels,
            positions=route_split_wells(
                self,
                normalize_positions(
                    positions,
                    well_order=well_order,
                    channel_count=len(channels),
                    get_spec=self.get_labware_spec,
                    channel_pitch_mm=self._CHANNEL_PITCH_MM,
                ),
                channels,
                self._ACTION_PREFIX,
            ),
            capacitive_lld=capacitive_lld,
            pressure_lld=pressure_lld,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.detectLiquidLevel",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    def _tip_check_impl(self) -> ChannelTipCheckResponse:
        """Return current tip status for active channels (implementation method)."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.tipCheck",
            )
        )
        return ChannelTipCheckResponse.model_validate(response.model_dump(by_alias=True))

    def _dispense_on_the_fly_impl(
        self,
        channels: list[int],
        labware_name: str,
        volumes: float | list[float],
        labware_surface_distance: float,
        start_x_offset: float = 0.0,
        x_speed: float = 0.0,
        x_acceleration_distance: float = 8.0,
        dispense_direction: int = 0,
        excluded_positions: list[str] | None = None,
    ) -> CommandResponse:
        """Dispense across wells while translating in X on a single pass (implementation method)."""
        parameters = ChannelDispenseOnTheFlyParameters(
            channels=channels,
            labware_name=labware_name,
            volumes=volumes,
            labware_surface_distance=labware_surface_distance,
            start_x_offset=start_x_offset,
            x_speed=x_speed,
            x_acceleration_distance=x_acceleration_distance,
            dispense_direction=dispense_direction,
            excluded_positions=excluded_positions or [],
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name=f"{self._ACTION_PREFIX}.dispenseOnTheFly",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )


def _create_channel_commands_mixin(
    name: str,
    channel_pitch_mm: float,
    default_channels: list[int],
    max_channels: int,
    action_prefix: str,
    method_suffix: str = "",
) -> type[_ChannelCommandsBase]:
    """Factory function to create channel command mixin classes.

    Args:
        name: Name of the mixin class.
        channel_pitch_mm: Channel pitch in mm.
        default_channels: Default list of channel numbers.
        max_channels: Maximum number of channels.
        action_prefix: Prefix for action names (e.g., "channels.1mL").
        method_suffix: Suffix for method names (e.g., "", "_5ml").

    Returns:
        A new mixin class with the specified configuration.
    """

    class ChannelCommandsMixin(_ChannelCommandsBase):
        _CHANNEL_PITCH_MM = channel_pitch_mm
        _DEFAULT_CHANNELS = default_channels
        _MAX_CHANNELS = max_channels
        _ACTION_PREFIX = action_prefix

    def _make_wrapper(impl_name: str) -> Any:
        """Create a wrapper method that captures the correct class variables."""
        impl_method = getattr(ChannelCommandsMixin, impl_name)

        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            original_action_prefix = self._ACTION_PREFIX
            original_channel_pitch_mm = self._CHANNEL_PITCH_MM
            original_default_channels = self._DEFAULT_CHANNELS
            original_max_channels = self._MAX_CHANNELS
            try:
                self._ACTION_PREFIX = action_prefix
                self._CHANNEL_PITCH_MM = channel_pitch_mm
                self._DEFAULT_CHANNELS = default_channels
                self._MAX_CHANNELS = max_channels
                return impl_method(self, *args, **kwargs)
            finally:
                self._ACTION_PREFIX = original_action_prefix
                self._CHANNEL_PITCH_MM = original_channel_pitch_mm
                self._DEFAULT_CHANNELS = original_default_channels
                self._MAX_CHANNELS = original_max_channels

        return wrapper

    for method_name, impl_name in [
        ("tip_pickup", "_tip_pickup_impl"),
        ("tip_eject", "_tip_eject_impl"),
        ("aspirate", "_aspirate_impl"),
        ("dispense", "_dispense_impl"),
        ("detect_liquid_level", "_detect_liquid_level_impl"),
        ("tip_check", "_tip_check_impl"),
        ("dispense_on_the_fly", "_dispense_on_the_fly_impl"),
        ("move_axis", "_move_axis_impl"),
        ("get_status", "_get_status_impl"),
    ]:
        public_name = f"{method_name}{method_suffix}"
        wrapper = _make_wrapper(impl_name)
        setattr(ChannelCommandsMixin, public_name, wrapper)

    ChannelCommandsMixin.__name__ = name
    return ChannelCommandsMixin


ChannelCommandsMixin = _create_channel_commands_mixin(
    "ChannelCommandsMixin",
    channel_pitch_mm=CHANNEL_PITCH_MM_1ML,
    default_channels=[1, 2, 3, 4, 5, 6, 7, 8],
    max_channels=MAX_CHANNELS,
    action_prefix="channels.1mL",
    method_suffix="",
)

Channels5mLCommandsMixin = _create_channel_commands_mixin(
    "Channels5mLCommandsMixin",
    channel_pitch_mm=CHANNEL_PITCH_MM_5ML,
    default_channels=[1, 2, 3, 4, 5, 6, 7, 8],
    max_channels=MAX_CHANNELS,
    action_prefix="channels.5mL",
    method_suffix="_5ml",
)
