"""Tip-pool consumable tracking: current tip counts, decremented from real
tip_pickup results (not from the requested params alone), plus manual
correction. Implements the StepObserver protocol directly (see
execution_engine.StepObserver) so it plugs into ExecutionEngine's
step_observers list unmodified.

Scope note: tip_pickup/tip_pickup_5ml return a bare CommandResponse with no
per-channel tip data (confirmed against hamilton_venus.mixins.channel_commands),
so the decrement amount comes from the *requested* channel count on a
successful call, not from a per-channel field in the response -- this is safe
because StepObserver.after_step is only invoked after a step succeeds (see
ExecutionEngine._execute_step), so "requested" and "actually picked up" agree
whenever the call didn't raise.

For the compound commands that also consume a tip pool (add_reagent,
copy_plate, hit_picking, pool_samples, replicate_samples,
serial_dilution_by_*), the exact per-iteration tip_pickup field varies by
command (see hamilton_venus.models.compound_results: some use
``tip_pickup: CommandResponse | None``, others ``tip_pickups: tuple[...]``,
populated only on the first iteration of a source block for some commands).
Rather than hand-author a bespoke extractor per command -- unverifiable here
without running each compound command against real hardware -- this tracker
uses a best-effort generic scan: count non-None CommandResponse-shaped
``tip_pickup``/``tip_pickups`` attributes across the result and any
``iteration_results``, and charge each one ``len(channels)`` tips. Treat this
path as approximate; the simple per-channel commands above are exact.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from hamilton_workflow_framework.execution_engine import SendFn, Step
from hamilton_workflow_framework.registry import RegistryEntry
from hamilton_workflow_framework.session import WorkflowSession

from .models import TipPoolCount

_logger = logging.getLogger("hamilton_workflow_framework.consumables.tip_tracker")

_DEFAULT_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

_SIMPLE_PICKUP_COMMANDS = {"tip_pickup", "tip_pickup_5ml"}

# command_id -> compound command's tip_pool kwarg name (all of them use "tip_pool").
_COMPOUND_TIP_POOL_COMMANDS = {
    "add_reagent",
    "copy_plate",
    "hit_picking",
    "pool_samples",
    "replicate_samples",
    "serial_dilution_by_volume",
    "serial_dilution_by_dilution_factor",
}


def _count_compound_tip_pickups(result: Any) -> int:
    """Best-effort scan for tip_pickup(s) across a compound command's result and
    its iteration_results (field name/shape varies by command -- see module
    docstring). Returns the number of distinct pickup events found; the caller
    multiplies by the channel count to get tips consumed.
    """
    count = 0

    def _check(obj: Any) -> None:
        nonlocal count
        for attr in ("tip_pickup", "tip_pickups"):
            value = getattr(obj, attr, None)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                count += sum(1 for v in value if v is not None)
            else:
                count += 1

    _check(result)
    for iteration in getattr(result, "iteration_results", None) or ():
        _check(iteration)
    return count


class TipConsumableTracker:
    """One instance per WorkflowSession/ExecutionEngine pairing."""

    def __init__(self) -> None:
        self.pools: dict[str, TipPoolCount] = {}

    async def seed_from_instrument(self, session: WorkflowSession, tip_pool: str, send: SendFn) -> None:
        """Populate/refresh a pool's total_capacity + current_count from the
        instrument's live tip counter (StarClient.tip_pool_get_available_tips).
        Called on-demand (see consumables.ws_messages.SeedTipPool) rather than
        automatically for every pool, since a workflow app only cares about the
        pools it actually uses.
        """
        response = await asyncio.to_thread(session.star.tip_pool_get_available_tips, tip_pool)
        total = response.return_parameters.total_available_tips
        existing = self.pools.get(tip_pool)
        manual = existing.manual_adjustments if existing else 0
        self.pools[tip_pool] = TipPoolCount(
            tip_pool=tip_pool, total_capacity=total, current_count=total, manual_adjustments=manual
        )
        await self._send_update(send, tip_pool)

    def adjust(self, tip_pool: str, delta: int) -> TipPoolCount:
        pool = self.pools.setdefault(
            tip_pool, TipPoolCount(tip_pool=tip_pool, total_capacity=0, current_count=0)
        )
        pool.current_count = max(0, pool.current_count + delta)
        pool.manual_adjustments += delta
        return pool

    async def _send_update(self, send: SendFn, tip_pool: str) -> None:
        pool = self.pools[tip_pool]
        await send({
            "type": "tip_count_update",
            "tip_pool": pool.tip_pool,
            "current_count": pool.current_count,
            "total_capacity": pool.total_capacity,
            "manual_adjustments": pool.manual_adjustments,
        })

    def _decrement(self, tip_pool: str, count: int) -> None:
        pool = self.pools.setdefault(
            tip_pool, TipPoolCount(tip_pool=tip_pool, total_capacity=0, current_count=0)
        )
        pool.current_count = max(0, pool.current_count - count)

    async def after_step(
        self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step, send: SendFn
    ) -> None:
        tip_pool = kwargs.get("tip_pool")
        if not tip_pool:
            return

        if entry.method_name in _SIMPLE_PICKUP_COMMANDS:
            channels = kwargs.get("channels") or _DEFAULT_CHANNELS
            self._decrement(tip_pool, len(channels))
            await self._send_update(send, tip_pool)
            return

        if entry.command_id in _COMPOUND_TIP_POOL_COMMANDS:
            pickups = _count_compound_tip_pickups(result)
            if pickups <= 0:
                return
            channels = kwargs.get("channels") or _DEFAULT_CHANNELS
            self._decrement(tip_pool, pickups * len(channels))
            await self._send_update(send, tip_pool)
