from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hamilton_venus.compound_commands._helpers._grid import DilutionGrid
from hamilton_venus.compound_commands.serial_dilution import (
    _count_transfer_tips,
    execute_serial_dilution_by_dilution_factor,
    execute_serial_dilution_by_volume,
)
from hamilton_venus.exceptions import OperatorCancelledError
from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
from hamilton_venus.models.compound_results import SerialDilutionResult
from hamilton_venus.models.enums import CapacitiveLLD, LastDilutionWaste
from hamilton_venus.models.liquid_handling_settings import AspirateSettings
from hamilton_venus.models.position import LabwareLayoutSpec, Position

_MODULE = "hamilton_venus.compound_commands.serial_dilution"
_LIQUID_MODULE = "hamilton_venus.compound_commands._helpers._liquid_manager"


def _asp(volumes: list[float] | None = None) -> ChannelAspirationResponse:
    channels = [{"liquidVolume_uL": v} for v in volumes] if volumes is not None else []
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={"channels": channels},
    )


def _disp() -> ChannelDispenseResponse:
    return ChannelDispenseResponse(return_status="Success", return_code=0, return_parameters={"channels": []})


def _mock_client(rows: int = 8, cols: int = 12, *, on_liquid_reload_prompt=None) -> MagicMock:
    client = MagicMock()
    client.on_liquid_reload_prompt = on_liquid_reload_prompt
    client.get_labware_spec.return_value = LabwareLayoutSpec(rows=rows, cols=cols)
    client.aspirate.return_value = _asp()
    client.dispense.return_value = _disp()
    client.use_error_profile.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False))
    return client


def _patch_env(monkeypatch, *, plate_ids=("Plate",), waste_well: str | None = "W1", capacity: float = 1000.0):
    """Patch the module-level helpers the command imports.

    Returns the MagicMocks so individual tests can tighten expectations.
    """
    resolve_multi = MagicMock(
        side_effect=lambda client, selectors: [Position(labware=pid, well="A1") for pid in plate_ids]
    )
    resolve_sel = MagicMock(side_effect=lambda client, selector: [Position(labware="Trough", well="A1")])
    validate_labware = MagicMock()
    resolve_tip_cap = MagicMock(return_value=capacity)
    ensure_tips = MagicMock()
    pickup = MagicMock()
    eject = MagicMock()
    plan_batches = MagicMock(side_effect=_real_plan_batches)
    waste = MagicMock(return_value=Position(labware="Waste", well=waste_well) if waste_well else None)

    monkeypatch.setattr(f"{_MODULE}.resolve_multi_selector", resolve_multi)
    # Diluent-source resolution now delegates to the shared consumable-liquid-management
    # helper (resolve_source_positions -> resolve_selector_positions), so patch it there.
    monkeypatch.setattr(f"{_LIQUID_MODULE}.resolve_selector_positions", resolve_sel)
    monkeypatch.setattr(f"{_MODULE}.validate_labware_on_deck", validate_labware)
    monkeypatch.setattr(f"{_MODULE}._resolve_tip_capacity", resolve_tip_cap)
    monkeypatch.setattr(f"{_MODULE}.ensure_tips_available", ensure_tips)
    monkeypatch.setattr(f"{_MODULE}.pickup_tips", pickup)
    monkeypatch.setattr(f"{_MODULE}.eject_tips", eject)
    monkeypatch.setattr(f"{_MODULE}.plan_dispense_batches", plan_batches)
    monkeypatch.setattr(f"{_MODULE}.resolve_waste_position", waste)

    return {
        "resolve_multi": resolve_multi,
        "resolve_sel": resolve_sel,
        "validate_labware": validate_labware,
        "resolve_tip_cap": resolve_tip_cap,
        "ensure_tips": ensure_tips,
        "pickup": pickup,
        "eject": eject,
        "plan_batches": plan_batches,
        "waste": waste,
    }


def _real_plan_batches(rows, capacity, budget=None):
    """Greedy pack rows into batches bounded by capacity (and budget when set)."""
    limit = capacity if budget is None else min(capacity, budget)
    batches: list[list] = []
    current: list = []
    total = 0.0
    for row in rows:
        row_vol = max(v for _, v in row)
        if current and total + row_vol > limit + 1e-9:
            batches.append(current)
            current = []
            total = 0.0
        current.append(row)
        total += row_vol
    if current:
        batches.append(current)
    return batches


