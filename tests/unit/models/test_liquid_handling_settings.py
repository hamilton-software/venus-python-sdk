"""Unit tests for liquid-handling settings models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hamilton_venus.models import AspirateSettings, DispenseSettings, MPH96AspirateSettings, MPH96DispenseSettings
from hamilton_venus.models.enums import AspirateMode, CapacitiveLLD, DispenseMode, PressureLLD


class TestAspirateSettings:
    def test_defaults_match_current_command_defaults(self):
        settings = AspirateSettings()

        assert settings.aspirate_mode == AspirateMode.NORMAL
        assert settings.capacitive_lld == CapacitiveLLD.OFF
        assert settings.pressure_lld == PressureLLD.OFF
        assert settings.liquid_following is False
        assert settings.tip_tracking_factor == 1.0
        assert settings.submerge_depth == 2.0
        assert settings.fixed_height == 5.0
        assert settings.max_lld_difference == 3.0
        assert settings.mix_cycles == 0
        assert settings.mix_position == 0.0
        assert settings.mix_volume == 0.0
        assert settings.air_transport_retract_dist == 5.0
        assert settings.touch_off == 0
        assert settings.touch_off_height == 1.0

    def test_supports_list_values(self):
        settings = AspirateSettings(
            aspirate_mode=[AspirateMode.NORMAL, AspirateMode.CONSECUTIVE],
            capacitive_lld=[CapacitiveLLD.OFF, CapacitiveLLD.MID],
            pressure_lld=[PressureLLD.OFF, PressureLLD.HIGH],
            liquid_following=[False, True],
            submerge_depth=[2.0, 3.0],
            fixed_height=[1.0, 2.0],
            max_lld_difference=[0.0, 1.0],
            mix_cycles=[0, 2],
            mix_position=[0.0, 1.0],
            mix_volume=[0.0, 10.0],
            air_transport_retract_dist=[5.0, 7.5],
            touch_off=[0, 1],
            touch_off_height=[0.0, 0.5],
        )

        assert settings.aspirate_mode == [AspirateMode.NORMAL, AspirateMode.CONSECUTIVE]
        assert settings.mix_cycles == [0, 2]
        assert settings.touch_off == [0, 1]
        assert settings.fixed_height == [1.0, 2.0]

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            AspirateSettings(unknown_field=True)

    def test_tip_tracking_factor_is_scalar_only(self):
        assert AspirateSettings(tip_tracking_factor=0.5).tip_tracking_factor == 0.5
        with pytest.raises(ValidationError):
            AspirateSettings(tip_tracking_factor=[0.5, 2.0])


class TestDispenseSettings:
    def test_defaults_match_current_command_defaults(self):
        settings = DispenseSettings()

        assert settings.dispense_mode == DispenseMode.FROM_LIQUID_CLASS
        assert settings.capacitive_lld == CapacitiveLLD.OFF
        assert settings.liquid_following is False
        assert settings.tip_tracking_factor == 1.0
        assert settings.submerge_depth == 2.0
        assert settings.fixed_height == 5.0
        assert settings.mix_cycles == 0
        assert settings.mix_position == 0.0
        assert settings.mix_volume == 0.0
        assert settings.air_transport_retract_dist == 5.0
        assert settings.touch_off == 0
        assert settings.touch_off_height == 1.0
        assert settings.use_side_touch is False

    def test_supports_list_values(self):
        settings = DispenseSettings(
            dispense_mode=[DispenseMode.SURFACE_PART_VOLUME, DispenseMode.JET_EMPTY_TIP],
            capacitive_lld=[CapacitiveLLD.OFF, CapacitiveLLD.MID],
            liquid_following=[True, False],
            submerge_depth=[2.0, 3.0],
            fixed_height=[5.0, 2.0],
            mix_cycles=[0, 2],
            mix_position=[0.0, 1.0],
            mix_volume=[0.0, 10.0],
            air_transport_retract_dist=[5.0, 7.5],
            touch_off=[0, 1],
            touch_off_height=[0.0, 0.5],
        )

        assert settings.dispense_mode == [DispenseMode.SURFACE_PART_VOLUME, DispenseMode.JET_EMPTY_TIP]
        assert settings.mix_cycles == [0, 2]
        assert settings.fixed_height == [5.0, 2.0]
        assert settings.touch_off == [0, 1]

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            DispenseSettings(unknown_field=True)


class TestMPH96AspirateSettings:
    def test_defaults(self):
        settings = MPH96AspirateSettings()

        assert settings.aspirate_mode == AspirateMode.NORMAL
        assert settings.capacitive_lld == CapacitiveLLD.OFF
        assert settings.liquid_following is False
        assert settings.tip_tracking_factor == 1.0
        assert settings.submerge_depth == 2.0
        assert settings.fixed_height == 5.0
        assert settings.mix_cycles == 0
        assert settings.mix_position == 0.0
        assert settings.mix_volume == 0.0
        assert settings.air_transport_retract_dist == 5.0

    def test_custom_values(self):
        settings = MPH96AspirateSettings(
            aspirate_mode=AspirateMode.CONSECUTIVE,
            capacitive_lld=CapacitiveLLD.MID,
            liquid_following=True,
            submerge_depth=1.5,
            fixed_height=3.0,
            mix_cycles=2,
            mix_position=0.5,
            mix_volume=30.0,
            air_transport_retract_dist=10.0,
        )

        assert settings.aspirate_mode == AspirateMode.CONSECUTIVE
        assert settings.liquid_following is True
        assert settings.mix_cycles == 2

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            MPH96AspirateSettings(unknown_field=True)


class TestMPH96DispenseSettings:
    def test_defaults(self):
        settings = MPH96DispenseSettings()

        assert settings.dispense_mode == DispenseMode.FROM_LIQUID_CLASS
        assert settings.capacitive_lld == CapacitiveLLD.OFF
        assert settings.liquid_following is False
        assert settings.tip_tracking_factor == 1.0
        assert settings.submerge_depth == 2.0
        assert settings.fixed_height == 5.0
        assert settings.mix_cycles == 0
        assert settings.mix_position == 0.0
        assert settings.mix_volume == 0.0
        assert settings.air_transport_retract_dist == 5.0

    def test_custom_values(self):
        settings = MPH96DispenseSettings(
            dispense_mode=DispenseMode.JET_EMPTY_TIP,
            liquid_following=True,
            mix_cycles=3,
        )

        assert settings.dispense_mode == DispenseMode.JET_EMPTY_TIP
        assert settings.liquid_following is True
        assert settings.mix_cycles == 3

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            MPH96DispenseSettings(unknown_field=True)
