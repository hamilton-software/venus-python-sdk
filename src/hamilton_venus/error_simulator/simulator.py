"""``ErrorSimulator`` -- the Pythonic facade over the ported ``ErrorSimulator``
HSL library.

Reproduces ``InitializeLibrary`` / ``SetError`` / ``SetErrorByCode`` /
``ResetConfigFile``: given a plain-language (or typed-constant) module / step /
error, resolve the firmware command + simulated reply string exactly as the HSL
did and write them into ``<instrument>_Simulator.cfg`` so Run Control's simulated
firmware returns that error on the next matching command.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from hamilton_venus.error_simulator.config_writer import SimulatorConfig
from hamilton_venus.error_simulator.constants import CHANNEL_MODULES, Module
from hamilton_venus.error_simulator.exceptions import ErrorSimulatorError, SimulationModeRequired
from hamilton_venus.error_simulator.knowledge_base import KnowledgeBase
from hamilton_venus.error_simulator.matching import match_error, match_firmware
from hamilton_venus.error_simulator.reply_builder import (
    build_channel_reply,
    build_single_reply,
    no_error_reply,
)

if TYPE_CHECKING:
    from hamilton_venus.error_simulator.run_control import RunControlInfo

_CHANNEL_ITEM = re.compile(r"^\s*(\d+)\s*\.\s*(.+)$", re.DOTALL)

#: Channels assumed for a per-channel module when the caller passes neither
#: ``channels=`` nor the ``"1.<desc>;2.<desc>"`` micro-syntax. Eight is the
#: standard 1mL/5mL head count on STAR and Vantage, and matches the demo app's
#: own default for every other channels= parameter (``_all_channels_default``).
_DEFAULT_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]


class ErrorSimulator:
    """Injects simulated firmware errors for one running VENUS instance.

    Construct via :meth:`from_client` (or pass a resolved
    :class:`~hamilton_venus.error_simulator.run_control.RunControlInfo`). Callers
    normally reach this through ``StarClient`` / ``VantageClient``'s
    ``simulate_error`` etc.

    Only one simulated error is ever active at a time: :meth:`set_error` and
    :meth:`set_error_by_code` each clear every previously injected error before
    writing the new one. VENUS's own firmware simulator misbehaves when more
    than one error is registered in ``<instrument>_Simulator.cfg`` at once, so
    stacking them is not supported -- register each error immediately before the
    command it targets.
    """

    def __init__(
        self,
        run_info: RunControlInfo,
        *,
        knowledge_base: KnowledgeBase | None = None,
        config: SimulatorConfig | None = None,
    ) -> None:
        self.run_info = run_info
        self.kb = knowledge_base or KnowledgeBase.load()
        self.config = config or SimulatorConfig(run_info.config_path)
        self._active_firmware_commands: set[str] = set()

    # -- public API -------------------------------------------------------------

    def set_error(
        self,
        module: Module | str,
        step: StrEnum | str,
        error: StrEnum | str,
        *,
        channels: list[int] | None = None,
    ) -> None:
        """Make the next *step* on *module* fail with *error*.

        Any previously injected error is cleared first, so exactly one simulated
        error is active afterwards (see the class docstring).

        *step* / *error* may be a generated typed constant (exact match) or a
        plain string (fuzzy keyword match, as the HSL does). For channel modules
        (1mL / 5mL / X1 / MagPip), *error* applies to every channel in
        *channels*; omit *channels* to apply it to all channels
        (:data:`_DEFAULT_CHANNELS`), pass ``channels=[...]`` for a subset, or use
        the ``"1.<desc>;2.<desc>"`` micro-syntax in *error* for a different error
        per channel.
        """
        self._require_simulation()
        instrument = self.run_info.instrument
        module_info = self.kb.resolve_module(str(module))
        prefix = module_info.command_prefix(instrument)

        fw_rows = self.kb.firmware_rows(instrument, module_info)
        if not fw_rows:
            raise ErrorSimulatorError(
                f"no firmware steps known for {instrument} {module_info.table}"
            )
        fw_command = match_firmware(str(step), fw_rows, exact=_is_exact(step))
        error_rows = self.kb.error_rows(instrument, module_info)

        is_channel_module = Module(module_info.table) in CHANNEL_MODULES
        # A per-channel module with no explicit channels and no per-channel
        # micro-syntax: apply the one error to all channels rather than failing.
        # `not channels` covers both channels=None and an empty list (which the
        # demo app sends when its Channels field is left blank).
        effective_channels = channels
        if is_channel_module and not channels:
            effective_channels = _DEFAULT_CHANNELS

        channel_errors = _parse_error_arg(str(error), effective_channels)
        if is_channel_module:
            if any(ch is None for ch, _ in channel_errors):
                # Only reachable via a malformed mix of "1.<desc>" and bare items.
                raise ErrorSimulatorError(
                    f"module {module_info.table} is per-channel: give every "
                    'item a channel in the "1.<desc>;2.<desc>" syntax, or pass '
                    "a plain description to apply to all channels"
                )
            codes: list[tuple[int, str]] = []
            for channel, description in channel_errors:
                assert channel is not None
                codes.append(
                    (
                        channel,
                        match_error(description, error_rows, instrument=instrument, exact=_is_exact(error)),
                    )
                )
            reply = build_channel_reply(
                instrument,
                prefix,
                is_magpip=Module(module_info.table) is Module.MAGPIP,
                channel_codes=codes,
                firmware_command=fw_command,
            )
        else:
            (_, desc), *rest = channel_errors
            if rest or channels:
                raise ErrorSimulatorError(f"module {module_info.table} does not take channels")
            code = match_error(desc, error_rows, instrument=instrument, exact=_is_exact(error))
            reply = build_single_reply(
                instrument, prefix, error_code=code, firmware_command=fw_command
            )

        values = self._no_error_values()
        values[reply.firmware_command] = reply.value
        values["updateKeyValue"] = reply.firmware_command
        values["updateParamValue"] = reply.no_error
        values["reload"] = "1"
        self.config.apply(values)
        self._active_firmware_commands = {reply.firmware_command}

    def set_error_by_code(
        self, firmware_command: str, error_code: str, error_recovery: str = ""
    ) -> None:
        """Write *error_code* as the raw simulated reply for *firmware_command*
        with no keyword matching (the HSL ``SetErrorByCode``).

        Like :meth:`set_error`, every previously injected error is cleared first
        so only this one is active (see the class docstring)."""
        self._require_simulation()
        values = self._no_error_values()
        values[firmware_command] = error_code
        values["updateKeyValue"] = firmware_command
        values["updateParamValue"] = error_recovery
        values["reload"] = "1"
        self.config.apply(values)
        self._active_firmware_commands = {firmware_command}

    def reset(self) -> None:
        """Clear every injected error: write the "no error" reply for every
        firmware command of every module (the HSL ``ResetConfigFile``)."""
        self._require_simulation()
        values = self._no_error_values()
        for firmware_command in self._active_firmware_commands:
            values[firmware_command] = no_error_reply(self.run_info.instrument, firmware_command)
        values["updateKeyValue"] = "0"
        values["updateParamValue"] = "0"
        self.config.apply(values)
        self._active_firmware_commands.clear()

    def _no_error_values(self) -> dict[str, str]:
        """``{firmware_command: "no error" reply}`` for every known FW command on
        this instrument. Prepended to every :meth:`set_error` /
        :meth:`set_error_by_code` write (and the whole of :meth:`reset`) so the
        cfg never holds more than one active simulated error at a time."""
        instrument = self.run_info.instrument
        values: dict[str, str] = {}
        for module in self.kb.modules:
            if not self.kb.has_table(instrument, module):
                continue
            for row in self.kb.firmware_rows(instrument, module):
                if row.code:
                    values[row.code] = no_error_reply(instrument, row.code)
        return values

    # -- discovery ------------------------------------------------------------

    def available_modules(self) -> list[str]:
        instrument = self.run_info.instrument
        return [m.table for m in self.kb.modules if self.kb.has_table(instrument, m)]

    def available_steps(self, module: Module | str) -> list[str]:
        module_info = self.kb.resolve_module(str(module))
        return [r.description for r in self.kb.firmware_rows(self.run_info.instrument, module_info)]

    def available_errors(self, module: Module | str) -> list[str]:
        module_info = self.kb.resolve_module(str(module))
        return [r.description for r in self.kb.error_rows(self.run_info.instrument, module_info)]

    # -- internals ------------------------------------------------------------

    def _require_simulation(self) -> None:
        if not self.run_info.is_simulating:
            raise SimulationModeRequired(
                "VENUS is not in simulation mode; the simulated firmware ignores "
                "the simulator config on a live instrument"
            )


def _is_exact(value: object) -> bool:
    """A generated typed constant -> exact description match; a plain str -> fuzzy."""
    return isinstance(value, StrEnum) and not isinstance(value, Module)


def _parse_error_arg(
    error: str, channels: list[int] | None
) -> list[tuple[int | None, str]]:
    items = [chunk for chunk in error.split(";") if chunk.strip()] if ";" in error else [error]
    parsed: list[tuple[int | None, str]] = []
    micro_syntax = False
    for item in items:
        match = _CHANNEL_ITEM.match(item)
        if match:
            micro_syntax = True
            parsed.append((int(match.group(1)), match.group(2).strip()))
        else:
            parsed.append((None, item.strip()))

    if micro_syntax:
        return parsed
    if channels:
        (_, desc) = parsed[0]
        return [(ch, desc) for ch in channels]
    return parsed
