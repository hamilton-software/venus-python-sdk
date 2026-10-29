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
    AddReagentIterationResult,
    AddReagentResult,
    AddReagentWellDispense,
    CompoundCommandResult,
)
from hamilton_venus.models.enums import PreAliquotDisposal


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


class TestPreAliquotDisposal:
    def test_enum_values(self):
        assert PreAliquotDisposal.SOURCE.value == "source"
        assert PreAliquotDisposal.WASTE.value == "waste"

    def test_is_str_enum(self):
        assert PreAliquotDisposal.SOURCE == "source"
        assert PreAliquotDisposal.WASTE == "waste"

    def test_members(self):
        assert set(PreAliquotDisposal) == {PreAliquotDisposal.SOURCE, PreAliquotDisposal.WASTE}


class TestAddReagentWellDispense:
    def test_construction(self):
        wd = AddReagentWellDispense(
            dest_plate_id="Plate1",
            dest_well="A1",
            response=_dispense(),
        )
        assert wd.dest_plate_id == "Plate1"
        assert wd.dest_well == "A1"
        assert isinstance(wd.response, ChannelDispenseResponse)

    def test_frozen(self):
        wd = AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense())
        with pytest.raises(ValidationError):
            wd.dest_well = "B2"  # type: ignore[misc]


class TestAddReagentIterationResult:
    def test_required_fields_only(self):
        it = AddReagentIterationResult(
            source_plate_id="Trough1",
            aspirate=_aspirate(),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense()),
            ],
        )
        assert it.tip_pickup is None
        assert it.tip_eject is None
        assert it.pre_aliquot_dispense is None
        assert it.post_aliquot_dispense is None
        assert len(it.well_dispenses) == 1

    def test_with_all_optionals(self):
        it = AddReagentIterationResult(
            source_plate_id="Trough1",
            tip_pickup=CommandResponse(return_status="Success", return_code=0),
            aspirate=_aspirate(),
            pre_aliquot_dispense=_dispense(),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense()),
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="B1", response=_dispense()),
            ],
            post_aliquot_dispense=_dispense(),
            tip_eject=CommandResponse(return_status="Success", return_code=0),
        )
        assert it.tip_pickup is not None
        assert it.tip_eject is not None
        assert it.pre_aliquot_dispense is not None
        assert it.post_aliquot_dispense is not None
        assert len(it.well_dispenses) == 2


class TestAddReagentResult:
    def _basic_iteration(self) -> AddReagentIterationResult:
        return AddReagentIterationResult(
            source_plate_id="Trough1",
            aspirate=_aspirate(),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense()),
            ],
        )

    def test_inherits_compound_result(self):
        result = AddReagentResult(
            iterations=1,
            total_wells_processed=1,
            source_plate_ids=["Trough1"],
            dest_plate_ids=["Plate1"],
            multi_dispense=False,
            wells_filled=1,
            wells_filled_by_plate={"Plate1": 1},
            iteration_results=[self._basic_iteration()],
        )
        assert isinstance(result, CompoundCommandResult)
        assert result.iterations == 1
        assert result.total_wells_processed == 1
        assert result.wells_filled == 1
        assert result.multi_dispense is False

    def test_multi_plate_aggregates(self):
        it1 = AddReagentIterationResult(
            source_plate_id="TroughA",
            aspirate=_aspirate(),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense()),
                AddReagentWellDispense(dest_plate_id="Plate2", dest_well="A1", response=_dispense()),
            ],
        )
        it2 = AddReagentIterationResult(
            source_plate_id="TroughB",
            aspirate=_aspirate(),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="B1", response=_dispense()),
            ],
        )
        result = AddReagentResult(
            iterations=2,
            total_wells_processed=3,
            source_plate_ids=["TroughA", "TroughB"],
            dest_plate_ids=["Plate1", "Plate2"],
            multi_dispense=True,
            wells_filled=3,
            wells_filled_by_plate={"Plate1": 2, "Plate2": 1},
            iteration_results=[it1, it2],
        )
        assert result.iterations == 2
        assert result.wells_filled == 3
        assert result.wells_filled_by_plate == {"Plate1": 2, "Plate2": 1}
        assert result.source_plate_ids == ("TroughA", "TroughB")
        assert result.dest_plate_ids == ("Plate1", "Plate2")

    def test_tadm_curves_empty_when_none(self):
        result = AddReagentResult(
            iterations=1,
            total_wells_processed=1,
            source_plate_ids=["Trough1"],
            dest_plate_ids=["Plate1"],
            multi_dispense=False,
            wells_filled=1,
            wells_filled_by_plate={"Plate1": 1},
            iteration_results=[self._basic_iteration()],
        )
        assert result.tadm_curves == []

    def test_tadm_curves_aggregates_all_phases(self):
        it = AddReagentIterationResult(
            source_plate_id="Trough1",
            aspirate=_aspirate(tadm=_tadm("asp")),
            pre_aliquot_dispense=_dispense(tadm=_tadm("pre")),
            well_dispenses=[
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="A1", response=_dispense(tadm=_tadm("well1"))),
                AddReagentWellDispense(dest_plate_id="Plate1", dest_well="B1", response=_dispense(tadm=_tadm("well2"))),
            ],
            post_aliquot_dispense=_dispense(tadm=_tadm("post")),
        )
        result = AddReagentResult(
            iterations=1,
            total_wells_processed=2,
            source_plate_ids=["Trough1"],
            dest_plate_ids=["Plate1"],
            multi_dispense=True,
            wells_filled=2,
            wells_filled_by_plate={"Plate1": 2},
            iteration_results=[it],
        )
        labels = [c.step_type_name for c in result.tadm_curves]
        assert labels == ["asp", "pre", "well1", "well2", "post"]

    def test_frozen(self):
        result = AddReagentResult(
            iterations=1,
            total_wells_processed=1,
            source_plate_ids=["Trough1"],
            dest_plate_ids=["Plate1"],
            multi_dispense=False,
            wells_filled=1,
            wells_filled_by_plate={"Plate1": 1},
            iteration_results=[self._basic_iteration()],
        )
        with pytest.raises(ValidationError):
            result.wells_filled = 99  # type: ignore[misc]
