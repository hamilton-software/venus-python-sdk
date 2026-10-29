from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands.copy_plate import _compute_tips_needed, execute_copy_plate
from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.models.command_types import (
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelTADM,
    ChannelTADMCurve,
)
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import CopyPlateIterationResult
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
from hamilton_venus.models.position import Position


def _make_response(**overrides) -> CommandResponse:
    return CommandResponse(**overrides)


def _make_aspirate_response(
    channels: list[dict] | None = None,
    tadm: ChannelTADM | None = None,
) -> ChannelAspirationResponse:
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={
            "channels": channels or [],
            **({"TADM": tadm.model_dump(by_alias=True)} if tadm is not None else {}),
        },
    )


def _make_dispense_response(
    channels: list[dict] | None = None,
    tadm: ChannelTADM | None = None,
) -> ChannelDispenseResponse:
    return ChannelDispenseResponse(
        return_status="Success",
        return_code=0,
        return_parameters={
            "channels": channels or [],
            **({"TADM": tadm.model_dump(by_alias=True)} if tadm is not None else {}),
        },
    )


def _make_positions(plate: str, count: int) -> list[Position]:
    wells = []
    for i in range(count):
        row = chr(ord("A") + i % 8)
        col = i // 8 + 1
        wells.append(Position(labware=plate, well=f"{row}{col}"))
    return wells


def _mock_client(source_wells: int = 96, dest_wells: int = 96, available_tips: int = 96, tip_capacity: float = 1000.0):
    client = MagicMock()
    client.on_tip_reload_prompt = None

    def _labware_side_effect(plate_name):
        resp = MagicMock()
        resp.return_parameters.definition = {"rack_layout": {"rows": 8, "columns": 12}}
        return resp

    client.labware_get_params_from_id.side_effect = _labware_side_effect

    tip_resp = MagicMock()
    tip_resp.return_parameters.total_available_tips = available_tips
    client.tip_pool_get_available_tips.return_value = tip_resp

    counter_resp = MagicMock()
    counter_resp.return_parameters.tip_type_id = "0"
    client.tip_pool_get_tip_counter.return_value = counter_resp

    types_resp = MagicMock()
    types_resp.return_parameters.tip_types = {"0": {"Max Liquid Volume": tip_capacity}}
    client.get_tip_types.return_value = types_resp

    client.tip_pickup.return_value = _make_response()
    client.tip_eject.return_value = _make_response()
    client.aspirate.return_value = _make_aspirate_response()
    client.dispense.return_value = _make_dispense_response()

    return client


def _get_call_kwarg(call, key, default=None):
    """Extract a keyword argument from a mock call, checking both ``.kwargs`` and positional ``[1]``."""
    return call.kwargs.get(key, call[1].get(key, default))


# ---------------------------------------------------------------------------
# Shared kwargs used by most execute_copy_plate tests
# ---------------------------------------------------------------------------

_BASIC_KWARGS: dict = dict(
    source_plate_id="Src",
    dest_plate_id="Dst",
    volume=100.0,
    tip_pool="TransferTips",
    liquid_class="Water",
)

_NAMED_KWARGS: dict = dict(
    source_plate_id="SrcPlate",
    dest_plate_id="DstPlate",
    volume=100.0,
    tip_pool="TransferTips",
    liquid_class="Water",
)

_ERROR_PROFILE_KWARGS: dict = dict(
    source_plate_id="SrcPlate",
    dest_plate_id="DstPlate",
    volume=50.0,
    tip_pool="TipPool",
    liquid_class="Water",
)


def _resolve(mock_resolve, *position_lists) -> None:
    """Set mock_resolve.side_effect from one or more position lists."""
    mock_resolve.side_effect = list(position_lists)


