"""Backwards-compatible alias for the InhecoTEC device command group."""

from hamilton_venus.devices.inheco_tec_commands import InhecoTECDeviceCommands as InhecoTECCommandsMixin

__all__ = ["InhecoTECCommandsMixin"]
