"""Stable, hand-written constants for :mod:`hamilton_venus.error_simulator`.

The firmware-step and error-description constants are *generated* (see
``_generated_steps`` / ``_generated_errors`` and
``hamilton_venus.tools.generate_error_simulator_data``); the module list is
small and stable, so it lives here.
"""

from __future__ import annotations

from enum import StrEnum


class Module(StrEnum):
    """A simulatable subsystem. The value is the knowledge-base table suffix
    (``<INSTR>-<value>``), matching ``MODULE.TABLE`` in the source database."""

    CHANNELS_1ML = "1mL"
    CHANNELS_5ML = "5mL"
    X1 = "X1"
    MPH96 = "MPH96"
    MPH384 = "MPH384"
    IPG_ISWAP = "IPG"
    AUTOLOAD_IDL = "IDL"
    MAGPIP = "MagPip"


#: Modules addressed per-channel (the ``x.y`` error micro-syntax / ``channels=``).
CHANNEL_MODULES = frozenset(
    {Module.CHANNELS_1ML, Module.CHANNELS_5ML, Module.X1, Module.MAGPIP}
)
