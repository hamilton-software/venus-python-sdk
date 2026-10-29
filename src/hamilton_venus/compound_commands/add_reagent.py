"""``add_reagent`` compound command implementation.

This module provides :func:`execute_add_reagent`, the entry point used by
:meth:`hamilton_venus.star_client.StarClient.add_reagent`, along with the
internal helpers that support it: the per-source-block runners
(:func:`_run_single_dispense`, :func:`_run_multi_dispense`).  CSV
parsing/grouping primitives live in
:mod:`hamilton_venus.compound_commands._helpers._transfer_plan`; tip-capacity
resolution lives in :mod:`hamilton_venus.compound_commands._helpers._tip_capacity`;
waste-position resolution lives in
:mod:`hamilton_venus.compound_commands._helpers._waste`.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    resolve_selector_positions,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._liquid_manager import (
    LiquidSourceTracker,
    connected_source_labware,
    expand_connected_sources,
    lld_enabled,
)
from hamilton_venus.compound_commands._helpers._multi_dispense import plan_dispense_batches
from hamilton_venus.compound_commands._helpers._multi_plate import (
    extract_labware_id,
    normalize_selector_list,
    resolve_multi_selector,
    split_positions_by_plate,
)
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import (
    eject_tips,
    ensure_tips_available,
    pickup_tips,
)
from hamilton_venus.compound_commands._helpers._transfer_plan import (
    TransferRow,
    _parse_transfer_csv,
    _validate_row_volumes_in_range,
    validate_labware_on_deck,
)
from hamilton_venus.compound_commands._helpers._waste import resolve_waste_position
from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
from hamilton_venus.models.compound_results import (
    AddReagentIterationResult,
    AddReagentResult,
    AddReagentWellDispense,
)
from hamilton_venus.models.enums import PreAliquotDisposal
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile

_logger = logging.getLogger(__name__)


def _plan_dest_runs(rows: list[TransferRow]) -> list[list[TransferRow]]:
    """Split *rows* into consecutive same-destination-plate runs, keeping CSV order."""
    runs: list[list[TransferRow]] = []
    for row in rows:
        if runs and runs[-1][-1].dest_labware == row.dest_labware:
            runs[-1].append(row)
        else:
            runs.append([row])
    return runs


def _broadcast_selector_list(
    value: str | list[str] | Position | list[Position],
) -> list[str | Position | list[Position]]:
    """Like :func:`normalize_selector_list`, but for the Q5 broadcast-pairing
    step specifically: a ``list[Position]`` is the pre-resolved equivalent of
    ONE selector (what a single ``"Plate@all"``-style string would expand
    to via ``normalize_positions``), not N independent selectors to
    broadcast/pair individually.

    ``normalize_selector_list`` itself must keep passing a ``list[Position]``
    through element-by-element -- its other caller here (the up-front
    labware-presence validation, which calls ``extract_labware_id`` per
    element) and its callers in ``pool_samples``/``replicate_samples`` all
    rely on that flat shape. Only the broadcast pairing below needs the
    list treated as one unit, so that distinction lives here instead of in
    the shared helper.

    Without this, passing ``dest_plate=normalize_positions("Plate@all",
    total_wells=N)`` (a documented, supported input form) would explode into
    N separate one-well runs, each capping every tip pickup/aspirate/dispense
    to a single channel instead of batching up to ``len(channels)`` wells per
    stroke.
    """
    if isinstance(value, (str, Position)):
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, Position) for item in value):
        return [cast("list[Position]", value)]
    return list(value)


def _pick(value: object, indices: list[int]) -> object:
    """Select *indices* from a per-channel list; scalars (and short lists) pass through."""
    if isinstance(value, list) and indices and max(indices) < len(value):
        return [value[i] for i in indices]
    return value


def _settings_for(settings: Any, indices: list[int]) -> Any:
    """Return *settings* with every per-channel list narrowed to *indices* of the stroke."""
    if settings is None or not isinstance(settings, BaseModel):
        return settings
    updates = {
        name: _pick(getattr(settings, name), indices)
        for name in type(settings).model_fields
        if isinstance(getattr(settings, name), list)
    }
    return settings.model_copy(update=updates) if updates else settings


def _merge_aspirations(responses: list[ChannelAspirationResponse]) -> ChannelAspirationResponse:
    """Combine the responses of one stroke's aspirate passes into one response."""
    if len(responses) == 1:
        return responses[0]
    first = responses[0]
    channels = [ch for resp in responses for ch in resp.return_parameters.channels]
    params = first.return_parameters.model_copy(update={"channels": channels})
    return first.model_copy(update={"return_parameters": params})


def _aspirate_source(
    client: InstrumentClient,
    tracker: LiquidSourceTracker,
    *,
    channels: list[int],
    volumes: list[float],
    liquid_class: str | list[str],
    settings: AspirateSettings | None,
) -> tuple[ChannelAspirationResponse, list[tuple[list[int], list[Position]]]]:
    """Aspirate *volumes* (one per channel) from the tracker's active source.

    A reservoir has fewer sections than a 16-channel head has channels, so the
    tracker may split the stroke into passes (channels 1-8 at sections 1-8, then
    channels 9-16 at sections 1-8 again).  Returns the merged response and the
    passes, which pre/post-aliquot returns to the source reuse.
    """
    passes = tracker.aspirate_passes(channels)
    responses = []
    for pass_channels, positions in passes:
        indices = [channels.index(ch) for ch in pass_channels]
        pass_volumes = [volumes[i] for i in indices]
        responses.append(
            client.aspirate(
                channels=pass_channels,
                positions=positions,
                volumes=pass_volumes[0] if len(set(pass_volumes)) == 1 else pass_volumes,
                liquid_class=_pick(liquid_class, indices),  # type: ignore[arg-type]
                settings=_settings_for(settings, indices),
            )
        )
    response = _merge_aspirations(responses)
    tracker.record_aspirate(response, measured_level=lld_enabled(settings))
    return response, passes


