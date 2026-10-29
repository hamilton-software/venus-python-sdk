from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands.replicate_samples import execute_replicate_samples
from hamilton_venus.exceptions import OperatorCancelledError, VenusCommandFailedError
from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import ReplicateSamplesResult
from hamilton_venus.models.enums import PreAliquotDisposal, WellOrder
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
from hamilton_venus.models.position import Position


def _ok() -> CommandResponse:
    return CommandResponse(return_status="Success", return_code=0, return_parameters={})


def _asp() -> ChannelAspirationResponse:
    return ChannelAspirationResponse(return_status="Success", return_code=0, return_parameters={"channels": []})


def _disp() -> ChannelDispenseResponse:
    return ChannelDispenseResponse(return_status="Success", return_code=0, return_parameters={"channels": []})


def _positions(plate: str, count: int) -> list[Position]:
    wells = []
    for i in range(count):
        row = chr(ord("A") + i % 8)
        col = i // 8 + 1
        wells.append(Position(labware=plate, well=f"{row}{col}"))
    return wells


def _mock_client(
    available_tips: int = 999,
    tip_capacity: float = 1000.0,
    raise_on_labware: set[str] | None = None,
    waste_positions: list[Position] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.on_tip_reload_prompt = None

    def _labware_side_effect(plate_name):
        if raise_on_labware and plate_name in raise_on_labware:
            fail_resp = MagicMock(
                action_name="labware.getLabwareParamsFromID",
                return_status="Failure",
                return_code=1,
                return_parameters={},
            )
            raise VenusCommandFailedError(fail_resp)
        resp = MagicMock()
        resp.return_parameters.definition = {"rack_layout": {"rows": 8, "columns": 12}}
        return resp

    client.labware_get_params_from_id.side_effect = _labware_side_effect

    tip_resp = MagicMock()
    tip_resp.return_parameters.total_available_tips = available_tips
    client.tip_pool_get_available_tips.return_value = tip_resp

    counter_resp = MagicMock()
    counter_resp.return_parameters.tip_type_id = "0"
    counter_resp.return_parameters.tip_type = 0
    client.tip_pool_get_tip_counter.return_value = counter_resp

    types_resp = MagicMock()
    types_resp.return_parameters.tip_types = {"0": {"Max Liquid Volume": tip_capacity}}
    client.get_tip_types.return_value = types_resp

    client.tip_pickup.return_value = _ok()
    client.tip_eject.return_value = _ok()
    client.aspirate.return_value = _asp()
    client.dispense.return_value = _disp()

    return client


_BASE = dict(
    source_plate="Source",
    dest_plate="Dest",
    replicates_per_source=3,
    volume_per_replicate=20.0,
    liquid_class="Water",
    tip_pool="Tips300",
)


# --- Task 9: single-dispense mode ----------------------------------------------------


class TestExecuteReplicateSamplesBasicSingle:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_4_sources_3_replicates(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=False)
        assert isinstance(result, ReplicateSamplesResult)
        assert result.multi_dispense is False
        assert result.sources_processed == 4
        assert result.replicates_filled == 12
        assert result.iterations == 12
        assert result.total_wells_processed == 12

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_fresh_tip_per_transfer(self, mock_resolve):
        """single-dispense mode: 12 transfers → 12 pickups and 12 ejects (chunks of 8)."""
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        execute_replicate_samples(client, **_BASE, multi_dispense=False)
        # 12 transfers / 8 channels = 2 chunks → 2 pickups + 2 ejects
        assert client.tip_pickup.call_count == 2
        assert client.tip_eject.call_count == 2
        # 2 aspirate chunks, 2 dispense chunks
        assert client.aspirate.call_count == 2
        assert client.dispense.call_count == 2

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_one_iteration_per_transfer(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 2), _positions("Dest", 6)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=False)
        assert len(result.iteration_results) == 6
        # Source A1 -> A1,B1,C1; source B1 -> D1,E1,F1
        srcs = [it.source_well for it in result.iteration_results]
        dsts = [it.dest_wells[0] for it in result.iteration_results]
        assert srcs == ["A1", "A1", "A1", "B1", "B1", "B1"]
        assert dsts == ["A1", "B1", "C1", "D1", "E1", "F1"]

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_aspirate_and_dispense_paired(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        execute_replicate_samples(client, **_BASE, multi_dispense=False)
        # 3 transfers in 1 chunk → 1 asp, 1 disp
        assert client.aspirate.call_count == 1
        assert client.dispense.call_count == 1
        # Aspirate positions are 3 copies of source A1
        asp = client.aspirate.call_args
        assert all(p.well == "A1" for p in asp.kwargs["positions"])
        disp = client.dispense.call_args
        assert [p.well for p in disp.kwargs["positions"]] == ["A1", "B1", "C1"]


class TestReplicateSamplesSetupValidation:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_empty_tip_pool_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="tip_pool"):
            execute_replicate_samples(client, **{**_BASE, "tip_pool": ""})

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_zero_replicates_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="replicates_per_source"):
            execute_replicate_samples(client, **{**_BASE, "replicates_per_source": 0})

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_negative_replicates_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="replicates_per_source"):
            execute_replicate_samples(client, **{**_BASE, "replicates_per_source": -1})

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_zero_volume_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="volume_per_replicate"):
            execute_replicate_samples(client, **{**_BASE, "volume_per_replicate": 0.0})

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_negative_volume_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="volume_per_replicate"):
            execute_replicate_samples(client, **{**_BASE, "volume_per_replicate": -5.0})

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_negative_pre_aliquot_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="pre_aliquot_volume"):
            execute_replicate_samples(client, **_BASE, pre_aliquot_volume=-1.0)

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_negative_post_aliquot_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="post_aliquot_volume"):
            execute_replicate_samples(client, **_BASE, post_aliquot_volume=-1.0)

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_dest_too_small_raises(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 3)]
        with pytest.raises(ValueError, match=r"[Dd]estination"):
            execute_replicate_samples(client, **_BASE)

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_empty_channels_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="channels"):
            execute_replicate_samples(client, **_BASE, channels=[])

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_empty_source_returns_zero(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [[], _positions("Dest", 4)]
        result = execute_replicate_samples(client, **_BASE)
        assert result.sources_processed == 0
        assert result.replicates_filled == 0
        assert result.iteration_results == ()

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_single_volume_exceeds_tip_capacity_raises(self, mock_resolve):
        client = _mock_client(tip_capacity=100.0)
        with pytest.raises(ValueError, match="tip capacity"):
            execute_replicate_samples(
                client,
                **{**_BASE, "volume_per_replicate": 150.0},
                multi_dispense=False,
            )

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_multi_per_rep_total_exceeds_capacity_raises(self, mock_resolve):
        client = _mock_client(tip_capacity=100.0)
        with pytest.raises(ValueError, match="tip capacity"):
            execute_replicate_samples(
                client,
                **{**_BASE, "volume_per_replicate": 80.0},
                pre_aliquot_volume=30.0,
                multi_dispense=True,
            )


class TestReplicateSamplesLabwareValidation:
    def test_missing_source_raises(self):
        client = _mock_client(raise_on_labware={"Source"})
        with pytest.raises(ValueError, match="Source"):
            execute_replicate_samples(client, **_BASE)

    def test_missing_dest_raises(self):
        client = _mock_client(raise_on_labware={"Dest"})
        with pytest.raises(ValueError, match="Dest"):
            execute_replicate_samples(client, **_BASE)

    def test_both_missing_combined(self):
        client = _mock_client(raise_on_labware={"Source", "Dest"})
        with pytest.raises(ValueError) as exc:
            execute_replicate_samples(client, **_BASE)
        msg = str(exc.value)
        assert "Source" in msg and "Dest" in msg


class TestReplicateSamplesWellOrder:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_source_order_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 2), _positions("Dest", 6)]
        execute_replicate_samples(client, **_BASE, source_order=WellOrder.ROW_ASC, multi_dispense=False)
        assert mock_resolve.call_args_list[0].kwargs.get("well_order") == WellOrder.ROW_ASC

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_dest_order_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 2), _positions("Dest", 6)]
        execute_replicate_samples(client, **_BASE, dest_order=WellOrder.COL_DESC, multi_dispense=False)
        assert mock_resolve.call_args_list[1].kwargs.get("well_order") == WellOrder.COL_DESC


