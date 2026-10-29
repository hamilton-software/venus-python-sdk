"""Backwards-compatible alias for the ODTC device command group."""

from hamilton_venus.devices.odtc_commands import ODTCDeviceCommands as ODTCCommandsMixin

__all__ = ["ODTCCommandsMixin"]
