from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse, ChannelTADMCurve
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.enums import LastDilutionWaste


def _extend_tadm_curves(
    curves: list[ChannelTADMCurve],
    *responses: ChannelAspirationResponse | ChannelDispenseResponse | None,
) -> None:
    """Append every TADM curve carried by *responses* into *curves* in place.

    Each response may be ``None`` (e.g. optional aliquot dispenses) and may
    have no TADM payload; both cases are silently skipped.  Shared by the
    ``tadm_curves`` properties on the various result models so the per-curve
    extraction logic lives in exactly one place.
    """
    for resp in responses:
        if resp is None:
            continue
        tadm = resp.return_parameters.tadm
        if tadm is not None:
            curves.extend(tadm.tadm_curves)


class CompoundCommandResult(BaseModel):
    """Base result model for compound commands."""

    model_config = ConfigDict(frozen=True)

    iterations: int
    total_wells_processed: int


class CopyPlateIterationResult(BaseModel):
    """Typed command responses for a single batch iteration of a copy-plate operation."""

    model_config = ConfigDict(frozen=True)

    tip_pickup: CommandResponse | None = None
    aspirate: ChannelAspirationResponse
    dispense: ChannelDispenseResponse
    tip_eject: CommandResponse | None = None


class CopyPlateResult(CompoundCommandResult):
    """Result of a :func:`~hamilton_venus.compounds.copy_plate.execute_copy_plate` operation."""

    source_plate_id: str
    dest_plate_ids: tuple[str, ...]
    wells_copied: int
    wells_skipped: int = 0
    iteration_results: tuple[CopyPlateIterationResult, ...]

    @property
    def dest_plate_id(self) -> str:
        """Backward-compatible alias for the first destination plate id.

        Use :attr:`dest_plate_ids` when multiple destination plates are involved.
        """
        return self.dest_plate_ids[0]

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.
        """
        curves: list[ChannelTADMCurve] = []
        for it in self.iteration_results:
            _extend_tadm_curves(curves, it.aspirate, it.dispense)
        return curves


class AddReagentWellDispense(BaseModel):
    """One per-well dispense recorded within an ``add_reagent`` aspiration."""

    model_config = ConfigDict(frozen=True)

    dest_plate_id: str
    dest_well: str
    response: ChannelDispenseResponse


class AddReagentIterationResult(BaseModel):
    """One aspirate + its associated dispenses (pre-aliquot, wells, post-aliquot).

    ``tip_pickup`` is populated only on the first iteration of a source block
    (a span of iterations sharing the same source plate); ``tip_eject`` is
    populated only on the last iteration of a source block. For single-dispense mode each
    chunk is its own source block.
    """

    model_config = ConfigDict(frozen=True)

    source_plate_id: str
    tip_pickup: CommandResponse | None = None
    aspirate: ChannelAspirationResponse
    pre_aliquot_dispense: ChannelDispenseResponse | None = None
    well_dispenses: tuple[AddReagentWellDispense, ...]
    post_aliquot_dispense: ChannelDispenseResponse | None = None
    tip_eject: CommandResponse | None = None


class AddReagentResult(CompoundCommandResult):
    """Result of an :func:`~hamilton_venus.compound_commands.add_reagent.execute_add_reagent` operation.

    Inherits ``iterations`` and ``total_wells_processed`` from
    :class:`CompoundCommandResult`. ``total_wells_processed`` equals
    ``wells_filled`` for this command.

    ``wells_filled`` counts dispense events, not distinct wells: if a CSV-driven
    run dispenses to the same destination well twice, it is counted twice.

    ``sources_used`` lists the reagent source containers in order of consumption
    across the whole run (consumable liquid management drains multiple sources in
    order as each is exhausted).
    """

    source_plate_ids: tuple[str, ...]
    dest_plate_ids: tuple[str, ...]
    multi_dispense: bool
    wells_filled: int
    wells_filled_by_plate: dict[str, int]
    sources_used: tuple[str, ...] = ()
    iteration_results: tuple[AddReagentIterationResult, ...]

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.
        """
        curves: list[ChannelTADMCurve] = []
        for it in self.iteration_results:
            _extend_tadm_curves(curves, it.aspirate, it.pre_aliquot_dispense)
            for wd in it.well_dispenses:
                _extend_tadm_curves(curves, wd.response)
            _extend_tadm_curves(curves, it.post_aliquot_dispense)
        return curves