class TestReplicateSamplesChannels:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_non_contiguous_channels(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        execute_replicate_samples(client, **_BASE, channels=[1, 3, 5, 7], multi_dispense=False)
        asp_chans = client.aspirate.call_args_list[0].kwargs["channels"]
        assert asp_chans == [1, 3, 5, 7]

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_single_channel(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 2), _positions("Dest", 6)]
        result = execute_replicate_samples(client, **_BASE, channels=[2], multi_dispense=False)
        # 6 transfers / 1 channel = 6 chunks
        assert client.tip_pickup.call_count == 6
        assert result.replicates_filled == 6


class TestReplicateSamplesErrorProfile:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_profile_scope_entered(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        profile = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=None)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        client.use_error_profile.return_value = ctx_mgr
        execute_replicate_samples(client, **_BASE, multi_dispense=False, error_profile=profile)
        client.use_error_profile.assert_called_once_with(profile)
        ctx_mgr.__enter__.assert_called_once()
        ctx_mgr.__exit__.assert_called_once()


class TestReplicateSamplesSettings:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_aspirate_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        asp = AspirateSettings(submerge_depth=4.0)
        execute_replicate_samples(client, **_BASE, aspirate_settings=asp, multi_dispense=False)
        assert client.aspirate.call_args.kwargs.get("settings") is not None

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_dispense_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        disp = DispenseSettings(mix_cycles=0)
        execute_replicate_samples(client, **_BASE, dispense_settings=disp, multi_dispense=False)
        assert client.dispense.call_args.kwargs.get("settings") is not None


