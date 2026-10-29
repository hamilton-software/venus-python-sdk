"""Reusable SDK settings models for liquid-handling commands."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from hamilton_venus.models.enums import (
    AspirateMode,
    CapacitiveLLD,
    DispenseMode,
    PressureLLD,
    TadmMode,
    TadmRecording,
)


class _LiquidHandlingSettingsModel(BaseModel):
    """Base model for reusable liquid-handling settings."""

    model_config = ConfigDict(extra="forbid")


class TadmSettings(_LiquidHandlingSettingsModel):
    """Reusable TADM (Total Aspiration and Dispense Monitoring) settings.

    Accepted by the MagPip channel commands
    (``aspirate_magpip`` / ``dispense_magpip`` / ``dispense_on_the_fly_magpip``).
    Serializes to a nested ``{"enabled": <int>, "recording": <int>}`` object on
    the wire. When omitted, VENUS applies its own defaults (``enabled=0``,
    ``recording=2``).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    enabled: TadmMode = TadmMode.OFF
    """``0`` = off, ``1`` = recording mode, ``2`` = monitoring mode."""
    recording: TadmRecording = TadmRecording.ALL_CURVES
    """``0`` = no curves recorded, ``1`` = error curves only, ``2`` = all curves."""


class AspirateSettings(_LiquidHandlingSettingsModel):
    """Reusable settings for `StarClient.aspirate()`.

    Every field except ``tip_tracking_factor`` supports either a scalar
    (applied uniformly to every channel) or a per-channel list.
    """

    aspirate_mode: AspirateMode | list[AspirateMode] = AspirateMode.NORMAL
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = CapacitiveLLD.OFF
    pressure_lld: PressureLLD | list[PressureLLD] = PressureLLD.OFF
    liquid_following: bool | list[bool] = False
    tip_tracking_factor: float = 1.0
    """Liquid-following movement factor. ``0.5`` tracks half the distance in
    the same time, ``2.0`` twice the distance; ``1.0`` (default) is normal
    tracking. VENUS accepts ``0.1``--``5.0``. Scalar only -- cannot be a
    per-channel list."""
    submerge_depth: float | list[float] = 2.0
    fixed_height: float | list[float] = 5.0
    max_lld_difference: float | list[float] = 3.0
    mix_cycles: int | list[int] = 0
    mix_position: float | list[float] = 0.0
    mix_volume: float | list[float] = 0.0
    air_transport_retract_dist: float | list[float] = 5.0
    touch_off: int | list[int] = 0
    touch_off_height: float | list[float] = 1.0


class DispenseSettings(_LiquidHandlingSettingsModel):
    """Reusable settings for `StarClient.dispense()`.

    Every field except ``use_side_touch`` and ``tip_tracking_factor``
    supports either a scalar (applied uniformly to every channel) or a
    per-channel list.
    """

    dispense_mode: DispenseMode | list[DispenseMode] = DispenseMode.FROM_LIQUID_CLASS
    capacitive_lld: CapacitiveLLD | list[CapacitiveLLD] = CapacitiveLLD.OFF
    liquid_following: bool | list[bool] = False
    tip_tracking_factor: float = 1.0
    """Liquid-following movement factor. ``0.5`` tracks half the distance in
    the same time, ``2.0`` twice the distance; ``1.0`` (default) is normal
    tracking. VENUS accepts ``0.1``--``5.0``. Scalar only -- cannot be a
    per-channel list."""
    submerge_depth: float | list[float] = 2.0
    fixed_height: float | list[float] = 5.0
    mix_cycles: int | list[int] = 0
    mix_position: float | list[float] = 0.0
    mix_volume: float | list[float] = 0.0
    air_transport_retract_dist: float | list[float] = 5.0
    touch_off: int | list[int] = 0
    touch_off_height: float | list[float] = 1.0
    use_side_touch: bool = False


class MPH96AspirateSettings(_LiquidHandlingSettingsModel):
    """Reusable settings for `StarClient.mph96_aspirate()`."""

    aspirate_mode: AspirateMode = AspirateMode.NORMAL
    capacitive_lld: CapacitiveLLD = CapacitiveLLD.OFF
    liquid_following: bool = False
    tip_tracking_factor: float = 1.0
    """Liquid-following movement factor. ``0.5`` tracks half the distance in
    the same time, ``2.0`` twice the distance; ``1.0`` (default) is normal
    tracking. VENUS accepts ``0.1``--``5.0``."""
    submerge_depth: float = 2.0
    fixed_height: float = 5.0
    mix_cycles: int = 0
    mix_position: float = 0.0
    mix_volume: float = 0.0
    air_transport_retract_dist: float = 5.0


class MPH96DispenseSettings(_LiquidHandlingSettingsModel):
    """Reusable settings for `StarClient.dispense_mph96()`."""

    dispense_mode: DispenseMode = DispenseMode.FROM_LIQUID_CLASS
    capacitive_lld: CapacitiveLLD = CapacitiveLLD.OFF
    liquid_following: bool = False
    tip_tracking_factor: float = 1.0
    """Liquid-following movement factor. ``0.5`` tracks half the distance in
    the same time, ``2.0`` twice the distance; ``1.0`` (default) is normal
    tracking. VENUS accepts ``0.1``--``5.0``."""
    submerge_depth: float = 2.0
    fixed_height: float = 5.0
    mix_cycles: int = 0
    mix_position: float = 0.0
    mix_volume: float = 0.0
    air_transport_retract_dist: float = 5.0
    use_side_touch: bool = False
    minimize_z_move: bool = False
