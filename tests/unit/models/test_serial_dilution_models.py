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
    SerialDilutionPlateResult,
    SerialDilutionResult,
    SerialDilutionSeriesResult,
    SerialDilutionStepResult,
)
from hamilton_venus.models.enums import LastDilutionWaste


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


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _step(
    *,
    step_index: int = 0,
    source_well: str = "A1",
    dest_well: str = "A2",
    aspirate: ChannelAspirationResponse | None = None,
    dispense: ChannelDispenseResponse | None = None,
    mix: ChannelDispenseResponse | None = None,
    asp_tadm: ChannelTADM | None = None,
    disp_tadm: ChannelTADM | None = None,
    mix_tadm: ChannelTADM | None = None,
) -> SerialDilutionStepResult:
    return SerialDilutionStepResult(
        step_index=step_index,
        source_well=source_well,
        dest_well=dest_well,
        aspirate=aspirate if aspirate is not None else _aspirate(tadm=asp_tadm),
        dispense=dispense if dispense is not None else (_dispense(tadm=disp_tadm) if disp_tadm else None),
        mix=mix if mix is not None else (_dispense(tadm=mix_tadm) if mix_tadm else None),
    )


def _series(
    *,
    channel: int = 1,
    row: str = "A",
    pass_index: int = 0,
    well_chain: tuple[str, ...] = ("A1", "A2", "A3"),
    diluent_dispenses: tuple[ChannelDispenseResponse, ...] = (),
    steps: tuple[SerialDilutionStepResult, ...] | None = None,
    last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
) -> SerialDilutionSeriesResult:
    if steps is None:
        steps = (
            _step(step_index=0, source_well="A1", dest_well="A2"),
            _step(step_index=1, source_well="A2", dest_well="A3"),
        )
    return SerialDilutionSeriesResult(
        channel=channel,
        row=row,
        pass_index=pass_index,
        well_chain=well_chain,
        diluent_dispenses=diluent_dispenses,
        steps=steps,
        last_excess=last_excess,
    )


def _plate(
    *,
    plate_id: str = "Plate1",
    num_passes: int = 1,
    series_results: tuple[SerialDilutionSeriesResult, ...] | None = None,
) -> SerialDilutionPlateResult:
    if series_results is None:
        series_results = (_series(),)
    return SerialDilutionPlateResult(
        plate_id=plate_id,
        num_passes=num_passes,
        series_results=series_results,
    )


def _result(
    plates: list[SerialDilutionPlateResult] | None = None,
    *,
    num_series: int | None = None,
    num_dilutions: int = 2,
    diluent_volume: float = 50.0,
    transfer_volume: float = 50.0,
    dilution_factor: float | None = None,
    reuse_tips: bool = False,
    mix_after_dispense: bool = True,
    diluent_multi_dispense: bool = True,
    discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
    diluent_sources_used: tuple[str, ...] = ("Buffer1",),
) -> SerialDilutionResult:
    if plates is None:
        plates = [_plate()]
    plate_ids = tuple({p.plate_id: None for p in plates})
    total_series = num_series if num_series is not None else sum(len(p.series_results) for p in plates)
    return SerialDilutionResult(
        iterations=len(plates),
        total_wells_processed=total_series * num_dilutions,
        plate_ids=plate_ids,
        num_series=total_series,
        num_dilutions=num_dilutions,
        diluent_volume=diluent_volume,
        transfer_volume=transfer_volume,
        dilution_factor=dilution_factor,
        reuse_tips=reuse_tips,
        mix_after_dispense=mix_after_dispense,
        diluent_multi_dispense=diluent_multi_dispense,
        discard_last_excess=discard_last_excess,
        diluent_sources_used=diluent_sources_used,
        plate_results=tuple(plates),
    )


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class TestLastDilutionWaste:
    def test_values(self):
        assert LastDilutionWaste.NONE.value == "none"
        assert LastDilutionWaste.TO_WASTE.value == "to_waste"
        assert LastDilutionWaste.WITH_TIP_EJECT.value == "with_tip_eject"

    def test_is_str_enum(self):
        assert isinstance(LastDilutionWaste.NONE, str)
        assert LastDilutionWaste("to_waste") is LastDilutionWaste.TO_WASTE


# ---------------------------------------------------------------------------
# Step / Series / Plate models
# ---------------------------------------------------------------------------


class TestSerialDilutionStepResult:
    def test_construction(self):
        step = _step(step_index=0, source_well="A1", dest_well="A2")
        assert step.step_index == 0
        assert step.source_well == "A1"
        assert step.dest_well == "A2"
        assert step.dispense is None
        assert step.mix is None

    def test_optional_dispense_and_mix(self):
        step = _step(disp_tadm=_tadm("d"), mix_tadm=_tadm("m"))
        assert step.dispense is not None
        assert step.mix is not None

    def test_frozen(self):
        step = _step()
        with pytest.raises(ValidationError):
            step.dest_well = "Z9"  # type: ignore[misc]


