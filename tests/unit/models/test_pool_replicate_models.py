from __future__ import annotations

import pytest
from pydantic import ValidationError

from hamilton_venus.models.command_types import (
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelTADM,
    ChannelTADMCurve,
)
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import (
    CompoundCommandResult,
    PoolSamplesIterationResult,
    PoolSamplesResult,
    ReplicateSamplesIterationResult,
    ReplicateSamplesResult,
)


def _aspirate(tadm: ChannelTADM | None = None) -> ChannelAspirationResponse:
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={
            "channels": [],
            **({"TADM": tadm.model_dump(by_alias=True)} if tadm is not None else {}),
        },
    )


def _dispense(tadm: ChannelTADM | None = None) -> ChannelDispenseResponse:
    return ChannelDispenseResponse(
        return_status="Success",
        return_code=0,
        return_parameters={
            "channels": [],
            **({"TADM": tadm.model_dump(by_alias=True)} if tadm is not None else {}),
        },
    )


def _ok() -> CommandResponse:
    return CommandResponse(return_status="Success", return_code=0, return_parameters={})


def _tadm(label: str) -> ChannelTADM:
    return ChannelTADM(tadm_curves=[ChannelTADMCurve(curve_id=1, step_type_name=label)])


# -------- Pool samples --------


def _pool_iter(
    *,
    source_wells: tuple[str, ...] = ("A1", "A2", "A3", "A4"),
    dest_well: str = "A1",
    asp_tadms: list[ChannelTADM | None] | None = None,
    disp_tadms: list[ChannelTADM | None] | None = None,
    mix_tadm: ChannelTADM | None = None,
    include_mix: bool = False,
) -> PoolSamplesIterationResult:
    asp_tadms = asp_tadms if asp_tadms is not None else [None] * len(source_wells)
    disp_tadms = disp_tadms if disp_tadms is not None else [None] * len(source_wells)
    return PoolSamplesIterationResult(
        source_plate_ids=("Source1",),
        dest_plate_id="Dest1",
        dest_well=dest_well,
        source_wells=source_wells,
        pool_size=len(source_wells),
        tip_pickups=(_ok(),),
        aspirates=tuple(_aspirate(tadm=t) for t in asp_tadms),
        dispenses=tuple(_dispense(tadm=t) for t in disp_tadms),
        mix_after=_dispense(tadm=mix_tadm) if include_mix else None,
        tip_ejects=(_ok(),),
    )


def _pool_result(
    iters: list[PoolSamplesIterationResult],
    *,
    mix_after_pool: bool = False,
    reuse_tips_within_pool: bool = False,
) -> PoolSamplesResult:
    src = tuple({pid: None for it in iters for pid in it.source_plate_ids})
    dst = tuple({it.dest_plate_id: None for it in iters})
    wells = sum(it.pool_size for it in iters)
    return PoolSamplesResult(
        iterations=len(iters),
        total_wells_processed=wells,
        source_plate_ids=src,
        dest_plate_ids=dst,
        pools_completed=len(iters),
        wells_pooled=wells,
        mix_after_pool=mix_after_pool,
        reuse_tips_within_pool=reuse_tips_within_pool,
        iteration_results=tuple(iters),
    )


class TestPoolSamplesIterationResult:
    def test_construction(self):
        it = _pool_iter()
        assert it.pool_size == 4
        assert it.source_wells == ("A1", "A2", "A3", "A4")
        assert it.mix_after is None
        assert len(it.aspirates) == 4
        assert len(it.dispenses) == 4

    def test_frozen(self):
        it = _pool_iter()
        with pytest.raises(ValidationError):
            it.dest_well = "Z9"  # type: ignore[misc]