def _dispense_to_source(
    client: InstrumentClient,
    passes: list[tuple[list[int], list[Position]]],
    *,
    channels: list[int],
    volume: float,
    settings: DispenseSettings | None,
) -> ChannelDispenseResponse:
    """Dispense *volume* from every channel back into the source, pass by pass."""
    response = None
    for pass_channels, positions in passes:
        indices = [channels.index(ch) for ch in pass_channels]
        response = client.dispense(
            channels=pass_channels,
            positions=positions,
            volumes=volume,
            settings=_settings_for(settings, indices),
        )
    assert response is not None
    return response


def _dispense_pre_aliquot(
    client: InstrumentClient,
    passes: list[tuple[list[int], list[Position]]],
    *,
    channels: list[int],
    volume: float,
    disposal: PreAliquotDisposal,
    waste_pos: Position | None,
    settings: DispenseSettings | None,
) -> ChannelDispenseResponse:
    if disposal == PreAliquotDisposal.WASTE:
        if waste_pos is None:
            raise RuntimeError("waste_pos required for WASTE disposal but was not set")
        return client.dispense(
            channels=channels,
            positions=[waste_pos] * len(channels),
            volumes=volume,
            settings=slice_settings(settings, len(channels)),
        )
    return _dispense_to_source(client, passes, channels=channels, volume=volume, settings=settings)


def _dispense_post_aliquot(
    client: InstrumentClient,
    passes: list[tuple[list[int], list[Position]]],
    *,
    channels: list[int],
    volume: float,
    height: float,
    settings: DispenseSettings | None,
) -> ChannelDispenseResponse:
    base = settings or DispenseSettings()
    post_settings = base.model_copy(update={"fixed_height": height})
    return _dispense_to_source(client, passes, channels=channels, volume=volume, settings=post_settings)


