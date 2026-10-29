"""Compound command: ``replicate_samples`` — transfer one source well into N destination wells.

This module implements :func:`execute_replicate_samples`, the entry point
invoked by :meth:`hamilton_venus.star_client.StarClient.replicate_samples`.
The command is the 1-to-N mirror of :mod:`pool_samples`: each source well is
copied into ``replicates_per_source`` consecutive destination wells.

Two dispense strategies are supported:

* **multi-dispense mode** (``multi_dispense=True``, default): one tip pickup per
  source well; the aspiration covers as many replicates as fit in the tip
  (auto-split into multiple aspirations when required), with optional
  pre/post-aliquot dead-volume handling.  Up to ``len(channels)`` sources
  are processed in parallel as a single channel-row.
* **single-dispense mode** (``multi_dispense=False``): every replicate uses a fresh
  tip.  Transfers are batched ``len(channels)`` at a time for throughput
  while preserving the one-tip-per-transfer accounting.
"""

from __future__ import annotations

import logging
import math
from contextlib import nullcontext
from typing import TYPE_CHECKING

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._multi_dispense import plan_dispense_batches
from hamilton_venus.compound_commands._helpers._multi_plate import (
    chunk_positions_per_plate,
    extract_labware_id,
    normalize_selector_list,
    resolve_multi_selector,
)
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import eject_tips, ensure_tips_available, pickup_tips
from hamilton_venus.compound_commands._helpers._transfer_plan import validate_labware_on_deck
from hamilton_venus.compound_commands._helpers._waste import resolve_waste_position
from hamilton_venus.models.compound_results import (
    ReplicateSamplesIterationResult,
    ReplicateSamplesResult,
)
from hamilton_venus.models.enums import PreAliquotDisposal, WellOrder
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
    from hamilton_venus.models.commands import CommandResponse
    from hamilton_venus.models.position import Position

_logger = logging.getLogger(__name__)


