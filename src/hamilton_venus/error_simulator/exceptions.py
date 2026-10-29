"""Exceptions raised by :mod:`hamilton_venus.error_simulator`."""

from __future__ import annotations


class ErrorSimulatorError(Exception):
    """Base class for all error-simulator failures."""


class SimulationModeRequired(ErrorSimulatorError):
    """Raised when error injection is attempted while VENUS is not simulating.

    The simulated firmware only consults ``<instrument>_Simulator.cfg`` in
    simulation mode, so injecting an error on a live instrument would silently do
    nothing.
    """


class InstrumentNotResolved(ErrorSimulatorError):
    """Raised when the registered instrument / config path could not be resolved
    from the Vector API (unknown ``defaultName``, unreachable WebAPI, ...)."""


class NoMatchError(ErrorSimulatorError):
    """Raised when a plain-language description matches no row in the knowledge
    base. ``candidates`` lists the closest valid descriptions, when known."""

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message)
        self.candidates: list[str] = candidates or []


class AmbiguousMatchError(ErrorSimulatorError):
    """Raised when a description matches more than one row and the keyword
    cascade could not narrow it to one. ``candidates`` lists the matches."""

    def __init__(self, message: str, candidates: list[str]) -> None:
        super().__init__(message)
        self.candidates: list[str] = candidates


class ConfigWriteError(ErrorSimulatorError):
    """Raised when the ``HxCfgFile`` COM object could not be created or the
    simulator config file could not be loaded/stored."""