# Level readings only count from aspirates that detect the liquid.
_LLD = AspirateSettings(capacitive_lld=CapacitiveLLD.MID)

_BASE = dict(
    plate_id="Plate",
    start_column=1,
    num_dilutions=3,
    transfer_volume=20.0,
    diluent_source="Trough",
    diluent_tip_pool="DiluentTips",
    transfer_tip_pool="TransferTips",
)


def _run_by_volume(client, monkeypatch_env_kwargs=None, **overrides):
    kwargs = {**_BASE, "diluent_volume": 180.0, **overrides}
    return execute_serial_dilution_by_volume(client, **kwargs)


class TestByVolumeBasic:
    def test_returns_result_and_counts(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        assert isinstance(result, SerialDilutionResult)
        # 8 rows -> 8 series, 3 dilutions each.
        assert result.num_series == 8
        assert result.num_dilutions == 3
        assert result.total_wells_processed == 24
        assert result.iterations == 1  # single (plate, pass)
        assert result.plate_ids == ("Plate",)

    def test_transfer_chain_columns(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        series = result.plate_results[0].series_results[0]
        # start_column=1, 3 dilutions -> chain 1,2,3,4.
        assert series.well_chain == ("A1", "A2", "A3", "A4")
        assert len(series.steps) == 3
        assert series.steps[0].source_well == "A1"
        assert series.steps[0].dest_well == "A2"


class TestByDilutionFactor:
    def test_diluent_volume_derived(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_dilution_factor(client, **_BASE, dilution_factor=10.0)
        # transfer_volume * (factor - 1) = 20 * 9 = 180.
        assert result.diluent_volume == 180.0
        assert result.dilution_factor == 10.0

    def test_two_fold(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_dilution_factor(client, **_BASE, dilution_factor=2.0)
        assert result.diluent_volume == 20.0

    def test_factor_below_one_raises(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        with pytest.raises(ValueError):
            execute_serial_dilution_by_dilution_factor(client, **_BASE, dilution_factor=0.5)


class TestDiluentPhase:
    def test_precharges_dilution_columns_only(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        series = result.plate_results[0].series_results[0]
        # 3 dilution columns (2,3,4) get diluent; sample column (1) does not.
        assert len(series.diluent_dispenses) == 3

    def test_zero_diluent_skips_phase(self, monkeypatch):
        env = _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **{**_BASE, "diluent_tip_pool": ""}, diluent_volume=0.0)
        series = result.plate_results[0].series_results[0]
        assert series.diluent_dispenses == ()
        # Only the transfer tip pool is ensured (no diluent phase).
        pools = [call.args[1] for call in env["ensure_tips"].call_args_list]
        assert "DiluentTips" not in pools

    def test_diluent_uses_source(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        # First aspirate is the diluent phase, from the resolved trough.
        first_asp = client.aspirate.call_args_list[0]
        assert first_asp.kwargs["positions"][0].labware == "Trough"


class TestDiluentMultiDispense:
    def test_multi_vs_single_dispense_counts(self, monkeypatch):
        _patch_env(monkeypatch, capacity=1000.0)
        client_multi = _mock_client()
        r_multi = execute_serial_dilution_by_volume(
            client_multi, **_BASE, diluent_volume=180.0, diluent_multi_dispense=True
        )
        client_single = _mock_client()
        r_single = execute_serial_dilution_by_volume(
            client_single, **_BASE, diluent_volume=180.0, diluent_multi_dispense=False
        )
        # Same number of diluent dispenses (3 columns) either way.
        assert len(r_multi.plate_results[0].series_results[0].diluent_dispenses) == 3
        assert len(r_single.plate_results[0].series_results[0].diluent_dispenses) == 3
        # Multi-dispense aspirates fewer times than single-dispense.
        multi_aspirates = client_multi.aspirate.call_count
        single_aspirates = client_single.aspirate.call_count
        assert multi_aspirates < single_aspirates


class TestDiluentTracking:
    def test_reactive_seed_and_source_switch(self, monkeypatch):
        # Two troughs; force the first to report a level below the next batch's
        # requirement so the tracker advances to the second *between* aspirates.
        env = _patch_env(monkeypatch, capacity=40.0)
        env["resolve_sel"].side_effect = lambda client, selector: [Position(labware=selector, well="A1")]
        client = _mock_client()
        # capacity == diluent_volume forces one column per aspirate.  The first
        # aspirate measures 30 uL remaining (< the next 40 uL batch), so the
        # second batch's ensure_available advances to TroughB.
        client.aspirate.side_effect = [
            _asp([30.0] * 8),  # diluent aspirate 1: TroughA nearly empty
            _asp([900.0] * 8),  # diluent aspirate 2: from TroughB
            *[_asp() for _ in range(50)],  # remaining strokes
        ]
        result = execute_serial_dilution_by_volume(
            client,
            **{**_BASE, "diluent_source": ["TroughA", "TroughB"]},
            diluent_volume=40.0,
            diluent_asp_settings=_LLD,
        )
        # Both sources recorded as used, in order.
        assert result.diluent_sources_used[0].startswith("TroughA@")
        assert any(s.startswith("TroughB@") for s in result.diluent_sources_used)

    def test_connected_diluent_spreads_across_positions(self, monkeypatch):
        # A connected-container diluent is aspirated by multiple channels at once,
        # each drawing from a distinct position of the shared liquid.
        env = _patch_env(monkeypatch)
        env["resolve_sel"].side_effect = lambda client, selector: [
            Position(labware="RgtContainer", well=str(i + 1)) for i in range(8)
        ]
        client = _mock_client()
        client.get_labware_spec.side_effect = lambda labware, *a, **k: LabwareLayoutSpec(
            rows=8, cols=12, connected_container=(labware == "RgtContainer")
        )
        execute_serial_dilution_by_volume(
            client, **{**_BASE, "diluent_source": "RgtContainer"}, diluent_volume=180.0
        )
        positions = client.aspirate.call_args_list[0].kwargs["positions"]
        assert len(positions) > 1
        assert len({p.well for p in positions}) == len(positions)

    def test_connected_diluent_caps_channels_when_fewer_positions(self, monkeypatch):
        # A connected container with fewer positions (4) than the plate's pass
        # rows (8) caps the simultaneous channels to 4 and charges the pass in
        # two channel-sized sub-groups; every aspirate spreads across the 4
        # distinct positions rather than broadcasting all tips onto one.
        env = _patch_env(monkeypatch)
        env["resolve_sel"].side_effect = lambda client, selector: [
            Position(labware="RgtContainer", well=str(i + 1)) for i in range(4)
        ]
        client = _mock_client()
        client.get_labware_spec.side_effect = lambda labware, *a, **k: LabwareLayoutSpec(
            rows=8, cols=12, connected_container=(labware == "RgtContainer")
        )
        execute_serial_dilution_by_volume(
            client, **{**_BASE, "diluent_source": "RgtContainer"}, diluent_volume=180.0
        )
        # Every diluent aspirate (from the connected container) uses exactly the
        # 4 available positions, each distinct (no broadcast-to-one).
        diluent_aspirates = [
            call
            for call in client.aspirate.call_args_list
            if call.kwargs["positions"] and call.kwargs["positions"][0].labware == "RgtContainer"
        ]
        assert diluent_aspirates  # sanity: diluent phase actually ran
        for call in diluent_aspirates:
            positions = call.kwargs["positions"]
            assert len(positions) == 4
            assert len({p.well for p in positions}) == 4

    def test_connected_diluent_dry_across_positions_switches_source(self, monkeypatch):
        # Two connected troughs of 8 positions each.  The first reports a level
        # (measured min across the 8 spread channels) below the next batch's
        # requirement, so the tracker advances to the second connected trough.
        env = _patch_env(monkeypatch, capacity=40.0)

        def _resolve(client, selector):
            return [Position(labware=selector, well=str(i + 1)) for i in range(8)]

        env["resolve_sel"].side_effect = _resolve
        client = _mock_client()
        client.get_labware_spec.side_effect = lambda labware, *a, **k: LabwareLayoutSpec(
            rows=8, cols=12, connected_container=True
        )
        client.aspirate.side_effect = [
            _asp([30.0] * 8),  # TroughA spread across 8 positions: nearly empty
            _asp([900.0] * 8),  # advanced to TroughB
            *[_asp() for _ in range(50)],
        ]
        result = execute_serial_dilution_by_volume(
            client,
            **{**_BASE, "diluent_source": ["TroughA", "TroughB"]},
            diluent_volume=40.0,
            diluent_asp_settings=_LLD,
        )
        assert result.diluent_sources_used[0].startswith("TroughA@")
        assert any(s.startswith("TroughB@") for s in result.diluent_sources_used)

    def test_exhaustion_without_callback_traces_and_finishes(self, monkeypatch, caplog):
        env = _patch_env(monkeypatch, capacity=100.0)
        env["resolve_sel"].side_effect = lambda client, selector: [Position(labware=selector, well="A1")]
        client = _mock_client(on_liquid_reload_prompt=None)
        # Every aspirate measures empty, so the tracker exhausts the only source.
        client.aspirate.side_effect = [_asp([0.0] * 8) for _ in range(50)]
        execute_serial_dilution_by_volume(
            client, **{**_BASE, "diluent_source": "TroughA"}, diluent_volume=40.0, diluent_asp_settings=_LLD
        )
        assert "no refill was logged" in caplog.text

    def test_exhaustion_cancel_raises_operator_cancelled(self, monkeypatch):
        env = _patch_env(monkeypatch, capacity=100.0)
        env["resolve_sel"].side_effect = lambda client, selector: [Position(labware=selector, well="A1")]
        client = _mock_client(on_liquid_reload_prompt=lambda ctx: False)
        client.aspirate.side_effect = [_asp([0.0] * 8) for _ in range(50)]
        with pytest.raises(OperatorCancelledError):
            execute_serial_dilution_by_volume(
                client, **{**_BASE, "diluent_source": "TroughA"}, diluent_volume=40.0, diluent_asp_settings=_LLD
            )


class TestTransferPhase:
    def test_step_k_aspirates_previous_dest(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        steps = result.plate_results[0].series_results[0].steps
        # Step 1's source is step 0's dest.
        assert steps[1].source_well == steps[0].dest_well


class TestMix:
    def _disp_settings_with_cycles(self, cycles: int):
        from hamilton_venus.models.liquid_handling_settings import DispenseSettings

        return DispenseSettings(mix_cycles=cycles)

    def test_mix_emits_extra_dispense(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        with_mix = execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            mix_after_dispense=True,
            transfer_disp_settings=self._disp_settings_with_cycles(3),
        )
        assert with_mix.plate_results[0].series_results[0].steps[0].mix is not None

    def test_mix_suppressed_when_disabled(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        no_mix = execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            mix_after_dispense=False,
            transfer_disp_settings=self._disp_settings_with_cycles(3),
        )
        assert no_mix.plate_results[0].series_results[0].steps[0].mix is None

    def test_no_mix_without_cycles(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0, mix_after_dispense=True)
        assert result.plate_results[0].series_results[0].steps[0].mix is None


class TestLastExcess:
    def test_none_no_extra_step(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client, **_BASE, diluent_volume=180.0, discard_last_excess=LastDilutionWaste.NONE
        )
        assert len(result.plate_results[0].series_results[0].steps) == 3

    def test_to_waste_adds_dispense_to_waste(self, monkeypatch):
        _patch_env(monkeypatch, waste_well="W1")
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            discard_last_excess=LastDilutionWaste.TO_WASTE,
        )
        steps = result.plate_results[0].series_results[0].steps
        assert len(steps) == 4
        assert steps[3].dispense is not None
        assert steps[3].dest_well == "W1"

    def test_with_tip_eject_no_dispense(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            discard_last_excess=LastDilutionWaste.WITH_TIP_EJECT,
        )
        steps = result.plate_results[0].series_results[0].steps
        assert len(steps) == 4
        assert steps[3].dispense is None
        assert steps[3].aspirate is not None


class TestTips:
    def test_diluent_and_transfer_use_separate_pools(self, monkeypatch):
        env = _patch_env(monkeypatch)
        client = _mock_client()
        execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        pickup_pools = [call.args[2] for call in env["pickup"].call_args_list]
        assert "DiluentTips" in pickup_pools
        assert "TransferTips" in pickup_pools

    def test_reuse_tips_true_single_transfer_pickup_multi_pass(self, monkeypatch):
        env = _patch_env(monkeypatch)
        client = _mock_client(rows=16)  # 16 rows -> 2 passes with 8 channels
        execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0, reuse_tips=True)
        transfer_pickups = [c for c in env["pickup"].call_args_list if c.args[2] == "TransferTips"]
        assert len(transfer_pickups) == 1  # carried across both passes

    def test_reuse_tips_false_fresh_transfer_per_pass(self, monkeypatch):
        env = _patch_env(monkeypatch)
        client = _mock_client(rows=16)
        execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0, reuse_tips=False)
        transfer_pickups = [c for c in env["pickup"].call_args_list if c.args[2] == "TransferTips"]
        assert len(transfer_pickups) == 2  # one per pass

    def test_with_tip_eject_forces_fresh_transfer_each_pass(self, monkeypatch):
        env = _patch_env(monkeypatch)
        client = _mock_client(rows=16)
        execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            reuse_tips=True,
            discard_last_excess=LastDilutionWaste.WITH_TIP_EJECT,
        )
        transfer_pickups = [c for c in env["pickup"].call_args_list if c.args[2] == "TransferTips"]
        assert len(transfer_pickups) == 2  # WITH_TIP_EJECT defeats reuse


class TestErrorProfiles:
    def test_profiles_entered(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        diluent_profile = MagicMock()
        transfer_profile = MagicMock()
        execute_serial_dilution_by_volume(
            client,
            **_BASE,
            diluent_volume=180.0,
            diluent_error_profile=diluent_profile,
            transfer_error_profile=transfer_profile,
        )
        entered = [call.args[0] for call in client.use_error_profile.call_args_list]
        assert diluent_profile in entered
        assert transfer_profile in entered

    def test_profiles_untouched_when_none(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        client.use_error_profile.assert_not_called()


class TestMultiPlate:
    def test_list_plates_aggregate(self, monkeypatch):
        _patch_env(monkeypatch, plate_ids=("PlateA", "PlateB"))
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client, **{**_BASE, "plate_id": ["PlateA", "PlateB"]}, diluent_volume=180.0
        )
        assert result.plate_ids == ("PlateA", "PlateB")
        assert result.num_series == 16  # 8 rows x 2 plates
        assert len(result.plate_results) == 2

    def test_global_ordering_diluent_before_transfer(self, monkeypatch):
        env = _patch_env(monkeypatch, plate_ids=("PlateA", "PlateB"))
        client = _mock_client()
        execute_serial_dilution_by_volume(client, **{**_BASE, "plate_id": ["PlateA", "PlateB"]}, diluent_volume=180.0)
        pools_in_order = [call.args[2] for call in env["pickup"].call_args_list]
        last_diluent = max(i for i, p in enumerate(pools_in_order) if p == "DiluentTips")
        first_transfer = min(i for i, p in enumerate(pools_in_order) if p == "TransferTips")
        assert last_diluent < first_transfer


class TestChannelsAndRows:
    def test_partial_channels(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0, channels=[1, 2, 3, 4])
        # 8 rows, 4 channels -> 2 passes; 8 series total.
        assert result.num_series == 8
        assert result.plate_results[0].num_passes == 2

    def test_exclude_rows_reduces_series(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0, exclude_rows=["A", "B"])
        assert result.num_series == 6


class TestResultModel:
    def test_series_reference_shared_step_responses(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        series = result.plate_results[0].series_results
        # Sibling series of the same pass share the same aspirate response object.
        assert series[0].steps[0].aspirate is series[1].steps[0].aspirate

    def test_diluent_sources_used_recorded(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **_BASE, diluent_volume=180.0)
        assert result.diluent_sources_used  # non-empty
        assert result.diluent_sources_used[0].startswith("Trough@")


class TestEdgeCases:
    def test_num_dilutions_one(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(client, **{**_BASE, "num_dilutions": 1}, diluent_volume=180.0)
        assert result.num_dilutions == 1
        assert len(result.plate_results[0].series_results[0].steps) == 1

    def test_non_positive_transfer_volume_raises(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        with pytest.raises(ValueError):
            execute_serial_dilution_by_volume(client, **{**_BASE, "transfer_volume": 0.0}, diluent_volume=180.0)

    def test_start_column_out_of_range_raises(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client(cols=4)
        with pytest.raises(ValueError):
            # start at col 3 with 3 dilutions needs cols 3,4,5,6 but only 4 exist.
            execute_serial_dilution_by_volume(client, **{**_BASE, "start_column": 3}, diluent_volume=180.0)

    def test_missing_transfer_tip_pool_raises(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        with pytest.raises(ValueError):
            execute_serial_dilution_by_volume(client, **{**_BASE, "transfer_tip_pool": ""}, diluent_volume=180.0)


class TestCountTransferTips:
    """The pre-run tip budget must be exact for variable-width passes (§5.6)."""

    @staticmethod
    def _work(passes_per_plate: list[list[int]], n_plates: int):
        spec = LabwareLayoutSpec(rows=8, cols=12)
        work = []
        for p in range(n_plates):
            grid = DilutionGrid(passes=passes_per_plate, column_sequence=[1, 2, 3])
            for pass_index in range(len(passes_per_plate)):
                work.append((f"Plate{p}", spec, grid, pass_index))
        return work

    def test_uniform_reuse_single_pickup(self):
        # 8 rows -> one full-width pass, tips reused: 8 tips only.
        work = self._work([[0, 1, 2, 3, 4, 5, 6, 7]], n_plates=1)
        got = _count_transfer_tips(
            work, list(range(1, 9)), reuse_tips=True, discard_last_excess=LastDilutionWaste.NONE
        )
        assert got == 8

    def test_variable_width_reuse_repicks(self):
        # 9 rows on 8 channels -> passes [8, 1]; reuse re-picks for the narrow pass: 8 + 1.
        work = self._work([[0, 1, 2, 3, 4, 5, 6, 7], [8]], n_plates=1)
        got = _count_transfer_tips(work, list(range(1, 9)), reuse_tips=True, discard_last_excess=LastDilutionWaste.NONE)
        assert got == 9

    def test_variable_width_reuse_multi_plate(self):
        # Two plates of [8, 1]: 8+1 per plate, with a re-pick between plates: 8+1+8+1.
        work = self._work([[0, 1, 2, 3, 4, 5, 6, 7], [8]], n_plates=2)
        got = _count_transfer_tips(work, list(range(1, 9)), reuse_tips=True, discard_last_excess=LastDilutionWaste.NONE)
        assert got == 18

    def test_no_reuse_fresh_set_per_pass(self):
        work = self._work([[0, 1, 2, 3, 4, 5, 6, 7], [8]], n_plates=1)
        got = _count_transfer_tips(
            work, list(range(1, 9)), reuse_tips=False, discard_last_excess=LastDilutionWaste.NONE
        )
        assert got == 9

    def test_with_tip_eject_forces_fresh_set(self):
        # WITH_TIP_EJECT drops tips each unit even when reuse_tips is True.
        work = self._work([[0, 1, 2, 3, 4, 5, 6, 7], [8]], n_plates=1)
        got = _count_transfer_tips(
            work, list(range(1, 9)), reuse_tips=True, discard_last_excess=LastDilutionWaste.WITH_TIP_EJECT
        )
        assert got == 9


class TestSerialDilutionPositionInput:
    """plate_id may be a pre-resolved Position/list[Position], not just a
    selector string."""

    def test_plate_id_as_position_list(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client,
            **{**_BASE, "plate_id": [Position(labware="Plate", well="A1")]},
            diluent_volume=180.0,
        )
        assert isinstance(result, SerialDilutionResult)
        assert result.num_series == 8

    def test_plate_id_as_single_position(self, monkeypatch):
        _patch_env(monkeypatch)
        client = _mock_client()
        result = execute_serial_dilution_by_volume(
            client,
            **{**_BASE, "plate_id": Position(labware="Plate", well="A1")},
            diluent_volume=180.0,
        )
        assert isinstance(result, SerialDilutionResult)
        assert result.num_series == 8
