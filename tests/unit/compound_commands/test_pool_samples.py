from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands.pool_samples import execute_pool_samples
from hamilton_venus.exceptions import OperatorCancelledError, VenusCommandFailedError
from hamilton_venus.models.command_types import ChannelAspirationResponse, ChannelDispenseResponse
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import PoolSamplesResult
from hamilton_venus.models.enums import WellOrder
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
    pool_size=4,
    volume_per_source=50.0,
    liquid_class="Water",
    tip_pool="Tips300",
)


class TestExecutePoolSamplesBasic:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_four_pools_16_sources(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("Source", 16),
            _positions("Dest", 16),
        ]
        result = execute_pool_samples(client, **_BASE, mix_after_pool=False)

        assert isinstance(result, PoolSamplesResult)
        assert result.pools_completed == 4
        assert result.wells_pooled == 16
        assert result.iterations == 4
        assert result.total_wells_processed == 16
        assert len(result.iteration_results) == 4

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_per_pool_has_pickup_aspirate_dispense_eject(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 8)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=False,
        )
        for it in result.iteration_results:
            assert len(it.tip_pickups) >= 1
            assert len(it.aspirates) >= 1
            assert len(it.dispenses) >= 1
            assert len(it.tip_ejects) >= 1
            assert it.mix_after is None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_and_dest_plate_ids_recorded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 4)]
        result = execute_pool_samples(client, **_BASE, mix_after_pool=False)
        assert result.source_plate_ids == ("Source",)
        assert result.dest_plate_ids == ("Dest",)
        for it in result.iteration_results:
            assert it.source_plate_ids == ("Source",)
            assert it.dest_plate_id == "Dest"

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dest_well_assigned_sequentially(self, mock_resolve):
        client = _mock_client()
        src = _positions("Source", 8)
        dst = _positions("Dest", 2)
        mock_resolve.side_effect = [src, dst]
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        dest_wells = [it.dest_well for it in result.iteration_results]
        assert dest_wells == ["A1", "B1"]

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_wells_per_iteration(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 4)]
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        assert len(result.iteration_results) == 1
        assert result.iteration_results[0].source_wells == ("A1", "B1", "C1", "D1")

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_aspirate_called_with_correct_positions(self, mock_resolve):
        client = _mock_client()
        src = _positions("Source", 4)
        mock_resolve.side_effect = [src, _positions("Dest", 1)]
        execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        assert client.aspirate.call_count == 1
        asp_call = client.aspirate.call_args
        assert asp_call.kwargs["positions"] == src

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dispense_positions_are_all_dest(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 8)]
        execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        for disp_call in client.dispense.call_args_list:
            positions = disp_call.kwargs["positions"]
            assert len(set(p.well for p in positions)) == 1


class TestPoolSamplesSetupValidation:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_empty_tip_pool_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="tip_pool"):
            execute_pool_samples(client, **{**_BASE, "tip_pool": ""})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_pool_size_zero_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="pool_size"):
            execute_pool_samples(client, **{**_BASE, "pool_size": 0})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_negative_pool_size_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="pool_size"):
            execute_pool_samples(client, **{**_BASE, "pool_size": -1})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_zero_volume_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="volume_per_source"):
            execute_pool_samples(client, **{**_BASE, "volume_per_source": 0.0})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_negative_volume_raises(self, mock_resolve):
        client = _mock_client()
        with pytest.raises(ValueError, match="volume_per_source"):
            execute_pool_samples(client, **{**_BASE, "volume_per_source": -10.0})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_volume_exceeds_tip_capacity_raises(self, mock_resolve):
        client = _mock_client(tip_capacity=100.0)
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        with pytest.raises(ValueError, match="tip capacity"):
            execute_pool_samples(client, **{**_BASE, "volume_per_source": 150.0})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dest_too_small_raises(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 1)]
        with pytest.raises(ValueError, match=r"[Dd]estination"):
            execute_pool_samples(client, **{**_BASE, "pool_size": 4})

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_empty_channels_raises(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        with pytest.raises(ValueError, match="channels"):
            execute_pool_samples(client, **_BASE, channels=[])

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_empty_source_returns_zero_iteration_result(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [[], _positions("Dest", 4)]
        result = execute_pool_samples(client, **_BASE)
        assert result.pools_completed == 0
        assert result.wells_pooled == 0
        assert result.iteration_results == ()


class TestPoolSamplesLabwareValidation:
    def test_missing_source_plate_raises(self):
        client = _mock_client(raise_on_labware={"Source"})
        with pytest.raises(ValueError, match="Source"):
            execute_pool_samples(client, **_BASE)

    def test_missing_dest_plate_raises(self):
        client = _mock_client(raise_on_labware={"Dest"})
        with pytest.raises(ValueError, match="Dest"):
            execute_pool_samples(client, **_BASE)

    def test_both_missing_raises_combined_error(self):
        client = _mock_client(raise_on_labware={"Source", "Dest"})
        with pytest.raises(ValueError) as exc:
            execute_pool_samples(client, **_BASE)
        msg = str(exc.value)
        assert "Source" in msg
        assert "Dest" in msg


class TestPoolSamplesIncompletePool:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_incomplete_final_pool(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 18), _positions("Dest", 5)]
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        assert result.pools_completed == 5
        assert result.wells_pooled == 18
        sizes = [it.pool_size for it in result.iteration_results]
        assert sizes == [4, 4, 4, 4, 2]

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_single_well_pool_size(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 4)]
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 1}, mix_after_pool=False)
        assert result.pools_completed == 4
        for it in result.iteration_results:
            assert it.pool_size == 1


