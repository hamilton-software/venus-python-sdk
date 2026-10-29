"""Backwards-compatible alias for the HHC device command group."""

from hamilton_venus.devices.heater_cooler_commands import HeaterCoolerDeviceCommands as HeaterCoolerCommandsMixin

__all__ = ["HeaterCoolerCommandsMixin"]
