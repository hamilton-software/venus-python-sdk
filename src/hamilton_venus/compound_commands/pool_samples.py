"""Compound command: ``pool_samples`` — combine N source wells into 1 destination well.

This module implements :func:`execute_pool_samples`, the entry point invoked
by :meth:`hamilton_venus.star_client.StarClient.pool_samples`.  The command
mirrors the conventions of :mod:`hamilton_venus.compound_commands.copy_plate`
and :mod:`hamilton_venus.compound_commands.add_reagent`: selector-string DSL
for source/dest labware, scoped :class:`~hamilton_venus.error_handling.profile.ErrorProfile`,
operator-prompted tip reload via
:attr:`~hamilton_venus.star_client.StarClient.on_tip_reload_prompt`, up-front
labware validation via :func:`validate_labware_on_deck`, and tip-aware volume
sanity via :func:`_resolve_tip_capacity`.
"""

from __future__ import annotations

import logging
import math
from contextlib import nullcontext
from typing import TYPE_CHECKING

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    emit_final_mix,
    mix_cycles_active,
    override_mix_cycles,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._multi_plate import (
    chunk_positions_per_plate,
    extract_labware_id,
    normalize_selector_list,
    resolve_multi_selector,
)
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import eject_tips, ensure_tips_available, pickup_tips
from hamilton_venus.compound_commands._helpers._transfer_plan import validate_labware_on_deck
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import PoolSamplesIterationResult, PoolSamplesResult
from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
    from hamilton_venus.models.position import Position

_logger = logging.getLogger(__name__)