def _run_multi_dispense(
    client: InstrumentClient,
    *,
    source_groups: list[list[Position]],
    dest_pairs: list[tuple[Position, float]],
    net_capacity: float,
    pre_aliquot_volume: float,
    pre_aliquot_disposal: PreAliquotDisposal,
    waste_pos: Position | None,
    post_aliquot_volume: float,
    post_aliquot_height: float,
    liquid_class: str | list[str],
    channels: list[int],
    tip_pool: str,
    optimized_tip_pickup: bool,
    aspirate_settings: AspirateSettings | None,
    dispense_settings: DispenseSettings | None,
    reuse_tips: bool = False,
) -> tuple[list[AddReagentIterationResult], int, dict[str, int], list[str], list[Position]]:
    """Execute the multi-dispense loop for a single source block.

    Tips are picked up **once** before the first aspiration and ejected **once**
    after all wells have been dispensed.  Batches are formed greedily: rows are
    accumulated until the next row would exceed *net_capacity*, then the batch
    is flushed as one aspiration.  Pre- and post-aliquot steps run once per
    aspiration batch.

    Each channel aspirates exactly what it will dispense in the batch (the sum of
    its wells' volumes) plus the aliquots, so variable CSV volumes leave nothing
    behind in the tip.

    When *reuse_tips* is ``True`` the caller has already mounted a shared tip set
    for the whole command, so pickup/eject are skipped here.  The channels share
    the active source group's positions, in passes when there are more channels
    than positions (see ``LiquidSourceTracker.aspirate_passes``).

    This generalises over both the uniform-volume (non-CSV) case — where every
    row has the same volume and greedy batching produces the same batch sizes as
    ``floor(net_capacity / volume)`` — and the CSV variable-volume case.

    *source_groups* are the reagent sources in drain order, one per
    ``reagent_source`` selector (consumable liquid management).  A
    :class:`~hamilton_venus.compound_commands._helpers._liquid_manager.LiquidSourceTracker`
    advances to the next group when the active one is exhausted, carrying the
    depletion estimate across every aspiration in this block.

    Args:
        dest_pairs: Ordered ``(dest_pos, volume)`` pairs for this source block.
        net_capacity: ``tip_capacity - pre_aliquot_volume - post_aliquot_volume``.
            Each batch's total reagent volume must not exceed this value.

    Returns:
        A 5-tuple of ``(iteration_results, wells_filled,
        wells_filled_by_plate, dest_plate_ids, sources_used)``.
    """
    iterations: list[AddReagentIterationResult] = []
    wells_filled = 0
    wells_filled_by_plate: dict[str, int] = {}
    dest_plate_ids: list[str] = []
    tracker = LiquidSourceTracker.from_groups(source_groups)

    if not dest_pairs:
        return iterations, wells_filled, wells_filled_by_plate, dest_plate_ids, tracker.sources_used

    # Build greedy batches: accumulate channel-rows until the next row would
    # exceed net_capacity, then start a new batch.  Each channel-row is a
    # slice of len(channels) destination wells that are dispensed in one
    # simultaneous dispense call.  The capacity check uses only the *per-
    # channel* volume for that row (the maximum across the slice for variable-
    # volume CSV runs), which bounds what any one channel aspirates.
    n_ch = len(channels)
    channel_rows: list[list[tuple[Position, float]]] = [
        dest_pairs[i : i + n_ch] for i in range(0, len(dest_pairs), n_ch)
    ]

    batches = plan_dispense_batches(channel_rows, net_capacity)

    # One pickup before the first aspiration; ejected after the last.  Only as
    # many channels as the widest row are used.
    active = channels[: min(n_ch, len(dest_pairs))]

    picked_up = False
    try:
        pickup_resp = None
        if not reuse_tips:
            pickup_resp = pickup_tips(client, active, tip_pool, optimized=optimized_tip_pickup)
            picked_up = True

        for batch_idx, batch in enumerate(batches):
            is_first = batch_idx == 0
            is_last = batch_idx == len(batches) - 1

            # Per channel: the sum of the volumes it dispenses in this batch, plus aliquots.
            batch_channels = channels[: max(len(row) for row in batch)]
            asp_volumes = [
                sum(row[i][1] for row in batch if i < len(row)) + pre_aliquot_volume + post_aliquot_volume
                for i in range(len(batch_channels))
            ]

            # Resolve the source for this batch through the consumable-liquid-management
            # tracker: it advances to the next source position when the active one is
            # exhausted, carrying the depletion estimate across batches.
            batch_source, _budget = tracker.ensure_available(
                client,
                max(asp_volumes),
                command_name="add_reagent",
            )
            asp_resp, passes = _aspirate_source(
                client,
                tracker,
                channels=batch_channels,
                volumes=asp_volumes,
                liquid_class=liquid_class,
                settings=aspirate_settings,
            )

            pre_resp = None
            if pre_aliquot_volume > 0:
                pre_resp = _dispense_pre_aliquot(
                    client,
                    passes,
                    channels=batch_channels,
                    volume=pre_aliquot_volume,
                    disposal=pre_aliquot_disposal,
                    waste_pos=waste_pos,
                    settings=dispense_settings,
                )

            # Dispense to each channel-row in the batch (one call per row)
            well_dispenses: list[AddReagentWellDispense] = []
            for row in batch:
                row_active = channels[: len(row)]
                row_vols = [v for _, v in row]
                uniform = len(set(row_vols)) == 1
                disp_resp = client.dispense(
                    channels=row_active,
                    positions=[p for p, _ in row],
                    volumes=row_vols[0] if uniform else row_vols,
                    settings=slice_settings(dispense_settings, len(row_active)),
                )
                # Reagent leaving the source toward destinations depletes the
                # active source estimate (per-channel max, matching the aspirate).
                tracker.consume(max(row_vols))
                for dest_pos, _ in row:
                    well_dispenses.append(
                        AddReagentWellDispense(
                            dest_plate_id=dest_pos.labware,
                            dest_well=dest_pos.well,
                            response=disp_resp,
                        )
                    )
                    if dest_pos.labware not in dest_plate_ids:
                        dest_plate_ids.append(dest_pos.labware)
                    wells_filled_by_plate[dest_pos.labware] = wells_filled_by_plate.get(dest_pos.labware, 0) + 1

            post_resp = None
            if post_aliquot_volume > 0:
                post_resp = _dispense_post_aliquot(
                    client,
                    passes,
                    channels=batch_channels,
                    volume=post_aliquot_volume,
                    height=post_aliquot_height,
                    settings=dispense_settings,
                )

            # Eject only on the last batch (unless the caller owns the tips)
            eject_resp = None
            if is_last and not reuse_tips:
                eject_resp = eject_tips(client, active)
                picked_up = False

            iterations.append(
                AddReagentIterationResult(
                    source_plate_id=batch_source.labware,
                    tip_pickup=pickup_resp if is_first else None,
                    aspirate=asp_resp,
                    pre_aliquot_dispense=pre_resp,
                    well_dispenses=tuple(well_dispenses),
                    post_aliquot_dispense=post_resp,
                    tip_eject=eject_resp,
                )
            )
            wells_filled += sum(len(row) for row in batch)

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

    return iterations, wells_filled, wells_filled_by_plate, dest_plate_ids, tracker.sources_used


