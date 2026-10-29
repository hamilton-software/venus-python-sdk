from __future__ import annotations

import pytest
from pydantic import ValidationError

from hamilton_venus.models.command_types import (
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelTADM,
    ChannelTADMCurve,
)
from hamilton_venus.models.compound_results import (
    CompoundCommandResult,
    HitPickingResult,
    HitPickingTransferResult,
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


def _tadm(label: str) -> ChannelTADM:
    return ChannelTADM(tadm_curves=[ChannelTADMCurve(curve_id=1, step_type_name=label)])


def _transfer(
    *,
    source_plate_id: str = "Source1",
    source_well: str = "A1",
    dest_plate_id: str = "Dest1",
    dest_well: str = "A1",
    volume: float = 50.0,
    asp_tadm: ChannelTADM | None = None,
    disp_tadm: ChannelTADM | None = None,
) -> HitPickingTransferResult:
    return HitPickingTransferResult(
        source_plate_id=source_plate_id,
        source_well=source_well,
        dest_plate_id=dest_plate_id,
        dest_well=dest_well,
        volume=volume,
        aspirate=_aspirate(tadm=asp_tadm),
        dispense=_dispense(tadm=disp_tadm),
    )


def _make_result(
    transfers: list[HitPickingTransferResult],
    *,
    iterations: int = 1,
    source_plate_ids: list[str] | None = None,
    dest_plate_ids: list[str] | None = None,
    tips_consumed: int = 1,
    minimize_tips: bool = False,
    change_tips: bool = True,
) -> HitPickingResult:
    src: list[str] = []
    dst: list[str] = []
    by_src: dict[str, int] = {}
    by_dst: dict[str, int] = {}
    for t in transfers:
        if t.source_plate_id not in src:
            src.append(t.source_plate_id)
        if t.dest_plate_id not in dst:
            dst.append(t.dest_plate_id)
        by_src[t.source_plate_id] = by_src.get(t.source_plate_id, 0) + 1
        by_dst[t.dest_plate_id] = by_dst.get(t.dest_plate_id, 0) + 1
    return HitPickingResult(
        iterations=iterations,
        total_wells_processed=len(transfers),
        source_plate_ids=tuple(source_plate_ids if source_plate_ids is not None else src),
        dest_plate_ids=tuple(dest_plate_ids if dest_plate_ids is not None else dst),
        transfers=tuple(transfers),
        transfers_by_source_plate=by_src,
        transfers_by_dest_plate=by_dst,
        tips_consumed=tips_consumed,
        minimize_tips=minimize_tips,
        change_tips=change_tips,
    )


class TestHitPickingTransferResult:
    def test_construction(self):
        t = _transfer(source_well="B2", dest_well="C3", volume=25.0)
        assert t.source_plate_id == "Source1"
        assert t.source_well == "B2"
        assert t.dest_plate_id == "Dest1"
        assert t.dest_well == "C3"
        assert t.volume == 25.0
        assert isinstance(t.aspirate, ChannelAspirationResponse)
        assert isinstance(t.dispense, ChannelDispenseResponse)

    def test_frozen(self):
        t = _transfer()
        with pytest.raises(ValidationError):
            t.dest_well = "Z9"  # type: ignore[misc]


class TestHitPickingResult:
    def test_inherits_compound_result(self):
        result = _make_result([_transfer()], iterations=1, tips_consumed=1)
        assert isinstance(result, CompoundCommandResult)
        assert result.iterations == 1
        assert result.total_wells_processed == 1
        assert result.tips_consumed == 1
        assert result.minimize_tips is False
        assert result.change_tips is True

    def test_multi_plate_aggregates(self):
        transfers = [
            _transfer(source_plate_id="SourceA", source_well="A1", dest_plate_id="Dest1", dest_well="A1"),
            _transfer(source_plate_id="SourceA", source_well="A1", dest_plate_id="Dest2", dest_well="A1"),
            _transfer(source_plate_id="SourceB", source_well="B1", dest_plate_id="Dest1", dest_well="B1"),
        ]
        result = _make_result(transfers, iterations=2, tips_consumed=2, minimize_tips=True)
        assert result.total_wells_processed == 3
        assert len(result.transfers) == 3
        assert result.source_plate_ids == ("SourceA", "SourceB")
        assert result.dest_plate_ids == ("Dest1", "Dest2")
        assert result.transfers_by_source_plate == {"SourceA": 2, "SourceB": 1}
        assert result.transfers_by_dest_plate == {"Dest1": 2, "Dest2": 1}
        assert result.tips_consumed == 2

    def test_transfers_preserve_execution_order(self):
        transfers = [
            _transfer(source_well="A1", dest_well="A1"),
            _transfer(source_well="B1", dest_well="B1"),
            _transfer(source_well="A1", dest_well="C1"),
        ]
        result = _make_result(transfers, change_tips=False)
        wells = [(t.source_well, t.dest_well) for t in result.transfers]
        assert wells == [("A1", "A1"), ("B1", "B1"), ("A1", "C1")]

    def test_tadm_curves_empty_when_none(self):
        result = _make_result([_transfer()])
        assert result.tadm_curves == []

    def test_tadm_curves_aggregates_across_transfers(self):
        transfers = [
            _transfer(asp_tadm=_tadm("asp1"), disp_tadm=_tadm("disp1")),
            _transfer(asp_tadm=_tadm("asp2"), disp_tadm=_tadm("disp2")),
        ]
        result = _make_result(transfers)
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["asp1", "disp1", "asp2", "disp2"]

    def test_frozen(self):
        result = _make_result([_transfer()])
        with pytest.raises(ValidationError):
            result.tips_consumed = 99  # type: ignore[misc]
