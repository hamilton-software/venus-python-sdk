"""Shared greedy multi-dispense batch planner.

A *channel-row* is the slice of destination wells dispensed in one simultaneous
multi-channel dispense call, represented as a list of ``(Position, volume)``
pairs (one per active channel).  Because every channel of a single aspiration
draws the same total volume, the per-channel volume of a row is the maximum
volume across its pairs (identical for uniform runs, the CSV maximum for
variable-volume runs).

:func:`plan_dispense_batches` groups consecutive channel-rows into *batches*.
Each batch is aspirated once, then its rows are dispensed in order.  Rows are
accumulated greedily until adding the next row would exceed the tip *capacity*
(and, when supplied, the remaining-source *budget*), at which point the current
batch is flushed and a new one is started.

``budget=None`` reproduces the capacity-only batching used today by
``add_reagent`` and ``replicate_samples`` exactly.  Serial dilution passes the
measured remaining-source budget from ``ensure_liquid_available`` so a batch is
never planned to aspirate more reagent than the current source can supply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hamilton_venus.models.position import Position

ChannelRow = list[tuple["Position", float]]
DispenseBatch = list[ChannelRow]


def _row_volume(row: ChannelRow) -> float:
    """Per-channel reagent volume for *row* (the max across its channel pairs)."""
    return max(v for _, v in row)


def plan_dispense_batches(
    channel_rows: list[ChannelRow],
    capacity: float,
    budget: float | None = None,
) -> list[DispenseBatch]:
    """Group *channel_rows* into greedy aspiration batches bounded by *capacity*.

    Rows are accumulated into the current batch until adding the next row would
    push the batch's cumulative per-channel reagent volume above *capacity*
    (or above *budget*, when supplied), at which point the current batch is
    flushed and the row starts a fresh batch.  A single row is always placed in
    a batch even if its own volume exceeds the bounds (callers validate that a
    single row fits the tip capacity before planning).

    Args:
        channel_rows: Ordered channel-rows to batch.  Each row is a list of
            ``(Position, volume)`` pairs, one per active channel.
        capacity: Net per-channel tip capacity available for reagent in a batch
            (i.e. tip capacity minus any fixed per-batch overhead such as
            pre-/post-aliquot volumes).  Each batch's cumulative row volume must
            not exceed this value.
        budget: Optional remaining-source per-channel estimate.  When provided,
            a batch is additionally bounded so its cumulative row volume does
            not exceed the budget.  ``None`` (default) means capacity-only.

    Returns:
        A list of batches, each a list of the channel-rows aspirated together.
        Returns an empty list when *channel_rows* is empty.
    """
    batches: list[DispenseBatch] = []
    current_batch: DispenseBatch = []
    current_vol = 0.0

    for row in channel_rows:
        row_vol = _row_volume(row)
        exceeds_capacity = current_vol + row_vol > capacity
        exceeds_budget = budget is not None and current_vol + row_vol > budget
        if current_batch and (exceeds_capacity or exceeds_budget):
            batches.append(current_batch)
            current_batch = [row]
            current_vol = row_vol
        else:
            current_batch.append(row)
            current_vol += row_vol

    if current_batch:
        batches.append(current_batch)

    return batches
