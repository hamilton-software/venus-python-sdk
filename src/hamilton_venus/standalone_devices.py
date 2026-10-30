"""Registry of pure-Python, no-VENUS device clients (HHC, ODTC, Inheco TEC, Tilt Module).

These devices don't need a `StarClient`/`VantageClient` -- each has its own
standalone client (:class:`~hamilton_venus.HeaterCoolerClient`,
:class:`~hamilton_venus.ODTCClient`) that can be used entirely on its own. This
module is the single place such a device gets registered; anything that needs
to route a command to the right object by name reads
:data:`STANDALONE_DEVICES` instead of hard-coding per-device knowledge.

Adding a third pure-Python device later means appending one
:class:`StandaloneDeviceSpec` here -- no other file needs to change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hamilton_venus.devices.heater_cooler_commands import HeaterCoolerClient
from hamilton_venus.devices.inheco_tec_commands import InhecoTECClient
from hamilton_venus.devices.media_fill_commands import MediaFillClient
from hamilton_venus.devices.odtc_commands import ODTCClient
from hamilton_venus.devices.tilt_module_commands import TiltModuleClient
from hamilton_venus.heater_cooler import heater_cooler_available
from hamilton_venus.inheco_tec import inheco_tec_available
from hamilton_venus.media_fill import media_fill_available
from hamilton_venus.odtc import odtc_available
from hamilton_venus.tilt_module import tilt_module_available


@dataclass(frozen=True)
class StandaloneDeviceSpec:
    """One pure-Python device: its command-method-name prefix, its standalone
    client class, and how to tell whether the vendor driver is usable."""

    prefix: str
    client_cls: type
    available: Callable[[], bool]


STANDALONE_DEVICES: list[StandaloneDeviceSpec] = [
    StandaloneDeviceSpec("hhc_", HeaterCoolerClient, heater_cooler_available),
    StandaloneDeviceSpec("odtc_", ODTCClient, odtc_available),
    StandaloneDeviceSpec("inheco_tec_", InhecoTECClient, inheco_tec_available),
    # "tilt_module_" moves the tilt hardware; StarClient/VantageClient's tilt_labware only
    # changes the deck layout, and does not start with this prefix.
    StandaloneDeviceSpec("tilt_module_", TiltModuleClient, tilt_module_available),
    StandaloneDeviceSpec("media_fill_", MediaFillClient, media_fill_available),
]


def find_standalone_device(method_name: str) -> StandaloneDeviceSpec | None:
    """The :class:`StandaloneDeviceSpec` whose prefix *method_name* starts
    with, or ``None`` if it isn't a standalone-device command."""
    for spec in STANDALONE_DEVICES:
        if method_name.startswith(spec.prefix):
            return spec
    return None


__all__ = ["STANDALONE_DEVICES", "StandaloneDeviceSpec", "find_standalone_device"]
