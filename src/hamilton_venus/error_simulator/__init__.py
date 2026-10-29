"""Python port of the custom ``ErrorSimulator`` VENUS HSL library.

Inject simulated firmware errors into STAR / VANTAGE Run Control (in simulation
mode) so error-recovery paths can be exercised without hardware. Normally used
through ``StarClient`` / ``VantageClient``'s ``simulate_error`` /
``simulate_error_by_code`` / ``clear_simulated_errors`` methods; the
:class:`ErrorSimulator` class and constants are exported here for direct use.
"""

from __future__ import annotations

from hamilton_venus.error_simulator.constants import CHANNEL_MODULES, Module
from hamilton_venus.error_simulator.exceptions import (
    AmbiguousMatchError,
    ConfigWriteError,
    ErrorSimulatorError,
    InstrumentNotResolved,
    NoMatchError,
    SimulationModeRequired,
)
from hamilton_venus.error_simulator.run_control import RunControlInfo, resolve, resolve_live
from hamilton_venus.error_simulator.simulator import ErrorSimulator

__all__ = [
    "CHANNEL_MODULES",
    "AmbiguousMatchError",
    "ConfigWriteError",
    "ErrorSimulator",
    "ErrorSimulatorError",
    "InstrumentNotResolved",
    "Module",
    "NoMatchError",
    "RunControlInfo",
    "SimulationModeRequired",
    "resolve",
    "resolve_live",
]
