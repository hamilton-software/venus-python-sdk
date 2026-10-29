"""Backwards-compatible alias for HHS device command group."""

from hamilton_venus.devices.heater_shaker_commands import HeaterShakerDeviceCommands as HeaterShakerCommandsMixin

__all__ = ["HeaterShakerCommandsMixin"]
