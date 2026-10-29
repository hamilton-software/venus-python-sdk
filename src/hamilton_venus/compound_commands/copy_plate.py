from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    resolve_plate_wells,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import eject_tips, ensure_tips_available, pickup_tips
from hamilton_venus.compound_commands._helpers._transfer_plan import validate_labware_on_deck
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import CopyPlateIterationResult, CopyPlateResult
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile


def execute_copy_plate(
    client: InstrumentClient,
    source_plate_id: str,
    dest_plate_id: str | list[str],
    *,
    volume: float,
    liquid_class: str | list[str],
    channels: list[int] | None = None,
    tip_pool: str,
    reuse_tips: bool = False,
    aspirate_settings: AspirateSettings | None = None,
    dispense_settings: DispenseSettings | None = None,
    error_profile: ErrorProfile | None = None,
) -> CopyPlateResult:
    """Copy liquid from every well on one plate to the corresponding well on another.

    Iterates over the paired source/dest wells in batches sized by ``channels``.
    Each batch performs a tip-pickup, aspirate, dispense, and tip-eject cycle
    (or a single pickup/eject when ``reuse_tips`` is enabled).

    Args:
        client: Connected instrument client used to issue hardware commands.
        source_plate_id: Deck identifier of the source labware.
        dest_plate_id: Deck identifier of the destination labware, or a list
            of identifiers to copy the source plate to multiple destinations.
            Each destination receives an independent copy of the source.
        volume: Aspiration/dispense volume applied to every channel.
        liquid_class: Liquid class name(s) forwarded to the aspirate step. Required.
        channels: 1-indexed channel numbers to use (default 1-8).
        tip_pool: Name of the tip-rack to draw tips from.
        reuse_tips: When ``True`` tips are picked up once and reused for all
            batches within a single destination copy, requiring only
            ``min(channels, wells)`` tips per destination.
        aspirate_settings: Optional aspirate settings forwarded to the aspirate call.
        dispense_settings: Optional dispense settings forwarded to the dispense call.
        error_profile: When provided, all liquid-handling steps run inside
            ``client.use_error_profile(error_profile)``.

    Returns:
        A :class:`CopyPlateResult` summarising iterations, wells copied,
        and raw command responses.

    Raises:
        ValueError: If ``dest_plate_id`` is an empty list, if insufficient tips
            are available in *tip_pool*, if *volume* exceeds the capacity of the
            tips assigned to *tip_pool*, or if ``source_plate_id`` /
            ``dest_plate_id`` are not present on the deck.  When multiple labware
            are missing, the error message lists all of them in a single
            ``ValueError``.
    """
    channels = channels if channels is not None else DEFAULT_CHANNELS
    validate_channels(channels)

    dest_plate_ids = [dest_plate_id] if isinstance(dest_plate_id, str) else list(dest_plate_id)
    if not dest_plate_ids:
        raise ValueError("dest_plate_id must contain at least one plate id")

    validate_labware_on_deck(client, [source_plate_id, *dest_plate_ids])

    source_wells = resolve_plate_wells(client, source_plate_id)
    ch_count = len(channels)

    # Pre-resolve all destination well lists and compute per-dest tip budgets.
    dest_specs: list[tuple[str, list[Position], int]] = []  # (plate_id, dest_wells, transferable_wells)
    total_tips = 0
    for dpid in dest_plate_ids:
        dw = resolve_plate_wells(client, dpid)
        tw = min(len(source_wells), len(dw))
        dest_specs.append((dpid, dw, tw))
        total_tips += _compute_tips_needed(tw, ch_count, reuse_tips=reuse_tips)

    if total_tips == 0:
        total_skipped = sum(max(len(source_wells), len(dw)) for _, dw, _ in dest_specs)
        return CopyPlateResult(
            iterations=0,
            total_wells_processed=0,
            iteration_results=(),
            source_plate_id=source_plate_id,
            dest_plate_ids=tuple(dest_plate_ids),
            wells_copied=0,
            wells_skipped=total_skipped,
        )

    ensure_tips_available(client, tip_pool, total_tips, command_name="copy_plate")

    tip_capacity = _resolve_tip_capacity(client, tip_pool)
    if volume > tip_capacity:
        raise ValueError(f"volume {volume} µL exceeds tip capacity {tip_capacity} µL for tip pool '{tip_pool}'.")

    all_iteration_results: list[CopyPlateIterationResult] = []
    total_wells_copied = 0
    total_wells_skipped = 0

    profile_scope = client.use_error_profile(error_profile) if error_profile is not None else nullcontext()

    with profile_scope:
        for _dpid, dest_wells, total_wells in dest_specs:
            wells_skipped_this = max(len(source_wells), len(dest_wells)) - total_wells
            total_wells_skipped += wells_skipped_this
            if total_wells == 0:
                continue

            wells_copied = 0
            iteration = 0

            for offset in range(0, total_wells, ch_count):
                batch_size = min(ch_count, total_wells - offset)
                batch_channels = channels[:batch_size]
                src_batch = source_wells[offset : offset + batch_size]
                dst_batch = dest_wells[offset : offset + batch_size]

                pickup_resp: CommandResponse | None = None
                if not reuse_tips or iteration == 0:
                    pickup_resp = pickup_tips(client, batch_channels, tip_pool)

                sliced_asp = slice_settings(aspirate_settings, batch_size)
                asp_resp = client.aspirate(
                    channels=batch_channels,
                    positions=src_batch,
                    volumes=volume,
                    liquid_class=liquid_class,
                    settings=sliced_asp,
                )

                sliced_disp = slice_settings(dispense_settings, batch_size)
                disp_resp = client.dispense(
                    channels=batch_channels,
                    positions=dst_batch,
                    volumes=volume,
                    settings=sliced_disp,
                )

                eject_resp: CommandResponse | None = None
                if not reuse_tips:
                    eject_resp = eject_tips(client, batch_channels)

                all_iteration_results.append(
                    CopyPlateIterationResult(
                        tip_pickup=pickup_resp,
                        aspirate=asp_resp,
                        dispense=disp_resp,
                        tip_eject=eject_resp,
                    )
                )
                wells_copied += batch_size
                iteration += 1

            if reuse_tips and iteration > 0:
                first_batch_tips = min(ch_count, total_wells)
                final_eject_channels = channels[:first_batch_tips]
                eject_resp = eject_tips(client, final_eject_channels)
                all_iteration_results[-1] = all_iteration_results[-1].model_copy(update={"tip_eject": eject_resp})

            total_wells_copied += wells_copied

    return CopyPlateResult(
        iterations=len(all_iteration_results),
        total_wells_processed=total_wells_copied,
        iteration_results=tuple(all_iteration_results),
        source_plate_id=source_plate_id,
        dest_plate_ids=tuple(dest_plate_ids),
        wells_copied=total_wells_copied,
        wells_skipped=total_wells_skipped,
    )


def _compute_tips_needed(total_wells: int, ch_count: int, *, reuse_tips: bool = False) -> int:
    """Return the number of tips required for a full copy-plate operation.

    When *reuse_tips* is ``False`` every well consumes a fresh tip, so the
    total equals *total_wells*.  When ``True`` only the first pickup batch is
    needed — ``min(ch_count, total_wells)``.
    """
    if reuse_tips:
        return min(ch_count, total_wells)
    return total_wells