def execute_pool_samples(
    client: InstrumentClient,
    *,
    source_plate: str | list[str] | Position | list[Position],
    dest_plate: str | list[str] | Position | list[Position],
    pool_size: int,
    volume_per_source: float,
    liquid_class: str | list[str],
    tip_pool: str,
    channels: list[int] | None = None,
    source_order: WellOrder = WellOrder.COL_ASC,
    dest_order: WellOrder = WellOrder.COL_ASC,
    mix_after_pool: bool = True,
    reuse_tips_within_pool: bool = False,
    optimized_tip_pickup: bool = True,
    aspirate_settings: AspirateSettings | None = None,
    dispense_settings: DispenseSettings | None = None,
    error_profile: ErrorProfile | None = None,
) -> PoolSamplesResult:
    """Combine ``N`` source wells into one destination well, iterating across pools.

    Each pool consumes ``pool_size`` source wells (the final pool may be
    shorter if the source count is not a multiple of ``pool_size``) and
    dispenses their aspirated contents into a single destination well.
    Multiple channels are exploited to process a pool's source wells in
    ``len(channels)`` -sized rows.

    Args:
        client: Connected instrument client used to issue hardware commands.
        source_plate: Source-plate selector string or a list of selectors
            spanning multiple plates (e.g. ``["PlateA@col:1", "PlateB@col:1"]``).
            May also be a pre-resolved ``Position``/``list[Position]``.
        dest_plate: Destination-plate selector string or a list of selectors
            spanning multiple plates. May also be a pre-resolved
            ``Position``/``list[Position]``.
        pool_size: Number of source wells combined into each destination well.
            Must be ``>= 1``.
        volume_per_source: Per-channel aspirate/dispense volume in µL applied
            to each source well in the pool.  Must be ``> 0`` and not exceed
            the tip capacity of *tip_pool*.
        liquid_class: Liquid class name(s) forwarded to the aspirate step.
        tip_pool: Name of the tip-rack to draw tips from.  Required.
        channels: 1-indexed channel numbers to use (default 1-8).
        source_order: Traversal order for source wells.  Defaults to
            ``COL_ASC`` (column-major ascending).
        dest_order: Traversal order for destination wells.  Defaults to
            ``COL_ASC``.
        mix_after_pool: When ``True`` (default), per-source dispenses are
            issued with ``mix_cycles=0`` and a single trailing zero-volume
            dispense applies the caller's ``mix_cycles`` / ``mix_volume`` /
            ``mix_position`` to the destination well.  When the caller's
            ``mix_cycles`` is unset or ``0`` the trailing mix is skipped.
            When ``False``, per-source dispenses retain the caller-supplied
            mix settings.
        reuse_tips_within_pool: When ``True``, a single tip pickup serves all
            source wells of one pool (tips are ejected after the pool
            completes).  When ``False`` (default), tips are changed between
            channel-row chunks within a pool, matching the spec's
            "change tip between sources" semantics.
        optimized_tip_pickup: Forwarded to :func:`pickup_tips`.
        aspirate_settings: Optional aspirate settings forwarded to each
            aspirate call (sliced per channel-row).
        dispense_settings: Optional dispense settings forwarded to each
            dispense call (sliced per channel-row).  Mix-related fields are
            overridden per the ``mix_after_pool`` rules above.
        error_profile: When provided, all liquid-handling steps run inside
            ``client.use_error_profile(error_profile)``.

    Returns:
        A :class:`PoolSamplesResult` recording every aspirate, dispense, tip
        pickup, tip eject, and optional final mix per pool.

    Raises:
        ValueError: If validation fails — empty ``tip_pool``, ``pool_size < 1``,
            ``volume_per_source <= 0``, ``volume_per_source`` exceeds tip
            capacity, source/dest labware missing on the deck, destination
            plate too small to hold one well per pool, or insufficient tips
            with no operator-reload callback configured.
        OperatorCancelledError: Operator cancelled the tip-reload prompt.
    """
    if not tip_pool or not tip_pool.strip():
        raise ValueError("tip_pool must be a non-empty string.")
    tip_pool = tip_pool.strip()
    if pool_size < 1:
        raise ValueError(f"pool_size must be >= 1, got {pool_size}.")
    if volume_per_source <= 0:
        raise ValueError(f"volume_per_source must be > 0, got {volume_per_source}.")

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
    if volume_per_source > tip_capacity:
        raise ValueError(
            f"volume_per_source {volume_per_source} µL exceeds tip capacity "
            f"{tip_capacity} µL for tip pool '{tip_pool}'."
        )

    source_positions = resolve_multi_selector(client, source_plate, well_order=source_order)
    dest_positions = resolve_multi_selector(client, dest_plate, well_order=dest_order)

    all_source_plate_ids = list(dict.fromkeys(p.labware for p in source_positions))
    all_dest_plate_ids = list(dict.fromkeys(p.labware for p in dest_positions))

    if not source_positions:
        return PoolSamplesResult(
            iterations=0,
            total_wells_processed=0,
            source_plate_ids=tuple(all_source_plate_ids),
            dest_plate_ids=tuple(all_dest_plate_ids),
            pools_completed=0,
            wells_pooled=0,
            mix_after_pool=mix_after_pool,
            reuse_tips_within_pool=reuse_tips_within_pool,
            iteration_results=(),
        )

    num_pools = math.ceil(len(source_positions) / pool_size)
    if len(dest_positions) < num_pools:
        raise ValueError(
            f"Destination selectors resolved to {len(dest_positions)} wells "
            f"but {num_pools} are required for {len(source_positions)} source wells "
            f"at pool_size={pool_size}."
        )

    pools: list[list[Position]] = [source_positions[i * pool_size : (i + 1) * pool_size] for i in range(num_pools)]

    ch_count = len(channels)
    do_final_mix = mix_after_pool and mix_cycles_active(dispense_settings)

    if reuse_tips_within_pool:
        tips_needed = sum(min(ch_count, len(p)) for p in pools)
    else:
        tips_needed = sum(len(p) for p in pools)
        if do_final_mix:
            tips_needed += num_pools
    ensure_tips_available(client, tip_pool, tips_needed, command_name="pool_samples")

    profile_scope = client.use_error_profile(error_profile) if error_profile is not None else nullcontext()

    iteration_results: list[PoolSamplesIterationResult] = []
    wells_pooled = 0
    disp_for_pool = override_mix_cycles(dispense_settings, 0) if mix_after_pool else dispense_settings

    with profile_scope:
        for pool_idx, pool_sources in enumerate(pools):
            dest_pos = dest_positions[pool_idx]
            tip_pickups: list[CommandResponse] = []
            aspirates: list[ChannelAspirationResponse] = []
            dispenses: list[ChannelDispenseResponse] = []
            tip_ejects: list[CommandResponse] = []
            mix_after_resp: ChannelDispenseResponse | None = None

            row_chunks: list[list[Position]] = list(chunk_positions_per_plate(pool_sources, ch_count))

            if reuse_tips_within_pool:
                pool_pickup_channels = channels[: min(ch_count, len(pool_sources))]
                tip_pickups.append(pickup_tips(client, pool_pickup_channels, tip_pool, optimized=optimized_tip_pickup))
                try:
                    for row in row_chunks:
                        row_channels = channels[: len(row)]
                        sliced_asp = slice_settings(aspirate_settings, len(row))
                        sliced_disp = slice_settings(disp_for_pool, len(row))
                        aspirates.append(
                            client.aspirate(
                                channels=row_channels,
                                positions=row,
                                volumes=volume_per_source,
                                liquid_class=liquid_class,
                                settings=sliced_asp,
                            )
                        )
                        dispenses.append(
                            client.dispense(
                                channels=row_channels,
                                positions=[dest_pos] * len(row),
                                volumes=volume_per_source,
                                settings=sliced_disp,
                            )
                        )
                    if do_final_mix:
                        mix_after_resp = emit_final_mix(
                            client,
                            dest_pos,
                            channels[:1],
                            dispense_settings,
                        )
                finally:
                    try:
                        tip_ejects.append(eject_tips(client, pool_pickup_channels))
                    except Exception as _e:
                        _logger.warning(
                            "Failed to eject tips on channels %s during cleanup: %s.",
                            pool_pickup_channels,
                            _e,
                        )
            else:
                for row in row_chunks:
                    row_channels = channels[: len(row)]
                    tip_pickups.append(pickup_tips(client, row_channels, tip_pool, optimized=optimized_tip_pickup))
                    try:
                        sliced_asp = slice_settings(aspirate_settings, len(row))
                        sliced_disp = slice_settings(disp_for_pool, len(row))
                        aspirates.append(
                            client.aspirate(
                                channels=row_channels,
                                positions=row,
                                volumes=volume_per_source,
                                liquid_class=liquid_class,
                                settings=sliced_asp,
                            )
                        )
                        dispenses.append(
                            client.dispense(
                                channels=row_channels,
                                positions=[dest_pos] * len(row),
                                volumes=volume_per_source,
                                settings=sliced_disp,
                            )
                        )
                    finally:
                        try:
                            tip_ejects.append(eject_tips(client, row_channels))
                        except Exception as _e:
                            _logger.warning(
                                "Failed to eject tips on channels %s during cleanup: %s.",
                                row_channels,
                                _e,
                            )
                if do_final_mix:
                    mix_channels = channels[:1]
                    tip_pickups.append(pickup_tips(client, mix_channels, tip_pool, optimized=optimized_tip_pickup))
                    try:
                        mix_after_resp = emit_final_mix(
                            client,
                            dest_pos,
                            mix_channels,
                            dispense_settings,
                        )
                    finally:
                        try:
                            tip_ejects.append(eject_tips(client, mix_channels))
                        except Exception as _e:
                            _logger.warning(
                                "Failed to eject tips on channels %s during cleanup: %s.",
                                mix_channels,
                                _e,
                            )

            iteration_results.append(
                PoolSamplesIterationResult(
                    source_plate_ids=tuple(dict.fromkeys(p.labware for p in pool_sources)),
                    dest_plate_id=dest_pos.labware,
                    dest_well=dest_pos.well,
                    source_wells=tuple(p.well for p in pool_sources),
                    pool_size=len(pool_sources),
                    tip_pickups=tuple(tip_pickups),
                    aspirates=tuple(aspirates),
                    dispenses=tuple(dispenses),
                    mix_after=mix_after_resp,
                    tip_ejects=tuple(tip_ejects),
                )
            )
            wells_pooled += len(pool_sources)

    return PoolSamplesResult(
        iterations=len(iteration_results),
        total_wells_processed=wells_pooled,
        source_plate_ids=tuple(all_source_plate_ids),
        dest_plate_ids=tuple(all_dest_plate_ids),
        pools_completed=len(iteration_results),
        wells_pooled=wells_pooled,
        mix_after_pool=mix_after_pool,
        reuse_tips_within_pool=reuse_tips_within_pool,
        iteration_results=tuple(iteration_results),
    )