def execute_replicate_samples(
    client: InstrumentClient,
    *,
    source_plate: str | list[str] | Position | list[Position],
    dest_plate: str | list[str] | Position | list[Position],
    replicates_per_source: int,
    volume_per_replicate: float,
    liquid_class: str | list[str],
    tip_pool: str,
    channels: list[int] | None = None,
    source_order: WellOrder = WellOrder.COL_ASC,
    dest_order: WellOrder = WellOrder.COL_ASC,
    multi_dispense: bool = True,
    pre_aliquot_volume: float = 0.0,
    pre_aliquot_disposal: PreAliquotDisposal = PreAliquotDisposal.SOURCE,
    post_aliquot_volume: float = 0.0,
    post_aliquot_height: float = 5.0,
    optimized_tip_pickup: bool = True,
    aspirate_settings: AspirateSettings | None = None,
    dispense_settings: DispenseSettings | None = None,
    error_profile: ErrorProfile | None = None,
) -> ReplicateSamplesResult:
    """Replicate every source well into ``replicates_per_source`` destination wells.

    Args:
        client: Connected instrument client used to issue hardware commands.
        source_plate: Source-plate selector string or a list of selectors
            spanning multiple plates (e.g. ``["PlateA@col:1", "PlateB@col:1"]``).
            May also be a pre-resolved ``Position``/``list[Position]``.
        dest_plate: Destination-plate selector string or a list of selectors
            spanning multiple plates. May also be a pre-resolved
            ``Position``/``list[Position]``.
        replicates_per_source: Number of destination wells per source. Must
            be ``>= 1``.
        volume_per_replicate: Per-channel dispense volume in µL applied to
            each destination well.  Must be ``> 0``.
        liquid_class: Liquid-class name(s) forwarded to the aspirate step.
        tip_pool: Tip-rack name. Required.
        channels: 1-indexed channel numbers (default 1-8).
        source_order: Traversal order for source wells (default
            ``COL_ASC``).
        dest_order: Traversal order for destination wells (default
            ``COL_ASC``).
        multi_dispense: ``True`` (default) batches replicates of one source
            into a single aspiration (auto-split if necessary); ``False``
            issues an independent transfer per replicate with a fresh tip.
        pre_aliquot_volume: Extra volume aspirated before the replicate
            volume, disposed per *pre_aliquot_disposal*.  Ignored in
            single-dispense mode.  Must be ``>= 0``.
        pre_aliquot_disposal: Where to send the pre-aliquot (``SOURCE`` or
            ``WASTE``).  Only honoured in multi-dispense mode.
        post_aliquot_volume: Extra volume aspirated and re-dispensed back
            to the source at *post_aliquot_height*.  Ignored in
            single-dispense mode.  Must be ``>= 0``.
        post_aliquot_height: Fixed height (mm) used for the post-aliquot
            re-dispense (overrides ``dispense_settings.fixed_height``).
        optimized_tip_pickup: Forwarded to :func:`pickup_tips`.
        aspirate_settings: Optional aspirate settings forwarded to each
            aspirate (sliced per channel-row).
        dispense_settings: Optional dispense settings forwarded to each
            dispense (sliced per channel-row).
        error_profile: When provided, all liquid-handling steps run inside
            ``client.use_error_profile(error_profile)``.

    Returns:
        A :class:`ReplicateSamplesResult` recording every aspirate,
        dispense, tip pickup, and tip eject.  In multi-dispense mode each source
        contributes one iteration; in single-dispense mode each source->dest
        transfer contributes one iteration.

    Raises:
        ValueError: If validation fails — empty ``tip_pool``,
            ``replicates_per_source < 1``, ``volume_per_replicate <= 0``,
            negative aliquot volumes, volume(s) exceed tip capacity,
            destination plate too small, source/destination labware
            missing on the deck, or insufficient tips with no
            operator-reload callback configured.
        OperatorCancelledError: Operator cancelled the tip-reload prompt.
    """
    if not tip_pool or not tip_pool.strip():
        raise ValueError("tip_pool must be a non-empty string.")
    tip_pool = tip_pool.strip()
    if replicates_per_source < 1:
        raise ValueError(f"replicates_per_source must be >= 1, got {replicates_per_source}.")
    if volume_per_replicate <= 0:
        raise ValueError(f"volume_per_replicate must be > 0, got {volume_per_replicate}.")
    if pre_aliquot_volume < 0:
        raise ValueError(f"pre_aliquot_volume must be >= 0, got {pre_aliquot_volume}.")
    if post_aliquot_volume < 0:
        raise ValueError(f"post_aliquot_volume must be >= 0, got {post_aliquot_volume}.")

    channels = channels if channels is not None else DEFAULT_CHANNELS
    validate_channels(channels)

    src_selectors = normalize_selector_list(source_plate)
    dst_selectors = normalize_selector_list(dest_plate)
    if not src_selectors:
        raise ValueError("source_plate list must contain at least one entry")
    if not dst_selectors:
        raise ValueError("dest_plate list must contain at least one entry")
    labware_ids: list[str] = []
    for sel in src_selectors + dst_selectors:
        lid = extract_labware_id(sel)
        if lid not in labware_ids:
            labware_ids.append(lid)
    validate_labware_on_deck(client, labware_ids)

    tip_capacity = _resolve_tip_capacity(client, tip_pool)

    if multi_dispense:
        per_rep_total = volume_per_replicate + pre_aliquot_volume + post_aliquot_volume
        if per_rep_total > tip_capacity:
            raise ValueError(
                f"volume_per_replicate + pre_aliquot + post_aliquot "
                f"({per_rep_total} µL) exceeds tip capacity {tip_capacity} µL "
                f"for tip pool '{tip_pool}'."
            )
        net_capacity = tip_capacity - pre_aliquot_volume - post_aliquot_volume
    else:
        if volume_per_replicate > tip_capacity:
            raise ValueError(
                f"volume_per_replicate {volume_per_replicate} µL exceeds tip capacity "
                f"{tip_capacity} µL for tip pool '{tip_pool}'."
            )
        net_capacity = tip_capacity  # unused in single-dispense mode

    source_positions = resolve_multi_selector(client, source_plate, well_order=source_order)
    dest_positions = resolve_multi_selector(client, dest_plate, well_order=dest_order)

    all_source_plate_ids = list(dict.fromkeys(p.labware for p in source_positions))
    all_dest_plate_ids = list(dict.fromkeys(p.labware for p in dest_positions))

    if not source_positions:
        return ReplicateSamplesResult(
            iterations=0,
            total_wells_processed=0,
            source_plate_ids=tuple(all_source_plate_ids),
            dest_plate_ids=tuple(all_dest_plate_ids),
            multi_dispense=multi_dispense,
            sources_processed=0,
            replicates_filled=0,
            iteration_results=(),
        )

    total_dest_needed = len(source_positions) * replicates_per_source
    if len(dest_positions) < total_dest_needed:
        raise ValueError(
            f"Destination selectors resolved to {len(dest_positions)} wells "
            f"but {total_dest_needed} are required for {len(source_positions)} "
            f"source wells at replicates_per_source={replicates_per_source}."
        )

    mapping: list[tuple[Position, list[Position]]] = [
        (
            source_positions[i],
            dest_positions[i * replicates_per_source : (i + 1) * replicates_per_source],
        )
        for i in range(len(source_positions))
    ]

    # Batch sizing for multi-dispense uses the shared greedy planner so all
    # three compound commands share one tested batching rule.  Each replicate
    # of a source is a single-well channel-row of ``volume_per_replicate``; the
    # first planned batch's length is the number of replicates that fit one
    # aspiration (capacity-only bound, matching legacy add_reagent behaviour).
    if multi_dispense:
        sizing_rows: list[list[tuple[Position, float]]] = [[(dest, volume_per_replicate)] for dest in mapping[0][1]]
        planned = plan_dispense_batches(sizing_rows, net_capacity)
        reps_per_batch = len(planned[0]) if planned else 1
    else:
        reps_per_batch = 1  # unused in single-dispense mode

    num_sources = len(source_positions)
    tips_needed = num_sources if multi_dispense else num_sources * replicates_per_source
    ensure_tips_available(client, tip_pool, tips_needed, command_name="replicate_samples")

    waste_pos: Position | None = None
    if multi_dispense and pre_aliquot_volume > 0 and pre_aliquot_disposal == PreAliquotDisposal.WASTE:
        waste_pos = resolve_waste_position(client, None)

    profile_scope = client.use_error_profile(error_profile) if error_profile is not None else nullcontext()

    iteration_results: list[ReplicateSamplesIterationResult] = []
    replicates_filled = 0

    with profile_scope:
        if multi_dispense:
            iteration_results, replicates_filled = _run_multi(
                client,
                mapping=mapping,
                channels=channels,
                reps_per_batch=reps_per_batch,
                replicates_per_source=replicates_per_source,
                volume_per_replicate=volume_per_replicate,
                pre_aliquot_volume=pre_aliquot_volume,
                pre_aliquot_disposal=pre_aliquot_disposal,
                post_aliquot_volume=post_aliquot_volume,
                post_aliquot_height=post_aliquot_height,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                optimized_tip_pickup=optimized_tip_pickup,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                waste_pos=waste_pos,
            )
        else:
            iteration_results, replicates_filled = _run_single(
                client,
                mapping=mapping,
                channels=channels,
                volume_per_replicate=volume_per_replicate,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                optimized_tip_pickup=optimized_tip_pickup,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
            )

    return ReplicateSamplesResult(
        iterations=len(iteration_results),
        total_wells_processed=replicates_filled,
        source_plate_ids=tuple(all_source_plate_ids),
        dest_plate_ids=tuple(all_dest_plate_ids),
        multi_dispense=multi_dispense,
        sources_processed=num_sources,
        replicates_filled=replicates_filled,
        iteration_results=tuple(iteration_results),
    )