class HitPickingTransferResult(BaseModel):
    """One source->dest transfer within a hit-picking operation."""

    model_config = ConfigDict(frozen=True)

    source_plate_id: str
    source_well: str
    dest_plate_id: str
    dest_well: str
    volume: float
    aspirate: ChannelAspirationResponse
    dispense: ChannelDispenseResponse


class HitPickingResult(CompoundCommandResult):
    """Result of a :func:`~hamilton_venus.compound_commands.hit_picking.execute_hit_picking` operation.

    Inherits ``iterations`` and ``total_wells_processed`` from
    :class:`CompoundCommandResult`. ``iterations`` equals the number of
    aspirate/dispense calls issued (matching ``add_reagent`` and
    ``copy_plate``); in the default ``change_tips=True, minimize_tips=False``
    mode this equals the number of tip blocks, while in tip-reuse and
    ``minimize_tips`` modes a single tip block may produce several aspirate
    calls (one per channel-sized chunk).  ``total_wells_processed`` equals
    ``len(transfers)`` (the CSV row count, since validation failures raise
    before any liquid handling).

    Each transfer is recorded individually in the flat ``transfers`` tuple, in
    execution order; ``transfers`` counts transfer events, not distinct wells,
    so multiple transfers to the same destination well are counted separately.
    The ``transfers_by_source_plate`` and ``transfers_by_dest_plate`` maps give
    quick per-plate transfer counts (keys ordered by first appearance).
    """

    source_plate_ids: tuple[str, ...]
    dest_plate_ids: tuple[str, ...]
    transfers: tuple[HitPickingTransferResult, ...]
    transfers_by_source_plate: dict[str, int]
    transfers_by_dest_plate: dict[str, int]
    tips_consumed: int
    minimize_tips: bool
    change_tips: bool

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.

        Within each channel-sized chunk, all ``HitPickingTransferResult`` entries
        share the same aspirate/dispense response objects (one multi-channel call
        per chunk).  Deduplication by response identity ensures each
        aspirate/dispense response is counted exactly once regardless of chunk size.
        """
        curves: list[ChannelTADMCurve] = []
        seen: set[int] = set()
        for t in self.transfers:
            for resp in (t.aspirate, t.dispense):
                rid = id(resp)
                if rid not in seen:
                    seen.add(rid)
                    _extend_tadm_curves(curves, resp)
        return curves


class PoolSamplesIterationResult(BaseModel):
    """One pool's worth of liquid handling within a ``pool_samples`` operation.

    A pool combines ``len(source_wells)`` source wells into a single destination
    well.  The recorded responses cover every aspirate/dispense the head issues
    while processing this pool, plus any tip pickups and ejects that bracketed
    the work.  ``mix_after`` carries the optional trailing zero-volume dispense
    used to mix the destination well when ``mix_after_pool=True``.
    """

    model_config = ConfigDict(frozen=True)

    source_plate_ids: tuple[str, ...]
    dest_plate_id: str
    dest_well: str
    source_wells: tuple[str, ...]
    pool_size: int
    tip_pickups: tuple[CommandResponse, ...]
    aspirates: tuple[ChannelAspirationResponse, ...]
    dispenses: tuple[ChannelDispenseResponse, ...]
    mix_after: ChannelDispenseResponse | None = None
    tip_ejects: tuple[CommandResponse, ...]


class PoolSamplesResult(CompoundCommandResult):
    """Result of a :func:`~hamilton_venus.compound_commands.pool_samples.execute_pool_samples` operation.

    Inherits ``iterations`` and ``total_wells_processed`` from
    :class:`CompoundCommandResult`.  ``iterations`` equals the number of pools
    executed (``len(iteration_results)``) and ``total_wells_processed`` equals
    ``wells_pooled`` (the total number of source wells aspirated across all
    pools, including any short final pool).
    """

    source_plate_ids: tuple[str, ...]
    dest_plate_ids: tuple[str, ...]
    pools_completed: int
    wells_pooled: int
    mix_after_pool: bool
    reuse_tips_within_pool: bool
    iteration_results: tuple[PoolSamplesIterationResult, ...]

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.

        No response-identity deduplication is needed here: every aspirate and
        dispense call in ``pool_samples`` produces an independent response
        object (there is no multi-channel chunking that shares a single
        response across multiple iteration boundaries, unlike
        :class:`ReplicateSamplesResult` and :class:`HitPickingResult`).
        """
        curves: list[ChannelTADMCurve] = []
        for it in self.iteration_results:
            _extend_tadm_curves(curves, *it.aspirates)
            _extend_tadm_curves(curves, *it.dispenses)
            _extend_tadm_curves(curves, it.mix_after)
        return curves


