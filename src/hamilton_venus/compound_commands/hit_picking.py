"""``hit_picking`` compound command implementation.

This module provides :func:`execute_hit_picking`, the entry point used by
:meth:`hamilton_venus.star_client.StarClient.hit_picking` (wired in a later
task), along with the internal helpers that support it: the per-tip-block
runner :func:`_run_tip_block` driven by an ordered list of :class:`_TipBlock`
objects produced by :func:`_plan_transfers`.

Hit picking transfers samples between *arbitrary* source and destination
wells described by a transfer CSV worklist (one ``(source_labware,
source_well, dest_labware, dest_well, volume)`` per row).  Unlike
``add_reagent``, the CSV is the worklist -- there are no parameter-level
source/dest/volume fallbacks.

CSV parsing/grouping primitives and the plate-grouped column-major reordering
helpers live in :mod:`hamilton_venus.compound_commands._helpers._transfer_plan`;
tip-capacity resolution lives in
:mod:`hamilton_venus.compound_commands._helpers._tip_capacity`.

All four ``(change_tips, minimize_tips)`` mode combinations are supported.
"""

from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    resolve_selector_positions,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import (
    eject_tips,
    ensure_tips_available,
    pickup_tips,
)
from hamilton_venus.compound_commands._helpers._transfer_plan import (
    _group_in_order,
    _parse_transfer_csv,
    _sort_plate_grouped_column_major,
    _validate_row_volumes_in_range,
    validate_labware_on_deck,
)
from hamilton_venus.models.compound_results import (
    HitPickingResult,
    HitPickingTransferResult,
)
from hamilton_venus.models.position import LabwareLayoutSpec, Position

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ResolvedTransfer:
    """A single transfer with both endpoints resolved to deck positions.

    Produced by :func:`_plan_transfers` (one per CSV row, in execution order)
    and consumed by the main loop to drive the aspirate/dispense pair and to
    build the corresponding :class:`HitPickingTransferResult`.
    """

    source_pos: Position
    dest_pos: Position
    volume: float
    line_no: int | None = None


@dataclass(frozen=True)
class _TipBlock:
    """One ``pickup -> N transfers -> eject`` unit of execution.

    *channels* is the set of channels picked up at the start of the block and
    ejected at the end.  *transfers* are walked in chunks of ``len(channels)``;
    each chunk issues one aspirate and one dispense across its active channels.
    """

    channels: list[int]
    transfers: list[_ResolvedTransfer] = field(default_factory=list)


def _group_resolved_by_source_well(
    resolved: list[_ResolvedTransfer],
) -> list[list[_ResolvedTransfer]]:
    """Group *resolved* transfers by their source well, first-appearance order."""
    return _group_in_order(resolved, key=lambda t: (t.source_pos.labware, t.source_pos.well))


def _plan_transfers(
    resolved: list[_ResolvedTransfer],
    *,
    channels: list[int],
    minimize_tips: bool,
    change_tips: bool,
) -> list[_TipBlock]:
    """Build the ordered list of :class:`_TipBlock` objects to execute.

    All four ``(change_tips, minimize_tips)`` combinations are supported:

    * **Default** (``change_tips=True, minimize_tips=False``): every transfer
      consumes a fresh tip.  *resolved* is split into channel-sized chunks and
      each chunk becomes one block (the final chunk may use fewer active
      channels).
    * **Reuse tips** (``change_tips=False, minimize_tips=False``): tips are
      picked up once and reused across every transfer.  All transfers collapse
      into a single block whose channel count is
      ``min(len(channels), len(resolved))``; the runner walks it in
      channel-sized chunks and ejects once at the end.
    * **Minimize tips** (``change_tips=True, minimize_tips=True``): transfers
      are grouped by ``(source_labware, source_well)`` and each group becomes
      one single-channel block.  One tip serves every destination fed by a
      source well, then is ejected before the next group.
    * **Minimize tips, keep tips** (``change_tips=False, minimize_tips=True``):
      a single tip is kept across **every** source well (the operator accepts
      cross-contamination, Q4).  Every transfer collapses into **one**
      single-channel block.

    Args:
        resolved: Transfers in execution order (already reordered by the
            caller when ``follow_csv_order=False``).
        channels: 1-indexed channels available for pipetting.  Under
            ``minimize_tips=True`` only the first channel is used.
        minimize_tips: Reuse one tip per source well.
        change_tips: Change tips between groups/transfers.  ``False`` reuses
            one set of tips for the whole worklist.

    Returns:
        Ordered list of tip blocks to execute.
    """
    if not resolved:
        return []

    if minimize_tips:
        first_channel = channels[:1]
        if not change_tips:
            # Q4: one tip kept across every source well.
            return [_TipBlock(channels=first_channel, transfers=list(resolved))]
        # One single-channel block per distinct source well.
        return [
            _TipBlock(channels=first_channel, transfers=group) for group in _group_resolved_by_source_well(resolved)
        ]

    n_ch = len(channels)

    if not change_tips:
        # Reuse tips: one pickup, every transfer, one eject.  A single block
        # holding all transfers gives the runner pickup-once / chunk /
        # eject-at-end semantics.  The pickup uses min(channels, transfers)
        # tips so we never claim more channels than there is work for.
        active = channels[: min(n_ch, len(resolved))]
        return [_TipBlock(channels=active, transfers=list(resolved))]

    blocks: list[_TipBlock] = []
    for offset in range(0, len(resolved), n_ch):
        chunk = resolved[offset : offset + n_ch]
        blocks.append(_TipBlock(channels=channels[: len(chunk)], transfers=list(chunk)))
    return blocks


