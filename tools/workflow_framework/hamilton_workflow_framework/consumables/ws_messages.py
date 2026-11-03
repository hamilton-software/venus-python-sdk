"""WS message types for consumable tracking. Opt-in: an app concatenates these
into its own ClientMessage union (see hamilton_workflow_framework.ws_protocol)
alongside the base tuple, only if it wires up tip/reagent tracking at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AdjustTipCount(BaseModel):
    type: Literal["adjust_tip_count"] = "adjust_tip_count"
    tip_pool: str
    delta: int


class SeedTipPool(BaseModel):
    """Refreshes a tip pool's total_capacity/current_count from the instrument's
    live tip counter (StarClient.tip_pool_get_available_tips) -- only meaningful
    while connected."""

    type: Literal["seed_tip_pool"] = "seed_tip_pool"
    tip_pool: str


class AdjustReagentVolume(BaseModel):
    type: Literal["adjust_reagent_volume"] = "adjust_reagent_volume"
    position: str
    delta_ul: float


class SeedReagent(BaseModel):
    """Declares (or re-declares) an operator-entered fill level for a reagent
    position -- there is no instrument query for this, it's ground truth the
    operator enters (e.g. from the app's Setup/Consumables tab)."""

    type: Literal["seed_reagent"] = "seed_reagent"
    position: str
    initial_volume_ul: float
    label: str = ""


CONSUMABLES_CLIENT_MESSAGES: tuple[type[BaseModel], ...] = (
    AdjustTipCount,
    SeedTipPool,
    AdjustReagentVolume,
    SeedReagent,
)