class TestComputeTipsNeeded:
    def test_exact_multiple(self):
        assert _compute_tips_needed(96, 8) == 96

    def test_with_remainder(self):
        assert _compute_tips_needed(10, 8) == 10

    def test_fewer_than_channels(self):
        assert _compute_tips_needed(3, 8) == 3

    def test_single_well(self):
        assert _compute_tips_needed(1, 8) == 1

    def test_reuse_tips_exact_multiple(self):
        assert _compute_tips_needed(96, 8, reuse_tips=True) == 8

    def test_reuse_tips_fewer_wells_than_channels(self):
        assert _compute_tips_needed(3, 8, reuse_tips=True) == 3

    def test_reuse_tips_single_well(self):
        assert _compute_tips_needed(1, 8, reuse_tips=True) == 1


class TestExecuteCopyPlateBasic:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_full_96_plate_copy(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("SrcPlate", 96), _make_positions("DstPlate", 96))

        result = execute_copy_plate(client, **_NAMED_KWARGS)

        assert result.source_plate_id == "SrcPlate"
        assert result.dest_plate_id == "DstPlate"
        assert result.iterations == 12
        assert result.wells_copied == 96
        assert result.total_wells_processed == 96
        assert result.wells_skipped == 0
        assert len(result.iteration_results) == 12

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_each_iteration_has_pickup_aspirate_dispense_eject(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.iterations == 2
        for it in result.iteration_results:
            assert it.tip_pickup is not None
            assert it.aspirate is not None
            assert it.dispense is not None
            assert it.tip_eject is not None

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_custom_channels(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS, channels=[1, 2, 3, 4])

        assert result.iterations == 2
        assert result.wells_copied == 8

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_custom_volumes(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        execute_copy_plate(
            client,
            source_plate_id="Src",
            dest_plate_id="Dst",
            tip_pool="TransferTips",
            liquid_class="Water",
            volume=50.0,
        )

        for asp_call in client.aspirate.call_args_list:
            assert _get_call_kwarg(asp_call, "volumes") == 50.0


class TestExecuteCopyPlateReuseTips:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_single_pickup(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)

        assert client.tip_pickup.call_count == 1

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_single_eject_at_end(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)

        assert client.tip_eject.call_count == 1

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_validates_first_pickup_only(self, mock_resolve):
        client = _mock_client(available_tips=8)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)

        client.tip_pool_get_available_tips.assert_called_once()
        assert result.wells_copied == 8

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_iteration_responses(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        result = execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)

        # first iteration: pickup, no eject; last iteration: no pickup, eject
        assert result.iteration_results[0].tip_pickup is not None
        assert result.iteration_results[0].tip_eject is None
        assert result.iteration_results[-1].tip_pickup is None
        assert result.iteration_results[-1].tip_eject is not None

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_fewer_wells_than_channels(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 3), _make_positions("Dst", 3))

        result = execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)

        assert result.iterations == 1
        assert result.wells_copied == 3
        pickup_call = client.tip_pickup.call_args
        assert _get_call_kwarg(pickup_call, "channels") == [1, 2, 3]


class TestExecuteCopyPlateTipValidation:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_insufficient_tips_raises(self, mock_resolve):
        client = _mock_client(available_tips=5)
        _resolve(mock_resolve, _make_positions("Src", 96), _make_positions("Dst", 96))

        with pytest.raises(ValueError, match="tips available"):
            execute_copy_plate(client, **_BASIC_KWARGS)

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_insufficient_for_first_pickup_raises(self, mock_resolve):
        client = _mock_client(available_tips=0)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        with pytest.raises(ValueError, match="tips available"):
            execute_copy_plate(client, **_BASIC_KWARGS, reuse_tips=True)