class TestPoolSamplesPoolSizeExceedsChannels:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_pool_size_16_with_8_channels(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 16), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 16},
            mix_after_pool=False,
            channels=[1, 2, 3, 4, 5, 6, 7, 8],
        )
        assert result.pools_completed == 1
        assert len(result.iteration_results[0].aspirates) == 2
        assert len(result.iteration_results[0].dispenses) == 2

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_partial_last_row(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 10), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 10},
            mix_after_pool=False,
        )
        assert result.pools_completed == 1
        assert result.wells_pooled == 10


class TestPoolSamplesWellOrder:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_order_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            source_order=WellOrder.ROW_ASC,
            mix_after_pool=False,
        )
        src_call = mock_resolve.call_args_list[0]
        assert src_call.kwargs.get("well_order") == WellOrder.ROW_ASC

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dest_order_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            dest_order=WellOrder.COL_DESC,
            mix_after_pool=False,
        )
        dst_call = mock_resolve.call_args_list[1]
        assert dst_call.kwargs.get("well_order") == WellOrder.COL_DESC


class TestPoolSamplesTipBudget:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_insufficient_tips_raises_without_callback(self, mock_resolve):
        client = _mock_client(available_tips=2)
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        with pytest.raises(ValueError, match=r"[Tt]ip"):
            execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_tip_reload_callback_true_proceeds(self, mock_resolve):
        client = _mock_client(available_tips=0)
        client.on_tip_reload_prompt = lambda ctx: True
        client.tip_pool_reset_tip_counter.return_value = _ok()
        reload_avail = MagicMock()
        reload_avail.return_parameters.total_available_tips = 999
        first_avail = MagicMock()
        first_avail.return_parameters.total_available_tips = 0
        client.tip_pool_get_available_tips.side_effect = [first_avail, reload_avail]
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)
        assert result.pools_completed == 1

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_tip_reload_callback_false_raises_cancelled(self, mock_resolve):
        client = _mock_client(available_tips=0)
        client.on_tip_reload_prompt = lambda ctx: False
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        with pytest.raises(OperatorCancelledError):
            execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False)


class TestPoolSamplesReuseTipsWithinPool:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_single_pickup_per_pool(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 8)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=False,
            reuse_tips_within_pool=True,
        )
        assert result.pools_completed == 2
        for it in result.iteration_results:
            assert len(it.tip_pickups) == 1
            assert len(it.tip_ejects) == 1

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_tips_picked_up_once_for_all_rows(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 16), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 16},
            mix_after_pool=False,
            reuse_tips_within_pool=True,
        )
        assert result.pools_completed == 1
        assert len(result.iteration_results[0].tip_pickups) == 1
        assert len(result.iteration_results[0].aspirates) == 2

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_result_flag_set(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=False,
            reuse_tips_within_pool=True,
        )
        assert result.reuse_tips_within_pool is True


