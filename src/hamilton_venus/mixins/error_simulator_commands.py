"""Simulated-firmware-error injection for the synchronous instrument clients.

Wraps :class:`hamilton_venus.error_simulator.ErrorSimulator`. Works for both
``StarClient`` and ``VantageClient`` -- the simulator config path and simulation
state are resolved from the Vector WebAPI; the instrument (which knowledge-base
tables and firmware commands apply) comes from the client's own type, since a
Vantage behind the STAR translator registers with platform ``ML_STAR``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
    from hamilton_venus.error_simulator import ErrorSimulator, Module
    from hamilton_venus.models.enums import InstrumentType


class ErrorSimulatorCommandsMixin:
    """Inject / clear simulated firmware errors (VENUS simulation mode only).

    Requires the custom ``ErrorSimulator`` knowledge base shipped with the SDK
    (``hamilton_venus.error_simulator``). Only meaningful while the session is
    simulating -- the simulated firmware ignores the simulator config on a live
    instrument, so these methods raise ``SimulationModeRequired`` otherwise.
    """

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        _instrument_type: InstrumentType

    _error_simulator: ErrorSimulator | None = None

    # -- public API -------------------------------------------------------------

    def simulate_error(
        self,
        module: Module | str,
        step: StrEnum | str,
        error: StrEnum | str,
        *,
        channels: list[int] | None = None,
    ) -> None:
        """Make the next *step* on *module* return *error*.

        Any previously injected simulated error is cleared first -- only one is
        ever active at a time (VENUS's firmware simulator misbehaves with
        several registered at once), so call this immediately before the step it
        targets.

        *step* / *error* accept a generated typed constant
        (``hamilton_venus.error_simulator`` ``*Step`` / ``*Error`` enums --
        exact match) or a plain string (fuzzy keyword match, as the HSL library
        does). For channel modules (1mL / 5mL / X1 / MagPip) *error* applies to
        every channel; pass ``channels=[...]`` for a subset, or the
        ``"1.<desc>;2.<desc>"`` micro-syntax in *error* for a per-channel error.
        """
        self._get_error_simulator().set_error(module, step, error, channels=channels)

    def simulate_error_by_code(
        self, firmware_command: str, error_code: str, error_recovery: str = ""
    ) -> None:
        """Write *error_code* as the raw simulated reply for *firmware_command*
        with no keyword matching. Clears any previously injected error first, as
        :meth:`simulate_error` does."""
        self._get_error_simulator().set_error_by_code(firmware_command, error_code, error_recovery)

    def clear_simulated_errors(self) -> None:
        """Reset every firmware command to its "no error" reply."""
        self._get_error_simulator().reset()

    def list_simulatable_modules(self) -> list[str]:
        """Module names valid for :meth:`simulate_error` on this instrument."""
        return self._get_error_simulator().available_modules()

    def list_simulatable_errors(self, module: Module | str) -> list[str]:
        """Error descriptions known for *module* on this instrument."""
        return self._get_error_simulator().available_errors(module)

    def list_simulatable_steps(self, module: Module | str) -> list[str]:
        """Firmware-step descriptions known for *module* on this instrument."""
        return self._get_error_simulator().available_steps(module)

    # -- internals ------------------------------------------------------------

    def _get_error_simulator(self) -> ErrorSimulator:
        if self._error_simulator is None:
            self._error_simulator = self._build_error_simulator()
        return self._error_simulator

    def _build_error_simulator(self) -> ErrorSimulator:
        from hamilton_venus.error_simulator import ErrorSimulator
        from hamilton_venus.error_simulator.run_control import resolve_live
        from hamilton_venus.models.enums import InstrumentType

        # The client's own type, not VENUS's platform name: a Vantage behind the
        # STAR translator reports platform ML_STAR (see run_control.resolve).
        instrument = {InstrumentType.STAR: "STAR", InstrumentType.Vantage: "VANTAGE"}.get(self._instrument_type)
        run_info = resolve_live(self._connected_instrument.venus, self._run, instrument=instrument)
        return ErrorSimulator(run_info)