class TestExecuteCopyPlateTipCapacityValidation:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_scalar_volume_exceeds_tip_capacity_raises(self, mock_resolve):
        client = _mock_client(tip_capacity=100.0)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        with pytest.raises(ValueError, match="exceeds tip capacity"):
            execute_copy_plate(
                client,
                source_plate_id="Src",
                dest_plate_id="Dst",
                tip_pool="TransferTips",
                liquid_class="Water",
                volume=150.0,
            )

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_scalar_volume_equal_to_tip_capacity_passes(self, mock_resolve):
        client = _mock_client(tip_capacity=100.0)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(
            client,
            source_plate_id="Src",
            dest_plate_id="Dst",
            tip_pool="TransferTips",
            liquid_class="Water",
            volume=100.0,
        )

        assert result.wells_copied == 8


class TestExecuteCopyPlateMismatchedPlates:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_source_smaller_than_dest(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 16))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.wells_copied == 8
        assert result.wells_skipped == 8

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_dest_smaller_than_source(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.wells_copied == 8
        assert result.wells_skipped == 8


class TestExecuteCopyPlateEmptyPlate:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_zero_wells_returns_empty_result(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, [], _make_positions("Dst", 96))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.iterations == 0
        assert result.wells_copied == 0
        assert result.total_wells_processed == 0
        assert result.iteration_results == ()
        client.tip_pickup.assert_not_called()
        client.aspirate.assert_not_called()


class TestExecuteCopyPlateSettings:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_aspirate_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))
        asp_settings = AspirateSettings(fixed_height=10.0)

        execute_copy_plate(client, **_BASIC_KWARGS, aspirate_settings=asp_settings)

        asp_call = client.aspirate.call_args
        passed_settings = asp_call.kwargs.get("settings")
        assert passed_settings is not None
        assert passed_settings.fixed_height == 10.0

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_dispense_settings_forwarded(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))
        disp_settings = DispenseSettings(fixed_height=15.0)

        execute_copy_plate(client, **_BASIC_KWARGS, dispense_settings=disp_settings)

        disp_call = client.dispense.call_args
        passed_settings = disp_call.kwargs.get("settings")
        assert passed_settings is not None
        assert passed_settings.fixed_height == 15.0

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_liquid_class_forwarded(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        execute_copy_plate(client, **_BASIC_KWARGS)

        asp_call = client.aspirate.call_args
        assert asp_call.kwargs.get("liquid_class") == "Water"
        disp_call = client.dispense.call_args
        assert "liquid_class" not in disp_call.kwargs


class TestExecuteCopyPlateChannelValidation:
    def test_invalid_channels_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="must not be empty"):
            execute_copy_plate(client, **_BASIC_KWARGS, channels=[])

    def test_duplicate_channels_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="duplicates"):
            execute_copy_plate(client, **_BASIC_KWARGS, channels=[1, 1])