def _run_single_dispense(
    client: InstrumentClient,
    *,
    source_groups: list[list[Position]],
    dest_pairs: list[tuple[Position, float]],
    pre_aliquot_volume: float,
    pre_aliquot_disposal: PreAliquotDisposal,
    waste_pos: Position | None,
    post_aliquot_volume: float,
    post_aliquot_height: float,
    liquid_class: str | list[str],
    channels: list[int],
    tip_pool: str,
    optimized_tip_pickup: bool,
    aspirate_settings: AspirateSettings | None,
    dispense_settings: DispenseSettings | None,
    reuse_tips: bool = False,
) -> tuple[list[AddReagentIterationResult], int, dict[str, int], list[str], list[Position]]:
    """Execute the single-dispense loop for a single source block.

    Tips are picked up and ejected once per channel-sized chunk of
    destination wells.  Each channel aspirates its own well's volume (from the
    transfer CSV when one is used, never the command-level default in its place)
    plus the pre/post aliquots, and all channels dispense in one call.

    When *reuse_tips* is ``True`` the runner assumes the caller has already
    mounted the tips and does **not** pick up or eject within this block.

    The channels share the active source group's positions, in passes when there
    are more channels than positions (see ``LiquidSourceTracker.aspirate_passes``).

    *source_groups* are the reagent sources in drain order, one per
    ``reagent_source`` selector (consumable liquid management).  A single
    :class:`~hamilton_venus.compound_commands._helpers._liquid_manager.LiquidSourceTracker`
    is created for the whole block so the depletion estimate carries across
    chunks and the next group is used once the active one is exhausted.

    Returns:
        A 5-tuple of ``(iteration_results, wells_filled,
        wells_filled_by_plate, dest_plate_ids, sources_used)``.
    """
    iterations: list[AddReagentIterationResult] = []
    wells_filled = 0
    wells_filled_by_plate: dict[str, int] = {}
    dest_plate_ids: list[str] = []
    tracker = LiquidSourceTracker.from_groups(source_groups)

    if not dest_pairs:
        return iterations, wells_filled, wells_filled_by_plate, dest_plate_ids, tracker.sources_used

    for offset in range(0, len(dest_pairs), len(channels)):
        chunk = dest_pairs[offset : offset + len(channels)]
        active = channels[: len(chunk)]

        picked_up = False
        try:
            # Tip pickup.  When reuse_tips is set the caller has already mounted a
            # shared tip set for the whole command, so skip pickup/eject here.
            pickup_resp = None
            if not reuse_tips:
                # Mid-run tip check (catches depletion between chunks)
                ensure_tips_available(client, tip_pool, len(active), command_name="add_reagent")
                pickup_resp = pickup_tips(client, active, tip_pool, optimized=optimized_tip_pickup)
                picked_up = True

            chunk_vols = [v for _, v in chunk]
            asp_volumes = [v + pre_aliquot_volume + post_aliquot_volume for v in chunk_vols]
            # Resolve the source for this chunk; the tracker advances to the next
            # source position once the active one is exhausted.
            chunk_source, _budget = tracker.ensure_available(
                client,
                max(asp_volumes),
                command_name="add_reagent",
            )
            asp_resp, passes = _aspirate_source(
                client,
                tracker,
                channels=active,
                volumes=asp_volumes,
                liquid_class=liquid_class,
                settings=aspirate_settings,
            )

            pre_resp = None
            if pre_aliquot_volume > 0:
                pre_resp = _dispense_pre_aliquot(
                    client,
                    passes,
                    channels=active,
                    volume=pre_aliquot_volume,
                    disposal=pre_aliquot_disposal,
                    waste_pos=waste_pos,
                    settings=dispense_settings,
                )

            # Main dispense: every channel its own well and volume, in one call.
            uniform = len(set(chunk_vols)) == 1
            disp_resp = client.dispense(
                channels=active,
                positions=[p for p, _ in chunk],
                volumes=chunk_vols[0] if uniform else chunk_vols,
                settings=slice_settings(dispense_settings, len(active)),
            )
            # Reagent leaving the source toward destinations depletes the active
            # source estimate (per-channel max, matching the largest aspirate).
            tracker.consume(max(chunk_vols))
            well_dispenses: list[AddReagentWellDispense] = []
            for dest_pos, _ in chunk:
                well_dispenses.append(
                    AddReagentWellDispense(
                        dest_plate_id=dest_pos.labware,
                        dest_well=dest_pos.well,
                        response=disp_resp,
                    )
                )
                if dest_pos.labware not in dest_plate_ids:
                    dest_plate_ids.append(dest_pos.labware)
                wells_filled_by_plate[dest_pos.labware] = wells_filled_by_plate.get(dest_pos.labware, 0) + 1

            post_resp = None
            if post_aliquot_volume > 0:
                post_resp = _dispense_post_aliquot(
                    client,
                    passes,
                    channels=active,
                    volume=post_aliquot_volume,
                    height=post_aliquot_height,
                    settings=dispense_settings,
                )

            eject_resp = None
            if not reuse_tips:
                eject_resp = eject_tips(client, active)
                picked_up = False

            iterations.append(
                AddReagentIterationResult(
                    source_plate_id=chunk_source.labware,
                    tip_pickup=pickup_resp,
                    aspirate=asp_resp,
                    pre_aliquot_dispense=pre_resp,
                    well_dispenses=tuple(well_dispenses),
                    post_aliquot_dispense=post_resp,
                    tip_eject=eject_resp,
                )
            )
            wells_filled += len(chunk)

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

    return iterations, wells_filled, wells_filled_by_plate, dest_plate_ids, tracker.sources_used