class TestPoolSamplesMixAfterPool:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_true_with_mix_cycles_emits_trailing_mix(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=3, mix_volume=40.0)
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            dispense_settings=disp,
        )
        assert result.iteration_results[0].mix_after is not None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_true_zero_mix_cycles_skips_trailing_mix(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=0)
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            dispense_settings=disp,
        )
        assert result.iteration_results[0].mix_after is None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_true_no_dispense_settings_skips_trailing_mix(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            dispense_settings=None,
        )
        assert result.iteration_results[0].mix_after is None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_false_no_trailing_mix(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=3, mix_volume=40.0)
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=False,
            dispense_settings=disp,
        )
        assert result.iteration_results[0].mix_after is None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_trailing_mix_called_with_zero_volume(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=2, mix_volume=30.0)
        execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            dispense_settings=disp,
        )
        last_disp = client.dispense.call_args_list[-1]
        assert last_disp.kwargs["volumes"] == 0.0

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_result_flag_set(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=1, mix_volume=25.0)
        result = execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=True, dispense_settings=disp)
        assert result.mix_after_pool is True

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_reuse_tips_no_extra_pickup(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=2, mix_volume=30.0)
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            reuse_tips_within_pool=True,
            dispense_settings=disp,
        )
        assert len(result.iteration_results[0].tip_pickups) == 1
        assert len(result.iteration_results[0].tip_ejects) == 1
        assert result.iteration_results[0].mix_after is not None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_mix_after_pool_no_reuse_extra_pickup_for_mix(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=2, mix_volume=30.0)
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            mix_after_pool=True,
            reuse_tips_within_pool=False,
            dispense_settings=disp,
        )
        it = result.iteration_results[0]
        assert len(it.tip_pickups) == 2
        assert len(it.tip_ejects) == 2
        assert it.mix_after is not None


class TestPoolSamplesSettings:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_aspirate_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        asp = AspirateSettings(submerge_depth=5.0)
        execute_pool_samples(client, **{**_BASE, "pool_size": 4}, aspirate_settings=asp, mix_after_pool=False)
        for c in client.aspirate.call_args_list:
            assert c.kwargs.get("settings") is not None

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dispense_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        disp = DispenseSettings(mix_cycles=0)
        execute_pool_samples(client, **{**_BASE, "pool_size": 4}, dispense_settings=disp, mix_after_pool=False)
        for c in client.dispense.call_args_list:
            assert c.kwargs.get("settings") is not None


class TestPoolSamplesChannels:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_non_contiguous_channels(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            channels=[1, 3, 5, 7],
            mix_after_pool=False,
        )
        assert result.pools_completed == 1
        asp_call = client.aspirate.call_args
        assert asp_call.kwargs["channels"] == [1, 3, 5, 7]

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_single_channel(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "pool_size": 4},
            channels=[2],
            mix_after_pool=False,
        )
        assert result.wells_pooled == 4
        assert result.pools_completed == 1
        assert len(result.iteration_results[0].aspirates) == 4


class TestPoolSamplesErrorProfile:
    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_error_profile_scope_entered(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]

        profile = MagicMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=None)
        ctx_mgr.__exit__ = MagicMock(return_value=False)
        client.use_error_profile.return_value = ctx_mgr

        execute_pool_samples(client, **{**_BASE, "pool_size": 4}, mix_after_pool=False, error_profile=profile)
        client.use_error_profile.assert_called_once_with(profile)
        ctx_mgr.__enter__.assert_called_once()
        ctx_mgr.__exit__.assert_called_once()


class TestPoolSamplesMixin:
    def test_star_client_has_pool_samples_method(self):
        from hamilton_venus.star_client import StarClient

        assert hasattr(StarClient, "pool_samples")
        assert callable(StarClient.pool_samples)

    def test_pool_samples_result_importable_from_top_level(self):
        from hamilton_venus import PoolSamplesIterationResult, PoolSamplesResult

        assert PoolSamplesResult is not None
        assert PoolSamplesIterationResult is not None


# ===========================================================================
# Multi-plate (list[str]) selectors
# ===========================================================================