class TestPoolSamplesResult:
    def test_inherits_compound_result(self):
        result = _pool_result([_pool_iter()])
        assert isinstance(result, CompoundCommandResult)
        assert result.iterations == 1
        assert result.total_wells_processed == 4
        assert result.pools_completed == 1
        assert result.wells_pooled == 4

    def test_incomplete_final_pool(self):
        result = _pool_result(
            [
                _pool_iter(source_wells=("A1", "A2", "A3", "A4"), dest_well="A1"),
                _pool_iter(source_wells=("A5", "A6"), dest_well="A2"),
            ]
        )
        assert result.pools_completed == 2
        assert result.wells_pooled == 6
        assert result.iteration_results[1].pool_size == 2

    def test_tadm_curves_empty_when_none(self):
        assert _pool_result([_pool_iter()]).tadm_curves == []

    def test_tadm_curves_aggregates(self):
        result = _pool_result(
            [
                _pool_iter(
                    source_wells=("A1", "A2"),
                    asp_tadms=[_tadm("asp1"), _tadm("asp2")],
                    disp_tadms=[_tadm("disp1"), _tadm("disp2")],
                    mix_tadm=_tadm("mix1"),
                    include_mix=True,
                ),
                _pool_iter(
                    source_wells=("A3", "A4"),
                    asp_tadms=[_tadm("asp3"), _tadm("asp4")],
                    disp_tadms=[_tadm("disp3"), _tadm("disp4")],
                ),
            ],
            mix_after_pool=True,
        )
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == [
            "asp1",
            "asp2",
            "disp1",
            "disp2",
            "mix1",
            "asp3",
            "asp4",
            "disp3",
            "disp4",
        ]

    def test_frozen(self):
        result = _pool_result([_pool_iter()])
        with pytest.raises(ValidationError):
            result.pools_completed = 99  # type: ignore[misc]


# -------- Replicate samples --------


def _rep_iter(
    *,
    source_well: str = "A1",
    dest_wells: tuple[str, ...] = ("A1", "A2", "A3"),
    multi_dispense: bool = True,
    asp_tadms: list[ChannelTADM | None] | None = None,
    disp_tadms: list[ChannelTADM | None] | None = None,
    pre_tadm: ChannelTADM | None = None,
    post_tadm: ChannelTADM | None = None,
    include_pre: bool = False,
    include_post: bool = False,
    shared_asp: ChannelAspirationResponse | None = None,
    shared_disps: tuple[ChannelDispenseResponse, ...] | None = None,
) -> ReplicateSamplesIterationResult:
    if shared_asp is not None:
        aspirates: tuple[ChannelAspirationResponse, ...] = (shared_asp,)
    else:
        asp_tadms = asp_tadms if asp_tadms is not None else [None]
        aspirates = tuple(_aspirate(tadm=t) for t in asp_tadms)
    if shared_disps is not None:
        dispenses: tuple[ChannelDispenseResponse, ...] = shared_disps
    else:
        disp_tadms = disp_tadms if disp_tadms is not None else [None] * len(dest_wells)
        dispenses = tuple(_dispense(tadm=t) for t in disp_tadms)
    return ReplicateSamplesIterationResult(
        source_plate_id="Source1",
        source_well=source_well,
        dest_plate_ids=("Dest1",),
        dest_wells=dest_wells,
        multi_dispense=multi_dispense,
        tip_pickup=_ok(),
        aspirates=aspirates,
        pre_aliquot_dispense=_dispense(tadm=pre_tadm) if include_pre else None,
        replicate_dispenses=dispenses,
        post_aliquot_dispense=_dispense(tadm=post_tadm) if include_post else None,
        tip_eject=_ok(),
    )


def _rep_result(
    iters: list[ReplicateSamplesIterationResult],
    *,
    multi_dispense: bool = True,
) -> ReplicateSamplesResult:
    src = tuple({it.source_plate_id: None for it in iters})
    dst = tuple({pid: None for it in iters for pid in it.dest_plate_ids})
    sources = len({it.source_well for it in iters})
    replicates = sum(len(it.dest_wells) for it in iters) if multi_dispense else len(iters)
    return ReplicateSamplesResult(
        iterations=len(iters),
        total_wells_processed=replicates,
        source_plate_ids=src,
        dest_plate_ids=dst,
        multi_dispense=multi_dispense,
        sources_processed=sources,
        replicates_filled=replicates,
        iteration_results=tuple(iters),
    )