class ReplicateSamplesIterationResult(BaseModel):
    """One source-well's worth (multi-dispense) or one transfer (single-dispense) of a ``replicate_samples`` operation.

    In ``multi_dispense=True`` mode each source well produces one iteration that
    aggregates the aspirate, the per-replicate dispenses, and any pre/post
    aliquot dispenses.  ``aspirates`` and ``replicate_dispenses`` are tuples
    because a single source may be split across multiple aspirations when the
    per-source total exceeds tip capacity (auto-split).

    In ``multi_dispense=False`` mode each individual source->dest transfer is
    its own iteration; ``aspirates`` and ``replicate_dispenses`` each contain a
    single element and the aliquot fields are ``None``.
    """

    model_config = ConfigDict(frozen=True)

    source_plate_id: str
    source_well: str
    dest_plate_ids: tuple[str, ...]
    dest_wells: tuple[str, ...]
    multi_dispense: bool
    tip_pickup: CommandResponse | None = None
    aspirates: tuple[ChannelAspirationResponse, ...]
    pre_aliquot_dispense: ChannelDispenseResponse | None = None
    replicate_dispenses: tuple[ChannelDispenseResponse, ...]
    post_aliquot_dispense: ChannelDispenseResponse | None = None
    tip_eject: CommandResponse | None = None