# --- Task 10: multi-dispense mode (single aspiration per source) ---------------------


class TestExecuteReplicateSamplesBasicMulti:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_4_sources_3_replicates(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=True)
        assert result.multi_dispense is True
        assert result.sources_processed == 4
        assert result.replicates_filled == 12
        # multi-dispense → one iteration per source
        assert result.iterations == 4
        assert len(result.iteration_results) == 4

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_one_tip_pickup_per_source_chunk(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        execute_replicate_samples(client, **_BASE, multi_dispense=True)
        # 4 sources / 8 channels = 1 chunk → 1 pickup, 1 eject
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_one_aspirate_three_dispenses(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        execute_replicate_samples(client, **_BASE, multi_dispense=True)
        # one batch fits all 3 reps → 1 aspirate, 3 replicate dispenses
        assert client.aspirate.call_count == 1
        assert client.dispense.call_count == 3
        asp_vol = client.aspirate.call_args.kwargs["volumes"]
        assert asp_vol == 60.0  # 3 reps * 20 µL


class TestReplicateSamplesMultiSingleAspiration:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_fits_in_one_aspiration(self, mock_resolve):
        client = _mock_client(tip_capacity=1000.0)
        mock_resolve.side_effect = [_positions("Source", 2), _positions("Dest", 6)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=True)
        # Per source: 1 aspirate
        for it in result.iteration_results:
            assert len(it.aspirates) == 1
            assert len(it.replicate_dispenses) == 3


class TestReplicateSamplesMultiChannelParallel:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_8_sources_single_chunk(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 24)]
        execute_replicate_samples(client, **_BASE, multi_dispense=True)
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_9_sources_two_chunks(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 9), _positions("Dest", 27)]
        execute_replicate_samples(client, **_BASE, multi_dispense=True)
        assert client.tip_pickup.call_count == 2
        assert client.tip_eject.call_count == 2


# --- Task 11: auto-split + pre/post aliquot ---------------------------------


class TestReplicateSamplesMultiAutoSplit:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_auto_split_two_batches(self, mock_resolve):
        # tip=100, 1 rep=40 → reps_per_batch=2; 3 reps → 2 batches
        client = _mock_client(tip_capacity=100.0)
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        result = execute_replicate_samples(
            client,
            **{**_BASE, "volume_per_replicate": 40.0},
            multi_dispense=True,
        )
        assert client.aspirate.call_count == 2
        # Total dispense calls = batch1(2 reps) + batch2(1 rep) = 3
        assert client.dispense.call_count == 3
        # Single iteration for the single source, with 2 aspirates
        assert len(result.iteration_results) == 1
        assert len(result.iteration_results[0].aspirates) == 2
        assert len(result.iteration_results[0].replicate_dispenses) == 3

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_auto_split_batch_size_computed_from_net_capacity(self, mock_resolve):
        # tip=100, pre=10, post=10 → net=80; rep=30 → reps_per_batch=2
        client = _mock_client(tip_capacity=100.0)
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        execute_replicate_samples(
            client,
            **{**_BASE, "volume_per_replicate": 30.0},
            pre_aliquot_volume=10.0,
            post_aliquot_volume=10.0,
            multi_dispense=True,
        )
        # 3 reps / 2 per batch = 2 batches → 2 aspirates
        assert client.aspirate.call_count == 2