def _run_tip_block(
    client: InstrumentClient,
    block: _TipBlock,
    *,
    tip_pool: str,
    liquid_class: str | list[str],
    optimized_tip_pickup: bool,
    aspirate_settings: AspirateSettings | None,
    dispense_settings: DispenseSettings | None,
    transfers_out: list[HitPickingTransferResult],
    source_plate_ids: list[str],
    dest_plate_ids: list[str],
) -> tuple[int, int]:
    """Execute one :class:`_TipBlock`: pickup -> chunked aspirate/dispense -> eject.

    Mutates *transfers_out*, *source_plate_ids*, *dest_plate_ids* in place to
    accumulate per-block results into the caller's worklist-wide collectors.
    Tip pickup uses ``block.channels``; transfers are processed in chunks of
    ``len(block.channels)`` (the final chunk may use fewer active channels).
    On error, ejection still runs in a ``finally`` clause; failures during
    ejection are logged and swallowed so the original exception propagates.

    Returns:
        Tuple ``(tips_consumed, aspirate_calls)`` for the block.  *tips_consumed*
        equals ``len(block.channels)`` when pickup succeeded (0 otherwise) and
        *aspirate_calls* is the number of aspirate/dispense pairs issued (one
        per chunk).
    """
    active = block.channels
    picked_up = False
    tips_consumed = 0
    aspirate_calls = 0
    try:
        pickup_tips(client, active, tip_pool, optimized=optimized_tip_pickup)
        picked_up = True
        tips_consumed = len(active)

        n_ch = len(active)
        for offset in range(0, len(block.transfers), n_ch):
            chunk = block.transfers[offset : offset + n_ch]
            chunk_active = active[: len(chunk)]
            volumes = [t.volume for t in chunk]
            uniform = len(set(volumes)) == 1

            asp_resp = client.aspirate(
                channels=chunk_active,
                positions=[t.source_pos for t in chunk],
                volumes=volumes[0] if uniform else volumes,
                liquid_class=liquid_class,
                settings=slice_settings(aspirate_settings, len(chunk_active)),
            )
            disp_resp = client.dispense(
                channels=chunk_active,
                positions=[t.dest_pos for t in chunk],
                volumes=volumes[0] if uniform else volumes,
                settings=slice_settings(dispense_settings, len(chunk_active)),
            )
            aspirate_calls += 1

            for t in chunk:
                transfers_out.append(
                    HitPickingTransferResult(
                        source_plate_id=t.source_pos.labware,
                        source_well=t.source_pos.well,
                        dest_plate_id=t.dest_pos.labware,
                        dest_well=t.dest_pos.well,
                        volume=t.volume,
                        aspirate=asp_resp,
                        dispense=disp_resp,
                    )
                )
                if t.source_pos.labware not in source_plate_ids:
                    source_plate_ids.append(t.source_pos.labware)
                if t.dest_pos.labware not in dest_plate_ids:
                    dest_plate_ids.append(t.dest_pos.labware)
    finally:
        if picked_up:
            try:
                eject_tips(client, active)
            except Exception as e:
                _logger.warning(
                    "Failed to eject tips on channels %s during cleanup: %s. Original exception will be raised.",
                    active,
                    e,
                )
    return tips_consumed, aspirate_calls


