"""Reagent volume ledger: tracks remaining volume at operator-declared fill
positions, decremented from the *actual* aspirated volume the instrument
reports (AspirationChannelData.aspirated_volume), not the requested volume.
Implements the StepObserver protocol directly (see execution_engine.StepObserver).

Scope note: a ledger entry is keyed by the DSL position string exactly as
typed in the aspirate step's ``positions`` field (e.g. "ReagentTrough@A1"),
not by individual well. When a single aspirate call addresses multiple wells
through one DSL expression (e.g. a column range), the SDK expands that
internally (hamilton_venus.models.position) into one well per channel --
this tracker does not reimplement that expansion, so it can't attribute
per-channel volume to distinct wells within one DSL expression. Instead it
sums every channel's aspirated_volume from the call and decrements the whole
entry by that total. This is exact for the common case of a single-well
reagent source (a trough/reservoir referenced by one position string used by
every channel) and an intentional simplification -- not a per-well ledger --
for a genuinely per-well multi-position source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hamilton_workflow_framework.execution_engine import SendFn, Step
from hamilton_workflow_framework.registry import RegistryEntry

from .models import ReagentLedgerEntry

_ASPIRATE_COMMANDS = {"aspirate", "aspirate_5ml"}

# command_id -> kwarg name holding the reagent source position(s). Compound
# commands vary in what they call their source param; only the ones that take
# a single reagent/diluent source position are listed -- multi-source compound
# commands (copy_plate/pool_samples/replicate_samples move plate-to-plate, not
# from a trackable reagent reservoir) are intentionally not covered here.
_COMPOUND_SOURCE_PARAM = {
    "add_reagent": "reagent_source",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReagentLedger:
    """One instance per WorkflowSession/ExecutionEngine pairing."""

    def __init__(self) -> None:
        self.entries: dict[str, ReagentLedgerEntry] = {}

    def setup_fill(self, position: str, initial_volume_ul: float, label: str = "") -> ReagentLedgerEntry:
        """Operator-declared ground truth for a reagent fill level. Not derived
        from the instrument -- VENUS has no logical liquid-content query --
        so this must be called (e.g. from the app's Setup tab) before a run
        that aspirates from *position* for tracking to mean anything.
        """
        entry = ReagentLedgerEntry(
            position=position,
            label=label,
            initial_volume_ul=initial_volume_ul,
            remaining_volume_ul=initial_volume_ul,
            last_updated=_now_iso(),
        )
        self.entries[position] = entry
        return entry

    def adjust(self, position: str, delta_ul: float) -> ReagentLedgerEntry:
        entry = self.entries.setdefault(
            position,
            ReagentLedgerEntry(position=position, initial_volume_ul=0.0, remaining_volume_ul=0.0, last_updated=_now_iso()),
        )
        entry.remaining_volume_ul = max(0.0, entry.remaining_volume_ul + delta_ul)
        entry.last_updated = _now_iso()
        return entry

    async def _send_update(self, send: SendFn, position: str) -> None:
        entry = self.entries[position]
        await send({
            "type": "reagent_level_update",
            "position": entry.position,
            "remaining_volume_ul": entry.remaining_volume_ul,
            "initial_volume_ul": entry.initial_volume_ul,
            "label": entry.label,
        })

    def _decrement(self, position: str, volume_ul: float) -> None:
        if position not in self.entries or volume_ul <= 0:
            return
        entry = self.entries[position]
        entry.remaining_volume_ul = max(0.0, entry.remaining_volume_ul - volume_ul)
        entry.last_updated = _now_iso()

    async def after_step(
        self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step, send: SendFn
    ) -> None:
        position: str | None = None
        total_volume = 0.0

        if entry.method_name in _ASPIRATE_COMMANDS:
            raw_positions = kwargs.get("positions")
            if isinstance(raw_positions, str):
                position = raw_positions
            channels_data = getattr(getattr(result, "return_parameters", None), "channels", None) or []
            total_volume = sum(getattr(c, "aspirated_volume", 0.0) for c in channels_data)
        elif entry.command_id in _COMPOUND_SOURCE_PARAM:
            source_param = _COMPOUND_SOURCE_PARAM[entry.command_id]
            raw_source = kwargs.get(source_param)
            if isinstance(raw_source, str):
                position = raw_source
            for iteration in getattr(result, "iteration_results", None) or ():
                aspirate_response = getattr(iteration, "aspirate", None)
                channels_data = getattr(getattr(aspirate_response, "return_parameters", None), "channels", None) or []
                total_volume += sum(getattr(c, "aspirated_volume", 0.0) for c in channels_data)

        if position is None or position not in self.entries or total_volume <= 0:
            return

        self._decrement(position, total_volume)
        await self._send_update(send, position)