class TestReplicateSamplesPreAliquotSource:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_pre_aliquot_dispenses_back_to_source(self, mock_resolve):
        client = _mock_client()
        srcs = _positions("Source", 1)
        mock_resolve.side_effect = [srcs, _positions("Dest", 3)]
        execute_replicate_samples(
            client,
            **_BASE,
            pre_aliquot_volume=5.0,
            pre_aliquot_disposal=PreAliquotDisposal.SOURCE,
            multi_dispense=True,
        )
        # Aspirate volume = 3*20 + 5 = 65
        assert client.aspirate.call_args.kwargs["volumes"] == 65.0
        # Pre-aliquot dispense should target the source position
        # Find dispense with volume=5.0
        pre_calls = [c for c in client.dispense.call_args_list if c.kwargs["volumes"] == 5.0]
        assert len(pre_calls) == 1
        assert pre_calls[0].kwargs["positions"][0].well == srcs[0].well


class TestReplicateSamplesPreAliquotWaste:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_waste_position")
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_pre_aliquot_dispenses_to_waste(self, mock_resolve, mock_waste):
        client = _mock_client()
        waste = Position(labware="liquid_waste", well="A1")
        # 1st call source, 2nd dest
        mock_resolve.side_effect = [
            _positions("Source", 1),
            _positions("Dest", 3),
        ]
        mock_waste.return_value = waste
        execute_replicate_samples(
            client,
            **_BASE,
            pre_aliquot_volume=5.0,
            pre_aliquot_disposal=PreAliquotDisposal.WASTE,
            multi_dispense=True,
        )
        pre_calls = [c for c in client.dispense.call_args_list if c.kwargs["volumes"] == 5.0]
        assert len(pre_calls) == 1
        assert pre_calls[0].kwargs["positions"][0].labware == "liquid_waste"


class TestReplicateSamplesPostAliquot:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_post_aliquot_overrides_fixed_height(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        execute_replicate_samples(
            client,
            **_BASE,
            post_aliquot_volume=7.0,
            post_aliquot_height=12.5,
            multi_dispense=True,
        )
        post_calls = [c for c in client.dispense.call_args_list if c.kwargs["volumes"] == 7.0]
        assert len(post_calls) == 1
        settings = post_calls[0].kwargs["settings"]
        assert settings is not None
        # fixed_height applied through model_copy
        fh = settings.fixed_height
        fh_val = fh if isinstance(fh, (int, float)) else fh[0]
        assert fh_val == 12.5


# --- Tip budget -------------------------------------------------------------


class TestReplicateSamplesTipBudget:
    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_multi_uses_num_sources_tips(self, mock_resolve):
        client = _mock_client(available_tips=4)
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=True)
        assert result.sources_processed == 4

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_single_uses_num_sources_times_reps(self, mock_resolve):
        client = _mock_client(available_tips=12)
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=False)
        assert result.replicates_filled == 12

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_insufficient_tips_raises_without_callback(self, mock_resolve):
        client = _mock_client(available_tips=2)
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        with pytest.raises(ValueError, match=r"[Tt]ip"):
            execute_replicate_samples(client, **_BASE, multi_dispense=True)

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_reload_callback_true_proceeds(self, mock_resolve):
        client = _mock_client(available_tips=0)
        client.on_tip_reload_prompt = lambda ctx: True
        client.tip_pool_reset_tip_counter.return_value = _ok()
        first = MagicMock()
        first.return_parameters.total_available_tips = 0
        reload = MagicMock()
        reload.return_parameters.total_available_tips = 999
        client.tip_pool_get_available_tips.side_effect = [first, reload]
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        result = execute_replicate_samples(client, **_BASE, multi_dispense=True)
        assert result.sources_processed == 1

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_reload_callback_false_cancels(self, mock_resolve):
        client = _mock_client(available_tips=0)
        client.on_tip_reload_prompt = lambda ctx: False
        mock_resolve.side_effect = [_positions("Source", 1), _positions("Dest", 3)]
        with pytest.raises(OperatorCancelledError):
            execute_replicate_samples(client, **_BASE, multi_dispense=True)


# --- Task 12: Mixin wire-up -------------------------------------------------


class TestReplicateSamplesMixin:
    def test_star_client_has_method(self):
        from hamilton_venus.star_client import StarClient

        assert hasattr(StarClient, "replicate_samples")
        assert callable(StarClient.replicate_samples)

    def test_result_importable_from_top_level(self):
        from hamilton_venus import ReplicateSamplesIterationResult, ReplicateSamplesResult

        assert ReplicateSamplesResult is not None
        assert ReplicateSamplesIterationResult is not None


# ===========================================================================
# Multi-plate (list[str]) selectors
# ===========================================================================