class TestReplicateSamplesIterationResult:
    def test_construction_multi(self):
        it = _rep_iter()
        assert it.multi_dispense is True
        assert it.dest_wells == ("A1", "A2", "A3")
        assert len(it.aspirates) == 1
        assert len(it.replicate_dispenses) == 3
        assert it.pre_aliquot_dispense is None
        assert it.post_aliquot_dispense is None

    def test_construction_single(self):
        it = _rep_iter(
            multi_dispense=False,
            dest_wells=("B1",),
            disp_tadms=[None],
        )
        assert it.multi_dispense is False
        assert len(it.replicate_dispenses) == 1

    def test_auto_split_multiple_aspirates(self):
        it = _rep_iter(
            dest_wells=("A1", "A2", "A3", "A4"),
            asp_tadms=[_tadm("a1"), _tadm("a2")],
            disp_tadms=[None, None, None, None],
        )
        assert len(it.aspirates) == 2

    def test_frozen(self):
        it = _rep_iter()
        with pytest.raises(ValidationError):
            it.source_well = "Z9"  # type: ignore[misc]


class TestReplicateSamplesResult:
    def test_inherits_compound_result(self):
        result = _rep_result([_rep_iter()])
        assert isinstance(result, CompoundCommandResult)
        assert result.iterations == 1
        assert result.sources_processed == 1
        assert result.replicates_filled == 3
        assert result.total_wells_processed == 3

    def test_single_mode_one_iter_per_transfer(self):
        iters = [
            _rep_iter(source_well="A1", dest_wells=("A1",), multi_dispense=False, disp_tadms=[None]),
            _rep_iter(source_well="A1", dest_wells=("A2",), multi_dispense=False, disp_tadms=[None]),
            _rep_iter(source_well="A2", dest_wells=("A3",), multi_dispense=False, disp_tadms=[None]),
        ]
        result = _rep_result(iters, multi_dispense=False)
        assert result.sources_processed == 2
        assert result.replicates_filled == 3

    def test_tadm_curves_empty_when_none(self):
        assert _rep_result([_rep_iter()]).tadm_curves == []

    def test_tadm_curves_aggregates(self):
        result = _rep_result(
            [
                _rep_iter(
                    source_well="A1",
                    dest_wells=("A1", "A2"),
                    asp_tadms=[_tadm("asp1")],
                    disp_tadms=[_tadm("d1"), _tadm("d2")],
                    pre_tadm=_tadm("pre1"),
                    post_tadm=_tadm("post1"),
                    include_pre=True,
                    include_post=True,
                ),
                _rep_iter(
                    source_well="A2",
                    dest_wells=("A3", "A4"),
                    asp_tadms=[_tadm("asp2")],
                    disp_tadms=[_tadm("d3"), _tadm("d4")],
                ),
            ]
        )
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["asp1", "pre1", "d1", "d2", "post1", "asp2", "d3", "d4"]

    def test_tadm_curves_dedupes_shared_responses(self):
        """single-dispense mode often shares one multi-channel response across iters."""
        shared_asp = _aspirate(tadm=_tadm("shared_asp"))
        shared_disp = _dispense(tadm=_tadm("shared_disp"))
        iters = [
            _rep_iter(
                source_well="A1",
                dest_wells=("A1",),
                multi_dispense=False,
                shared_asp=shared_asp,
                shared_disps=(shared_disp,),
            ),
            _rep_iter(
                source_well="A2",
                dest_wells=("A2",),
                multi_dispense=False,
                shared_asp=shared_asp,
                shared_disps=(shared_disp,),
            ),
        ]
        result = _rep_result(iters, multi_dispense=False)
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["shared_asp", "shared_disp"]

    def test_frozen(self):
        result = _rep_result([_rep_iter()])
        with pytest.raises(ValidationError):
            result.replicates_filled = 99  # type: ignore[misc]