class ReplicateSamplesResult(CompoundCommandResult):
    """Result of a :func:`~hamilton_venus.compound_commands.replicate_samples.execute_replicate_samples` operation.

    Inherits ``iterations`` and ``total_wells_processed`` from
    :class:`CompoundCommandResult`.  ``total_wells_processed`` equals
    ``replicates_filled`` (the total number of destination dispense events).

    In ``multi_dispense=True`` mode ``iterations`` equals
    ``sources_processed`` (one iteration per source).  In
    ``multi_dispense=False`` mode ``iterations`` equals ``replicates_filled``
    (one iteration per source->dest transfer).  ``aspirate``/``dispense``
    responses recorded across iterations may be shared when the multi-channel
    head executes several channels in parallel; ``tadm_curves`` deduplicates
    by response identity.
    """

    source_plate_ids: tuple[str, ...]
    dest_plate_ids: tuple[str, ...]
    multi_dispense: bool
    sources_processed: int
    replicates_filled: int
    iteration_results: tuple[ReplicateSamplesIterationResult, ...]

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.

        Multi-channel responses shared across iterations (e.g. single-dispense mode
        channel-row chunks where ``n_ch`` transfers share one aspirate response)
        are deduplicated by response identity so each curve appears exactly once.
        """
        curves: list[ChannelTADMCurve] = []
        seen: set[int] = set()
        for it in self.iteration_results:
            for resp in (
                *it.aspirates,
                it.pre_aliquot_dispense,
                *it.replicate_dispenses,
                it.post_aliquot_dispense,
            ):
                if resp is None:
                    continue
                rid = id(resp)
                if rid in seen:
                    continue
                seen.add(rid)
                _extend_tadm_curves(curves, resp)
        return curves


class SerialDilutionStepResult(BaseModel):
    """One transfer step within a single serial-dilution series.

    A step carries ``transfer_volume`` from ``source_well`` into ``dest_well``
    (the next column in the chain) with a mix-suppressed dispense, optionally
    followed by a dedicated mix stroke.  Because every step is a single
    multi-channel stroke across all active rows of a pass, the ``aspirate`` /
    ``dispense`` / ``mix`` response objects are shared by the sibling series of
    the same pass; :attr:`SerialDilutionResult.tadm_curves` deduplicates by
    response identity so each curve is counted once.
    """

    model_config = ConfigDict(frozen=True)

    step_index: int
    source_well: str
    dest_well: str
    aspirate: ChannelAspirationResponse
    # ``None`` only for the trailing excess-removal step under
    # ``LastDilutionWaste.WITH_TIP_EJECT``, which aspirates the excess and ejects
    # it with the tips (no dispense is issued).  Normal transfer steps always
    # set this.
    dispense: ChannelDispenseResponse | None = None
    mix: ChannelDispenseResponse | None = None


class SerialDilutionSeriesResult(BaseModel):
    """One independent dilution series (a single active row) within a plate pass.

    ``well_chain`` lists the wells the series touches in order: the pre-loaded
    sample column followed by the ``num_dilutions`` dilution columns.
    ``diluent_dispenses`` records the per-well diluent pre-charge for this
    series' dilution columns, and ``steps`` records the transfer chain.
    ``last_excess`` echoes how the trailing excess in the final well was
    handled (see :class:`~hamilton_venus.models.enums.LastDilutionWaste`).
    """

    model_config = ConfigDict(frozen=True)

    channel: int
    row: str
    pass_index: int
    well_chain: tuple[str, ...]
    diluent_dispenses: tuple[ChannelDispenseResponse, ...]
    steps: tuple[SerialDilutionStepResult, ...]
    last_excess: LastDilutionWaste


class SerialDilutionPlateResult(BaseModel):
    """All dilution series performed on a single plate, grouped for inspection.

    A plate is processed in ``num_passes`` passes of at most ``len(channels)``
    rows each (multi-pass handling for plates with more active rows than
    channels); ``series_results`` aggregates every series across those passes.
    """

    model_config = ConfigDict(frozen=True)

    plate_id: str
    num_passes: int
    series_results: tuple[SerialDilutionSeriesResult, ...]


class SerialDilutionResult(CompoundCommandResult):
    """Result of a serial-dilution compound command (by-volume or by-factor).

    Inherits ``iterations`` and ``total_wells_processed`` from
    :class:`CompoundCommandResult`.  ``total_wells_processed`` equals
    ``num_series * num_dilutions`` — the count of transfer-step destination
    wells across every series.  It deliberately excludes the pre-loaded sample
    column and the diluent pre-charge dispenses (each dilution well is
    pre-charged once *and* receives one transfer, so counting only transfers
    avoids double counting).  This differs from ``add_reagent``'s
    ``wells_filled`` semantics.

    ``dilution_factor`` is populated only for the by-dilution-factor command
    (``None`` for by-volume).  ``diluent_sources_used`` lists the diluent
    sources in order of consumption across the whole run.
    """

    plate_ids: tuple[str, ...]
    num_series: int
    num_dilutions: int
    diluent_volume: float
    transfer_volume: float
    dilution_factor: float | None
    reuse_tips: bool
    mix_after_dispense: bool
    diluent_multi_dispense: bool
    discard_last_excess: LastDilutionWaste
    diluent_sources_used: tuple[str, ...]
    plate_results: tuple[SerialDilutionPlateResult, ...]

    @property
    def tadm_curves(self) -> list[ChannelTADMCurve]:
        """Flat list of all TADM curves from every aspirate and dispense in the operation.

        Returns an empty list if no TADM data was provided by the instrument.

        Each transfer step and diluent pre-charge is a single multi-channel
        stroke whose response object is shared by the sibling series of the
        same pass, so responses are deduplicated by identity to ensure every
        curve appears exactly once.
        """
        curves: list[ChannelTADMCurve] = []
        seen: set[int] = set()
        for plate in self.plate_results:
            for series in plate.series_results:
                for resp in (
                    *series.diluent_dispenses,
                    *(r for step in series.steps for r in (step.aspirate, step.dispense, step.mix)),
                ):
                    if resp is None:
                        continue
                    rid = id(resp)
                    if rid in seen:
                        continue
                    seen.add(rid)
                    _extend_tadm_curves(curves, resp)
        return curves
