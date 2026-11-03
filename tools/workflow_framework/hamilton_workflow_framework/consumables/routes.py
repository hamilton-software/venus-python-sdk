"""REST endpoints for manual tip/reagent adjustment -- an alternative to the
adjust_tip_count/adjust_reagent_volume WS messages (e.g. for a standalone
inventory page outside the main run session). Trackers are in-memory per WS
session (see tip_tracker.py/reagent_tracker.py), so these endpoints operate on
one session at a time, looked up by session_id in a small in-memory registry
an app populates when it wires tracking into a WS connection.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .reagent_tracker import ReagentLedger
from .tip_tracker import TipConsumableTracker

_active_trackers: dict[str, tuple[TipConsumableTracker, ReagentLedger]] = {}


def register_trackers(session_id: str, tip_tracker: TipConsumableTracker, reagent_ledger: ReagentLedger) -> None:
    _active_trackers[session_id] = (tip_tracker, reagent_ledger)


def unregister_trackers(session_id: str) -> None:
    _active_trackers.pop(session_id, None)


def _get_trackers(session_id: str) -> tuple[TipConsumableTracker, ReagentLedger]:
    trackers = _active_trackers.get(session_id)
    if trackers is None:
        raise HTTPException(status_code=404, detail=f"No active tracked session {session_id!r}")
    return trackers


class AdjustTipCountBody(BaseModel):
    delta: int


class AdjustReagentVolumeBody(BaseModel):
    delta_ul: float


def build_consumables_http_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/consumables/{session_id}/tip-pools/{tip_pool}/adjust")
    async def adjust_tip_pool(session_id: str, tip_pool: str, body: AdjustTipCountBody) -> dict:
        tip_tracker, _ = _get_trackers(session_id)
        pool = tip_tracker.adjust(tip_pool, body.delta)
        return pool.model_dump()

    @router.post("/api/consumables/{session_id}/reagents/{position}/adjust")
    async def adjust_reagent(session_id: str, position: str, body: AdjustReagentVolumeBody) -> dict:
        _, reagent_ledger = _get_trackers(session_id)
        entry = reagent_ledger.adjust(position, body.delta_ul)
        return entry.model_dump()

    return router