class TestSerialDilutionSeriesResult:
    def test_construction(self):
        series = _series(channel=3, row="C", well_chain=("C1", "C2", "C3"))
        assert series.channel == 3
        assert series.row == "C"
        assert series.well_chain == ("C1", "C2", "C3")
        assert len(series.steps) == 2
        assert series.last_excess is LastDilutionWaste.NONE

    def test_frozen(self):
        series = _series()
        with pytest.raises(ValidationError):
            series.row = "Z"  # type: ignore[misc]


class TestSerialDilutionPlateResult:
    def test_construction(self):
        plate = _plate(plate_id="P2", num_passes=2)
        assert plate.plate_id == "P2"
        assert plate.num_passes == 2
        assert len(plate.series_results) == 1

    def test_frozen(self):
        plate = _plate()
        with pytest.raises(ValidationError):
            plate.plate_id = "Other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Top-level result model
# ---------------------------------------------------------------------------


class TestSerialDilutionResult:
    def test_inherits_compound_result(self):
        result = _result()
        assert isinstance(result, CompoundCommandResult)
        assert result.iterations == 1

    def test_total_wells_processed_is_series_times_dilutions(self):
        # 2 series, 3 dilutions -> 6 transfer-step destination wells.
        series = (_series(channel=1, row="A"), _series(channel=2, row="B"))
        result = _result([_plate(series_results=series)], num_dilutions=3)
        assert result.num_series == 2
        assert result.num_dilutions == 3
        assert result.total_wells_processed == 6

    def test_total_wells_processed_across_plates(self):
        p1 = _plate(plate_id="P1", series_results=(_series(row="A"), _series(row="B")))
        p2 = _plate(plate_id="P2", series_results=(_series(row="A"),))
        result = _result([p1, p2], num_dilutions=4)
        assert result.num_series == 3
        assert result.total_wells_processed == 12

    def test_dilution_factor_none_for_by_volume(self):
        assert _result().dilution_factor is None

    def test_dilution_factor_recorded_for_by_factor(self):
        assert _result(dilution_factor=2.0).dilution_factor == 2.0

    def test_diluent_sources_used_order_preserved(self):
        result = _result(diluent_sources_used=("Buffer1", "Buffer2", "Buffer3"))
        assert result.diluent_sources_used == ("Buffer1", "Buffer2", "Buffer3")

    def test_plate_ids_deduped_across_plates(self):
        p1 = _plate(plate_id="P1")
        p2 = _plate(plate_id="P2")
        result = _result([p1, p2])
        assert result.plate_ids == ("P1", "P2")

    def test_frozen(self):
        result = _result()
        with pytest.raises(ValidationError):
            result.num_series = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# tadm_curves aggregation
# ---------------------------------------------------------------------------


class TestSerialDilutionTadmCurves:
    def test_empty_when_no_tadm(self):
        assert _result().tadm_curves == []

    def test_aggregates_diluent_and_steps_in_order(self):
        diluent = (_dispense(tadm=_tadm("dil1")), _dispense(tadm=_tadm("dil2")))
        steps = (
            _step(step_index=0, asp_tadm=_tadm("asp1"), disp_tadm=_tadm("d1"), mix_tadm=_tadm("m1")),
            _step(step_index=1, asp_tadm=_tadm("asp2"), disp_tadm=_tadm("d2")),
        )
        series = _series(diluent_dispenses=diluent, steps=steps)
        result = _result([_plate(series_results=(series,))])
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["dil1", "dil2", "asp1", "d1", "m1", "asp2", "d2"]

    def test_dedupes_responses_shared_across_sibling_series(self):
        """A single multi-channel stroke is shared by the sibling series of a pass."""
        shared_diluent = _dispense(tadm=_tadm("shared_dil"))
        shared_asp = _aspirate(tadm=_tadm("shared_asp"))
        shared_disp = _dispense(tadm=_tadm("shared_disp"))
        shared_step_a = _step(step_index=0, source_well="A1", dest_well="A2", aspirate=shared_asp, dispense=shared_disp)
        shared_step_b = _step(step_index=0, source_well="B1", dest_well="B2", aspirate=shared_asp, dispense=shared_disp)
        series_a = _series(channel=1, row="A", diluent_dispenses=(shared_diluent,), steps=(shared_step_a,))
        series_b = _series(channel=2, row="B", diluent_dispenses=(shared_diluent,), steps=(shared_step_b,))
        result = _result([_plate(series_results=(series_a, series_b))])
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["shared_dil", "shared_asp", "shared_disp"]