def execute_hit_picking(
    client: InstrumentClient,
    *,
    transfer_csv: str | os.PathLike[str],
    liquid_class: str | list[str],
    tip_pool: str,
    channels: list[int] | None = None,
    optimized_tip_pickup: bool = True,
    change_tips: bool = True,
    minimize_tips: bool = False,
    follow_csv_order: bool = False,
    aspirate_settings: AspirateSettings | None = None,
    dispense_settings: DispenseSettings | None = None,
    error_profile: ErrorProfile | None = None,
) -> HitPickingResult:
    """Transfer samples between arbitrary source and destination wells.

    Reads a transfer CSV worklist and executes one source->dest transfer per
    row.  In the default ``change_tips=True, minimize_tips=False`` mode each
    transfer uses a fresh tip; transfers are processed in channel-sized chunks
    so an 8-channel head fills one column per cycle.  In the
    ``change_tips=False, minimize_tips=False`` mode the same tips are picked up
    once and reused for the whole worklist (one eject at the end).  Under
    ``minimize_tips=True`` transfers are grouped by ``(source_labware,
    source_well)`` and one tip serves every destination fed by a source well
    (a single channel per group); with ``change_tips=False`` that single tip is
    kept across every source well (the operator accepts cross-contamination).

    Args:
        client: Connected :class:`~hamilton_venus.star_client.StarClient`.
        transfer_csv: Path to a transfer CSV file (required), as a ``str`` or
            ``os.PathLike``.  Columns:
            ``source_labware``, ``source_well``, ``dest_labware``,
            ``dest_well``, ``volume``.  Every row must specify all columns --
            there are no parameter-level fallbacks.
        liquid_class: Liquid-class name(s) forwarded to the aspirate step.
        tip_pool: Name of the tip pool to draw tips from (required).
        channels: 1-indexed channel numbers (default 1-8).
        optimized_tip_pickup: Pass through to tip-pickup command.
        change_tips: Change tips between transfers.  When ``False`` one set of
            tips is reused for the whole worklist.
        minimize_tips: When ``True``, reuse one tip for all transfers from the
            same source well (a single channel per source-well group).
        follow_csv_order: When ``False`` (default), transfers are reordered for
            pipetting efficiency (plate-grouped, then column-major within each
            plate).  When ``True``, transfers run in original CSV row order.
        aspirate_settings: Optional aspirate settings forwarded to aspirate
            calls (per-channel list fields are sliced to the active count).
        dispense_settings: Optional dispense settings forwarded to dispense
            calls.
        error_profile: When provided, all liquid-handling steps run inside
            ``client.use_error_profile(error_profile)``.

    Returns:
        :class:`~hamilton_venus.models.compound_results.HitPickingResult`
        summarising the executed transfers and raw command responses.

    Raises:
        ValueError: If *tip_pool* is empty, the CSV is empty or malformed, any
            row's volume exceeds tip capacity, any referenced labware is
            missing from the deck (all missing labware listed in one message),
            any referenced well does not exist (all bad wells listed in one
            message), or insufficient tips are available and no reload callback
            is configured.
        OperatorCancelledError: If the operator cancels a tip-reload prompt.
    """
    # ------------------------------------------------------------------
    # 1. Parameter validation
    # ------------------------------------------------------------------
    if not tip_pool or not tip_pool.strip():
        raise ValueError("tip_pool must not be empty")
    tip_pool = tip_pool.strip()

    channels = list(channels) if channels is not None else list(DEFAULT_CHANNELS)
    validate_channels(channels)

    # ------------------------------------------------------------------
    # 2. Parse CSV (no defaults -- every row must specify all columns)
    # ------------------------------------------------------------------
    rows = _parse_transfer_csv(transfer_csv)

    # ------------------------------------------------------------------
    # 3. Up-front labware validation -- collect every distinct labware id
    #    referenced by the CSV and raise a single error listing all missing
    #    labware.  The returned geometry is parsed into LabwareLayoutSpecs
    #    and registered on the client so that downstream
    #    resolve_selector_positions calls reuse them (no second deck
    #    round-trip per labware) and the sort below can read them from
    #    the same source of truth.
    # ------------------------------------------------------------------
    labware_ids: list[str] = []
    row_origin: dict[str, int] = {}
    for row in rows:
        for lid in (row.source_labware, row.dest_labware):
            if lid not in row_origin:
                row_origin[lid] = row.line_no if row.line_no is not None else 0
                labware_ids.append(lid)
    geometry = validate_labware_on_deck(client, labware_ids, row_origin=row_origin)
    spec_cache: dict[str, LabwareLayoutSpec] = {}
    for lid, params in geometry.items():
        spec = LabwareLayoutSpec.from_definition(params.definition)
        client.register_labware_definition(lid, spec)
        spec_cache[lid] = spec

    # ------------------------------------------------------------------
    # 4. Tip capacity + per-row volume sanity
    # ------------------------------------------------------------------
    tip_capacity = _resolve_tip_capacity(client, tip_pool)
    _validate_row_volumes_in_range(rows, max_aspiration=tip_capacity)

    # ------------------------------------------------------------------
    # 5. Determine execution order (reorder vs. CSV order), then resolve
    #    well positions with a per-(labware, well) cache so repeated wells --
    #    very common in hit picking -- query the deck at most once.
    # ------------------------------------------------------------------
    ordered_rows = rows if follow_csv_order else _sort_plate_grouped_column_major(rows, spec_cache)

    position_cache: dict[tuple[str, str], Position | None] = {}
    bad_wells: list[str] = []

    def _resolve(labware: str, well: str, *, line_no: int | None) -> Position | None:
        key = (labware, well)
        if key in position_cache:
            return position_cache[key]
        positions = resolve_selector_positions(client, f"{labware}@wells:{well}")
        if not positions:
            where = f" (CSV line {line_no})" if line_no is not None else ""
            bad_wells.append(f"'{labware}'/'{well}'{where}")
            position_cache[key] = None
            return None
        position_cache[key] = positions[0]
        return positions[0]

    resolved: list[_ResolvedTransfer] = []
    for row in ordered_rows:
        src_pos = _resolve(row.source_labware, row.source_well, line_no=row.line_no)
        dst_pos = _resolve(row.dest_labware, row.dest_well, line_no=row.line_no)
        if src_pos is None or dst_pos is None:
            continue
        resolved.append(_ResolvedTransfer(source_pos=src_pos, dest_pos=dst_pos, volume=row.volume, line_no=row.line_no))

    if bad_wells:
        joined = "\n  - ".join(bad_wells)
        raise ValueError(
            "The following wells could not be resolved on their labware:\n  - "
            f"{joined}\n"
            "Check the well ids against the labware geometry."
        )

    # ------------------------------------------------------------------
    # 6. Build transfer plan + pre-flight tip budget
    # ------------------------------------------------------------------
    tip_blocks = _plan_transfers(
        resolved,
        channels=channels,
        minimize_tips=minimize_tips,
        change_tips=change_tips,
    )

    # Tip budget depends on the mode:
    #   minimize_tips=False, change_tips=True  -> one fresh tip per transfer
    #                                             (len(resolved)).
    #   minimize_tips=False, change_tips=False -> one pickup reused for the
    #                                             whole worklist
    #                                             (min(channels, transfers)).
    #   minimize_tips=True,  change_tips=True  -> one tip per distinct source
    #                                             well.
    #   minimize_tips=True,  change_tips=False -> a single tip kept across
    #                                             every source well (Q4).
    if minimize_tips:
        if change_tips:
            tips_needed = len({(t.source_pos.labware, t.source_pos.well) for t in resolved})
        else:
            tips_needed = 1 if resolved else 0
            _logger.warning(
                "hit_picking: change_tips=False with minimize_tips=True keeps a single "
                "tip across every source well; the operator accepts cross-contamination."
            )
    elif change_tips:
        tips_needed = len(resolved)
    else:
        tips_needed = min(len(channels), len(resolved))
    ensure_tips_available(client, tip_pool, tips_needed, command_name="hit_picking")

    # ------------------------------------------------------------------
    # 7. Execute -- one _run_tip_block call per planned block.  ``iterations``
    #    counts aspirate calls (matching ``add_reagent`` and ``copy_plate``);
    #    in the default mode each block has exactly one aspirate call, but
    #    in tip-reuse and minimize_tips modes a single block may carry
    #    multiple chunks, each contributing one aspirate call.
    # ------------------------------------------------------------------
    transfers: list[HitPickingTransferResult] = []
    source_plate_ids: list[str] = []
    dest_plate_ids: list[str] = []
    tips_consumed = 0
    iterations = 0

    profile_scope = client.use_error_profile(error_profile) if error_profile is not None else nullcontext()

    with profile_scope:
        for block in tip_blocks:
            consumed, asp_calls = _run_tip_block(
                client,
                block,
                tip_pool=tip_pool,
                liquid_class=liquid_class,
                optimized_tip_pickup=optimized_tip_pickup,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                transfers_out=transfers,
                source_plate_ids=source_plate_ids,
                dest_plate_ids=dest_plate_ids,
            )
            tips_consumed += consumed
            iterations += asp_calls

    transfers_by_source_plate: dict[str, int] = {}
    transfers_by_dest_plate: dict[str, int] = {}
    for t in transfers:
        transfers_by_source_plate[t.source_plate_id] = transfers_by_source_plate.get(t.source_plate_id, 0) + 1
        transfers_by_dest_plate[t.dest_plate_id] = transfers_by_dest_plate.get(t.dest_plate_id, 0) + 1

    return HitPickingResult(
        iterations=iterations,
        total_wells_processed=len(transfers),
        source_plate_ids=tuple(source_plate_ids),
        dest_plate_ids=tuple(dest_plate_ids),
        transfers=tuple(transfers),
        transfers_by_source_plate=transfers_by_source_plate,
        transfers_by_dest_plate=transfers_by_dest_plate,
        tips_consumed=tips_consumed,
        minimize_tips=minimize_tips,
        change_tips=change_tips,
    )