def _run_multi(
    client: InstrumentClient,
    *,
    mapping: list[tuple[Position, list[Position]]],
    channels: list[int],
    reps_per_batch: int,
    replicates_per_source: int,
    volume_per_replicate: float,
    pre_aliquot_volume: float,
    pre_aliquot_disposal: PreAliquotDisposal,
    post_aliquot_volume: float,
    post_aliquot_height: float,
    liquid_class: str | list[str],
    tip_pool: str,
    optimized_tip_pickup: bool,
    aspirate_settings: AspirateSettings | None,
    dispense_settings: DispenseSettings | None,
    waste_pos: Position | None,
) -> tuple[list[ReplicateSamplesIterationResult], int]:
    """multi-dispense loop: one tip per source, batched replicates per source.

    Sources are processed in channel-row chunks of ``len(channels)``.  Each
    chunk picks up ``len(chunk)`` tips, runs ``ceil(replicates_per_source /
    reps_per_batch)`` aspirate/dispense batches, then ejects.
    """
    n_ch = len(channels)
    # Chunk mapping entries so source chunks never cross a plate boundary.
    src_positions_only = [src for src, _ in mapping]
    chunks: list[list[tuple[Position, list[Position]]]] = []
    offset = 0
    for plate_chunk in chunk_positions_per_plate(src_positions_only, n_ch):
        size = len(plate_chunk)
        chunks.append(mapping[offset : offset + size])
        offset += size
    batches_per_source = math.ceil(replicates_per_source / reps_per_batch)
    iterations: list[ReplicateSamplesIterationResult] = []
    replicates_filled = 0

    if dispense_settings is not None:
        post_settings = dispense_settings.model_copy(update={"fixed_height": post_aliquot_height})
    else:
        post_settings = DispenseSettings(fixed_height=post_aliquot_height)

    for chunk in chunks:
        chunk_sources = [src for src, _ in chunk]
        chunk_dests = [dests for _, dests in chunk]
        active = channels[: len(chunk)]

        per_source_aspirates: list[list[ChannelAspirationResponse]] = [[] for _ in chunk]
        per_source_pre: list[ChannelDispenseResponse | None] = [None for _ in chunk]
        per_source_reps: list[list[ChannelDispenseResponse]] = [[] for _ in chunk]
        per_source_post: list[ChannelDispenseResponse | None] = [None for _ in chunk]

        picked_up = False
        try:
            pickup_resp = pickup_tips(client, active, tip_pool, optimized=optimized_tip_pickup)
            picked_up = True

            for b in range(batches_per_source):
                start = b * reps_per_batch
                batch_reps = min(reps_per_batch, replicates_per_source - start)
                if batch_reps <= 0:
                    break
                batch_asp = volume_per_replicate * batch_reps + pre_aliquot_volume + post_aliquot_volume

                asp_resp = client.aspirate(
                    channels=active,
                    positions=chunk_sources,
                    volumes=batch_asp,
                    liquid_class=liquid_class,
                    settings=slice_settings(aspirate_settings, len(active)),
                )
                for i in range(len(chunk)):
                    per_source_aspirates[i].append(asp_resp)

                if pre_aliquot_volume > 0:
                    if pre_aliquot_disposal == PreAliquotDisposal.WASTE:
                        if waste_pos is None:
                            raise RuntimeError("waste_pos required for WASTE disposal but was not set")
                        pre_targets = [waste_pos] * len(active)
                    else:
                        pre_targets = list(chunk_sources)
                    pre_resp = client.dispense(
                        channels=active,
                        positions=pre_targets,
                        volumes=pre_aliquot_volume,
                        settings=slice_settings(dispense_settings, len(active)),
                    )
                    # Record on the first batch only (pre-aliquot is once per source per batch
                    # but the iteration result keeps a single pre_aliquot_dispense per source).
                    for i in range(len(chunk)):
                        if per_source_pre[i] is None:
                            per_source_pre[i] = pre_resp

                for r in range(batch_reps):
                    dest_row = [chunk_dests[i][start + r] for i in range(len(chunk))]
                    disp_resp = client.dispense(
                        channels=active,
                        positions=dest_row,
                        volumes=volume_per_replicate,
                        settings=slice_settings(dispense_settings, len(active)),
                    )
                    for i in range(len(chunk)):
                        per_source_reps[i].append(disp_resp)
                    replicates_filled += len(chunk)

                if post_aliquot_volume > 0:
                    post_resp = client.dispense(
                        channels=active,
                        positions=list(chunk_sources),
                        volumes=post_aliquot_volume,
                        settings=slice_settings(post_settings, len(active)),
                    )
                    for i in range(len(chunk)):
                        if per_source_post[i] is None:
                            per_source_post[i] = post_resp

            eject_resp = eject_tips(client, active)
            picked_up = False
        finally:
            if picked_up:
                try:
                    eject_tips(client, active)
                except Exception as e:
                    _logger.warning(
                        "Failed to eject tips on channels %s during cleanup: %s.",
                        active,
                        e,
                    )

        for i, (src, dests) in enumerate(chunk):
            iterations.append(
                ReplicateSamplesIterationResult(
                    source_plate_id=src.labware,
                    source_well=src.well,
                    dest_plate_ids=tuple(dict.fromkeys(d.labware for d in dests)) if dests else (src.labware,),
                    dest_wells=tuple(d.well for d in dests),
                    multi_dispense=True,
                    tip_pickup=pickup_resp if i == 0 else None,
                    aspirates=tuple(per_source_aspirates[i]),
                    pre_aliquot_dispense=per_source_pre[i],
                    replicate_dispenses=tuple(per_source_reps[i]),
                    post_aliquot_dispense=per_source_post[i],
                    tip_eject=eject_resp if i == len(chunk) - 1 else None,
                )
            )

    return iterations, replicates_filled