class TestReplicateSamplesMultiPlate:
    """source_plate / dest_plate accept str | list[str]."""

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_multi_source_two_plates_multi_mode(self, mock_resolve):
        """4 sources spanning 2 plates, 2 replicates each → 8 dest wells total."""
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("SrcA", 2) + _positions("SrcB", 2),
            _positions("Dest", 8),
        ]
        result = execute_replicate_samples(
            client,
            source_plate=["SrcA@col:1", "SrcB@col:1"],
            dest_plate="Dest",
            replicates_per_source=2,
            volume_per_replicate=20.0,
            liquid_class="Water",
            tip_pool="Tips300",
            multi_dispense=True,
        )
        assert result.sources_processed == 4
        assert result.replicates_filled == 8
        assert set(result.source_plate_ids) == {"SrcA", "SrcB"}

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_multi_dest_two_plates_multi_mode(self, mock_resolve):
        """2 sources, 4 replicates each; destinations span two plates."""
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("Src", 2),
            _positions("DestA", 4) + _positions("DestB", 4),
        ]
        result = execute_replicate_samples(
            client,
            source_plate="Src",
            dest_plate=["DestA@col:1", "DestB@col:1"],
            replicates_per_source=4,
            volume_per_replicate=20.0,
            liquid_class="Water",
            tip_pool="Tips300",
            multi_dispense=True,
        )
        assert result.replicates_filled == 8
        assert set(result.dest_plate_ids) == {"DestA", "DestB"}

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_single_mode_two_source_plates(self, mock_resolve):
        """single-dispense mode: sources from 2 plates, chunk boundaries respected."""
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("SrcA", 2) + _positions("SrcB", 2),
            _positions("Dest", 8),
        ]
        result = execute_replicate_samples(
            client,
            source_plate=["SrcA@col:1", "SrcB@col:1"],
            dest_plate="Dest",
            replicates_per_source=2,
            volume_per_replicate=20.0,
            liquid_class="Water",
            tip_pool="Tips300",
            multi_dispense=False,
        )
        assert result.replicates_filled == 8

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_single_element_list_equivalent_to_string(self, mock_resolve):
        client_a = _mock_client()
        client_b = _mock_client()
        mock_resolve.side_effect = [
            _positions("Source", 2),
            _positions("Dest", 6),
            _positions("Source", 2),
            _positions("Dest", 6),
        ]
        r_str = execute_replicate_samples(client_a, **_BASE)
        r_list = execute_replicate_samples(
            client_b,
            source_plate=["Source"],
            dest_plate=["Dest"],
            replicates_per_source=3,
            volume_per_replicate=20.0,
            liquid_class="Water",
            tip_pool="Tips300",
        )
        assert r_str.sources_processed == r_list.sources_processed
        assert r_str.replicates_filled == r_list.replicates_filled

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_source_and_dest_plate_ids_recorded_for_multi_plate(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("PA", 2) + _positions("PB", 2),
            _positions("DA", 4) + _positions("DB", 4),
        ]
        result = execute_replicate_samples(
            client,
            source_plate=["PA@col:1", "PB@col:1"],
            dest_plate=["DA@col:1", "DB@col:1"],
            replicates_per_source=2,
            volume_per_replicate=20.0,
            liquid_class="Water",
            tip_pool="Tips300",
        )
        assert set(result.source_plate_ids) == {"PA", "PB"}
        assert set(result.dest_plate_ids) == {"DA", "DB"}

    def test_empty_source_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="source_plate list"):
            execute_replicate_samples(
                client,
                source_plate=[],
                dest_plate="Dest",
                replicates_per_source=2,
                volume_per_replicate=20.0,
                liquid_class="W",
                tip_pool="T",
            )

    def test_empty_dest_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="dest_plate list"):
            execute_replicate_samples(
                client,
                source_plate="Src",
                dest_plate=[],
                replicates_per_source=2,
                volume_per_replicate=20.0,
                liquid_class="W",
                tip_pool="T",
            )


class TestReplicateSamplesPositionInput:
    """source_plate/dest_plate may be pre-resolved Position objects, not just
    selector strings."""

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_source_plate_as_position_list(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(
            client,
            **{**_BASE, "source_plate": [Position(labware="Source", well="A1")]},
            multi_dispense=False,
        )
        assert result.sources_processed == 4
        assert result.source_plate_ids == ("Source",)

    @patch("hamilton_venus.compound_commands.replicate_samples.resolve_multi_selector")
    def test_dest_plate_as_single_position(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 12)]
        result = execute_replicate_samples(
            client,
            **{**_BASE, "dest_plate": Position(labware="Dest", well="A1")},
            multi_dispense=False,
        )
        assert result.dest_plate_ids == ("Dest",)
