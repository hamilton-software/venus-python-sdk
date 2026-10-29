"""Unit tests for add_reagent module helpers and execute_add_reagent (single-dispense mode).

Task-7 scope: ``execute_add_reagent`` single-dispense mode.
Further test classes will be added in tasks 8-9 as multi-dispense mode is implemented.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands.add_reagent import execute_add_reagent
from hamilton_venus.exceptions import OperatorCancelledError, VenusCommandFailedError
from hamilton_venus.models.command_types import (
    ChannelAspirationResponse,
    ChannelDispenseResponse,
)
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import AddReagentResult
from hamilton_venus.models.enums import CapacitiveLLD, PreAliquotDisposal
from hamilton_venus.models.liquid_handling_settings import AspirateSettings
from hamilton_venus.models.position import Position

# ---------------------------------------------------------------------------
# Response factories (mirrors test_copy_plate.py conventions)
# ---------------------------------------------------------------------------


def _make_response(**overrides) -> CommandResponse:
    return CommandResponse(
        return_status=overrides.get("return_status", "Success"),
        return_code=overrides.get("return_code", 0),
    )


def _make_aspirate_response() -> ChannelAspirationResponse:
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={"channels": []},
    )


def _make_dispense_response() -> ChannelDispenseResponse:
    return ChannelDispenseResponse(
        return_status="Success",
        return_code=0,
        return_parameters={"channels": []},
    )


def _make_aspirate_response_with_volume(measured_ul: float) -> ChannelAspirationResponse:
    """Aspirate response reporting *measured_ul* liquid volume on one channel.

    Used to drive consumable-liquid-management source advancement: the tracker
    seeds its remaining estimate from this measured minimum, so a low value
    forces a switch to the next source before the following aspirate.
    """
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={"channels": [{"liquidVolume_uL": measured_ul}]},
    )


# ---------------------------------------------------------------------------
# _make_execute_client — configurable mock client for execute_add_reagent tests
# ---------------------------------------------------------------------------


def _make_avail_resp(total: int) -> MagicMock:
    r = MagicMock()
    r.return_parameters.total_available_tips = total
    return r


def _make_execute_client(
    *,
    source_labware: str = "Source1",
    dest_labware: str = "Plate1",
    source_rows: int = 1,
    source_cols: int = 1,
    dest_rows: int = 8,
    dest_cols: int = 12,
    tip_capacity: float = 300.0,
    tip_type_id: str = "0",
    available_tips: int = 200,
    waste_rows: int = 1,
    waste_cols: int = 1,
    source_connected: bool = False,
) -> MagicMock:
    """Build a fully-wired mock client for execute_add_reagent single-dispense mode tests."""
    client = MagicMock()

    # --- labware geometry -------------------------------------------------
    geometry_map = {
        source_labware: (source_rows, source_cols),
        dest_labware: (dest_rows, dest_cols),
        "liquid_waste": (waste_rows, waste_cols),
    }

    def _definition_for(name: str) -> dict:
        rows, cols = geometry_map.get(name, (8, 12))
        layout: dict = {"rows": rows, "columns": cols}
        # Reagent sources are reservoirs/troughs, which the labware
        # definition marks as numeric-addressed (indexing.index == 0).
        if name == source_labware:
            layout["indexing"] = {"index": 0}
            if source_connected:
                layout["connected_container"] = True
        return {"rack_layout": layout}

    def _labware_side_effect(name: str) -> MagicMock:
        r = MagicMock()
        r.return_parameters.definition = _definition_for(name)
        return r

    def _spec_side_effect(name: str):
        from hamilton_venus.models.position import LabwareLayoutSpec

        return LabwareLayoutSpec.from_definition(_definition_for(name))

    client.labware_get_params_from_id.side_effect = _labware_side_effect
    client.get_labware_spec.side_effect = _spec_side_effect

    # --- tip capacity mocks -----------------------------------------------
    counter_resp = MagicMock()
    counter_resp.return_parameters.tip_type_id = tip_type_id
    client.tip_pool_get_tip_counter.return_value = counter_resp

    types_resp = MagicMock()
    types_resp.return_parameters.tip_types = {tip_type_id: {"Max Liquid Volume": tip_capacity}}
    client.get_tip_types.return_value = types_resp

    # --- tip availability -------------------------------------------------
    client.tip_pool_get_available_tips.return_value = _make_avail_resp(available_tips)

    # --- tip pickup / eject -----------------------------------------------
    client.tip_pickup.return_value = _make_response()
    client.tip_eject.return_value = _make_response()

    # --- aspirate / dispense ---------------------------------------------
    client.aspirate.return_value = _make_aspirate_response()
    client.dispense.return_value = _make_dispense_response()

    return client


# ---------------------------------------------------------------------------
# Shared call-argument extractor
# ---------------------------------------------------------------------------


def _kwarg(mock_call, key):
    """Return keyword arg *key* from a mock call (checks kwargs then args[1])."""
    return mock_call.kwargs.get(key, mock_call[1].get(key))


def _make_counter_response(tip_type_id: str = "0", tip_type: int = -1) -> MagicMock:
    """Build a mock TipPoolCounterResponse with the given tip_type_id / tip_type."""
    resp = MagicMock()
    resp.return_parameters.tip_type_id = tip_type_id
    resp.return_parameters.tip_type = tip_type
    return resp


def _make_tip_types_response(entries: dict[str, dict]) -> MagicMock:
    """Build a mock TipTypesResponse with the given {tip_type_id: props} dict."""
    resp = MagicMock()
    resp.return_parameters.tip_types = entries
    return resp


def _make_client(
    *,
    tip_type_id: str = "0",
    tip_type: int = -1,
    tip_types: dict[str, dict] | None = None,
    labware_rows: int = 8,
    labware_columns: int = 12,
    labware_cmd_fails: bool = False,
) -> MagicMock:
    client = MagicMock()
    client.tip_pool_get_tip_counter.return_value = _make_counter_response(tip_type_id, tip_type)
    client.get_tip_types.return_value = _make_tip_types_response(
        tip_types if tip_types is not None else {"0": {"Max Liquid Volume": 300, "tipTypeName": "300uL"}}
    )

    if labware_cmd_fails:
        _mock_resp = MagicMock(
            action_name="labware.getLabwareParamsFromID",
            return_status="Failure",
            return_code=1,
            return_parameters={},
        )
        client.labware_get_params_from_id.side_effect = VenusCommandFailedError(_mock_resp)
        client.get_labware_spec.side_effect = VenusCommandFailedError(_mock_resp)
    else:
        from hamilton_venus.models.position import LabwareLayoutSpec

        definition = {"rack_layout": {"rows": labware_rows, "columns": labware_columns}}
        labware_resp = MagicMock()
        labware_resp.return_parameters.definition = definition
        client.labware_get_params_from_id.return_value = labware_resp
        client.get_labware_spec.side_effect = lambda _lid, _d=definition: LabwareLayoutSpec.from_definition(_d)

    return client


# ---------------------------------------------------------------------------
# _resolve_waste_position tests live in tests/unit/compound_commands/test_waste.py
# ---------------------------------------------------------------------------


# ===========================================================================
# execute_add_reagent — single-dispense mode
# ===========================================================================


_BASIC_KWARGS: dict = dict(
    reagent_source="Source1",
    dest_plate="Plate1",
    volume=50.0,
    tip_pool="TransferTips",
    liquid_class="Water",
)


class TestExecuteAddReagentBasic:
    """Happy-path single-dispense mode: 96-well plate, 8 channels."""

    def test_returns_add_reagent_result(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert isinstance(result, AddReagentResult)

    def test_96_wells_12_iterations(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.iterations == 12
        assert result.wells_filled == 96
        assert result.total_wells_processed == 96

    def test_tip_pickup_called_once_per_chunk(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.tip_pickup.call_count == 12

    def test_tip_eject_called_once_per_chunk(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.tip_eject.call_count == 12

    def test_aspirate_called_once_per_chunk(self):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.aspirate.call_count == 12

    def test_dispense_called_once_per_chunk(self):
        # No pre/post aliquot → exactly one dispense call per chunk
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.dispense.call_count == 12

    def test_aspirate_volume_equals_volume_when_no_aliquots(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        asp_volumes = [_kwarg(c, "volumes") for c in client.aspirate.call_args_list]
        assert all(v == 50.0 for v in asp_volumes)

    def test_source_plate_ids_in_result(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.source_plate_ids == ("Source1",)

    def test_dest_plate_ids_in_result(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.dest_plate_ids == ("Plate1",)

    def test_multi_dispense_false_in_result(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.multi_dispense is False

    def test_wells_filled_by_plate(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.wells_filled_by_plate == {"Plate1": 96}

    def test_iteration_results_length(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert len(result.iteration_results) == 12

    def test_each_iteration_has_well_dispenses(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        for it in result.iteration_results:
            assert len(it.well_dispenses) == 8

    def test_each_iteration_has_tip_pickup_and_eject(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        for it in result.iteration_results:
            assert it.tip_pickup is not None
            assert it.tip_eject is not None

    def test_final_chunk_uses_fewer_channels(self):
        """10 wells: chunk 1 → 8 channels, chunk 2 → 2 channels."""
        client = _make_execute_client(dest_rows=1, dest_cols=10)
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.iterations == 2
        assert result.wells_filled == 10
        first_pickup_channels = _kwarg(client.tip_pickup.call_args_list[0], "channels")
        second_pickup_channels = _kwarg(client.tip_pickup.call_args_list[1], "channels")
        assert len(first_pickup_channels) == 8
        assert len(second_pickup_channels) == 2

    def test_aspirate_positions_are_source(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        for c in client.aspirate.call_args_list:
            positions = _kwarg(c, "positions")
            assert all(p.labware == "Source1" for p in positions)

    def test_dispense_positions_are_dest_wells(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        # All dispense positions (no pre/post) should be on Plate1
        for c in client.dispense.call_args_list:
            positions = _kwarg(c, "positions")
            assert all(p.labware == "Plate1" for p in positions)


class TestAddReagentResultModel:
    """Result model integrity and tadm_curves aggregation."""

    def test_total_wells_processed_equals_wells_filled(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.total_wells_processed == result.wells_filled

    def test_tadm_curves_empty_when_no_tadm_data(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.tadm_curves == []

    def test_iteration_result_source_plate_id(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        for it in result.iteration_results:
            assert it.source_plate_id == "Source1"

    def test_well_dispense_dest_plate_id_and_well(self):
        # dest_cols must be > 1 so the labware uses letter-based row labels (A1)
        client = _make_execute_client(dest_rows=1, dest_cols=2)
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.iteration_results[0].well_dispenses[0].dest_plate_id == "Plate1"
        assert result.iteration_results[0].well_dispenses[0].dest_well == "A1"


# ===========================================================================
# multi-dispense mode
# ===========================================================================

_MULTI_KWARGS: dict = dict(
    reagent_source="Source1",
    dest_plate="Plate1",
    volume=50.0,
    tip_pool="TransferTips",
    multi_dispense=True,
    liquid_class="Water",
)


class TestAddReagentMultiDispense:
    """multi-dispense mode: one tip pickup, multiple wells per aspiration."""

    # ------------------------------------------------------------------
    # Result shape
    # ------------------------------------------------------------------

    def test_returns_add_reagent_result(self):
        # 300 µL capacity, 50 µL/well, 8 channels → 6 rows per batch, 12 rows → 2 batches
        client = _make_execute_client()
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert isinstance(result, AddReagentResult)

    def test_multi_dispense_flag_true_in_result(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert result.multi_dispense is True

    def test_96_wells_filled(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert result.wells_filled == 96

    # ------------------------------------------------------------------
    # Wells-per-aspiration calculation
    # ------------------------------------------------------------------

    def test_wells_per_aspiration_fits_in_capacity(self):
        """300 µL tip / 50 µL per well, 8 channels → 6 rows per batch → ceil(12/6)=2 aspirations."""
        client = _make_execute_client(tip_capacity=300.0, source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.aspirate.call_count == 2

    def test_wells_per_aspiration_single_well(self):
        """When volume == tip_capacity each batch holds 1 channel-row → 12 aspirations."""
        client = _make_execute_client(tip_capacity=50.0, source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.aspirate.call_count == 12

    def test_wells_per_aspiration_partial_last_batch(self):
        """3 destination wells form 1 partial channel-row → 1 batch."""
        client = _make_execute_client(
            dest_rows=1, dest_cols=3, tip_capacity=110.0, source_rows=8, source_cols=1, source_connected=True
        )
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.aspirate.call_count == 1

    def test_aspirate_volume_adjusted_for_partial_last_batch(self):
        """3 dest wells = 1 partial channel-row; aspirate = max(vol)*1 = 50 µL."""
        client = _make_execute_client(dest_rows=1, dest_cols=3, tip_capacity=110.0)
        execute_add_reagent(client, **_MULTI_KWARGS)
        # 1 batch, 1 channel-row of 3 wells; per-channel asp = 1 row x 50 uL
        first_vol = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert first_vol == 50.0

    # ------------------------------------------------------------------
    # Volume-exceeds-capacity guard
    # ------------------------------------------------------------------

    def test_volume_exceeds_capacity_raises(self):
        """volume > tip_capacity - pre - post must raise ValueError."""
        client = _make_execute_client(tip_capacity=40.0)
        with pytest.raises(ValueError, match="tip capacity"):
            execute_add_reagent(client, **_MULTI_KWARGS)

    def test_volume_exceeds_net_capacity_with_aliquots_raises(self):
        """volume fits in tip alone but not after reserving pre + post → ValueError."""
        client = _make_execute_client(tip_capacity=60.0)
        with pytest.raises(ValueError, match="tip capacity"):
            execute_add_reagent(
                client,
                **_MULTI_KWARGS,
                pre_aliquot_volume=5.0,
                post_aliquot_volume=10.0,
            )

    # ------------------------------------------------------------------
    # Tip management: one pickup, one eject per source block
    # ------------------------------------------------------------------

    def test_tip_pickup_called_once(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.tip_pickup.call_count == 1

    def test_tip_eject_called_once(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.tip_eject.call_count == 1

    def test_tip_eject_in_finally_on_aspirate_error(self):
        """If aspirate raises after tip pickup, tips are still ejected."""
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        client.aspirate.side_effect = RuntimeError("aspirate failed")
        with pytest.raises(RuntimeError, match="aspirate failed"):
            execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.tip_eject.call_count == 1

    # ------------------------------------------------------------------
    # Iteration results
    # ------------------------------------------------------------------

    def test_iteration_count_matches_aspiration_count(self):
        """300 µL / 50 µL = 6 rows/batch; 12 rows → 2 iterations."""
        client = _make_execute_client(tip_capacity=300.0, source_rows=8, source_cols=1, source_connected=True)
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert result.iterations == client.aspirate.call_count

    def test_tip_pickup_only_on_first_iteration(self):
        client = _make_execute_client(tip_capacity=300.0)
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert result.iteration_results[0].tip_pickup is not None
        for it in result.iteration_results[1:]:
            assert it.tip_pickup is None

    def test_tip_eject_only_on_last_iteration(self):
        client = _make_execute_client(tip_capacity=300.0)
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        for it in result.iteration_results[:-1]:
            assert it.tip_eject is None
        assert result.iteration_results[-1].tip_eject is not None

    def test_each_iteration_has_correct_well_dispenses(self):
        """6 channel-rows per batch x 8 channels = 48 well_dispenses per iteration."""
        client = _make_execute_client(tip_capacity=300.0)
        result = execute_add_reagent(client, **_MULTI_KWARGS)
        assert len(result.iteration_results[0].well_dispenses) == 48

    # ------------------------------------------------------------------
    # Dispense call counts per aspiration
    # ------------------------------------------------------------------

    def test_dispense_calls_equal_wells_no_aliquots(self):
        """No pre/post → 1 dispense per channel-row = 12 dispense calls."""
        client = _make_execute_client()
        execute_add_reagent(client, **_MULTI_KWARGS)
        assert client.dispense.call_count == 12

    def test_dispense_calls_with_pre_aliquot(self):
        """With pre-aliquot: 1 pre + N row dispenses per batch."""
        client = _make_execute_client(tip_capacity=300.0, source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_MULTI_KWARGS, pre_aliquot_volume=10.0)
        # net=290, 5 rows/batch → 3 batches; dispenses = 12 rows + 3 pre = 15
        assert client.dispense.call_count == 15

    def test_dispense_calls_with_post_aliquot(self):
        """With post-aliquot: N row dispenses + 1 post per batch."""
        client = _make_execute_client(tip_capacity=300.0, source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_MULTI_KWARGS, post_aliquot_volume=5.0)
        # net=295, 5 rows/batch → 3 batches; dispenses = 12 rows + 3 post = 15
        assert client.dispense.call_count == 15

    # ------------------------------------------------------------------
    # Pre/post-aliquot in multi-dispense mode
    # ------------------------------------------------------------------

    def test_pre_aliquot_volume_included_in_aspirate(self):
        """Aspirate volume = (rows_in_batch x vol) + pre_aliquot."""
        client = _make_execute_client(dest_rows=1, dest_cols=2, tip_capacity=120.0)
        # 2 wells = 1 channel-row; 1 batch; asp = 1x50 + 10 = 60
        execute_add_reagent(client, **_MULTI_KWARGS, pre_aliquot_volume=10.0)
        asp_vol = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert asp_vol == 60.0

    def test_post_aliquot_volume_included_in_aspirate(self):
        """Aspirate volume = (rows_in_batch x vol) + post_aliquot."""
        client = _make_execute_client(dest_rows=1, dest_cols=2, tip_capacity=120.0)
        # 2 wells = 1 channel-row; 1 batch; asp = 1x50 + 5 = 55
        execute_add_reagent(client, **_MULTI_KWARGS, post_aliquot_volume=5.0)
        asp_vol = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert asp_vol == 55.0

    def test_pre_aliquot_source_disposal_targets_source(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1, tip_capacity=60.0)
        execute_add_reagent(
            client,
            **_MULTI_KWARGS,
            pre_aliquot_volume=5.0,
            pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
        )
        # First dispense call is the pre-aliquot
        first_positions = _kwarg(client.dispense.call_args_list[0], "positions")
        assert all(p.labware == "Source1" for p in first_positions)

    def test_pre_aliquot_waste_disposal_targets_liquid_waste(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1, tip_capacity=60.0)
        execute_add_reagent(
            client,
            **_MULTI_KWARGS,
            pre_aliquot_volume=5.0,
            pre_aliquot_disposal=PreAliquotDisposal.WASTE,
        )
        first_positions = _kwarg(client.dispense.call_args_list[0], "positions")
        assert all(p.labware == "liquid_waste" for p in first_positions)

    def test_post_aliquot_dispense_targets_source(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1, tip_capacity=60.0)
        execute_add_reagent(client, **_MULTI_KWARGS, post_aliquot_volume=5.0)
        # Last dispense call is the post-aliquot
        last_positions = _kwarg(client.dispense.call_args_list[-1], "positions")
        assert all(p.labware == "Source1" for p in last_positions)

    # ------------------------------------------------------------------
    # Source / dest positions
    # ------------------------------------------------------------------

    def test_aspirate_positions_are_source(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_MULTI_KWARGS)
        for c in client.aspirate.call_args_list:
            positions = _kwarg(c, "positions")
            assert all(p.labware == "Source1" for p in positions)


# ===========================================================================
# Pre-aliquot and post-aliquot
# ===========================================================================


class TestAddReagentPreAliquot:
    """Pre-aliquot routing: SOURCE vs WASTE and call-count verification."""

    def test_pre_aliquot_adds_extra_dispense_call_per_chunk(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=10.0)
        # 1 chunk: 1 aspirate + 1 pre-aliquot dispense + 1 well dispense = 2 dispense calls
        assert client.dispense.call_count == 2

    def test_pre_aliquot_aspirate_volume_includes_pre_aliquot(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=10.0)
        asp_volume = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert asp_volume == 60.0  # 50 + 10

    def test_pre_aliquot_source_disposal_targets_source(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(
            client,
            **_BASIC_KWARGS,
            pre_aliquot_volume=10.0,
            pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
        )
        # First dispense call is the pre-aliquot
        first_disp_positions = _kwarg(client.dispense.call_args_list[0], "positions")
        assert all(p.labware == "Source1" for p in first_disp_positions)

    def test_pre_aliquot_waste_disposal_targets_liquid_waste(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(
            client,
            **_BASIC_KWARGS,
            pre_aliquot_volume=10.0,
            pre_aliquot_disposal=PreAliquotDisposal.WASTE,
        )
        first_disp_positions = _kwarg(client.dispense.call_args_list[0], "positions")
        assert all(p.labware == "liquid_waste" for p in first_disp_positions)

    def test_no_pre_aliquot_skips_extra_dispense(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=0.0)
        assert client.dispense.call_count == 1

    def test_iteration_pre_aliquot_dispense_populated(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        result = execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=10.0)
        assert result.iteration_results[0].pre_aliquot_dispense is not None

    def test_iteration_pre_aliquot_dispense_none_when_zero(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        result = execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=0.0)
        assert result.iteration_results[0].pre_aliquot_dispense is None


class TestAddReagentPostAliquot:
    """Post-aliquot re-dispense behavior."""

    def test_post_aliquot_adds_extra_dispense_call_per_chunk(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=5.0)
        # 1 chunk: 1 well dispense + 1 post-aliquot dispense = 2 dispense calls
        assert client.dispense.call_count == 2

    def test_post_aliquot_aspirate_volume_includes_post_aliquot(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=5.0)
        asp_volume = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert asp_volume == 55.0  # 50 + 5

    def test_post_aliquot_dispense_targets_source(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=5.0)
        # Last dispense call is the post-aliquot (order: well, then post)
        last_disp_positions = _kwarg(client.dispense.call_args_list[-1], "positions")
        assert all(p.labware == "Source1" for p in last_disp_positions)

    def test_no_post_aliquot_skips_extra_dispense(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=0.0)
        assert client.dispense.call_count == 1

    def test_iteration_post_aliquot_dispense_populated(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        result = execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=5.0)
        assert result.iteration_results[0].post_aliquot_dispense is not None

    def test_iteration_post_aliquot_dispense_none_when_zero(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        result = execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=0.0)
        assert result.iteration_results[0].post_aliquot_dispense is None

    def test_aspirate_includes_both_aliquots(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(
            client,
            **_BASIC_KWARGS,
            pre_aliquot_volume=10.0,
            post_aliquot_volume=5.0,
        )
        asp_volume = _kwarg(client.aspirate.call_args_list[0], "volumes")
        assert asp_volume == 65.0  # 50 + 10 + 5

    def test_three_dispense_calls_when_both_aliquots(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(
            client,
            **_BASIC_KWARGS,
            pre_aliquot_volume=10.0,
            post_aliquot_volume=5.0,
        )
        assert client.dispense.call_count == 3


# ===========================================================================
# Channel slicing
# ===========================================================================


class TestAddReagentChannels:
    """Custom channel lists are respected."""

    def test_custom_single_channel_produces_96_iterations(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS, channels=[1])
        assert result.iterations == 96
        assert result.wells_filled == 96

    def test_custom_single_channel_pickup_96_times(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS, channels=[1])
        assert client.tip_pickup.call_count == 96

    def test_channels_passed_to_aspirate(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, channels=[3])
        channels_used = _kwarg(client.aspirate.call_args_list[0], "channels")
        assert channels_used == [3]

    def test_channels_sliced_at_last_chunk(self):
        """9 destinations with 8 channels → chunk 2 uses 1 channel."""
        client = _make_execute_client(dest_rows=1, dest_cols=9)
        execute_add_reagent(client, **_BASIC_KWARGS)
        ch = _kwarg(client.tip_pickup.call_args_list[1], "channels")
        assert len(ch) == 1


# ===========================================================================
# Tip management
# ===========================================================================


class TestAddReagentReuseTips:
    """reuse_tips picks up one shared set for the whole command."""

    def test_single_pickup_across_all_chunks(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS, reuse_tips=True)
        assert client.tip_pickup.call_count == 1

    def test_single_eject_across_all_chunks(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS, reuse_tips=True)
        assert client.tip_eject.call_count == 1

    def test_still_fills_all_wells(self):
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS, reuse_tips=True)
        assert result.wells_filled == 96

    def test_default_picks_up_per_chunk(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.tip_pickup.call_count == 12
        assert client.tip_eject.call_count == 12

    def test_multi_dispense_single_pickup(self):
        client = _make_execute_client()
        execute_add_reagent(client, **_BASIC_KWARGS, multi_dispense=True, reuse_tips=True)
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1

    def test_shared_tips_ejected_on_aspirate_error(self):
        """A mid-run failure must not leave the shared reuse_tips set mounted."""
        client = _make_execute_client()
        client.aspirate.side_effect = RuntimeError("aspirate failed")
        with pytest.raises(RuntimeError, match="aspirate failed"):
            execute_add_reagent(client, **_BASIC_KWARGS, reuse_tips=True)
        assert client.tip_eject.call_count == 1

    def test_shared_tips_ejected_on_multi_dispense_error(self):
        client = _make_execute_client()
        client.aspirate.side_effect = RuntimeError("aspirate failed")
        with pytest.raises(RuntimeError, match="aspirate failed"):
            execute_add_reagent(client, **_BASIC_KWARGS, multi_dispense=True, reuse_tips=True)
        assert client.tip_eject.call_count == 1


class TestAddReagentConnectedContainer:
    """A connected-container source is aspirated by multiple channels at once."""

    def test_aspirate_spreads_across_container_positions(self):
        # 8-row single-column connected container feeding an 8-channel stroke:
        # each channel draws from a distinct position of the shared liquid.
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_BASIC_KWARGS)
        first_positions = _kwarg(client.aspirate.call_args_list[0], "positions")
        assert len(first_positions) == 8
        assert len({p.well for p in first_positions}) == 8

    def test_non_connected_source_broadcasts_single_position(self):
        # A 1x1 (non-connected) source broadcasts the same well to all channels.
        client = _make_execute_client(source_rows=1, source_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS)
        first_positions = _kwarg(client.aspirate.call_args_list[0], "positions")
        assert len({p.well for p in first_positions}) == 1

    def test_connected_multi_dispense_spreads_positions(self):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        execute_add_reagent(client, **_BASIC_KWARGS, multi_dispense=True)
        first_positions = _kwarg(client.aspirate.call_args_list[0], "positions")
        assert len({p.well for p in first_positions}) == 8


def _worklist(tmp_path, rows: list[tuple[str, str, float]]) -> str:
    """Write a transfer CSV of (source_well, dest_well, volume) rows from Source1 to Plate1."""
    lines = ["source_labware,source_well,dest_labware,dest_well,volume"]
    lines += [f"Source1,{src},Plate1,{dest},{vol}" for src, dest, vol in rows]
    path = tmp_path / "worklist.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


_COLUMN_1 = ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]


class TestAddReagentReservoirChannels:
    """A reservoir is one liquid with a section per channel: every channel is used,
    in passes when there are more channels than sections."""

    def test_reservoir_addressed_by_one_section_uses_every_section(self, tmp_path):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        csv = _worklist(tmp_path, [("1", w, 50.0) for w in _COLUMN_1])
        execute_add_reagent(client, **_BASIC_KWARGS, transfer_csv=csv)
        (asp,) = client.aspirate.call_args_list
        assert _kwarg(asp, "channels") == list(range(1, 9))
        assert [p.well for p in _kwarg(asp, "positions")] == [str(i) for i in range(1, 9)]

    def test_more_channels_than_sections_aspirates_in_passes(self):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True, dest_rows=16, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, channels=list(range(1, 17)))
        first, second = client.aspirate.call_args_list[:2]
        assert _kwarg(first, "channels") == list(range(1, 9))
        assert _kwarg(second, "channels") == list(range(9, 17))
        sections = [str(i) for i in range(1, 9)]
        assert [p.well for p in _kwarg(first, "positions")] == sections
        assert [p.well for p in _kwarg(second, "positions")] == sections
        # One dispense for all 16 channels.
        assert _kwarg(client.dispense.call_args_list[0], "channels") == list(range(1, 17))

    def test_pre_and_post_aliquots_return_to_the_reservoir_in_passes(self):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True, dest_rows=16, dest_cols=1)
        execute_add_reagent(
            client, **_BASIC_KWARGS, channels=list(range(1, 17)), pre_aliquot_volume=5.0, post_aliquot_volume=5.0
        )
        to_source = [c for c in client.dispense.call_args_list if _kwarg(c, "positions")[0].labware == "Source1"]
        assert [_kwarg(c, "channels") for c in to_source] == [list(range(1, 9)), list(range(9, 17))] * 2

    def test_per_channel_settings_follow_their_channels_into_each_pass(self):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True, dest_rows=16, dest_cols=1)
        heights = [float(i) for i in range(1, 17)]
        execute_add_reagent(
            client,
            **_BASIC_KWARGS,
            channels=list(range(1, 17)),
            aspirate_settings=AspirateSettings(fixed_height=heights),
        )
        first, second = client.aspirate.call_args_list[:2]
        assert _kwarg(first, "settings").fixed_height == heights[:8]
        assert _kwarg(second, "settings").fixed_height == heights[8:]


class TestAddReagentWorklistVolumes:
    """Each channel aspirates its own worklist volume, never the command-level fallback."""

    def test_a_single_well_aspirates_its_worklist_volume(self, tmp_path):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        csv = _worklist(tmp_path, [("1", "A1", 80.4)])
        execute_add_reagent(client, **{**_BASIC_KWARGS, "volume": 100.0}, transfer_csv=csv)
        (asp,) = client.aspirate.call_args_list
        assert _kwarg(asp, "volumes") == 80.4

    def test_variable_volumes_are_aspirated_and_dispensed_per_channel(self, tmp_path):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        csv = _worklist(tmp_path, [("1", "A1", 10.0), ("1", "B1", 20.0), ("1", "C1", 30.0)])
        execute_add_reagent(client, **_BASIC_KWARGS, transfer_csv=csv, pre_aliquot_volume=5.0)
        (asp,) = client.aspirate.call_args_list
        assert _kwarg(asp, "volumes") == [15.0, 25.0, 35.0]
        to_plate = [c for c in client.dispense.call_args_list if _kwarg(c, "positions")[0].labware == "Plate1"]
        (disp,) = to_plate
        assert _kwarg(disp, "volumes") == [10.0, 20.0, 30.0]

    def test_multi_dispense_aspirates_each_channels_own_total(self, tmp_path):
        client = _make_execute_client(source_rows=8, source_cols=1, source_connected=True)
        # Two channel-rows: channel 1 gets 10 + 40, channel 2 gets 20 + 50, channel 3 only 30.
        csv = _worklist(
            tmp_path,
            [("1", "A1", 10.0), ("1", "B1", 20.0), ("1", "C1", 30.0)]
            + [("1", w, 50.0) for w in _COLUMN_1[3:]]
            + [("1", "A2", 40.0), ("1", "B2", 50.0)],
        )
        execute_add_reagent(client, **_BASIC_KWARGS, transfer_csv=csv, multi_dispense=True)
        (asp,) = client.aspirate.call_args_list
        assert _kwarg(asp, "volumes") == [50.0, 70.0, 30.0, 50.0, 50.0, 50.0, 50.0, 50.0]

    def test_the_fallback_volume_is_not_checked_against_the_tip(self, tmp_path):
        client = _make_execute_client(tip_capacity=300.0)
        csv = _worklist(tmp_path, [("1", "A1", 50.0)])
        result = execute_add_reagent(client, **{**_BASIC_KWARGS, "volume": 1000.0}, transfer_csv=csv)
        assert result.wells_filled == 1


class TestAddReagentTipManagement:
    """Tip availability checks, per-chunk pickup/eject pairing."""

    def test_ensure_tips_called_at_start(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        with patch("hamilton_venus.compound_commands.add_reagent.ensure_tips_available") as mock_ensure:
            execute_add_reagent(client, **_BASIC_KWARGS)
        # tip_pool is the second positional argument to ensure_tips_available
        first_call_args = mock_ensure.call_args_list[0]
        assert first_call_args.args[1] == "TransferTips"

    def test_ensure_tips_called_before_each_chunk(self):
        """1 pre-flight + 1 per-chunk = 2 calls for a single chunk."""
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        with patch("hamilton_venus.compound_commands.add_reagent.ensure_tips_available") as mock_ensure:
            execute_add_reagent(client, **_BASIC_KWARGS)
        assert mock_ensure.call_count == 2

    def test_tip_eject_in_finally_on_aspirate_error(self):
        """If aspirate raises after tip pickup, tips are still ejected."""
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        client.aspirate.side_effect = RuntimeError("aspirate failed")
        with pytest.raises(RuntimeError, match="aspirate failed"):
            execute_add_reagent(client, **_BASIC_KWARGS)
        assert client.tip_eject.call_count == 1


# ===========================================================================
# Tip-reload prompt integration
# ===========================================================================


class TestAddReagentTipReload:
    """Operator tip-reload callback is exercised via ensure_tips_available."""

    def test_operator_cancelled_error_propagates(self):
        client = _make_execute_client()
        with (
            patch(
                "hamilton_venus.compound_commands.add_reagent.ensure_tips_available",
                side_effect=OperatorCancelledError("operator cancelled"),
            ),
            pytest.raises(OperatorCancelledError),
        ):
            execute_add_reagent(client, **_BASIC_KWARGS)


# ===========================================================================
# Consumable liquid management — multiple reagent sources
# ===========================================================================


class TestExecuteAddReagentMultiSource:
    """Each reagent_source selector is one source the channels are spread across;
    a list of selectors (with a worklist) is drained in order as each runs out.

    Source1 is an 8-row / 1-column tube rack (not a connected container), so
    each ``Source1@n`` is one tube.
    """

    _LLD = AspirateSettings(capacitive_lld=CapacitiveLLD.MID)

    def _run(self, client, tmp_path, reagent_source, *, n_wells=24, aspirate_settings=_LLD, channels=None):
        rows = [f"Plate1,{r}{c},50.0" for c in range(1, 4) for r in "ABCDEFGH"][:n_wells]
        csv = tmp_path / "worklist.csv"
        csv.write_text("dest_labware,dest_well,volume\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return execute_add_reagent(
            client,
            reagent_source=reagent_source,
            dest_plate="Plate1",
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
            transfer_csv=str(csv),
            aspirate_settings=aspirate_settings,
            **({"channels": channels} if channels else {}),
        )

    @staticmethod
    def _client():
        client = _make_execute_client(source_rows=8, source_cols=1, dest_rows=8, dest_cols=3)
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response()
        return client

    def test_one_tube_takes_every_channel_in_turn(self, tmp_path):
        client = self._client()
        self._run(client, tmp_path, "Source1@1", n_wells=8)
        calls = client.aspirate.call_args_list
        assert [_kwarg(c, "channels") for c in calls] == [[ch] for ch in range(1, 9)]
        assert {p.well for c in calls for p in _kwarg(c, "positions")} == {"1"}

    def test_channels_are_spread_across_the_selected_tubes(self, tmp_path):
        client = self._client()
        result = self._run(client, tmp_path, "Source1@1:4", n_wells=8)
        first, second = client.aspirate.call_args_list
        assert _kwarg(first, "channels") == [1, 2, 3, 4]
        assert _kwarg(second, "channels") == [5, 6, 7, 8]
        tubes = ["1", "2", "3", "4"]
        assert [p.well for p in _kwarg(first, "positions")] == tubes
        assert [p.well for p in _kwarg(second, "positions")] == tubes
        assert result.sources_used == ("Source1@1", "Source1@2", "Source1@3", "Source1@4")

    def test_every_channel_is_used_whatever_the_tube_count(self, tmp_path):
        client = self._client()
        self._run(client, tmp_path, "Source1@1:3", n_wells=16, channels=list(range(1, 17)))
        passes = [_kwarg(c, "channels") for c in client.aspirate.call_args_list]
        assert passes == [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12], [13, 14, 15], [16]]

    def test_a_list_of_selectors_is_drained_in_order(self, tmp_path):
        client = self._client()
        # Each stroke measures 10 uL left -- below the next stroke's 50 uL -- so
        # the next selector's tubes are used for every stroke.
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response_with_volume(10.0)
        result = self._run(client, tmp_path, ["Source1@1:4", "Source1@5:8"], n_wells=16)
        wells = [p.well for c in client.aspirate.call_args_list for p in _kwarg(c, "positions")]
        assert wells == ["1", "2", "3", "4"] * 2 + ["5", "6", "7", "8"] * 2
        assert result.sources_used[-1] == "Source1@8"

    def test_a_list_of_single_tubes_empties_one_tube_at_a_time(self, tmp_path):
        client = self._client()
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response_with_volume(10.0)
        result = self._run(client, tmp_path, ["Source1@1", "Source1@2", "Source1@3", "Source1@4"], n_wells=16)
        calls = client.aspirate.call_args_list
        # Stroke 1: every channel in turn at tube 1; stroke 2: at tube 2.
        assert [(_kwarg(c, "channels"), _kwarg(c, "positions")[0].well) for c in calls] == [
            ([ch], tube) for tube in ("1", "2") for ch in range(1, 9)
        ]
        assert result.sources_used == ("Source1@1", "Source1@2")

    def test_does_not_advance_while_the_source_has_enough(self, tmp_path):
        client = self._client()
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response_with_volume(500.0)
        result = self._run(client, tmp_path, ["Source1@1:4", "Source1@5:8"])
        assert result.sources_used == ("Source1@1", "Source1@2", "Source1@3", "Source1@4")

    def test_all_sources_exhausted_without_callback_traces_and_finishes(self, tmp_path, caplog):
        client = self._client()
        client.on_liquid_reload_prompt = None
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response_with_volume(1.0)
        result = self._run(client, tmp_path, ["Source1@1:4", "Source1@5:8"])
        assert result.wells_filled == 24
        assert "no refill was logged" in caplog.text

    def test_readings_from_aspirates_without_lld_are_ignored(self, tmp_path):
        # Without LLD VENUS reports the fixed aspirate height (0.0 uL), not a
        # measurement; it must not drain the sources.
        client = self._client()
        client.aspirate.side_effect = lambda **kw: _make_aspirate_response_with_volume(0.0)
        result = self._run(client, tmp_path, ["Source1@1:4", "Source1@5:8"], aspirate_settings=None)
        assert result.sources_used == ("Source1@1", "Source1@2", "Source1@3", "Source1@4")


# ===========================================================================
# Error-profile scoping
# ===========================================================================


class TestAddReagentErrorProfile:
    """When error_profile is provided, commands run inside the profile context."""

    def test_error_profile_context_entered(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        profile = MagicMock()
        ctx_manager = MagicMock()
        ctx_manager.__enter__ = MagicMock(return_value=None)
        ctx_manager.__exit__ = MagicMock(return_value=False)
        client.use_error_profile.return_value = ctx_manager
        execute_add_reagent(client, **_BASIC_KWARGS, error_profile=profile)
        client.use_error_profile.assert_called_once_with(profile)
        ctx_manager.__enter__.assert_called_once()

    def test_no_error_profile_does_not_call_use_error_profile(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        execute_add_reagent(client, **_BASIC_KWARGS, error_profile=None)
        client.use_error_profile.assert_not_called()


# ===========================================================================
# Parameter validation
# ===========================================================================


class TestAddReagentParameterValidation:
    """execute_add_reagent raises ValueError for bad inputs."""

    def test_volume_zero_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="volume must be > 0"):
            execute_add_reagent(client, **{**_BASIC_KWARGS, "volume": 0})

    def test_volume_negative_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="volume must be > 0"):
            execute_add_reagent(client, **{**_BASIC_KWARGS, "volume": -1})

    def test_pre_aliquot_negative_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="pre_aliquot_volume"):
            execute_add_reagent(client, **_BASIC_KWARGS, pre_aliquot_volume=-5.0)

    def test_post_aliquot_negative_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="post_aliquot_volume"):
            execute_add_reagent(client, **_BASIC_KWARGS, post_aliquot_volume=-1.0)

    def test_multi_dispense_returns_result(self):
        """multi_dispense=True is now implemented and returns AddReagentResult."""
        client = _make_execute_client()
        result = execute_add_reagent(client, **_BASIC_KWARGS, multi_dispense=True)
        assert isinstance(result, AddReagentResult)
        assert result.multi_dispense is True

    def test_transfer_csv_executes(self, tmp_path):
        """A valid CSV runs without error and returns AddReagentResult."""
        import textwrap

        csv_file = tmp_path / "transfer.csv"
        csv_file.write_text(
            textwrap.dedent(
                """\
                source_labware,source_well,dest_labware,dest_well,volume
                Source1,A1,Plate1,A1,50.0
                Source1,A1,Plate1,B1,50.0
                """
            ),
            encoding="utf-8",
        )
        src_pos = Position(labware="Source1", well="A1")
        dest_positions = [
            Position(labware="Plate1", well="A1"),
            Position(labware="Plate1", well="B1"),
        ]

        def _resolve(client, selector):
            if "Source1" in selector:
                return [src_pos]
            if "Plate1@wells:A1" in selector:
                return [dest_positions[0]]
            if "Plate1@wells:B1" in selector:
                return [dest_positions[1]]
            return []

        client = _make_execute_client()
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_resolve,
        ):
            result = execute_add_reagent(
                client,
                **{k: v for k, v in _BASIC_KWARGS.items() if k != "volume"},
                volume=50.0,
                transfer_csv=str(csv_file),
            )
        assert isinstance(result, AddReagentResult)
        assert result.wells_filled == 2
        assert result.source_plate_ids == ("Source1",)

    def test_total_volume_exceeds_tip_capacity_raises(self):
        client = _make_execute_client(tip_capacity=50.0)
        # Build kwargs without 'volume' so we can override it without conflict
        kwargs = {k: v for k, v in _BASIC_KWARGS.items() if k != "volume"}
        with pytest.raises(ValueError, match="tip capacity"):
            execute_add_reagent(
                client,
                **kwargs,
                volume=30.0,
                pre_aliquot_volume=15.0,
                post_aliquot_volume=10.0,
            )


# ===========================================================================
# Edge cases
# ===========================================================================


class TestAddReagentEdgeCases:
    """Empty destinations and single-well cases."""

    def test_empty_dest_returns_empty_result(self):
        client = _make_execute_client(dest_rows=0, dest_cols=0)
        # resolve_multi_selector will return [] for 0-row labware; patch it
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_multi_selector",
            side_effect=lambda c, selector, **kw: (
                [Position(labware="Source1", well="A1")] if "Source1" in selector else []
            ),
        ):
            result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.wells_filled == 0
        assert result.iterations == 0
        assert result.iteration_results == ()

    def test_single_well_single_iteration(self):
        client = _make_execute_client(dest_rows=1, dest_cols=1)
        result = execute_add_reagent(client, **_BASIC_KWARGS)
        assert result.iterations == 1
        assert result.wells_filled == 1

    def test_empty_source_raises_value_error(self):
        client = _make_execute_client()
        with (
            patch(
                "hamilton_venus.compound_commands.add_reagent.resolve_multi_selector",
                return_value=[],
            ),
            pytest.raises(ValueError, match="Reagent source"),
        ):
            execute_add_reagent(client, **_BASIC_KWARGS)


# ===========================================================================
# CSV execution
# ===========================================================================


def _make_csv_resolve(positions: dict[str, list[Position]]):
    """Return a side_effect function for patching resolve_selector_positions.

    *positions* maps selector substrings (e.g. ``"Source1@wells:A1"``) to the
    list of Position objects that should be returned.  The first matching key
    wins; if nothing matches, an empty list is returned.
    """

    def _resolve(_client, selector: str):
        for key, pos_list in positions.items():
            if key in selector:
                return pos_list
        return []

    return _resolve


def _make_csv_client(*, tip_capacity: float = 300.0, available_tips: int = 200) -> MagicMock:
    """Minimal mock client for CSV execution tests (no labware geometry needed)."""
    from hamilton_venus.models.position import LabwareLayoutSpec

    client = MagicMock()
    counter_resp = MagicMock()
    counter_resp.return_parameters.tip_type_id = "0"
    client.tip_pool_get_tip_counter.return_value = counter_resp
    types_resp = MagicMock()
    types_resp.return_parameters.tip_types = {"0": {"Max Liquid Volume": tip_capacity}}
    client.get_tip_types.return_value = types_resp
    avail_resp = MagicMock()
    avail_resp.return_parameters.total_available_tips = available_tips
    client.tip_pool_get_available_tips.return_value = avail_resp
    client.tip_pickup.return_value = _make_response()
    client.tip_eject.return_value = _make_response()
    client.aspirate.return_value = _make_aspirate_response()
    client.dispense.return_value = _make_dispense_response()
    client.get_labware_spec.side_effect = lambda _lid: LabwareLayoutSpec.from_definition(
        {"rack_layout": {"rows": 8, "columns": 12}}
    )
    return client


class TestAddReagentCsvExecution:
    """execute_add_reagent CSV path: position resolution and row ordering."""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    _SRC1_A1 = Position(labware="Source1", well="A1")
    _PLT1_A1 = Position(labware="Plate1", well="A1")
    _PLT1_B1 = Position(labware="Plate1", well="B1")
    _PLT1_C1 = Position(labware="Plate1", well="C1")
    _SRC2_A1 = Position(labware="Source2", well="A1")
    _PLT2_A1 = Position(labware="Plate2", well="A1")

    def _write_csv(self, tmp_path, rows: list[tuple[str, str, str, str, float]]) -> str:
        p = tmp_path / "transfer.csv"
        lines = ["source_labware,source_well,dest_labware,dest_well,volume"]
        for sl, sw, dl, dw, vol in rows:
            lines.append(f"{sl},{sw},{dl},{dw},{vol}")
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)

    def _pos_map(self) -> dict[str, list[Position]]:
        return {
            "Source1@wells:A1": [self._SRC1_A1],
            "Source2@wells:A1": [self._SRC2_A1],
            "Plate1@wells:A1": [self._PLT1_A1],
            "Plate1@wells:B1": [self._PLT1_B1],
            "Plate1@wells:C1": [self._PLT1_C1],
            "Plate2@wells:A1": [self._PLT2_A1],
        }

    # ------------------------------------------------------------------
    # basic CSV execution
    # ------------------------------------------------------------------

    def test_csv_two_rows_same_source_fills_two_wells(self, tmp_path):
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Source1", "A1", "Plate1", "A1", 50.0),
                ("Source1", "A1", "Plate1", "B1", 50.0),
            ],
        )
        client = _make_csv_client()
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                liquid_class="Water",
            )
        assert result.wells_filled == 2
        assert result.source_plate_ids == ("Source1",)
        assert result.dest_plate_ids == ("Plate1",)

    def test_csv_source_columns_are_ignored(self, tmp_path, caplog):
        """The reagent always comes from reagent_source; a worklist's own source
        columns (e.g. a reused hit-picking worklist) are ignored with a warning."""
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Source1", "A1", "Plate1", "A1", 50.0),
                ("Source2", "A1", "Plate2", "A1", 60.0),
            ],
        )
        client = _make_csv_client()
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                liquid_class="Water",
            )
        assert result.wells_filled == 2
        assert result.source_plate_ids == ("Source1",)
        assert set(result.dest_plate_ids) == {"Plate1", "Plate2"}
        assert "is ignored" in caplog.text

    def test_csv_without_source_columns(self, tmp_path):
        p = tmp_path / "worklist.csv"
        p.write_text("dest_well,volume\nA1,50.0\nB1,60.0\n", encoding="utf-8")
        client = _make_csv_client()
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=str(p),
                liquid_class="Water",
            )
        assert result.wells_filled == 2
        assert result.dest_plate_ids == ("Plate1",)

    def test_a_multi_tube_reagent_source_spreads_the_channels(self, tmp_path):
        """reagent_source picks the tubes, e.g. "Source1@1:4" -- not the worklist."""
        csv_path = self._write_csv(tmp_path, [("Other", "B7", "Plate1", "A1", 50.0)])
        client = _make_csv_client()
        tubes = [Position(labware="Source1", well=str(i)) for i in range(1, 5)]
        with (
            patch(
                "hamilton_venus.compound_commands.add_reagent.resolve_multi_selector",
                side_effect=lambda c, sel: tubes if sel == "Source1@1:4" else [],
            ),
            patch(
                "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
                side_effect=_make_csv_resolve(self._pos_map()),
            ),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1@1:4",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                liquid_class="Water",
            )
        # One well, so one channel: it takes the first tube.
        (asp,) = client.aspirate.call_args_list
        assert _kwarg(asp, "positions") == [tubes[0]]
        assert result.source_plate_ids == ("Source1",)

    def test_csv_multi_dispense_mode(self, tmp_path):
        """CSV + multi_dispense=True: one tip pickup for the whole source run."""
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Source1", "A1", "Plate1", "A1", 50.0),
                ("Source1", "A1", "Plate1", "B1", 50.0),
                ("Source1", "A1", "Plate1", "C1", 50.0),
            ],
        )
        client = _make_csv_client()
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                multi_dispense=True,
                liquid_class="Water",
            )
        assert result.wells_filled == 3
        assert result.multi_dispense is True
        # One tip pickup for all three wells in one source run.
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1

    # ------------------------------------------------------------------
    # follow_csv_order
    # ------------------------------------------------------------------

    def test_follow_csv_order_false_groups_by_dest_plate(self, tmp_path):
        """Default (False): an A->B->A plate pattern collapses to two plate runs."""
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Source1", "A1", "Plate1", "A1", 50.0),
                ("Source2", "A1", "Plate2", "A1", 60.0),
                ("Source1", "A1", "Plate1", "B1", 50.0),
            ],
        )
        client = _make_csv_client()

        # Track the source of every aspirate and the plate of every dispense.
        asp_labware: list[str] = []
        disp_plates: list[str] = []

        def _track_asp(**kw):
            asp_labware.append(kw["positions"][0].labware)
            return _make_aspirate_response()

        def _track_disp(**kw):
            disp_plates.append(kw["positions"][0].labware)
            return _make_dispense_response()

        client.aspirate.side_effect = _track_asp
        client.dispense.side_effect = _track_disp

        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                follow_csv_order=False,
                liquid_class="Water",
            )

        assert result.wells_filled == 3
        assert set(asp_labware) == {"Source1"}
        # Plate1's two wells go in one stroke, then Plate2.
        assert disp_plates == ['Plate1', 'Plate2']

    def test_follow_csv_order_true_preserves_csv_order(self, tmp_path):
        """True: an A->B->A plate pattern yields three runs in CSV order."""
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Source1", "A1", "Plate1", "A1", 50.0),
                ("Source2", "A1", "Plate2", "A1", 60.0),
                ("Source1", "A1", "Plate1", "B1", 50.0),
            ],
        )
        client = _make_csv_client()

        # Track the source of every aspirate and the plate of every dispense.
        asp_labware: list[str] = []
        disp_plates: list[str] = []

        def _track_asp(**kw):
            asp_labware.append(kw["positions"][0].labware)
            return _make_aspirate_response()

        def _track_disp(**kw):
            disp_plates.append(kw["positions"][0].labware)
            return _make_dispense_response()

        client.aspirate.side_effect = _track_asp
        client.dispense.side_effect = _track_disp

        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            side_effect=_make_csv_resolve(self._pos_map()),
        ):
            result = execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate="Plate1",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                follow_csv_order=True,
                liquid_class="Water",
            )

        assert result.wells_filled == 3
        assert set(asp_labware) == {"Source1"}
        # CSV order: Plate1, Plate2, Plate1 (three independent runs).
        assert disp_plates == ['Plate1', 'Plate2', 'Plate1']

class TestAddReagentLabwareValidation:
    """Up-front labware validation accumulates errors across all bad labware."""

    @staticmethod
    def _client_missing(missing: set[str]) -> MagicMock:
        client = _make_csv_client()

        def _side_effect(labware_id: str) -> MagicMock:
            if labware_id in missing:
                fail = MagicMock(
                    action_name="labware.getLabwareParamsFromID",
                    return_status="Failure",
                    return_code=1,
                    return_parameters={},
                )
                raise VenusCommandFailedError(fail)
            resp = MagicMock()
            resp.return_parameters.definition = {"rack_layout": {"rows": 8, "columns": 12}}
            return resp

        client.labware_get_params_from_id.side_effect = _side_effect
        return client

    @staticmethod
    def _write_csv(tmp_path, rows: list[tuple[str, str, str, str, float]]) -> str:
        p = tmp_path / "transfer.csv"
        lines = ["source_labware,source_well,dest_labware,dest_well,volume"]
        for sl, sw, dl, dw, vol in rows:
            lines.append(f"{sl},{sw},{dl},{dw},{vol}")
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)

    def test_non_csv_raises_when_source_missing(self):
        client = self._client_missing({"Src"})
        with pytest.raises(ValueError, match="Src"):
            execute_add_reagent(
                client,
                reagent_source="Src",
                dest_plate="Dst",
                volume=50.0,
                tip_pool="tips",
                liquid_class="Water",
            )

    def test_non_csv_lists_both_when_both_missing(self):
        client = self._client_missing({"Src", "Dst"})
        with pytest.raises(ValueError) as exc:
            execute_add_reagent(
                client,
                reagent_source="Src",
                dest_plate="Dst",
                volume=50.0,
                tip_pool="tips",
                liquid_class="Water",
            )
        msg = str(exc.value)
        assert "Src" in msg
        assert "Dst" in msg

    def test_non_csv_strips_well_selector_before_validation(self):
        client = self._client_missing(set())
        with patch(
            "hamilton_venus.compound_commands.add_reagent.resolve_selector_positions",
            return_value=[Position(labware="Src", well="A1")],
        ):
            execute_add_reagent(
                client,
                reagent_source="Src@A1",
                dest_plate="Dst@A1:H1",
                volume=50.0,
                tip_pool="tips",
                liquid_class="Water",
            )
        called = {c.args[0] for c in client.labware_get_params_from_id.call_args_list}
        assert "Src" in called
        assert "Dst" in called
        assert "Src@A1" not in called

    def test_csv_lists_all_missing_in_one_error(self, tmp_path):
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Ignored", "A1", "BadDst", "A1", 50.0),
                ("Ignored", "A1", "OkDst", "A1", 50.0),
            ],
        )
        client = self._client_missing({"BadSrc", "BadDst"})
        with pytest.raises(ValueError) as exc:
            execute_add_reagent(
                client,
                reagent_source="BadSrc",
                dest_plate="OkDst",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                liquid_class="Water",
            )
        msg = str(exc.value)
        assert "BadSrc" in msg
        assert "BadDst" in msg

    def test_csv_error_includes_first_referenced_line_numbers(self, tmp_path):
        csv_path = self._write_csv(
            tmp_path,
            [
                ("Ignored", "A1", "OkDst", "A1", 50.0),
                ("Ignored", "A1", "OkDst", "B1", 50.0),
                ("Ignored", "A1", "BadDst", "A1", 50.0),
            ],
        )
        client = self._client_missing({"BadSrc", "BadDst"})
        with pytest.raises(ValueError) as exc:
            execute_add_reagent(
                client,
                reagent_source="BadSrc",
                dest_plate="OkDst",
                volume=50.0,
                tip_pool="tips",
                transfer_csv=csv_path,
                liquid_class="Water",
            )
        msg = str(exc.value)
        # BadDst first appears on line 4; the reagent source is not from the CSV.
        assert "'BadDst' (first referenced on CSV line 4)" in msg
        assert "'BadSrc'" in msg
        assert "'BadSrc' (first referenced" not in msg

# ===========================================================================
# Multi-plate (list[str]) selectors — non-CSV path
# ===========================================================================


class TestAddReagentMultiPlate:
    """list[str] selector support: broadcast (1 src → N dst) and index-wise (N → N)."""

    def test_dest_list_two_plates_one_iteration_per_plate(self):
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source="Source1",
            dest_plate=["Plate1@col:1", "Plate2@col:1"],
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert result.wells_filled == 16
        assert set(result.dest_plate_ids) == {"Plate1", "Plate2"}
        assert result.wells_filled_by_plate == {"Plate1": 8, "Plate2": 8}
        # single-dispense mode: each plate's 8 wells = 1 chunk of 8 channels → 2 iterations total.
        assert result.iterations == 2

    def test_dest_list_single_entry_equivalent_to_string(self):
        client_a = _make_execute_client()
        client_b = _make_execute_client()
        r_str = execute_add_reagent(
            client_a,
            reagent_source="Source1",
            dest_plate="Plate1@col:1",
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        r_list = execute_add_reagent(
            client_b,
            reagent_source="Source1",
            dest_plate=["Plate1@col:1"],
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert r_str.wells_filled == r_list.wells_filled
        assert r_str.iterations == r_list.iterations
        assert r_str.dest_plate_ids == r_list.dest_plate_ids

    def test_n_to_n_source_dest_pairs_index_wise(self):
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source=["Source1@A1", "Source2@A1"],
            dest_plate=["Plate1@col:1", "Plate2@col:1"],
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert result.wells_filled == 16
        assert set(result.source_plate_ids) == {"Source1", "Source2"}
        assert set(result.dest_plate_ids) == {"Plate1", "Plate2"}

    def test_mismatched_lengths_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="must have matching length or one source must broadcast"):
            execute_add_reagent(
                client,
                reagent_source=["Source1@A1", "Source2@A1"],
                dest_plate=["Plate1@col:1", "Plate2@col:1", "Plate3@col:1"],
                volume=50.0,
                tip_pool="TransferTips",
                liquid_class="Water",
            )

    def test_empty_dest_list_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="dest_plate list must contain at least one entry"):
            execute_add_reagent(
                client,
                reagent_source="Source1",
                dest_plate=[],
                volume=50.0,
                tip_pool="TransferTips",
                liquid_class="Water",
            )

    def test_empty_source_list_raises(self):
        client = _make_execute_client()
        with pytest.raises(ValueError, match="reagent_source list must contain at least one entry"):
            execute_add_reagent(
                client,
                reagent_source=[],
                dest_plate="Plate1@col:1",
                volume=50.0,
                tip_pool="TransferTips",
                liquid_class="Water",
            )

    def test_csv_path_with_list_source_drains_the_list(self, tmp_path):
        """reagent_source may be a list with a worklist too: it is the drain order."""
        csv_path = tmp_path / "x.csv"
        csv_path.write_text("dest_labware,dest_well,volume\nPlate1,A1,50.0\n")
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source=["Source1"],
            dest_plate="Plate1",
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
            transfer_csv=str(csv_path),
        )
        assert result.wells_filled == 1
        assert result.source_plate_ids == ("Source1",)

    def test_multi_dispense_does_not_cross_plate_boundary(self):
        # multi-dispense mode with tip_capacity=300 and volume=50 → up to 6 wells per
        # aspirate; with 8 channels each row = 8 wells = 400 > 300, so each
        # row spans one aspirate → 2 iterations (one per plate column).
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source="Source1",
            dest_plate=["Plate1@col:1", "Plate2@col:1"],
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
            multi_dispense=True,
        )
        assert result.wells_filled == 16
        # Each iteration belongs to a single plate.
        for it in result.iteration_results:
            plates_in_iter = {wd.dest_plate_id for wd in it.well_dispenses}
            assert len(plates_in_iter) == 1


class TestAddReagentPositionInput:
    """dest_plate/reagent_source may be pre-resolved Position objects (e.g. from
    normalize_positions), not just selector strings."""

    def test_dest_plate_as_position_list(self):
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source="Source1",
            dest_plate=[Position(labware="Plate1", well="A1"), Position(labware="Plate1", well="B1")],
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert result.wells_filled == 2
        assert result.dest_plate_ids == ("Plate1",)

    def test_dest_plate_as_position_list_still_batches_by_channel_count(self):
        """Regression test: a pre-resolved dest_plate list[Position] (e.g. from
        normalize_positions) must be treated as ONE destination selector
        spanning all its wells -- not exploded into one broadcast run per
        well, which would silently cap every tip pickup/aspirate/dispense to
        a single channel regardless of the requested channel count."""
        client = _make_execute_client(dest_rows=2, dest_cols=8)  # 16 wells
        dest_positions = [
            Position(labware="Plate1", well=f"{row}{col}")
            for col in range(1, 9)
            for row in ("A", "B")
        ]
        execute_add_reagent(
            client,
            reagent_source="Source1",
            dest_plate=dest_positions,
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert client.tip_pickup.call_count == 2  # 16 wells / 8 channels, not 16 single-channel chunks
        first_channels = _kwarg(client.tip_pickup.call_args_list[0], "channels")
        assert len(first_channels) == 8

    def test_reagent_source_as_single_position(self):
        client = _make_execute_client()
        result = execute_add_reagent(
            client,
            reagent_source=Position(labware="Source1", well="1"),
            dest_plate="Plate1@A1",
            volume=50.0,
            tip_pool="TransferTips",
            liquid_class="Water",
        )
        assert result.wells_filled == 1
        assert result.source_plate_ids == ("Source1",)
