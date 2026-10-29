"""Compound commands: ``serial_dilution_by_volume`` / ``serial_dilution_by_dilution_factor``.

This module implements the two peer serial-dilution compound commands.  They
share almost all behaviour and differ only in how the per-well **diluent
volume** is determined:

* :func:`execute_serial_dilution_by_volume` — the caller supplies
  ``diluent_volume`` directly.
* :func:`execute_serial_dilution_by_dilution_factor` — the caller supplies
  ``dilution_factor``; the diluent volume is derived as
  ``diluent_volume = transfer_volume * (dilution_factor - 1)``.

Both delegate to the shared private core :func:`_execute_serial_dilution`, which
performs a serial dilution **across the columns** of one or more plates, one
independent series **per row**, running all active rows in parallel on the
multi-channel head.  The samples to be diluted are assumed to be pre-loaded at
``start_column``.  A run has two globally ordered phases (§3.7): first the
**diluent pre-charge** for every ``(plate, pass)`` unit, then the **transfer
chains**.  See ``docs/planning/serial-dilution-plan.md`` for the full design.

The command follows established SDK conventions: selector-string DSL via
:func:`resolve_selector_positions` / :func:`resolve_multi_selector`; scoped
:class:`~hamilton_venus.error_handling.profile.ErrorProfile` per phase via
``client.use_error_profile``; operator-prompted tip reload via
:func:`ensure_tips_available`; operator-prompted diluent reload via
:func:`ensure_liquid_available`; up-front labware validation via
:func:`validate_labware_on_deck`; tip-aware volume sanity via
:func:`_resolve_tip_capacity`; mixing via a dedicated :func:`emit_final_mix`
stroke (same mechanism as ``pool_samples``); and a frozen
:class:`SerialDilutionResult` with a ``tadm_curves`` aggregation property.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING, cast

from hamilton_venus.compound_commands._helpers._base import (
    DEFAULT_CHANNELS,
    emit_final_mix,
    mix_cycles_active,
    override_mix_cycles,
    slice_settings,
    validate_channels,
)
from hamilton_venus.compound_commands._helpers._grid import (
    DilutionGrid,
    _resolve_dilution_grid,
    _validate_volumes,
)
from hamilton_venus.compound_commands._helpers._liquid_manager import (
    LiquidSourceTracker,
    connected_channel_cap,
    connected_source_labware,
    lld_enabled,
    resolve_source_positions,
)
from hamilton_venus.compound_commands._helpers._multi_dispense import plan_dispense_batches
from hamilton_venus.compound_commands._helpers._multi_plate import normalize_selector_list, resolve_multi_selector
from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity
from hamilton_venus.compound_commands._helpers._tip_manager import eject_tips, ensure_tips_available, pickup_tips
from hamilton_venus.compound_commands._helpers._transfer_plan import validate_labware_on_deck
from hamilton_venus.compound_commands._helpers._waste import resolve_waste_position
from hamilton_venus.models.compound_results import (
    SerialDilutionPlateResult,
    SerialDilutionResult,
    SerialDilutionSeriesResult,
    SerialDilutionStepResult,
)
from hamilton_venus.models.enums import LastDilutionWaste
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
    from hamilton_venus.models.position import LabwareLayoutSpec

_logger = logging.getLogger(__name__)

# A (plate_id, spec, grid, pass_index) unit of work.  Passes are indexed
# globally-per-plate (0-based) so the result can report which pass a series
# belonged to (§3.7).
_WorkUnit = tuple[str, "LabwareLayoutSpec", DilutionGrid, int]


def _well(spec: LabwareLayoutSpec, plate_id: str, row_index: int, column: int) -> Position:
    """Build a :class:`Position` for a 0-based *row_index* and 1-based *column*."""
    return Position(labware=plate_id, well=spec.emit_well(row_index, column))


def _pass_channels(channels: list[int], pass_rows: list[int]) -> list[int]:
    """Return the channels servicing *pass_rows* (channel *i* → i-th active row)."""
    return channels[: len(pass_rows)]


def _pass_positions(spec: LabwareLayoutSpec, plate_id: str, pass_rows: list[int], column: int) -> list[Position]:
    """Return the ordered wells at *column* for each row in *pass_rows*."""
    return [_well(spec, plate_id, r, column) for r in pass_rows]


def _count_transfer_tips(
    work_list: list[_WorkUnit],
    channels: list[int],
    reuse_tips: bool,
    discard_last_excess: LastDilutionWaste,
) -> int:
    """Return the exact number of transfer tips consumed across *work_list*.

    Mirrors the pickup/eject logic of :func:`_run_transfer_phase` (§5.6): a tip
    set is re-picked whenever no set is carried or the carried set's channel
    count differs from the current pass, and it is ejected after every unit when
    tips are not reused or the excess leaves with the tips
    (``WITH_TIP_EJECT``).  This makes the pre-run ``ensure_tips_available`` check
    exact even for variable-width passes (e.g. a 9-row plate on 8 channels).
    """
    always_eject = (not reuse_tips) or discard_last_excess == LastDilutionWaste.WITH_TIP_EJECT
    total = 0
    carried = False
    active_carry: list[int] = []
    for _pid, _spec, grid, pass_index in work_list:
        row_channels = _pass_channels(channels, grid.passes[pass_index])
        if carried and active_carry != row_channels:
            carried = False
        if not carried:
            total += len(row_channels)
            carried = True
            active_carry = row_channels
        if always_eject:
            carried = False
    return total


def _resolve_plate_ids(
    client: InstrumentClient, plate_id: str | list[str] | Position | list[Position]
) -> list[str]:
    """Resolve *plate_id* selector(s) to an ordered, de-duplicated list of plate ids.

    Selectors are resolved to positions and reduced to their distinct labware
    ids, so a well-scoped selector such as ``"Plate1@A1:A4"`` is accepted and
    treated as the whole plate ``"Plate1"`` (the well expression only selects
    which plate is referenced, not which wells the dilution runs on — the active
    grid is derived from the labware geometry and the ``start_column`` /
    ``exclude_*`` arguments). May also be a pre-resolved ``Position``/
    ``list[Position]`` instead of a selector string.
    """
    selectors = normalize_selector_list(plate_id)
    if not selectors:
        raise ValueError("plate_id must contain at least one entry.")
    positions = resolve_multi_selector(
        client, cast("str | list[str] | Position | list[Position]", selectors)
    )
    plate_ids = list(dict.fromkeys(p.labware for p in positions))
    if not plate_ids:
        raise ValueError(f"plate_id {plate_id!r} resolved to no plates on the deck.")
    return plate_ids


def _resolve_diluent_sources(client: InstrumentClient, diluent_source: str | list[str]) -> list[Position]:
    """Resolve *diluent_source* selector(s) to the ordered source positions to drain.

    Thin wrapper over the shared
    :func:`~hamilton_venus.compound_commands._helpers._liquid_manager.resolve_source_positions`
    (multi-source container selection is a general capability, not
    serial-dilution-specific).  Each selector is expanded to **all** the
    positions it addresses, and the results are concatenated in selector order.
    A multi-well selector such as ``"Trough@1,2,3"`` therefore yields three
    ordered sources (drained in turn as each is exhausted), exactly as the
    equivalent list ``["Trough@1", "Trough@2", "Trough@3"]`` would.
    """
    return resolve_source_positions(client, diluent_source)


def _execute_serial_dilution(
    client: InstrumentClient,
    *,
    plate_id: str | list[str] | Position | list[Position],
    start_column: int,
    num_dilutions: int,
    transfer_volume: float,
    diluent_volume: float,
    diluent_source: str | list[str],
    diluent_liquid_class: str | list[str],
    diluent_tip_pool: str,
    transfer_liquid_class: str | list[str],
    transfer_tip_pool: str,
    channels: list[int] | None = None,
    exclude_columns: list[int] | None = None,
    exclude_rows: list[int | str] | None = None,
    mix_after_dispense: bool = True,
    diluent_multi_dispense: bool = True,
    reuse_tips: bool = False,
    discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
    waste_location: str | None = None,
    optimized_tip_pickup: bool = True,
    diluent_asp_settings: AspirateSettings | None = None,
    diluent_disp_settings: DispenseSettings | None = None,
    transfer_asp_settings: AspirateSettings | None = None,
    transfer_disp_settings: DispenseSettings | None = None,
    diluent_error_profile: ErrorProfile | None = None,
    transfer_error_profile: ErrorProfile | None = None,
    dilution_factor: float | None = None,
) -> SerialDilutionResult:
    """Shared serial-dilution core taking a concrete *diluent_volume* (§5.2).

    Performs a serial dilution across the columns of one or more plates, one
    independent series per row, running the active rows of each pass in parallel
    on the multi-channel head.  Phases run globally (§3.7): all diluent
    pre-charge for every ``(plate, pass)`` first, then all transfer chains.

    Args:
        client: Connected instrument client used to issue hardware commands.
        plate_id: Plate selector string or a list of selectors (multi-plate,
            §3.6); plates are processed sequentially and share the diluent
            source, tips (when ``reuse_tips``) and waste location. May also
            be a pre-resolved ``Position``/``list[Position]``.
        start_column: 1-based column holding the pre-loaded sample.
        num_dilutions: Number of dilution steps (transfers); must be ``>= 1``.
        transfer_volume: Per-channel volume carried between wells in the series.
        diluent_volume: Per-well diluent pre-charge volume.  ``0`` skips the
            diluent phase entirely.
        diluent_source: One or more diluent source selectors, drained in order
            with reactive volume tracking (§3.4).
        diluent_liquid_class: Liquid class(es) for the diluent pre-charge.
        diluent_tip_pool: Tip pool for the diluent phase (required when
            ``diluent_volume > 0``).
        transfer_liquid_class: Liquid class(es) for the transfer chain.
        transfer_tip_pool: Tip pool for the transfer phase.  Required.
        channels: 1-indexed channels to use (default 1-8).  Active rows beyond
            ``len(channels)`` are processed in additional passes (§3.7).
        exclude_columns: 1-based columns to skip during traversal (they do not
            consume a dilution step, Q-COL2).
        exclude_rows: Rows to exclude, as 1-based ints and/or letters (§3.7).
        mix_after_dispense: When ``True`` (default) and the transfer dispense
            settings request mix cycles, a dedicated mix stroke follows each
            transfer dispense.  The diluent pre-charge never mixes.
        diluent_multi_dispense: When ``True`` (default) the diluent phase
            aspirates a capacity/budget-bounded batch feeding several columns;
            when ``False`` it aspirates once per column (§3.5).
        reuse_tips: When ``True`` the transfer tip set is kept mounted across
            passes and plates (fast, accepts cross-pass contamination); when
            ``False`` a fresh transfer set is picked up per pass (§5.6).  Never
            bridges the diluent and transfer phases.
        discard_last_excess: How to dispose of the trailing ``transfer_volume``
            left in the final dilution well (§3.3).
        waste_location: Explicit waste selector for ``TO_WASTE``; ``None`` falls
            back to the deck's fixed ``liquid_waste`` labware (§5.4a).
        optimized_tip_pickup: Forwarded to :func:`pickup_tips`.
        diluent_asp_settings: Optional aspirate settings for the diluent phase.
        diluent_disp_settings: Optional dispense settings for the diluent phase.
        transfer_asp_settings: Optional aspirate settings for the transfer phase.
        transfer_disp_settings: Optional dispense settings for the transfer
            phase; mix fields are overridden per the ``mix_after_dispense``
            rules above.
        diluent_error_profile: When provided, the diluent phase runs inside
            ``client.use_error_profile(diluent_error_profile)``.
        transfer_error_profile: When provided, the transfer phase runs inside
            ``client.use_error_profile(transfer_error_profile)``.
        dilution_factor: Recorded on the result for the by-factor command;
            ``None`` for the by-volume command.

    Returns:
        A :class:`SerialDilutionResult` aggregating per-plate, per-series, and
        per-step responses.

    Raises:
        ValueError: Validation fails — empty required tip pool,
            ``num_dilutions < 1``, non-positive ``transfer_volume``, a volume
            exceeding tip capacity, labware missing on the deck, a column/row
            range violation, an exhausted diluent source with no reload
            callback, ``TO_WASTE`` with no resolvable waste location, or
            insufficient tips with no reload callback.
        OperatorCancelledError: The operator cancelled a tip or liquid reload.
    """
    _validate_volumes(
        transfer_volume=transfer_volume,
        diluent_volume=diluent_volume,
        dilution_factor=dilution_factor,
    )

    run_diluent = diluent_volume > 0
    if run_diluent and (not diluent_tip_pool or not diluent_tip_pool.strip()):
        raise ValueError("diluent_tip_pool must be a non-empty string when diluent_volume > 0.")
    if not transfer_tip_pool or not transfer_tip_pool.strip():
        raise ValueError("transfer_tip_pool must be a non-empty string.")
    diluent_tip_pool = (diluent_tip_pool or "").strip()
    transfer_tip_pool = transfer_tip_pool.strip()

    channels = channels if channels is not None else DEFAULT_CHANNELS
    validate_channels(channels)

    plate_ids = _resolve_plate_ids(client, plate_id)
    diluent_sources = _resolve_diluent_sources(client, diluent_source)

    # Up-front labware validation for every plate plus the diluent/waste labware.
    diluent_labware = list(dict.fromkeys(s.labware for s in diluent_sources))
    labware_ids = list(dict.fromkeys([*plate_ids, *diluent_labware]))
    validate_labware_on_deck(client, labware_ids)

    # Tip-capacity sanity for both running pools.
    transfer_capacity = _resolve_tip_capacity(client, transfer_tip_pool)
    if transfer_volume > transfer_capacity:
        raise ValueError(
            f"transfer_volume {transfer_volume} µL exceeds tip capacity "
            f"{transfer_capacity} µL for transfer tip pool '{transfer_tip_pool}'."
        )
    if run_diluent:
        diluent_capacity = _resolve_tip_capacity(client, diluent_tip_pool)
        if diluent_volume > diluent_capacity:
            raise ValueError(
                f"diluent_volume {diluent_volume} µL exceeds tip capacity "
                f"{diluent_capacity} µL for diluent tip pool '{diluent_tip_pool}'."
            )
    else:
        diluent_capacity = 0.0

    # Resolve each plate's grid geometry and build the (plate, pass) work list.
    work_list: list[_WorkUnit] = []
    plate_grids: dict[str, DilutionGrid] = {}
    for pid in plate_ids:
        spec = client.get_labware_spec(pid)
        grid = _resolve_dilution_grid(
            spec,
            start_column=start_column,
            num_dilutions=num_dilutions,
            exclude_columns=exclude_columns,
            exclude_rows=exclude_rows,
            channels=channels,
        )
        plate_grids[pid] = grid
        for pass_index in range(len(grid.passes)):
            work_list.append((pid, spec, grid, pass_index))

    # Tip budgeting for the whole run (§5.6).
    if run_diluent:
        # One clean diluent set reused across the entire pre-charge phase.
        ensure_tips_available(client, diluent_tip_pool, len(channels), command_name="serial_dilution")
    transfer_tips_needed = _count_transfer_tips(work_list, channels, reuse_tips, discard_last_excess)
    ensure_tips_available(client, transfer_tip_pool, transfer_tips_needed, command_name="serial_dilution")

    # Resolve the waste position once when needed (shared across all plates).
    waste_pos: Position | None = None
    if discard_last_excess == LastDilutionWaste.TO_WASTE:
        waste_pos = resolve_waste_position(client, waste_location)

    diluent_connected = connected_source_labware(client, diluent_sources)
    tracker = LiquidSourceTracker(
        diluent_sources,
        connected_labware=diluent_connected,
    )
    # Cap simultaneous diluent channels to a connected container's position count
    # (mirrors add_reagent); a non-connected source leaves the cap at len(channels).
    diluent_channel_cap = connected_channel_cap(diluent_sources, diluent_connected, len(channels))

    diluent_scope = (
        client.use_error_profile(diluent_error_profile) if diluent_error_profile is not None else nullcontext()
    )
    transfer_scope = (
        client.use_error_profile(transfer_error_profile) if transfer_error_profile is not None else nullcontext()
    )

    # Per (plate, pass) diluent dispenses, keyed by (plate_id, pass_index),
    # then by 0-based dilution-column ordinal → one shared response per column.
    diluent_records: dict[tuple[str, int], list[ChannelDispenseResponse]] = {}
    if run_diluent:
        with diluent_scope:
            _run_diluent_phase(
                client,
                work_list=work_list,
                channels=channels,
                diluent_volume=diluent_volume,
                diluent_liquid_class=diluent_liquid_class,
                diluent_tip_pool=diluent_tip_pool,
                diluent_asp_settings=diluent_asp_settings,
                diluent_disp_settings=diluent_disp_settings,
                diluent_multi_dispense=diluent_multi_dispense,
                diluent_capacity=diluent_capacity,
                tracker=tracker,
                diluent_channel_cap=diluent_channel_cap,
                optimized_tip_pickup=optimized_tip_pickup,
                diluent_records=diluent_records,
            )

    with transfer_scope:
        series_by_plate = _run_transfer_phase(
            client,
            work_list=work_list,
            channels=channels,
            num_dilutions=num_dilutions,
            transfer_volume=transfer_volume,
            transfer_liquid_class=transfer_liquid_class,
            transfer_tip_pool=transfer_tip_pool,
            transfer_asp_settings=transfer_asp_settings,
            transfer_disp_settings=transfer_disp_settings,
            mix_after_dispense=mix_after_dispense,
            reuse_tips=reuse_tips,
            discard_last_excess=discard_last_excess,
            waste_pos=waste_pos,
            optimized_tip_pickup=optimized_tip_pickup,
            diluent_records=diluent_records,
        )

    # Assemble the result.
    plate_results: list[SerialDilutionPlateResult] = []
    num_series = 0
    for pid in plate_ids:
        series = series_by_plate.get(pid, [])
        num_series += len(series)
        plate_results.append(
            SerialDilutionPlateResult(
                plate_id=pid,
                num_passes=len(plate_grids[pid].passes),
                series_results=tuple(series),
            )
        )

    return SerialDilutionResult(
        iterations=len(work_list),
        total_wells_processed=num_series * num_dilutions,
        plate_ids=tuple(plate_ids),
        num_series=num_series,
        num_dilutions=num_dilutions,
        diluent_volume=diluent_volume,
        transfer_volume=transfer_volume,
        dilution_factor=dilution_factor,
        reuse_tips=reuse_tips,
        mix_after_dispense=mix_after_dispense,
        diluent_multi_dispense=diluent_multi_dispense,
        discard_last_excess=discard_last_excess,
        diluent_sources_used=tuple(f"{s.labware}@{s.well}" for s in tracker.sources_used),
        plate_results=tuple(plate_results),
    )


def _run_diluent_phase(
    client: InstrumentClient,
    *,
    work_list: list[_WorkUnit],
    channels: list[int],
    diluent_volume: float,
    diluent_liquid_class: str | list[str],
    diluent_tip_pool: str,
    diluent_asp_settings: AspirateSettings | None,
    diluent_disp_settings: DispenseSettings | None,
    diluent_multi_dispense: bool,
    diluent_capacity: float,
    tracker: LiquidSourceTracker,
    diluent_channel_cap: int,
    optimized_tip_pickup: bool,
    diluent_records: dict[tuple[str, int], list[ChannelDispenseResponse]],
) -> None:
    """Pre-charge every dilution well with ``diluent_volume`` of buffer (§3.4, §3.5).

    Uses one clean diluent tip set for the whole phase (buffer is clean, Q-TIP3),
    picked up once on all *channels* and ejected at the phase boundary.  Per
    ``(plate, pass)`` unit the dilution columns are charged either with
    capacity/budget-bounded multi-dispense (default) or one aspirate per column.
    The shared *tracker* provides the active source and remaining budget and is
    updated from each aspirate's measured volume; a short aspirate tops the
    remaining columns up from the next source (Q-VOL1f).  One shared dispense
    response is recorded per ``(plate_id, pass_index)`` and dilution-column
    ordinal into *diluent_records*.

    When the diluent is a connected container with fewer positions than the pass
    has rows, *diluent_channel_cap* bounds how many channels aspirate at once; the
    pass rows are then charged in channel-sized sub-groups so every tip draws from
    a distinct position of the shared liquid rather than broadcasting all tips
    onto a single position (consistent with ``add_reagent``).
    """
    active = list(channels)
    picked_up = False
    try:
        pickup_tips(client, active, diluent_tip_pool, optimized=optimized_tip_pickup)
        picked_up = True
        for plate_id, spec, grid, pass_index in work_list:
            pass_rows = grid.passes[pass_index]
            # Charge the pass in channel-sized sub-groups.  With no connected
            # cap (group_size >= len(pass_rows)) this is a single group and the
            # behaviour is identical to the classic single-stroke path.
            group_size = min(diluent_channel_cap, len(pass_rows)) or len(pass_rows)
            unit_dispenses: list[ChannelDispenseResponse] = []
            for start in range(0, len(pass_rows), group_size):
                sub_rows = pass_rows[start : start + group_size]
                sub_channels = _pass_channels(channels, sub_rows)
                # One channel-row per dilution column: the sub-group wells at that column.
                column_rows: list[tuple[int, list[Position]]] = [
                    (ordinal, _pass_positions(spec, plate_id, sub_rows, column))
                    for ordinal, column in enumerate(grid.dilution_columns)
                ]
                unit_dispenses.extend(
                    _charge_unit(
                        client,
                        row_channels=sub_channels,
                        column_rows=column_rows,
                        diluent_volume=diluent_volume,
                        diluent_liquid_class=diluent_liquid_class,
                        diluent_asp_settings=diluent_asp_settings,
                        diluent_disp_settings=diluent_disp_settings,
                        diluent_multi_dispense=diluent_multi_dispense,
                        diluent_capacity=diluent_capacity,
                        tracker=tracker,
                    )
                )
            diluent_records[(plate_id, pass_index)] = unit_dispenses
    finally:
        if picked_up:
            try:
                eject_tips(client, active)
            except Exception as _e:
                _logger.warning("Failed to eject diluent tips on channels %s during cleanup: %s.", active, _e)


def _charge_unit(
    client: InstrumentClient,
    *,
    row_channels: list[int],
    column_rows: list[tuple[int, list[Position]]],
    diluent_volume: float,
    diluent_liquid_class: str | list[str],
    diluent_asp_settings: AspirateSettings | None,
    diluent_disp_settings: DispenseSettings | None,
    diluent_multi_dispense: bool,
    diluent_capacity: float,
    tracker: LiquidSourceTracker,
) -> list[ChannelDispenseResponse]:
    """Charge one ``(plate, pass)`` unit's dilution columns; return per-column dispenses.

    Columns are processed left-to-right in greedy aspiration batches
    (:func:`plan_dispense_batches`).  Each batch is bounded by the tip
    *capacity* and, from the second aspirate onward, the tracker's measured
    remaining budget, so a batch never plans to draw more than the active source
    can supply (§3.5, Q-VOL2a).  A short aspirate is handled reactively: the
    measured value overrides the estimate, so the *next* batch's
    :func:`ensure_liquid_available` advances to the next source, topping up the
    remaining columns (Q-VOL1f).
    """
    n = len(row_channels)
    sliced_asp = slice_settings(diluent_asp_settings, n)
    sliced_disp = slice_settings(diluent_disp_settings, n)
    dispenses: list[ChannelDispenseResponse] = []

    # Build one channel-row per dilution column carrying the per-channel diluent
    # volume, then group them into aspiration batches.  In single-dispense mode
    # every column is its own batch (one aspirate per column).
    planning_rows: list[list[tuple[Position, float]]] = [
        [(pos, diluent_volume) for pos in positions] for _ordinal, positions in column_rows
    ]
    if diluent_multi_dispense:
        budget = tracker.budget
        batches = plan_dispense_batches(planning_rows, diluent_capacity, budget)
    else:
        batches = [[row] for row in planning_rows]

    column_iter = iter(column_rows)
    for batch in batches:
        batch_total = diluent_volume * len(batch)
        _source, _budget = tracker.ensure_available(
            client,
            batch_total,
            command_name="serial_dilution",
        )
        # Spread channels across a connected diluent container's positions when
        # they fit; otherwise broadcast the single active position (classic).
        asp_positions = tracker.aspirate_plan(n)
        asp_resp = client.aspirate(
            channels=row_channels,
            positions=asp_positions,
            volumes=batch_total,
            liquid_class=diluent_liquid_class,
            settings=sliced_asp,
        )
        tracker.record_aspirate(asp_resp, measured_level=lld_enabled(sliced_asp))
        for _row in batch:
            _ordinal, positions = next(column_iter)
            disp_resp = client.dispense(
                channels=row_channels,
                positions=positions,
                volumes=diluent_volume,
                settings=sliced_disp,
            )
            dispenses.append(disp_resp)
            tracker.consume(diluent_volume)

    return dispenses


def _run_transfer_phase(
    client: InstrumentClient,
    *,
    work_list: list[_WorkUnit],
    channels: list[int],
    num_dilutions: int,
    transfer_volume: float,
    transfer_liquid_class: str | list[str],
    transfer_tip_pool: str,
    transfer_asp_settings: AspirateSettings | None,
    transfer_disp_settings: DispenseSettings | None,
    mix_after_dispense: bool,
    reuse_tips: bool,
    discard_last_excess: LastDilutionWaste,
    waste_pos: Position | None,
    optimized_tip_pickup: bool,
    diluent_records: dict[tuple[str, int], list[ChannelDispenseResponse]],
) -> dict[str, list[SerialDilutionSeriesResult]]:
    """Run every ``(plate, pass)`` transfer chain and build the series records.

    For each unit a fresh transfer tip set is mounted unless a set is being
    carried from the previous unit (``reuse_tips`` and not ``WITH_TIP_EJECT``,
    §5.6).  Each step ``k`` aspirates ``transfer_volume`` from column ``k`` and
    dispenses it (mix-suppressed) into column ``k + 1`` across the pass rows,
    optionally followed by a dedicated :func:`emit_final_mix` stroke.  After the
    final step the trailing excess is handled per *discard_last_excess*.  Every
    stroke is a single multi-channel call whose response is shared by the pass's
    sibling series; each series record references the shared responses with its
    own per-row well names.

    Returns:
        A mapping ``plate_id -> [SerialDilutionSeriesResult, ...]`` preserving
        work-list (pass) order.
    """
    do_mix = mix_after_dispense and mix_cycles_active(transfer_disp_settings)
    disp_for_transfer = override_mix_cycles(transfer_disp_settings, 0) if do_mix else transfer_disp_settings

    series_by_plate: dict[str, list[SerialDilutionSeriesResult]] = {}
    carried = False  # whether a transfer tip set is currently mounted
    active_carry: list[int] = []  # channels the carried set occupies

    try:
        for plate_id, spec, grid, pass_index in work_list:
            pass_rows = grid.passes[pass_index]
            row_channels = _pass_channels(channels, pass_rows)
            n = len(row_channels)

            if carried and active_carry != row_channels:
                # A carried set was picked up for a wider pass than the current
                # one; eject and re-pick to match this pass's channel count.
                _safe_eject(client, active_carry)
                carried = False
            if not carried:
                pickup_tips(client, row_channels, transfer_tip_pool, optimized=optimized_tip_pickup)
                carried = True
                active_carry = row_channels

            sliced_asp = slice_settings(transfer_asp_settings, n)
            sliced_disp = slice_settings(disp_for_transfer, n)

            # One shared step response set per pass; per-row well names differ.
            step_asps: list[ChannelAspirationResponse] = []
            step_disps: list[ChannelDispenseResponse] = []
            step_mixes: list[ChannelDispenseResponse | None] = []
            for k in range(num_dilutions):
                src_col = grid.column_sequence[k]
                dst_col = grid.column_sequence[k + 1]
                src_positions = _pass_positions(spec, plate_id, pass_rows, src_col)
                dst_positions = _pass_positions(spec, plate_id, pass_rows, dst_col)
                asp_resp = client.aspirate(
                    channels=row_channels,
                    positions=src_positions,
                    volumes=transfer_volume,
                    liquid_class=transfer_liquid_class,
                    settings=sliced_asp,
                )
                disp_resp = client.dispense(
                    channels=row_channels,
                    positions=dst_positions,
                    volumes=transfer_volume,
                    settings=sliced_disp,
                )
                mix_resp: ChannelDispenseResponse | None = None
                if do_mix:
                    mix_resp = emit_final_mix(
                        client,
                        dst_positions,
                        row_channels,
                        transfer_disp_settings,
                    )
                step_asps.append(asp_resp)
                step_disps.append(disp_resp)
                step_mixes.append(mix_resp)

            # Trailing excess in the final dilution column (§3.3).
            excess_asp, excess_disp, eject_after = _handle_last_excess(
                client,
                spec=spec,
                plate_id=plate_id,
                pass_rows=pass_rows,
                row_channels=row_channels,
                final_column=grid.column_sequence[-1],
                transfer_volume=transfer_volume,
                transfer_liquid_class=transfer_liquid_class,
                transfer_asp_settings=sliced_asp,
                transfer_disp_settings=sliced_disp,
                discard_last_excess=discard_last_excess,
                waste_pos=waste_pos,
            )

            # Assemble one series record per active row of this pass.
            plate_series = series_by_plate.setdefault(plate_id, [])
            for row_offset, row_index in enumerate(pass_rows):
                channel = channels[row_offset]
                well_chain = tuple(_well(spec, plate_id, row_index, col).well for col in grid.column_sequence)
                steps: list[SerialDilutionStepResult] = []
                for k in range(num_dilutions):
                    steps.append(
                        SerialDilutionStepResult(
                            step_index=k,
                            source_well=_well(spec, plate_id, row_index, grid.column_sequence[k]).well,
                            dest_well=_well(spec, plate_id, row_index, grid.column_sequence[k + 1]).well,
                            aspirate=step_asps[k],
                            dispense=step_disps[k],
                            mix=step_mixes[k],
                        )
                    )
                if excess_asp is not None:
                    steps.append(
                        SerialDilutionStepResult(
                            step_index=num_dilutions,
                            source_well=_well(spec, plate_id, row_index, grid.column_sequence[-1]).well,
                            dest_well=(waste_pos.well if excess_disp is not None and waste_pos is not None else ""),
                            aspirate=excess_asp,
                            dispense=excess_disp,
                            mix=None,
                        )
                    )
                plate_series.append(
                    SerialDilutionSeriesResult(
                        channel=channel,
                        # Physical-row descriptor: always the alphabetic label
                        # (e.g. "A") for the plate row, independent of whether
                        # the labware emits numeric or alphanumeric well ids.
                        row=spec.row_labels[row_index],
                        pass_index=pass_index,
                        well_chain=well_chain,
                        diluent_dispenses=tuple(diluent_records.get((plate_id, pass_index), [])),
                        steps=tuple(steps),
                        last_excess=discard_last_excess,
                    )
                )

            # Decide whether to keep the tips for the next unit (§5.6).  The
            # transfer set is dropped after this unit when the excess left with
            # the tips (WITH_TIP_EJECT) or the caller did not opt into reuse.
            if eject_after or not reuse_tips:
                _safe_eject(client, active_carry)
                carried = False
    finally:
        if carried:
            _safe_eject(client, active_carry)

    return series_by_plate


def _handle_last_excess(
    client: InstrumentClient,
    *,
    spec: LabwareLayoutSpec,
    plate_id: str,
    pass_rows: list[int],
    row_channels: list[int],
    final_column: int,
    transfer_volume: float,
    transfer_liquid_class: str | list[str],
    transfer_asp_settings: AspirateSettings | None,
    transfer_disp_settings: DispenseSettings | None,
    discard_last_excess: LastDilutionWaste,
    waste_pos: Position | None,
) -> tuple[ChannelAspirationResponse | None, ChannelDispenseResponse | None, bool]:
    """Dispose of the trailing ``transfer_volume`` in the final well (§3.3).

    Returns ``(aspirate, dispense, eject_after)`` where *eject_after* is
    ``True`` only for ``WITH_TIP_EJECT`` (the retained excess leaves with the
    tips, forcing a fresh set for the next unit).  ``NONE`` issues no stroke.
    """
    if discard_last_excess == LastDilutionWaste.NONE:
        return None, None, False

    final_positions = _pass_positions(spec, plate_id, pass_rows, final_column)
    asp_resp = client.aspirate(
        channels=row_channels,
        positions=final_positions,
        volumes=transfer_volume,
        liquid_class=transfer_liquid_class,
        settings=transfer_asp_settings,
    )
    if discard_last_excess == LastDilutionWaste.WITH_TIP_EJECT:
        # Keep the liquid in the tips and eject; no dispense is issued.
        return asp_resp, None, True

    # TO_WASTE: dispense the excess to the shared waste position (broadcast).
    if waste_pos is None:
        raise ValueError("waste_pos is required for TO_WASTE disposal but was not resolved.")
    disp_resp = client.dispense(
        channels=row_channels,
        positions=[waste_pos] * len(row_channels),
        volumes=transfer_volume,
        settings=transfer_disp_settings,
    )
    return asp_resp, disp_resp, False


def _safe_eject(client: InstrumentClient, channels: list[int]) -> None:
    """Eject tips on *channels*, logging (not raising) on failure."""
    if not channels:
        return
    try:
        eject_tips(client, channels)
    except Exception as _e:
        _logger.warning("Failed to eject transfer tips on channels %s during cleanup: %s.", channels, _e)


def execute_serial_dilution_by_volume(
    client: InstrumentClient,
    *,
    plate_id: str | list[str] | Position | list[Position],
    start_column: int,
    num_dilutions: int,
    transfer_volume: float,
    diluent_volume: float,
    diluent_source: str | list[str],
    diluent_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
    diluent_tip_pool: str = "",
    transfer_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
    transfer_tip_pool: str,
    channels: list[int] | None = None,
    exclude_columns: list[int] | None = None,
    exclude_rows: list[int | str] | None = None,
    mix_after_dispense: bool = True,
    diluent_multi_dispense: bool = True,
    reuse_tips: bool = False,
    discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
    waste_location: str | None = None,
    optimized_tip_pickup: bool = True,
    diluent_asp_settings: AspirateSettings | None = None,
    diluent_disp_settings: DispenseSettings | None = None,
    transfer_asp_settings: AspirateSettings | None = None,
    transfer_disp_settings: DispenseSettings | None = None,
    diluent_error_profile: ErrorProfile | None = None,
    transfer_error_profile: ErrorProfile | None = None,
) -> SerialDilutionResult:
    """Serial-dilute across plate columns using an explicit per-well diluent volume.

    One independent dilution series is run per plate row, with the active rows of
    each pass processed in parallel on the multi-channel head.  Samples are
    assumed pre-loaded at ``start_column``.  The run has two globally ordered
    phases (§3.7): every ``(plate, pass)`` unit is diluent-pre-charged first,
    then all transfer chains execute.  See
    :func:`execute_serial_dilution_by_dilution_factor` for the variant that
    derives the diluent volume from a target dilution factor.

    Args:
        client: Connected instrument client used to issue hardware commands.
        plate_id: Plate selector string or a list of selectors (multi-plate);
            plates are processed sequentially and share the diluent source, tips
            (when ``reuse_tips``) and waste location. May also be a
            pre-resolved ``Position``/``list[Position]``.
        start_column: 1-based column holding the pre-loaded sample.
        num_dilutions: Number of dilution steps (transfers); must be ``>= 1``.
        transfer_volume: Per-channel volume carried between wells in the series.
        diluent_volume: Per-well diluent pre-charge volume.  ``0`` skips the
            diluent phase entirely (a pure transfer chain).
        diluent_source: One or more diluent source selectors, drained in order
            with reactive volume tracking and operator-prompted reload.
        diluent_liquid_class: Liquid class(es) for the diluent pre-charge.
        diluent_tip_pool: Tip pool for the diluent phase.  Required (non-empty)
            whenever ``diluent_volume > 0``.
        transfer_liquid_class: Liquid class(es) for the transfer chain.
        transfer_tip_pool: Tip pool for the transfer phase.  Required.
        channels: 1-indexed channels to use (default 1-8).  Active rows beyond
            ``len(channels)`` are processed in additional passes.
        exclude_columns: 1-based columns to skip during traversal (they do not
            consume a dilution step).
        exclude_rows: Rows to exclude, given as 1-based ints and/or letters.
        mix_after_dispense: When ``True`` (default) and the transfer dispense
            settings request mix cycles, a dedicated mix stroke follows each
            transfer dispense.  The diluent pre-charge never mixes.
        diluent_multi_dispense: When ``True`` (default) the diluent phase
            aspirates a capacity/budget-bounded batch feeding several columns;
            when ``False`` it aspirates once per column.
        reuse_tips: When ``True`` the transfer tip set is kept mounted across
            passes and plates (fast, accepts cross-pass contamination); when
            ``False`` a fresh transfer set is picked up per pass.  Never bridges
            the diluent and transfer phases.
        discard_last_excess: How to dispose of the trailing ``transfer_volume``
            left in the final dilution well.
        waste_location: Explicit waste selector for ``TO_WASTE``; ``None`` falls
            back to the deck's fixed ``liquid_waste`` labware.
        optimized_tip_pickup: Forwarded to tip pickup.
        diluent_asp_settings: Optional aspirate settings for the diluent phase.
        diluent_disp_settings: Optional dispense settings for the diluent phase.
        transfer_asp_settings: Optional aspirate settings for the transfer phase.
        transfer_disp_settings: Optional dispense settings for the transfer
            phase; mix fields are overridden per the ``mix_after_dispense`` rule.
        diluent_error_profile: Optional scoped error profile for the diluent
            phase.
        transfer_error_profile: Optional scoped error profile for the transfer
            phase.

    Returns:
        A :class:`SerialDilutionResult` aggregating per-plate, per-series, and
        per-step responses.

    Raises:
        ValueError: Any validation failure (see :func:`_execute_serial_dilution`).
        OperatorCancelledError: The operator cancelled a tip or liquid reload.
    """
    return _execute_serial_dilution(
        client,
        plate_id=plate_id,
        start_column=start_column,
        num_dilutions=num_dilutions,
        transfer_volume=transfer_volume,
        diluent_volume=diluent_volume,
        diluent_source=diluent_source,
        diluent_liquid_class=diluent_liquid_class,
        diluent_tip_pool=diluent_tip_pool,
        transfer_liquid_class=transfer_liquid_class,
        transfer_tip_pool=transfer_tip_pool,
        channels=channels,
        exclude_columns=exclude_columns,
        exclude_rows=exclude_rows,
        mix_after_dispense=mix_after_dispense,
        diluent_multi_dispense=diluent_multi_dispense,
        reuse_tips=reuse_tips,
        discard_last_excess=discard_last_excess,
        waste_location=waste_location,
        optimized_tip_pickup=optimized_tip_pickup,
        diluent_asp_settings=diluent_asp_settings,
        diluent_disp_settings=diluent_disp_settings,
        transfer_asp_settings=transfer_asp_settings,
        transfer_disp_settings=transfer_disp_settings,
        diluent_error_profile=diluent_error_profile,
        transfer_error_profile=transfer_error_profile,
        dilution_factor=None,
    )


def execute_serial_dilution_by_dilution_factor(
    client: InstrumentClient,
    *,
    plate_id: str | list[str] | Position | list[Position],
    start_column: int,
    num_dilutions: int,
    transfer_volume: float,
    dilution_factor: float,
    diluent_source: str | list[str],
    diluent_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
    diluent_tip_pool: str = "",
    transfer_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
    transfer_tip_pool: str,
    channels: list[int] | None = None,
    exclude_columns: list[int] | None = None,
    exclude_rows: list[int | str] | None = None,
    mix_after_dispense: bool = True,
    diluent_multi_dispense: bool = True,
    reuse_tips: bool = False,
    discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
    waste_location: str | None = None,
    optimized_tip_pickup: bool = True,
    diluent_asp_settings: AspirateSettings | None = None,
    diluent_disp_settings: DispenseSettings | None = None,
    transfer_asp_settings: AspirateSettings | None = None,
    transfer_disp_settings: DispenseSettings | None = None,
    diluent_error_profile: ErrorProfile | None = None,
    transfer_error_profile: ErrorProfile | None = None,
) -> SerialDilutionResult:
    """Serial-dilute across plate columns using a target *dilution_factor*.

    Identical to :func:`execute_serial_dilution_by_volume` except the per-well
    diluent volume is derived from the fold dilution:
    ``diluent_volume = transfer_volume * (dilution_factor - 1)``.  For example a
    10-fold dilution with a 20 µL transfer pre-charges each well with 180 µL of
    diluent.  ``dilution_factor`` must be ``>= 1`` (a factor of ``1`` yields a
    zero diluent volume and skips the diluent phase).

    Args:
        client: Connected instrument client used to issue hardware commands.
        plate_id: Plate selector string or a list of selectors (multi-plate).
            May also be a pre-resolved ``Position``/``list[Position]``.
        start_column: 1-based column holding the pre-loaded sample.
        num_dilutions: Number of dilution steps (transfers); must be ``>= 1``.
        transfer_volume: Per-channel volume carried between wells in the series.
        dilution_factor: Target fold dilution per step; must be ``>= 1``.  The
            per-well diluent volume is ``transfer_volume * (dilution_factor - 1)``.
        diluent_source: One or more diluent source selectors, drained in order.
        diluent_liquid_class: Liquid class(es) for the diluent pre-charge.
        diluent_tip_pool: Tip pool for the diluent phase.  Required (non-empty)
            unless ``dilution_factor`` yields a zero diluent volume.
        transfer_liquid_class: Liquid class(es) for the transfer chain.
        transfer_tip_pool: Tip pool for the transfer phase.  Required.
        channels: 1-indexed channels to use (default 1-8).
        exclude_columns: 1-based columns to skip during traversal.
        exclude_rows: Rows to exclude, given as 1-based ints and/or letters.
        mix_after_dispense: See :func:`execute_serial_dilution_by_volume`.
        diluent_multi_dispense: See :func:`execute_serial_dilution_by_volume`.
        reuse_tips: See :func:`execute_serial_dilution_by_volume`.
        discard_last_excess: See :func:`execute_serial_dilution_by_volume`.
        waste_location: See :func:`execute_serial_dilution_by_volume`.
        optimized_tip_pickup: Forwarded to tip pickup.
        diluent_asp_settings: Optional aspirate settings for the diluent phase.
        diluent_disp_settings: Optional dispense settings for the diluent phase.
        transfer_asp_settings: Optional aspirate settings for the transfer phase.
        transfer_disp_settings: Optional dispense settings for the transfer phase.
        diluent_error_profile: Optional scoped error profile for the diluent phase.
        transfer_error_profile: Optional scoped error profile for the transfer phase.

    Returns:
        A :class:`SerialDilutionResult` whose ``dilution_factor`` field records
        the requested fold dilution.

    Raises:
        ValueError: Any validation failure, including ``dilution_factor < 1``.
        OperatorCancelledError: The operator cancelled a tip or liquid reload.
    """
    diluent_volume = transfer_volume * (dilution_factor - 1)
    return _execute_serial_dilution(
        client,
        plate_id=plate_id,
        start_column=start_column,
        num_dilutions=num_dilutions,
        transfer_volume=transfer_volume,
        diluent_volume=diluent_volume,
        diluent_source=diluent_source,
        diluent_liquid_class=diluent_liquid_class,
        diluent_tip_pool=diluent_tip_pool,
        transfer_liquid_class=transfer_liquid_class,
        transfer_tip_pool=transfer_tip_pool,
        channels=channels,
        exclude_columns=exclude_columns,
        exclude_rows=exclude_rows,
        mix_after_dispense=mix_after_dispense,
        diluent_multi_dispense=diluent_multi_dispense,
        reuse_tips=reuse_tips,
        discard_last_excess=discard_last_excess,
        waste_location=waste_location,
        optimized_tip_pickup=optimized_tip_pickup,
        diluent_asp_settings=diluent_asp_settings,
        diluent_disp_settings=diluent_disp_settings,
        transfer_asp_settings=transfer_asp_settings,
        transfer_disp_settings=transfer_disp_settings,
        diluent_error_profile=diluent_error_profile,
        transfer_error_profile=transfer_error_profile,
        dilution_factor=dilution_factor,
    )
