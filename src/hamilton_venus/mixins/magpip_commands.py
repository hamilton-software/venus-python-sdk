"""MagPip channel command methods for VantageClient.

The Vantage MagPip channels are the 1 mL pipetting channels driven in
magnetic-bead (``Mag*``) firmware mode. Command coverage mirrors
:class:`~hamilton_venus.mixins.channel_commands.ChannelCommandsMixin` (all nine
``channels.MagPip.*`` actions -- there are no MagPip transport commands), with
three differences on the wire:

* ``aspirate`` / ``dispense`` / ``dispenseOnTheFly`` accept an optional nested
  ``TADM`` object (:class:`~hamilton_venus.models.TadmSettings`).
* ``dispenseOnTheFly`` additionally accepts the ``ADC`` flag.
* The MagPip channels do not use ``tipTrackingFactor``; it is dropped from the
  wire payload even when a passed ``AspirateSettings`` / ``DispenseSettings``
  carries one.

Methods are suffixed ``_magpip`` (mirroring the ``_5ml`` convention) so they can
live on ``VantageClient`` alongside the 1 mL and 5 mL command sets.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML, MAX_CHANNELS
from hamilton_venus.mixins.channel_commands import _ChannelCommandsBase
from hamilton_venus.models import (
    AspirateSettings,
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelGetStatusResponse,
    ChannelMoveAxisParameters,
    ChannelMoveAxisResponse,
    ChannelTipCheckResponse,
    CommandResponse,
    DispenseSettings,
    MagPipAspirateParameters,
    MagPipDispenseOnTheFlyParameters,
    MagPipDispenseParameters,
    PositionInput,
    TadmSettings,
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
    from hamilton_venus.models.position import LabwareLayoutSpec

_MAGPIP_ACTION_PREFIX = "channels.MagPip"
_MAGPIP_DEFAULT_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
_MAGPIP_MAX_CHANNELS = MAX_CHANNELS


class ChannelsMagPipCommandsMixin(_ChannelCommandsBase):
    """MagPip (magnetic-bead) 1 mL channel commands for :class:`VantageClient`."""

    _CHANNEL_PITCH_MM = CHANNEL_PITCH_MM_1ML
    _DEFAULT_CHANNELS = _MAGPIP_DEFAULT_CHANNELS
    _MAX_CHANNELS = _MAGPIP_MAX_CHANNELS
    _ACTION_PREFIX = _MAGPIP_ACTION_PREFIX

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def get_labware_spec(self, labware_id: str) -> LabwareLayoutSpec: ...

    @contextmanager
    def _magpip_scope(self) -> Any:
        """Pin the channel-geometry class vars to MagPip values for the duration
        of a shared ``_ChannelCommandsBase`` impl call.

        ``VantageClient`` also mixes in the 1 mL command set, whose class vars
        appear earlier in the MRO, so ``self._ACTION_PREFIX`` would otherwise
        resolve to ``channels.1mL``. This mirrors the save/restore wrapper the
        1 mL/5 mL factory uses.
        """
        saved = (
            self._ACTION_PREFIX,
            self._CHANNEL_PITCH_MM,
            self._DEFAULT_CHANNELS,
            self._MAX_CHANNELS,
        )
        self._ACTION_PREFIX = _MAGPIP_ACTION_PREFIX
        self._CHANNEL_PITCH_MM = CHANNEL_PITCH_MM_1ML
        self._DEFAULT_CHANNELS = _MAGPIP_DEFAULT_CHANNELS
        self._MAX_CHANNELS = _MAGPIP_MAX_CHANNELS
        try:
            yield
        finally:
            (
                self._ACTION_PREFIX,
                self._CHANNEL_PITCH_MM,
                self._DEFAULT_CHANNELS,
                self._MAX_CHANNELS,
            ) = saved

    # ---- commands identical to the 1 mL variants (delegated) ----------------

    def tip_pickup_magpip(
        self,
        channels: list[int] | None = None,
        positions: PositionInput | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        tip_pool: str | None = None,
        optimized_pickup: bool = True,
    ) -> CommandResponse:
        """Pick up tips on the MagPip channels. See
        :meth:`ChannelCommandsMixin.tip_pickup
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.tip_pickup>`."""
        with self._magpip_scope():
            return self._tip_pickup_impl(
                channels=channels,
                positions=positions,
                well_order=well_order,
                tip_pool=tip_pool,
                optimized_pickup=optimized_pickup,
            )

    def tip_eject_magpip(
        self,
        channels: list[int] | None = None,
        eject_mode: EjectMode = EjectMode.WASTE,
        positions: PositionInput | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        tip_pool: str | None = None,
    ) -> CommandResponse:
        """Eject tips from the MagPip channels. See
        :meth:`ChannelCommandsMixin.tip_eject
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.tip_eject>`."""
        with self._magpip_scope():
            return self._tip_eject_impl(
                channels=channels,
                eject_mode=eject_mode,
                positions=positions,
                well_order=well_order,
                tip_pool=tip_pool,
            )

    def detect_liquid_level_magpip(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        capacitive_lld: CapacitiveLLD = CapacitiveLLD.MAX,
        pressure_lld: PressureLLD = PressureLLD.OFF,
        well_order: WellOrder = WellOrder.COL_ASC,
    ) -> CommandResponse:
        """Detect liquid level with the MagPip channels. See
        :meth:`ChannelCommandsMixin.detect_liquid_level
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.detect_liquid_level>`."""
        with self._magpip_scope():
            return self._detect_liquid_level_impl(
                positions,
                channels=channels,
                capacitive_lld=capacitive_lld,
                pressure_lld=pressure_lld,
                well_order=well_order,
            )

    def tip_check_magpip(self) -> ChannelTipCheckResponse:
        """Return current tip status for active MagPip channels."""
        with self._magpip_scope():
            return self._tip_check_impl()

    # ---- commands with MagPip-only wire params -----------------------------

    def aspirate_magpip(
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
        tadm: TadmSettings | None = None,
    ) -> ChannelAspirationResponse:
        """Aspirate liquid with the MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.aspirate
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.aspirate>`
        with one extra parameter:

        Args:
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`
                controlling Total Aspiration and Dispense Monitoring. ``None``
                (default) omits the ``TADM`` object, so VENUS applies its own
                defaults (``enabled=0``, ``recording=2``).

        ``settings.tip_tracking_factor`` is ignored -- the MagPip channels do
        not support it.
        """
        if channels is None:
            channels = _MAGPIP_DEFAULT_CHANNELS
        with self._magpip_scope():
            self._validate_channel_count(channels)
        resolved_settings = settings or AspirateSettings()
        channel_count = len(channels)
        parameters = MagPipAspirateParameters(
            channels=channels,
            positions=normalize_positions(
                positions,
                well_order=well_order,
                channel_count=channel_count,
                get_spec=self.get_labware_spec,
                channel_pitch_mm=CHANNEL_PITCH_MM_1ML,
            ),
            volumes=self._validate_per_channel(volumes, channel_count, "volumes"),
            liquid_class=self._validate_per_channel(liquid_class, channel_count, "liquid_class"),
            aspirate_mode=self._validate_per_channel(resolved_settings.aspirate_mode, channel_count, "aspirate_mode"),
            capacitive_lld=self._validate_per_channel(
                resolved_settings.capacitive_lld, channel_count, "capacitive_lld"
            ),
            pressure_lld=self._validate_per_channel(resolved_settings.pressure_lld, channel_count, "pressure_lld"),
            liquid_following=self._validate_per_channel(
                resolved_settings.liquid_following, channel_count, "liquid_following"
            ),
            submerge_depth=self._validate_per_channel(
                resolved_settings.submerge_depth, channel_count, "submerge_depth"
            ),
            fixed_height=self._validate_per_channel(resolved_settings.fixed_height, channel_count, "fixed_height"),
            max_lld_difference=self._validate_per_channel(
                resolved_settings.max_lld_difference, channel_count, "max_lld_difference"
            ),
            mix_cycles=self._validate_per_channel(resolved_settings.mix_cycles, channel_count, "mix_cycles"),
            mix_position=self._validate_per_channel(resolved_settings.mix_position, channel_count, "mix_position"),
            mix_volume=self._validate_per_channel(resolved_settings.mix_volume, channel_count, "mix_volume"),
            air_transport_retract_dist=self._validate_per_channel(
                resolved_settings.air_transport_retract_dist, channel_count, "air_transport_retract_dist"
            ),
            touch_off=self._validate_per_channel(resolved_settings.touch_off, channel_count, "touch_off"),
            touch_off_height=self._validate_per_channel(
                resolved_settings.touch_off_height, channel_count, "touch_off_height"
            ),
            mad_enabled=mad_enabled,
            mad_threshold=mad_threshold,
            adc=adc,
            tadm=tadm,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="channels.MagPip.aspirate",
                parameters=self._slot_align(parameters.model_dump(by_alias=True, exclude_none=True), channels),
            )
        )
        return ChannelAspirationResponse.model_validate(response.model_dump())

    def dispense_magpip(
        self,
        positions: PositionInput,
        *,
        channels: list[int] | None = None,
        volumes: float | list[float],
        settings: DispenseSettings | None = None,
        well_order: WellOrder = WellOrder.COL_ASC,
        adc: bool | None = None,
        tadm: TadmSettings | None = None,
    ) -> ChannelDispenseResponse:
        """Dispense liquid with the MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.dispense
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.dispense>`
        with one extra parameter:

        Args:
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`
                controlling Total Aspiration and Dispense Monitoring. ``None``
                (default) omits the ``TADM`` object, so VENUS applies its own
                defaults (``enabled=0``, ``recording=2``).

        ``settings.tip_tracking_factor`` is ignored -- the MagPip channels do
        not support it.
        """
        if channels is None:
            channels = _MAGPIP_DEFAULT_CHANNELS
        with self._magpip_scope():
            self._validate_channel_count(channels)
        resolved_settings = settings or DispenseSettings()
        channel_count = len(channels)
        parameters = MagPipDispenseParameters(
            channels=channels,
            positions=normalize_positions(
                positions,
                well_order=well_order,
                channel_count=channel_count,
                get_spec=self.get_labware_spec,
                channel_pitch_mm=CHANNEL_PITCH_MM_1ML,
            ),
            volumes=self._validate_per_channel(volumes, channel_count, "volumes"),
            dispense_mode=self._validate_per_channel(resolved_settings.dispense_mode, channel_count, "dispense_mode"),
            capacitive_lld=self._validate_per_channel(
                resolved_settings.capacitive_lld, channel_count, "capacitive_lld"
            ),
            liquid_following=self._validate_per_channel(
                resolved_settings.liquid_following, channel_count, "liquid_following"
            ),
            submerge_depth=self._validate_per_channel(
                resolved_settings.submerge_depth, channel_count, "submerge_depth"
            ),
            fixed_height=self._validate_per_channel(resolved_settings.fixed_height, channel_count, "fixed_height"),
            mix_cycles=self._validate_per_channel(resolved_settings.mix_cycles, channel_count, "mix_cycles"),
            mix_position=self._validate_per_channel(resolved_settings.mix_position, channel_count, "mix_position"),
            mix_volume=self._validate_per_channel(resolved_settings.mix_volume, channel_count, "mix_volume"),
            air_transport_retract_dist=self._validate_per_channel(
                resolved_settings.air_transport_retract_dist, channel_count, "air_transport_retract_dist"
            ),
            touch_off=self._validate_per_channel(resolved_settings.touch_off, channel_count, "touch_off"),
            touch_off_height=self._validate_per_channel(
                resolved_settings.touch_off_height, channel_count, "touch_off_height"
            ),
            use_side_touch=resolved_settings.use_side_touch,
            adc=adc,
            tadm=tadm,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="channels.MagPip.dispense",
                parameters=self._slot_align(parameters.model_dump(by_alias=True, exclude_none=True), channels),
            )
        )
        return ChannelDispenseResponse.model_validate(response.model_dump())

    def dispense_on_the_fly_magpip(
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
        *,
        adc: bool | None = None,
        tadm: TadmSettings | None = None,
    ) -> CommandResponse:
        """Dispense across wells while translating in X on a single pass, MagPip channels.

        Mirrors :meth:`ChannelCommandsMixin.dispense_on_the_fly
        <hamilton_venus.mixins.channel_commands.ChannelCommandsMixin.dispense_on_the_fly>`
        with two extra parameters:

        Args:
            adc: Enable Aspiration/Dispense Control (TADM-based). ``None``
                (default) omits the field, so VENUS applies its own default
                (disabled).
            tadm: Optional :class:`~hamilton_venus.models.TadmSettings`. ``None``
                (default) omits the ``TADM`` object.
        """
        parameters = MagPipDispenseOnTheFlyParameters(
            channels=channels,
            labware_name=labware_name,
            volumes=volumes,
            labware_surface_distance=labware_surface_distance,
            start_x_offset=start_x_offset,
            x_speed=x_speed,
            x_acceleration_distance=x_acceleration_distance,
            dispense_direction=dispense_direction,
            excluded_positions=excluded_positions or [],
            adc=adc,
            tadm=tadm,
        )
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="channels.MagPip.dispenseOnTheFly",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )

    # ---- axis / status --------------------------------------------------------

    def move_axis_magpip(
        self,
        channels: list[int] | int,
        *,
        x: float | None = None,
        y: float | list[float] | None = None,
        z: float | list[float] | None = None,
        safety_bypass_token: str | None = None,
    ) -> ChannelMoveAxisResponse:
        """Move MagPip channels directly to absolute X/Y/Z coordinates. See
        :meth:`ChannelCommandsMixin.move_axis
        <hamilton_venus.mixins.channel_commands._ChannelCommandsBase.move_axis>`."""
        channel_list = [channels] if isinstance(channels, int) else list(channels)
        self._validate_per_channel(y, len(channel_list), "y")
        self._validate_per_channel(z, len(channel_list), "z")
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
                action_name="channels.MagPip.moveAxis",
                parameters=self._slot_align(
                    parameters.model_dump(by_alias=True, exclude_none=True),
                    channel_list,
                    keys=("y", "z"),
                ),
            )
        )
        return ChannelMoveAxisResponse.model_validate(response.model_dump(by_alias=True))

    def get_status_magpip(self) -> ChannelGetStatusResponse:
        """Return the current X/Y/Z position and tip-loaded status for every MagPip channel."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="channels.MagPip.getStatus",
            )
        )
        return ChannelGetStatusResponse.model_validate(response.model_dump(by_alias=True))

    def move_axis_relative_magpip(
        self,
        channels: list[int] | int,
        *,
        x: float | None = None,
        y: float | list[float] | None = None,
        z: float | list[float] | None = None,
        safety_bypass_token: str | None = None,
    ) -> ChannelMoveAxisResponse:
        """Move MagPip channels by a relative X/Y/Z offset.

        Like :meth:`move_axis_relative
        <hamilton_venus.mixins.channel_commands._ChannelCommandsBase.move_axis_relative>`
        but for the MagPip channels: reads each channel's current position via
        :meth:`get_status_magpip`, adds the requested offset, and issues an
        absolute :meth:`move_axis_magpip`.
        """
        channel_list = [channels] if isinstance(channels, int) else list(channels)
        channel_count = len(channel_list)
        current = self.get_status_magpip()
        positions_by_channel = {status.channel: status for status in current.return_parameters.channel_status}

        missing = [ch for ch in channel_list if ch not in positions_by_channel]
        if missing:
            raise ValueError(
                f"move_axis_relative_magpip: channel(s) {missing} not present in get_status_magpip() response "
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

        return self.move_axis_magpip(
            channel_list,
            x=new_x,
            y=new_y,
            z=new_z,
            safety_bypass_token=safety_bypass_token,
        )


__all__ = ["ChannelsMagPipCommandsMixin"]