class TestCopyPlateIterationResults:
    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_iteration_results_length_matches_iterations(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert len(result.iteration_results) == result.iterations

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_iteration_results_are_typed(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert len(result.iteration_results) == 1
        it = result.iteration_results[0]
        assert isinstance(it, CopyPlateIterationResult)
        assert isinstance(it.aspirate, ChannelAspirationResponse)
        assert isinstance(it.dispense, ChannelDispenseResponse)

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_tadm_curves_empty_when_no_tadm_in_response(self, mock_resolve):
        client = _mock_client()
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.tadm_curves == []

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_tadm_curves_populated_from_aspirate_response(self, mock_resolve):
        tadm = ChannelTADM(
            tadm_curves=[
                ChannelTADMCurve(
                    curve_id=1,
                    liquid_class_name="Water",
                    step_type_name="Aspirating",
                    volume=50.0,
                    channel_number=1,
                )
            ]
        )
        client = _mock_client()
        client.aspirate.return_value = _make_aspirate_response(tadm=tadm)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert len(result.tadm_curves) == 1
        assert result.tadm_curves[0].curve_id == 1
        assert result.tadm_curves[0].liquid_class_name == "Water"

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_tadm_curves_populated_from_dispense_response(self, mock_resolve):
        tadm = ChannelTADM(
            tadm_curves=[
                ChannelTADMCurve(
                    curve_id=2,
                    liquid_class_name="Water",
                    step_type_name="Dispensing",
                    volume=50.0,
                    channel_number=1,
                )
            ]
        )
        client = _mock_client()
        client.dispense.return_value = _make_dispense_response(tadm=tadm)
        _resolve(mock_resolve, _make_positions("Src", 8), _make_positions("Dst", 8))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert len(result.tadm_curves) == 1
        assert result.tadm_curves[0].curve_id == 2
        assert result.tadm_curves[0].step_type_name == "Dispensing"

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_tadm_curves_flattened_across_all_iterations(self, mock_resolve):
        def _asp_side_effect(**_kwargs):
            return _make_aspirate_response(
                tadm=ChannelTADM(tadm_curves=[ChannelTADMCurve(curve_id=99, volume=50.0, channel_number=1)])
            )

        client = _mock_client()
        client.aspirate.side_effect = _asp_side_effect
        _resolve(mock_resolve, _make_positions("Src", 16), _make_positions("Dst", 16))

        result = execute_copy_plate(client, **_BASIC_KWARGS)

        assert result.iterations == 2
        # one TADM curve per aspirate, two iterations
        assert len(result.tadm_curves) == 2


class TestExecuteCopyPlateErrorProfile:
    """When error_profile is provided, copy_plate runs inside client.use_error_profile."""

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_error_profile_context_entered(self, mock_resolve):
        client = _mock_client(source_wells=8, dest_wells=8, available_tips=8)
        _resolve(
            mock_resolve,
            _make_positions("SrcPlate", 8),
            _make_positions("DstPlate", 8),
        )
        profile = MagicMock()
        ctx_manager = MagicMock()
        ctx_manager.__enter__ = MagicMock(return_value=None)
        ctx_manager.__exit__ = MagicMock(return_value=False)
        client.use_error_profile.return_value = ctx_manager

        execute_copy_plate(client, **_ERROR_PROFILE_KWARGS, error_profile=profile)

        client.use_error_profile.assert_called_once_with(profile)
        ctx_manager.__enter__.assert_called_once()

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_no_error_profile_does_not_call_use_error_profile(self, mock_resolve):
        client = _mock_client(source_wells=8, dest_wells=8, available_tips=8)
        _resolve(
            mock_resolve,
            _make_positions("SrcPlate", 8),
            _make_positions("DstPlate", 8),
        )

        execute_copy_plate(client, **_ERROR_PROFILE_KWARGS)

        client.use_error_profile.assert_not_called()


class TestExecuteCopyPlateLabwareValidation:
    @staticmethod
    def _make_client_missing(missing: set[str]) -> MagicMock:
        client = _mock_client()

        def _side_effect(plate_name: str):
            if plate_name in missing:
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

        client.labware_get_params_from_id.side_effect = _side_effect
        return client

    def test_raises_when_source_missing(self):
        client = self._make_client_missing({"Src"})
        with pytest.raises(ValueError, match="Src"):
            execute_copy_plate(client, **_BASIC_KWARGS)

    def test_raises_when_dest_missing(self):
        client = self._make_client_missing({"Dst"})
        with pytest.raises(ValueError, match="Dst"):
            execute_copy_plate(client, **_BASIC_KWARGS)

    def test_lists_both_when_both_missing(self):
        client = self._make_client_missing({"Src", "Dst"})
        with pytest.raises(ValueError) as exc:
            execute_copy_plate(client, **_BASIC_KWARGS)
        msg = str(exc.value)
        assert "Src" in msg
        assert "Dst" in msg


# ===========================================================================
# Multi-dest (list[str]) support
# ===========================================================================


class TestExecuteCopyPlateMultiDest:
    """dest_plate_id accepts str | list[str]; single-plate behavior is preserved."""

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_single_dest_string_backward_compat(self, mock_resolve):
        client = _mock_client(available_tips=96)
        mock_resolve.side_effect = [
            _make_positions("Src", 16),
            _make_positions("Dst", 16),
        ]
        result = execute_copy_plate(client, "Src", "Dst", volume=50.0, tip_pool="T", liquid_class="W")
        assert result.dest_plate_id == "Dst"
        assert result.dest_plate_ids == ("Dst",)
        assert result.wells_copied == 16

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_two_dest_plates_copies_to_each(self, mock_resolve):
        client = _mock_client(available_tips=200)
        mock_resolve.side_effect = [
            _make_positions("Src", 16),  # source
            _make_positions("Dst1", 16),  # dest 1
            _make_positions("Dst2", 16),  # dest 2
        ]
        result = execute_copy_plate(
            client,
            "Src",
            ["Dst1", "Dst2"],
            volume=50.0,
            tip_pool="T",
            liquid_class="W",
        )
        assert result.dest_plate_ids == ("Dst1", "Dst2")
        assert result.dest_plate_id == "Dst1"
        assert result.wells_copied == 32
        assert result.total_wells_processed == 32
        # 2 iterations per dest (16 wells / 8 channels) = 4 total
        assert result.iterations == 4

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_three_dest_plates_aggregates_all_iterations(self, mock_resolve):
        client = _mock_client(available_tips=300)
        mock_resolve.side_effect = [
            _make_positions("Src", 8),  # source
            _make_positions("D1", 8),  # dest 1
            _make_positions("D2", 8),  # dest 2
            _make_positions("D3", 8),  # dest 3
        ]
        result = execute_copy_plate(
            client,
            "Src",
            ["D1", "D2", "D3"],
            volume=50.0,
            tip_pool="T",
            liquid_class="W",
        )
        assert result.dest_plate_ids == ("D1", "D2", "D3")
        assert result.wells_copied == 24
        # Each dest: 8 wells / 8 channels = 1 iteration → 3 total
        assert result.iterations == 3

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_single_element_list_equivalent_to_string(self, mock_resolve):
        client_a = _mock_client(available_tips=96)
        client_b = _mock_client(available_tips=96)
        mock_resolve.side_effect = [
            _make_positions("Src", 16),
            _make_positions("Dst", 16),
            _make_positions("Src", 16),
            _make_positions("Dst", 16),
        ]
        r_str = execute_copy_plate(client_a, "Src", "Dst", volume=50.0, tip_pool="T", liquid_class="W")
        r_list = execute_copy_plate(client_b, "Src", ["Dst"], volume=50.0, tip_pool="T", liquid_class="W")
        assert r_str.wells_copied == r_list.wells_copied
        assert r_str.iterations == r_list.iterations
        assert r_str.dest_plate_ids == r_list.dest_plate_ids

    def test_empty_dest_list_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="at least one"):
            execute_copy_plate(client, "Src", [], volume=50.0, tip_pool="T", liquid_class="W")

    @patch("hamilton_venus.compound_commands.copy_plate.resolve_plate_wells")
    def test_reuse_tips_across_two_dests_ejects_between_copies(self, mock_resolve):
        """With reuse_tips=True each dest gets its own pickup/eject cycle."""
        client = _mock_client(available_tips=16)
        mock_resolve.side_effect = [
            _make_positions("Src", 8),
            _make_positions("D1", 8),
            _make_positions("D2", 8),
        ]
        result = execute_copy_plate(
            client,
            "Src",
            ["D1", "D2"],
            volume=50.0,
            tip_pool="T",
            liquid_class="W",
            reuse_tips=True,
        )
        assert result.dest_plate_ids == ("D1", "D2")
        assert result.wells_copied == 16
        # reuse_tips: 1 iter per dest, eject on last iter of each
        assert result.iterations == 2
        assert result.iteration_results[0].tip_eject is not None
        assert result.iteration_results[1].tip_eject is not None
