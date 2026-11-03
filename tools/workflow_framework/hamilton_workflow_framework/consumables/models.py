"""Data shapes for tip/reagent consumable tracking. All state is in-memory,
scoped to one WorkflowSession/ExecutionEngine pairing (one WS connection) --
see tip_tracker.py/reagent_tracker.py. There is no cross-session persistence;
an app that needs durability must snapshot these itself (e.g. alongside its
run-log directory).
"""

from __future__ import annotations

from pydantic import BaseModel


class TipPoolCount(BaseModel):
    tip_pool: str
    total_capacity: int
    current_count: int
    # Cumulative delta from manual adjust_tip_count messages, kept separate from
    # current_count so the UI/audit trail can show "how much of this was
    # observed-consumption vs. an operator correction."
    manual_adjustments: int = 0


class ReagentLedgerEntry(BaseModel):
    # DSL position string as typed by the operator (e.g. "ReagentPlate@A1"),
    # matching the same encoding aspirate/dispense positions use -- see
    # reagent_tracker.py for why per-well subdivision isn't attempted.
    position: str
    label: str = ""
    initial_volume_ul: float
    remaining_volume_ul: float
    last_updated: str