class TestPoolSamplesMultiPlate:
    """source_plate / dest_plate accept str | list[str]."""

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_list_two_plates_pools_across_plates(self, mock_resolve):
        """16 sources across two plates, pool_size=4 → 4 pools."""
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("SrcA", 8) + _positions("SrcB", 8),
            _positions("Dest", 4),
        ]
        result = execute_pool_samples(
            client,
            source_plate=["SrcA@col:1", "SrcB@col:1"],
            dest_plate="Dest",
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
        )
        assert result.pools_completed == 4
        assert result.wells_pooled == 16
        assert set(result.source_plate_ids) == {"SrcA", "SrcB"}
        assert result.dest_plate_ids == ("Dest",)

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dest_list_two_plates_pools_split_across_dests(self, mock_resolve):
        """8 sources, pool_size=4 → 2 pools; each dest on a separate plate."""
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("Src", 8),
            _positions("DestA", 1) + _positions("DestB", 1),
        ]
        result = execute_pool_samples(
            client,
            source_plate="Src",
            dest_plate=["DestA@A1", "DestB@A1"],
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
        )
        assert result.pools_completed == 2
        assert set(result.dest_plate_ids) == {"DestA", "DestB"}

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_single_element_list_equivalent_to_string(self, mock_resolve):
        client_a = _mock_client()
        client_b = _mock_client()
        positions_a = [_positions("Src", 4), _positions("Dest", 1)]
        positions_b = [_positions("Src", 4), _positions("Dest", 1)]
        mock_resolve.side_effect = positions_a + positions_b
        r_str = execute_pool_samples(
            client_a,
            source_plate="Src",
            dest_plate="Dest",
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
        )
        r_list = execute_pool_samples(
            client_b,
            source_plate=["Src@all"],
            dest_plate=["Dest@all"],
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
        )
        assert r_str.pools_completed == r_list.pools_completed
        assert r_str.wells_pooled == r_list.wells_pooled

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_cross_plate_pool_row_chunk_stays_within_plate(self, mock_resolve):
        """Pool of 4 with sources [A1, B1] from SrcA and [A1, B1] from SrcB.
        chunk_positions_per_plate ensures each row stays on one plate."""
        client = _mock_client()
        mock_resolve.side_effect = [
            [
                _positions("SrcA", 2)[0],
                _positions("SrcA", 2)[1],
                _positions("SrcB", 2)[0],
                _positions("SrcB", 2)[1],
            ],
            _positions("Dest", 1),
        ]
        result = execute_pool_samples(
            client,
            source_plate=["SrcA@col:1", "SrcB@col:1"],
            dest_plate="Dest",
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
            channels=[1, 2],
        )
        assert result.pools_completed == 1
        # Two aspirate calls (one per plate in the pool)
        assert len(result.iteration_results[0].aspirates) == 2

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_plate_ids_reflect_all_plates(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [
            _positions("PlateA", 4) + _positions("PlateB", 4),
            _positions("Dest", 2),
        ]
        result = execute_pool_samples(
            client,
            source_plate=["PlateA@col:1", "PlateB@col:1"],
            dest_plate="Dest",
            pool_size=4,
            volume_per_source=50.0,
            liquid_class="Water",
            tip_pool="Tips300",
            mix_after_pool=False,
        )
        assert set(result.source_plate_ids) == {"PlateA", "PlateB"}

    def test_empty_source_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="source_plate list"):
            execute_pool_samples(
                client,
                source_plate=[],
                dest_plate="Dest",
                pool_size=4,
                volume_per_source=50.0,
                liquid_class="W",
                tip_pool="T",
            )

    def test_empty_dest_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="dest_plate list"):
            execute_pool_samples(
                client,
                source_plate="Src",
                dest_plate=[],
                pool_size=4,
                volume_per_source=50.0,
                liquid_class="W",
                tip_pool="T",
            )


class TestPoolSamplesPositionInput:
    """source_plate/dest_plate may be pre-resolved Position objects, not just
    selector strings."""

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_source_plate_as_position_list(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 8), _positions("Dest", 2)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "source_plate": [Position(labware="Source", well="A1")]},
            mix_after_pool=False,
        )
        assert result.wells_pooled == 8
        assert result.source_plate_ids == ("Source",)

    @patch("hamilton_venus.compound_commands.pool_samples.resolve_multi_selector")
    def test_dest_plate_as_single_position(self, mock_resolve):
        client = _mock_client()
        mock_resolve.side_effect = [_positions("Source", 4), _positions("Dest", 1)]
        result = execute_pool_samples(
            client,
            **{**_BASE, "dest_plate": Position(labware="Dest", well="A1"), "pool_size": 4},
            mix_after_pool=False,
        )
        assert result.dest_plate_ids == ("Dest",)