def execute_add_reagent(
    client: InstrumentClient,
    *,
    reagent_source: str | list[str] | Position | list[Position],
    dest_plate: str | list[str] | Position | list[Position],
    volume: float,
    liquid_class: str | list[str],
    tip_pool: str,
    multi_dispense: bool = False,
    pre_aliquot_volume: float = 0.0,
    pre_aliquot_disposal: PreAliquotDisposal = PreAliquotDisposal.SOURCE,
    post_aliquot_volume: float = 0.0,
    post_aliquot_height: float = 5.0,
    channels: list[int] | None = None,
    optimized_tip_pickup: bool = True,
    reuse_tips: bool = False,
    aspirate_settings: AspirateSettings | None = None,
    dispense_settings: DispenseSettings | None = None,
    error_profile: ErrorProfile | None = None,
    transfer_csv: str | None = None,
    follow_csv_order: bool = False,
) -> AddReagentResult:
    """Transfer reagent from one or more source containers to multiple destination wells.

    Every channel is used on the reagent: the channels are spread across the
    positions *reagent_source* selects, in passes when there are more channels
    than positions ("Tubes@1" -- every channel in turn at tube 1; "Tubes@1:4" --
    channels 1-4 at tubes 1-4, then 5-8 at tubes 1-4).  A reservoir counts as one
    well: any section of it means all of its sections.  With a worklist, a list of
    such selectors is drained in order as each runs out (*consumable liquid
    management*: depletion is tracked from LLD-measured aspirates, and an operator
    reload is prompted -- or, with no prompt configured, the shortage is traced and
    the run continues -- only when every source is short).

    Supports two dispense distribution strategies controlled by *multi_dispense*:

    - **single-dispense mode** (``multi_dispense=False``, default): each destination well
      receives its own aspiration.  Pre- and post-aliquot volumes are included in
      each aspiration; tips are picked up and ejected per channel-sized chunk.
    - **multi-dispense mode** (``multi_dispense=True``): tips are picked up once; each
      aspiration covers as many wells as the tip capacity allows (computed
      automatically from the tip type assigned to *tip_pool*).  Pre- and
      post-aliquot steps run once per aspiration.  Tips are ejected after all
      destination wells have been filled.

    Args:
        client: Connected :class:`~hamilton_venus.star_client.StarClient`.
        reagent_source: Selector for the source container(s), e.g.
            ``"Tubes@1:4"``, ``"ReagentTrough"`` or ``"Source1@1"``.  The
            channels are spread across every position one selector resolves
            to (see above).  With *transfer_csv*, a list is drained in order,
            each entry being one source: ``["Tubes@1", "Tubes@2", "Tubes@3"]``
            uses tube 1 (every channel in turn) until it runs low, then tube 2,
            then 3; ``["Tubes@1:4", "Tubes@5:8"]`` uses tubes 1-4 together, then
            5-8.  Moving on needs an LLD-measured level.  Without
            *transfer_csv*, a list is paired with *dest_plate* (see
            ``Multi-Plate Selectors``).
            May also be a pre-resolved ``Position``/``list[Position]`` (e.g.
            from ``normalize_positions``) instead of a selector string.
        dest_plate: Selector string for the destination labware/wells, e.g.
            ``"Plate1@col:1,3:5"`` or ``"Plate1"``.  May also be a
            pre-resolved ``Position``/``list[Position]`` instead of a
            selector string.
        volume: Volume (µL) to dispense per destination well.  Must be > 0.
        liquid_class: Liquid-class name(s) forwarded to the aspirate step. Required.
        tip_pool: Name of the tip pool to draw tips from (required).
        multi_dispense: When ``True``, use multi-dispense mode (one tip pickup
            per source block, multiple wells per aspiration).
        pre_aliquot_volume: Extra volume aspirated before the main volume.
            Set to 0.0 to skip.  Disposed according to *pre_aliquot_disposal*.
        pre_aliquot_disposal: Where to send the pre-aliquot.
            ``SOURCE`` (default) returns it to the source; ``WASTE`` sends it
            to the ``liquid_waste`` labware on the deck.
        post_aliquot_volume: Extra volume aspirated after the main volume and
            re-dispensed back to the source at *post_aliquot_height*.
        post_aliquot_height: Fixed height (mm) for the post-aliquot re-dispense.
        channels: 1-indexed channel numbers (default 1-8).
        optimized_tip_pickup: Pass through to tip-pickup command.
        reuse_tips: When ``True`` a single tip set is picked up once and reused
            for the entire command (all source runs and chunks), then ejected at
            the end.  Because the same reagent is transferred throughout, this is
            safe and minimises tip usage.  When ``False`` (default) tips are
            changed per channel-sized chunk (single-dispense) or per source run
            (multi-dispense).
        aspirate_settings: Optional aspirate settings forwarded to aspirate calls.
        dispense_settings: Optional dispense settings forwarded to dispense calls.
            For post-aliquot dispenses the ``fixed_height`` field is overridden
            with *post_aliquot_height*.
        error_profile: When provided, all liquid-handling steps run inside
            ``client.use_error_profile(error_profile)``.
        transfer_csv: Optional path to a worklist CSV saying where the reagent
            goes and how much.  Columns: ``dest_labware``, ``dest_well``,
            ``volume``; a missing ``dest_labware`` or ``volume`` falls back to
            *dest_plate* / *volume*.  The reagent always comes from
            *reagent_source* -- ``source_labware`` / ``source_well`` columns
            are ignored (with a warning), so a hit-picking worklist can be
            reused as-is.
        follow_csv_order: Only relevant when *transfer_csv* is provided.
            When ``False`` (default), rows are grouped by destination plate.
            When ``True``, consecutive rows for the same plate are kept
            together in original CSV order, but plates are not globally merged
            -- an A->B->A pattern produces three runs rather than two.

    Returns:
        :class:`~hamilton_venus.models.compound_results.AddReagentResult`
        summarising iterations, wells filled, and raw command responses.  Its
        ``sources_used`` field lists the source containers actually drained, in
        order of consumption.

    Raises:
        ValueError: If *volume* ≤ 0, aliquot volumes are negative, total
            aspiration volume exceeds tip capacity (single-dispense mode), single-well
            volume exceeds net capacity (multi-dispense mode), insufficient tips
            and no reload callback is configured, or any referenced labware
            is missing from the deck.  When multiple labware are missing,
            the error message lists all of them in a single ``ValueError``.
        OperatorCancelledError: If the operator cancels a tip-reload prompt.
    """
    # -------
    # 1. Parameter validation
    # ------------------------------------------------------------------
    if not tip_pool or not tip_pool.strip():
        raise ValueError("tip_pool must not be empty")
    tip_pool = tip_pool.strip()

    if volume <= 0:
        raise ValueError(f"volume must be > 0, got {volume}")
    if pre_aliquot_volume < 0:
        raise ValueError(f"pre_aliquot_volume must be >= 0, got {pre_aliquot_volume}")
    if post_aliquot_volume < 0:
        raise ValueError(f"post_aliquot_volume must be >= 0, got {post_aliquot_volume}")

    channels = list(channels) if channels is not None else list(DEFAULT_CHANNELS)
    validate_channels(channels)

    # ------------------------------------------------------------------
    # 1b. Parse CSV up-front (so labware ids are known for validation)
    # ------------------------------------------------------------------
    csv_rows: list[TransferRow] | None = None
    if transfer_csv is not None:
        if not isinstance(dest_plate, str):
            raise ValueError(
                "transfer_csv mode requires dest_plate to be a single string (the default for rows "
                "without a dest_labware); pass a list only when using the parameter-driven path."
            )
        # The reagent always comes from reagent_source: the CSV only says where it
        # goes and how much, so its source columns (if any) are ignored.
        csv_rows = _parse_transfer_csv(
            transfer_csv,
            default_dest_labware=dest_plate,
            default_volume=volume,
            ignore_source=True,
        )

    # ------------------------------------------------------------------
    # 1c. Up-front labware validation — collect every distinct labware id
    #     referenced by the command and raise a single error listing all
    #     missing labware rather than failing on the first one.
    # ------------------------------------------------------------------
    src_selectors = normalize_selector_list(reagent_source)
    if not src_selectors:
        raise ValueError("reagent_source list must contain at least one entry")
    if csv_rows is not None:
        # The reagent labware comes from reagent_source, not a CSV line, so it
        # carries no line number in the error.
        labware_ids = [extract_labware_id(sel) for sel in src_selectors]
        row_origin: dict[str, int] = {}
        for row in csv_rows:
            if row.dest_labware not in row_origin and row.dest_labware not in labware_ids:
                row_origin[row.dest_labware] = row.line_no if row.line_no is not None else 0
                labware_ids.append(row.dest_labware)
        validate_labware_on_deck(client, labware_ids, row_origin=row_origin)
    else:
        dst_selectors = normalize_selector_list(dest_plate)
        if not dst_selectors:
            raise ValueError("dest_plate list must contain at least one entry")
        labware_ids = []
        for sel in src_selectors + dst_selectors:
            lid = extract_labware_id(sel)
            if lid not in labware_ids:
                labware_ids.append(lid)
        validate_labware_on_deck(client, labware_ids)

    # ------------------------------------------------------------------
    # 2. Tip capacity + volume sanity
    # ------------------------------------------------------------------
    tip_capacity = _resolve_tip_capacity(client, tip_pool)
    net_capacity = tip_capacity - pre_aliquot_volume - post_aliquot_volume

    # With a transfer CSV, *volume* is only the fallback for rows without one; every
    # row's actual volume is checked against the tip below instead.
    if csv_rows is None and multi_dispense:
        if volume > net_capacity:
            raise ValueError(
                f"volume {volume} µL exceeds available tip capacity after aliquots "
                f"({net_capacity} µL).  Cannot dispense even one well per aspiration."
            )
    elif csv_rows is None:
        # single-dispense mode: total aspiration per chunk must fit in the tip.
        asp_total = volume + pre_aliquot_volume + post_aliquot_volume
        if asp_total > tip_capacity:
            raise ValueError(
                f"Total aspiration volume {asp_total} µL (volume + pre_aliquot + post_aliquot) "
                f"exceeds tip capacity {tip_capacity} µL. "
                "Cannot split into multiple aspirations in single-dispense mode."
            )

    # ------------------------------------------------------------------
    # 3. Build resolved source runs: list of (source_pos, dest_pairs)
    #
    # CSV path: parse rows, group by source (or worklist order), then
    #   resolve each row's positions.
    # Non-CSV path: resolve selector positions directly; wrap into one run.
    # ------------------------------------------------------------------

    # Each entry is (sources, [(dest_pos, vol), ...]) where ``sources`` is the
    # ordered list of source positions to drain for that run (consumable liquid
    # management advances through them as each is exhausted).
    resolved_runs: list[tuple[list[list[Position]], list[tuple[Position, float]]]] = []

    if csv_rows is not None:
        rows = csv_rows

        # Validate per-row volume fits in tip capacity BEFORE grouping/reordering.
        # This preserves the original CSV line numbers in error messages.
        if multi_dispense:
            _validate_row_volumes_in_range(
                rows,
                max_aspiration=net_capacity,
                capacity_label="net capacity",
            )
        else:
            _validate_row_volumes_in_range(
                rows,
                max_aspiration=tip_capacity,
                overhead=pre_aliquot_volume + post_aliquot_volume,
                capacity_label="tip capacity",
                mode_suffix=" in single-dispense mode",
            )

        # The reagent comes from reagent_source for every row, one source group per
        # selector (see the grouping note at step 4).
        reagent_groups = [resolve_multi_selector(client, unit) for unit in _broadcast_selector_list(reagent_source)]
        if not all(reagent_groups):
            raise ValueError(f"Reagent source {reagent_source!r} resolved to no positions.")

        # A multi-channel stroke dispenses to one plate, so split the rows by
        # destination plate: grouped by plate (default), or -- with
        # follow_csv_order -- into consecutive same-plate runs in CSV order.
        if follow_csv_order:
            row_runs: list[list[TransferRow]] = _plan_dest_runs(rows)
        else:
            by_plate: dict[str, list[TransferRow]] = {}
            for row in rows:
                by_plate.setdefault(row.dest_labware, []).append(row)
            row_runs = list(by_plate.values())

        for run_rows in row_runs:
            run_groups = [list(g) for g in reagent_groups]

            run_dest_pairs: list[tuple[Position, float]] = []
            for row in run_rows:
                dst_positions = resolve_selector_positions(
                    client,
                    f"{row.dest_labware}@wells:{row.dest_well}",
                )
                if not dst_positions:
                    raise ValueError(
                        f"Destination '{row.dest_labware}' / well '{row.dest_well}' resolved to no positions."
                    )
                run_dest_pairs.append((dst_positions[0], row.volume))

            resolved_runs.append((run_groups, run_dest_pairs))
    else:
        # Non-CSV: resolve selector positions directly — no double round-trip.
        # Apply Q5 broadcast rule on the SELECTOR LISTS (not flat position counts):
        #   - 1 source selector  → N dest selectors: broadcast
        #   - N source selectors → N dest selectors: index-wise pairing
        #   - else: ValueError
        # For each (source_selector, dest_selector) pair we build one or more
        # resolved runs, splitting the dest positions by plate so that every
        # ``dest_pairs`` list passed to the inner runners stays on a single
        # plate (a hard invariant for multi-channel strokes).
        src_units = _broadcast_selector_list(reagent_source)
        dst_units = _broadcast_selector_list(dest_plate)

        if len(src_units) == 1:
            paired = [(src_units[0], d) for d in dst_units]
        elif len(src_units) == len(dst_units):
            paired = list(zip(src_units, dst_units, strict=True))
        else:
            raise ValueError(
                f"reagent_source has {len(src_units)} selector(s) but dest_plate has "
                f"{len(dst_units)} selector(s); sources and destinations must have matching "
                "length or one source must broadcast to many destinations."
            )

        source_plates_seen: list[str] = []
        for src_sel, dst_sel in paired:
            src_positions = resolve_multi_selector(client, src_sel)
            if not src_positions:
                raise ValueError(f"Reagent source '{src_sel}' resolved to no positions.")
            # All of this selector's positions form one source group, which
            # the channels are spread across (see step 4).
            for sp in src_positions:
                if sp.labware not in source_plates_seen:
                    source_plates_seen.append(sp.labware)

            dst_positions = resolve_multi_selector(client, dst_sel)
            if not dst_positions:
                continue

            for _plate_id, sub_positions in split_positions_by_plate(dst_positions):
                resolved_runs.append(([list(src_positions)], [(p, volume) for p in sub_positions]))

        if not resolved_runs:
            return AddReagentResult(
                iterations=0,
                total_wells_processed=0,
                source_plate_ids=tuple(source_plates_seen),
                dest_plate_ids=(),
                multi_dispense=multi_dispense,
                wells_filled=0,
                wells_filled_by_plate={},
                sources_used=(),
                iteration_results=(),
            )

    # ------------------------------------------------------------------
    # 4. Source groups + pre-flight tip budget
    #
    # Each reagent_source selector is one source group, and every channel is
    # used on it: the channels share the group's positions, in passes when there
    # are more channels than positions (LiquidSourceTracker.aspirate_passes).
    # "Tubes@1" sends every channel to tube 1 in turn; "Tubes@1:4" sends channels
    # 1-4 to tubes 1-4, then 5-8 to tubes 1-4.  A reservoir has no walls between
    # its sections, so it is one liquid however it was addressed: "Trough@1"
    # becomes every section of the trough.  With a list of selectors (worklist
    # mode) the groups are drained in order as each runs out.
    # ------------------------------------------------------------------
    all_source_positions = [p for groups, _ in resolved_runs for g in groups for p in g]
    connected_labware = connected_source_labware(client, all_source_positions)

    # (source_groups, dest_pairs, run_channels) for each resolved run.
    run_plans: list[tuple[list[list[Position]], list[tuple[Position, float]], list[int]]] = [
        ([expand_connected_sources(client, g, connected_labware) for g in groups], dest_pairs, list(channels))
        for groups, dest_pairs in resolved_runs
    ]

    if reuse_tips:
        # One shared tip set for the whole command: size it to the widest stroke.
        tips_needed = max((min(len(rc), len(dp)) for _, dp, rc in run_plans), default=0)
    elif multi_dispense:
        # multi-dispense mode performs exactly one pickup of len(run_channels)
        # tips per source run, regardless of destination-well count.
        tips_needed = sum(len(rc) for _, _, rc in run_plans)
    else:
        # single-dispense mode uses one tip per destination well.  _run_single_dispense
        # re-validates per channel-row, but a coarse up-front check still
        # catches obvious shortfalls.
        tips_needed = sum(len(dest_pairs) for _, dest_pairs, _ in run_plans)
    ensure_tips_available(client, tip_pool, tips_needed, command_name="add_reagent")

    # ------------------------------------------------------------------
    # 5. Resolve waste position up-front if required
    # ------------------------------------------------------------------
    waste_pos: Position | None = None
    if pre_aliquot_volume > 0 and pre_aliquot_disposal == PreAliquotDisposal.WASTE:
        waste_pos = resolve_waste_position(client, None)

    # ------------------------------------------------------------------
    # 6. Main loop — iterate over resolved source runs
    # ------------------------------------------------------------------
    all_iterations: list[AddReagentIterationResult] = []
    wells_filled = 0
    wells_filled_by_plate: dict[str, int] = {}
    dest_plate_ids: list[str] = []
    source_plate_ids: list[str] = []
    sources_used: list[str] = []

    profile_scope = client.use_error_profile(error_profile) if error_profile is not None else nullcontext()

    with profile_scope:
        # When reusing tips across the whole command, mount one shared set now
        # (sized to the widest stroke) and eject it after every run completes.
        reuse_pickup = None
        reuse_channels: list[int] = []
        reuse_ejected = False
        if reuse_tips:
            max_span = max((min(len(rc), len(dp)) for _, dp, rc in run_plans), default=0)
            reuse_channels = channels[:max_span] if max_span else []
            if reuse_channels:
                reuse_pickup = pickup_tips(client, reuse_channels, tip_pool, optimized=optimized_tip_pickup)

        try:
            for run_groups, dest_pairs, run_channels in run_plans:
                if multi_dispense:
                    run_its, run_wf, run_wfbp, run_dids, run_sources_used = _run_multi_dispense(
                        client,
                        source_groups=run_groups,
                        dest_pairs=dest_pairs,
                        net_capacity=net_capacity,
                        pre_aliquot_volume=pre_aliquot_volume,
                        pre_aliquot_disposal=pre_aliquot_disposal,
                        waste_pos=waste_pos,
                        post_aliquot_volume=post_aliquot_volume,
                        post_aliquot_height=post_aliquot_height,
                        liquid_class=liquid_class,
                        channels=run_channels,
                        tip_pool=tip_pool,
                        optimized_tip_pickup=optimized_tip_pickup,
                        aspirate_settings=aspirate_settings,
                        dispense_settings=dispense_settings,
                        reuse_tips=reuse_tips,
                    )
                else:
                    run_its, run_wf, run_wfbp, run_dids, run_sources_used = _run_single_dispense(
                        client,
                        source_groups=run_groups,
                        dest_pairs=dest_pairs,
                        pre_aliquot_volume=pre_aliquot_volume,
                        pre_aliquot_disposal=pre_aliquot_disposal,
                        waste_pos=waste_pos,
                        post_aliquot_volume=post_aliquot_volume,
                        post_aliquot_height=post_aliquot_height,
                        liquid_class=liquid_class,
                        channels=run_channels,
                        tip_pool=tip_pool,
                        optimized_tip_pickup=optimized_tip_pickup,
                        aspirate_settings=aspirate_settings,
                        dispense_settings=dispense_settings,
                        reuse_tips=reuse_tips,
                    )

                all_iterations.extend(run_its)
                wells_filled += run_wf
                for plate_id, count in run_wfbp.items():
                    wells_filled_by_plate[plate_id] = wells_filled_by_plate.get(plate_id, 0) + count
                for did in run_dids:
                    if did not in dest_plate_ids:
                        dest_plate_ids.append(did)
                # Aggregate the source positions actually drained (in consumption
                # order), and the distinct source plates they belong to.
                for src in run_sources_used:
                    label = f"{src.labware}@{src.well}"
                    if label not in sources_used:
                        sources_used.append(label)
                    if src.labware not in source_plate_ids:
                        source_plate_ids.append(src.labware)

        # Eject the shared tip set and record it on the first/last iterations.
        # This runs in a finally so an error mid-run never leaves the shared
        # tips mounted on the channels (matching the per-runner cleanup path).
        finally:
            if reuse_tips and reuse_channels and not reuse_ejected:
                try:
                    reuse_eject = eject_tips(client, reuse_channels)
                    reuse_ejected = True
                    if all_iterations:
                        all_iterations[0] = all_iterations[0].model_copy(update={"tip_pickup": reuse_pickup})
                        all_iterations[-1] = all_iterations[-1].model_copy(
                            update={"tip_eject": reuse_eject}
                        )
                except Exception as e:
                    _logger.warning(
                        "Failed to eject shared tips on channels %s during cleanup: %s. "
                        "Original exception (if any) will be raised.",
                        reuse_channels,
                        e,
                    )


    return AddReagentResult(
        iterations=len(all_iterations),
        total_wells_processed=wells_filled,
        source_plate_ids=tuple(source_plate_ids),
        dest_plate_ids=tuple(dest_plate_ids),
        multi_dispense=multi_dispense,
        wells_filled=wells_filled,
        wells_filled_by_plate=wells_filled_by_plate,
        sources_used=tuple(sources_used),
        iteration_results=tuple(all_iterations),
    )