def _chunk_transfers(
    transfers: list[tuple[Position, Position]],
    chunk_size: int,
) -> list[list[tuple[Position, Position]]]:
    """Chunk ``(src, dest)`` transfer pairs, never crossing a plate boundary on either side.

    A new chunk starts when either ``src.labware`` or ``dest.labware`` changes
    from the first element in the current chunk, or when the chunk reaches
    ``chunk_size``.
    """
    if not transfers:
        return []
    chunks: list[list[tuple[Position, Position]]] = []
    current: list[tuple[Position, Position]] = [transfers[0]]
    ref_src_plate = transfers[0][0].labware
    ref_dst_plate = transfers[0][1].labware
    for src, dest in transfers[1:]:
        if src.labware != ref_src_plate or dest.labware != ref_dst_plate or len(current) >= chunk_size:
            chunks.append(current)
            current = [(src, dest)]
            ref_src_plate = src.labware
            ref_dst_plate = dest.labware
        else:
            current.append((src, dest))
    chunks.append(current)
    return chunks


def _run_single(
    client: InstrumentClient,
    *,
    mapping: list[tuple[Position, list[Position]]],
    channels: list[int],
    volume_per_replicate: float,
    liquid_class: str | list[str],
    tip_pool: str,
    optimized_tip_pickup: bool,
    aspirate_settings: AspirateSettings | None,
    dispense_settings: DispenseSettings | None,
) -> tuple[list[ReplicateSamplesIterationResult], int]:
    """single-dispense loop: fresh tip per transfer, batched ``len(channels)`` at a time.

    Transfers are flattened ``(source, dest)`` in source-major order and
    chunked by ``len(channels)``.  Every chunk: pickup → parallel aspirate →
    parallel dispense → eject.  Each individual transfer produces one
    iteration result; aspirate/dispense responses are shared by the
    channels in a chunk.
    """
    transfers: list[tuple[Position, Position]] = [(src, dest) for src, dests in mapping for dest in dests]
    n_ch = len(channels)
    chunks: list[list[tuple[Position, Position]]] = list(_chunk_transfers(transfers, n_ch))
    iterations: list[ReplicateSamplesIterationResult] = []
    replicates_filled = 0

    for chunk in chunks:
        active = channels[: len(chunk)]
        srcs = [s for s, _ in chunk]
        dsts = [d for _, d in chunk]

        pickup_resp: CommandResponse | None = None
        eject_resp: CommandResponse | None = None
        picked_up = False
        try:
            pickup_resp = pickup_tips(client, active, tip_pool, optimized=optimized_tip_pickup)
            picked_up = True
            asp_resp = client.aspirate(
                channels=active,
                positions=srcs,
                volumes=volume_per_replicate,
                liquid_class=liquid_class,
                settings=slice_settings(aspirate_settings, len(active)),
            )
            disp_resp = client.dispense(
                channels=active,
                positions=dsts,
                volumes=volume_per_replicate,
                settings=slice_settings(dispense_settings, len(active)),
            )
            eject_resp = eject_tips(client, active)
            picked_up = False
        finally:
            if picked_up:
                try:
                    eject_tips(client, active)
                except Exception as e:
                    _logger.warning(
                        "Failed to eject tips on channels %s during cleanup: %s.",
                        active,
                        e,
                    )

        for i, (src, dest) in enumerate(chunk):
            iterations.append(
                ReplicateSamplesIterationResult(
                    source_plate_id=src.labware,
                    source_well=src.well,
                    dest_plate_ids=(dest.labware,),
                    dest_wells=(dest.well,),
                    multi_dispense=False,
                    tip_pickup=pickup_resp if i == 0 else None,
                    aspirates=(asp_resp,),
                    pre_aliquot_dispense=None,
                    replicate_dispenses=(disp_resp,),
                    post_aliquot_dispense=None,
                    tip_eject=eject_resp if i == len(chunk) - 1 else None,
                )
            )
        replicates_filled += len(chunk)

    return iterations, replicates_filled
