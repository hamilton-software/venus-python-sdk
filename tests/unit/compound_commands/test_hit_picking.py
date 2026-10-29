"""Unit tests for ``execute_hit_picking`` and its helpers.

Covers the ``change_tips=True, minimize_tips=False`` (default) and
``change_tips=False, minimize_tips=False`` (reuse-tips) modes.  The
``minimize_tips=True`` combinations raise :class:`NotImplementedError` and are
asserted as such here; they are implemented in task 8.

Mirrors the conventions in ``test_add_reagent.py``: a configurable mock client
factory, CSV temp-file helpers, and ``resolve_selector_positions`` patched with
a selector->positions map.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands._helpers._transfer_plan import TransferRow, _validate_row_volumes_in_range
from hamilton_venus.compound_commands.hit_picking import (
    _plan_transfers,
    _ResolvedTransfer,
    execute_hit_picking,
)
from hamilton_venus.exceptions import OperatorCancelledError, VenusCommandFailedError
from hamilton_venus.models.command_types import (
    ChannelAspirationResponse,
    ChannelDispenseResponse,
    ChannelTADM,
    ChannelTADMCurve,
)
from hamilton_venus.models.commands import CommandResponse
from hamilton_venus.models.compound_results import HitPickingResult
from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings
from hamilton_venus.models.position import Position

_RESOLVE_TARGET = "hamilton_venus.compound_commands.hit_picking.resolve_selector_positions"


# ---------------------------------------------------------------------------
# Response factories
# ---------------------------------------------------------------------------


def _make_response(**overrides) -> CommandResponse:
    return CommandResponse(
        return_status=overrides.get("return_status", "Success"),
        return_code=overrides.get("return_code", 0),
    )


def _make_aspirate_response(tadm: ChannelTADM | None = None) -> ChannelAspirationResponse:
    params: dict = {"channels": []}
    if tadm is not None:
        params["TADM"] = tadm.model_dump(by_alias=True)
    return ChannelAspirationResponse(return_status="Success", return_code=0, return_parameters=params)


def _make_dispense_response(tadm: ChannelTADM | None = None) -> ChannelDispenseResponse:
    params: dict = {"channels": []}
    if tadm is not None:
        params["TADM"] = tadm.model_dump(by_alias=True)
    return ChannelDispenseResponse(return_status="Success", return_code=0, return_parameters=params)


def _tadm(label: str) -> ChannelTADM:
    return ChannelTADM(tadm_curves=[ChannelTADMCurve(curve_id=1, step_type_name=label)])


# ---------------------------------------------------------------------------
# Mock client factory
# ---------------------------------------------------------------------------


def _make_client(
    *,
    tip_capacity: float = 300.0,
    available_tips: int = 200,
    rows: int = 8,
    cols: int = 12,
    missing_labware: set[str] | None = None,
) -> MagicMock:
    """Build a fully-wired mock client for ``execute_hit_picking`` tests.

    ``labware_get_params_from_id`` returns a real ``rack_layout`` dict so the
    column-major reorder path can build a ``LabwareLayoutSpec``.  Any labware id
    in *missing_labware* raises ``VenusCommandFailedError`` to simulate
    not-on-deck labware.
    """
    client = MagicMock()
    missing = missing_labware or set()

    def _labware_side_effect(name: str) -> MagicMock:
        if name in missing:
            resp = MagicMock(
                action_name="labware.getLabwareParamsFromID",
                return_status="Failure",
                return_code=1,
                return_parameters={},
            )
            raise VenusCommandFailedError(resp)
        r = MagicMock()
        r.return_parameters.definition = {"rack_layout": {"rows": rows, "columns": cols}}
        return r

    client.labware_get_params_from_id.side_effect = _labware_side_effect

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
    client.on_tip_reload_prompt = None
    return client


def _kwarg(mock_call, key):
    """Return keyword arg *key* from a mock call."""
    return mock_call.kwargs.get(key, mock_call[1].get(key))


def _identity_resolve(_client, selector: str, _ctx=None):
    """Resolve ``Labware@wells:Well`` selectors into a single matching Position."""
    labware, _, rest = selector.partition("@")
    well = rest.split(":", 1)[1] if ":" in rest else "A1"
    return [Position(labware=labware, well=well)]


def _write_csv(tmp_path, rows: list[tuple[str, str, str, str, float]]) -> str:
    p = tmp_path / "transfer.csv"
    lines = ["source_labware,source_well,dest_labware,dest_well,volume"]
    for sl, sw, dl, dw, vol in rows:
        lines.append(f"{sl},{sw},{dl},{dw},{vol}")
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


_BASE_KWARGS = {"liquid_class": "Water", "tip_pool": "tips"}


# ===========================================================================
# Helper-level tests
# ===========================================================================


class TestValidateVolumesInRange:
    def test_within_capacity_ok(self):
        rows = [TransferRow("S", "A1", "D", "A1", 100.0, line_no=2)]
        _validate_row_volumes_in_range(rows, max_aspiration=300.0)  # no raise

    def test_exceeds_capacity_raises_with_line(self):
        rows = [TransferRow("S", "A1", "D", "B1", 400.0, line_no=5)]
        with pytest.raises(ValueError, match="exceeds tip capacity"):
            _validate_row_volumes_in_range(rows, max_aspiration=300.0)

    def test_non_positive_raises_with_line(self):
        rows = [TransferRow("S", "A1", "D", "B1", 0.0, line_no=7)]
        with pytest.raises(ValueError, match="must be > 0"):
            _validate_row_volumes_in_range(rows, max_aspiration=300.0)


class TestPlanTransfers:
    def _t(self, n: int) -> list[_ResolvedTransfer]:
        return [
            _ResolvedTransfer(
                source_pos=Position(labware="S", well=f"A{i}"),
                dest_pos=Position(labware="D", well=f"A{i}"),
                volume=50.0,
            )
            for i in range(1, n + 1)
        ]

    def _t_wells(self, pairs: list[tuple[str, str]]) -> list[_ResolvedTransfer]:
        """Build transfers from explicit ``(source_well, dest_well)`` pairs."""
        return [
            _ResolvedTransfer(
                source_pos=Position(labware="S", well=sw),
                dest_pos=Position(labware="D", well=dw),
                volume=50.0,
            )
            for sw, dw in pairs
        ]

    def test_default_mode_chunks_by_channels(self):
        blocks = _plan_transfers(self._t(20), channels=[1, 2, 3, 4, 5, 6, 7, 8], minimize_tips=False, change_tips=True)
        assert [len(b.transfers) for b in blocks] == [8, 8, 4]
        assert [len(b.channels) for b in blocks] == [8, 8, 4]

    def test_single_partial_block(self):
        blocks = _plan_transfers(self._t(3), channels=[1, 2, 3, 4, 5, 6, 7, 8], minimize_tips=False, change_tips=True)
        assert len(blocks) == 1
        assert blocks[0].channels == [1, 2, 3]

    def test_minimize_tips_one_block_per_source_well(self):
        # Two source wells (A1 fed twice, B1 once) -> two single-channel blocks.
        transfers = self._t_wells([("A1", "A1"), ("A1", "B1"), ("B1", "C1")])
        blocks = _plan_transfers(transfers, channels=[1, 2, 3, 4, 5, 6, 7, 8], minimize_tips=True, change_tips=True)
        assert len(blocks) == 2
        assert all(b.channels == [1] for b in blocks)
        assert [len(b.transfers) for b in blocks] == [2, 1]
        # First block carries both A1 destinations; second carries B1's.
        assert [t.dest_pos.well for t in blocks[0].transfers] == ["A1", "B1"]
        assert [t.dest_pos.well for t in blocks[1].transfers] == ["C1"]

    def test_minimize_tips_groups_non_adjacent_source_wells(self):
        # A1 -> B1 -> A1 collapses A1 into one group (first-appearance order).
        transfers = self._t_wells([("A1", "A1"), ("B1", "B1"), ("A1", "C1")])
        blocks = _plan_transfers(transfers, channels=[1, 2], minimize_tips=True, change_tips=True)
        assert len(blocks) == 2
        assert [len(b.transfers) for b in blocks] == [2, 1]
        assert [t.dest_pos.well for t in blocks[0].transfers] == ["A1", "C1"]

    def test_minimize_tips_keep_tips_single_block(self):
        # change_tips=False keeps one tip across all source wells (Q4).
        transfers = self._t_wells([("A1", "A1"), ("B1", "B1"), ("C1", "C1")])
        blocks = _plan_transfers(transfers, channels=[1, 2, 3, 4], minimize_tips=True, change_tips=False)
        assert len(blocks) == 1
        assert blocks[0].channels == [1]
        assert len(blocks[0].transfers) == 3

    def test_minimize_tips_empty_returns_no_blocks(self):
        assert _plan_transfers([], channels=[1, 2], minimize_tips=True, change_tips=True) == []
        assert _plan_transfers([], channels=[1, 2], minimize_tips=True, change_tips=False) == []

    def test_reuse_tips_single_block(self):
        # change_tips=False collapses the whole worklist into one TipBlock.
        blocks = _plan_transfers(self._t(20), channels=[1, 2, 3, 4, 5, 6, 7, 8], minimize_tips=False, change_tips=False)
        assert len(blocks) == 1
        assert len(blocks[0].channels) == 8
        assert len(blocks[0].transfers) == 20

    def test_reuse_tips_caps_channels_to_transfers(self):
        # Fewer transfers than channels -> pickup only as many tips as needed.
        blocks = _plan_transfers(self._t(3), channels=[1, 2, 3, 4, 5, 6, 7, 8], minimize_tips=False, change_tips=False)
        assert len(blocks) == 1
        assert blocks[0].channels == [1, 2, 3]

    def test_reuse_tips_empty_returns_no_blocks(self):
        assert _plan_transfers([], channels=[1, 2], minimize_tips=False, change_tips=False) == []

    def test_default_mode_empty_returns_no_blocks(self):
        # Symmetry: every (change_tips, minimize_tips) combo returns [] for empty input.
        assert _plan_transfers([], channels=[1, 2], minimize_tips=False, change_tips=True) == []


# ===========================================================================
# Basic execution
# ===========================================================================


class TestExecuteHitPickingBasic:
    def test_eight_transfers_eight_channels(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [(f"S{i}", "A1", "D", f"A{i}", 50.0) for i in range(1, 9)],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert isinstance(result, HitPickingResult)
        assert result.total_wells_processed == 8
        assert len(result.transfers) == 8
        # 8 transfers from distinct sources, default mode -> one tip per transfer.
        assert result.tips_consumed == 8

    def test_returns_change_tips_minimize_flags(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S1", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert result.change_tips is True
        assert result.minimize_tips is False

    def test_transfer_records_capture_endpoints(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("Src", "A1", "Dst", "B2", 75.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        t = result.transfers[0]
        assert (t.source_plate_id, t.source_well) == ("Src", "A1")
        assert (t.dest_plate_id, t.dest_well) == ("Dst", "B2")
        assert t.volume == 75.0


# ===========================================================================
# change_tips=True chunking / tip management
# ===========================================================================


class TestHitPickingChangeTipsTrue:
    def test_pickup_eject_per_chunk(self, tmp_path):
        # 10 transfers from one source plate, 8 channels -> 2 chunks/blocks.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert result.iterations == 2
        assert client.tip_pickup.call_count == 2
        assert client.tip_eject.call_count == 2

    def test_partial_last_chunk_uses_fewer_channels(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        last_pickup = client.tip_pickup.call_args_list[-1]
        assert _kwarg(last_pickup, "channels") == [1, 2]

    def test_tip_eject_in_finally_on_aspirate_error(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        client.aspirate.side_effect = RuntimeError("aspirate failed")
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            pytest.raises(RuntimeError, match="aspirate failed"),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert client.tip_eject.call_count == 1


# ===========================================================================
# change_tips=False reuse-tips mode
# ===========================================================================


_REUSE_KWARGS = {**_BASE_KWARGS, "change_tips": False}


class TestHitPickingReuseTips:
    def test_single_pickup_single_eject(self, tmp_path):
        # 10 transfers, 8 channels: default mode would use 2 blocks, but
        # reuse-tips collapses everything into one pickup/eject.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        # One pickup/eject, but 10 transfers split into 8 + 2 chunks -> 2 aspirate calls.
        assert result.iterations == 2
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1

    def test_transfers_still_chunked_by_channels(self, tmp_path):
        # All 10 transfers run, chunked into 8 + 2 aspirate/dispense pairs.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        assert client.aspirate.call_count == 2
        assert client.dispense.call_count == 2
        assert result.total_wells_processed == 10

    def test_tips_consumed_is_single_pickup_count(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        # One pickup of 8 tips reused for all 10 transfers.
        assert result.tips_consumed == 8

    def test_pickup_caps_channels_to_transfers(self, tmp_path):
        # Three transfers, eight channels -> pick up only three tips.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 4)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        first_pickup = client.tip_pickup.call_args_list[0]
        assert _kwarg(first_pickup, "channels") == [1, 2, 3]
        assert result.tips_consumed == 3

    def test_result_flags_reflect_reuse_mode(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        assert result.change_tips is False
        assert result.minimize_tips is False

    def test_tip_eject_in_finally_on_dispense_error(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12)
        client.dispense.side_effect = RuntimeError("dispense failed")
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            pytest.raises(RuntimeError, match="dispense failed"),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        # Single block -> single eject even though the failure occurred mid-block.
        assert client.tip_eject.call_count == 1

    def test_budget_is_min_channels_rows_insufficient_raises(self, tmp_path):
        # 10 transfers but only 8 channels -> budget is 8, not 10.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12, available_tips=4)
        client.on_tip_reload_prompt = None
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            pytest.raises(ValueError, match="tips available"),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)

    def test_budget_min_channels_rows_sufficient_with_few_tips(self, tmp_path):
        # 10 transfers, 8 channels, only 8 tips available: reuse mode succeeds
        # where change_tips=True (needing 10) would fail.
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(rows=8, cols=12, available_tips=8)
        client.on_tip_reload_prompt = None
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_REUSE_KWARGS)
        assert result.total_wells_processed == 10


# ===========================================================================
# CSV parsing wiring
# ===========================================================================


class TestHitPickingCsvParsing:
    def test_missing_column_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("source_labware,source_well,dest_labware,dest_well\nS,A1,D,A1\n", encoding="utf-8")
        client = _make_client()
        with pytest.raises(ValueError, match="volume"):
            execute_hit_picking(client, transfer_csv=str(p), **_BASE_KWARGS)

    def test_non_numeric_volume_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text(
            "source_labware,source_well,dest_labware,dest_well,volume\nS,A1,D,A1,abc\n",
            encoding="utf-8",
        )
        client = _make_client()
        with pytest.raises(ValueError, match="invalid volume"):
            execute_hit_picking(client, transfer_csv=str(p), **_BASE_KWARGS)

    def test_empty_csv_raises(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        client = _make_client()
        with pytest.raises(ValueError, match="empty"):
            execute_hit_picking(client, transfer_csv=str(p), **_BASE_KWARGS)


# ===========================================================================
# Volume validation
# ===========================================================================


class TestHitPickingVolumeValidation:
    def test_volume_exceeds_capacity_raises_with_line(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "B1", 500.0)])
        client = _make_client(tip_capacity=300.0)
        with pytest.raises(ValueError, match="tip capacity"):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)

    def test_non_positive_volume_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 0.0)])
        client = _make_client()
        with pytest.raises(ValueError, match="must be > 0"):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)


# ===========================================================================
# Labware / well validation
# ===========================================================================


class TestHitPickingLabwareValidation:
    def test_missing_labware_lists_all(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("GoodSrc", "A1", "BadDst", "A1", 50.0), ("BadSrc", "A1", "GoodDst", "A1", 50.0)],
        )
        client = _make_client(missing_labware={"BadSrc", "BadDst"})
        with pytest.raises(ValueError, match="BadDst") as exc:
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert "BadSrc" in str(exc.value)

    def test_unknown_well_lists_all_with_lines(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "Z9", 50.0), ("S", "Q9", "D", "A1", 50.0)],
        )
        client = _make_client()

        def _resolve(_client, selector: str, _ctx=None):
            # Z9 and Q9 resolve to nothing; everything else resolves.
            if "Z9" in selector or "Q9" in selector:
                return []
            return _identity_resolve(_client, selector, _ctx)

        with (
            patch(_RESOLVE_TARGET, side_effect=_resolve),
            pytest.raises(ValueError, match="could not be resolved") as exc,
        ):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        msg = str(exc.value)
        assert "Z9" in msg and "Q9" in msg


# ===========================================================================
# follow_csv_order vs reorder
# ===========================================================================


class TestHitPickingFollowCsvOrder:
    def test_follow_csv_order_preserves_rows(self, tmp_path):
        # Deliberately out of column-major order; follow_csv_order keeps it.
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "B1", "D", "C1", 50.0),
                ("S", "A1", "D", "A1", 50.0),
                ("S", "A2", "D", "B1", 50.0),
            ],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        wells = [(t.source_well, t.dest_well) for t in result.transfers]
        assert wells == [("B1", "C1"), ("A1", "A1"), ("A2", "B1")]

    def test_reorder_column_major_default(self, tmp_path):
        # follow_csv_order=False reorders by source plate -> source column-major.
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "B1", "D", "A1", 50.0),  # col 1, row 1 (B=row idx 1)
                ("S", "A2", "D", "A2", 50.0),  # col 2, row 0
                ("S", "A1", "D", "A3", 50.0),  # col 1, row 0
            ],
        )
        client = _make_client(rows=8, cols=12)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        # Column-major on source: A1 (col1,row0), B1 (col1,row1), A2 (col2,row0)
        source_wells = [t.source_well for t in result.transfers]
        assert source_wells == ["A1", "B1", "A2"]


# ===========================================================================
# Tip budget
# ===========================================================================


class TestHitPickingTipBudget:
    def test_budget_equals_row_count(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 6)])
        client = _make_client(available_tips=200)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        # ensure_tips_available checks availability against len(rows) == 5.
        assert client.tip_pool_get_available_tips.called

    def test_insufficient_tips_no_callback_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(available_tips=3)
        client.on_tip_reload_prompt = None
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            pytest.raises(ValueError, match="tips available"),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)

    def test_insufficient_tips_callback_reloads(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 4)])
        client = _make_client(available_tips=0)
        # First availability check sees 0; after reload, sees plenty.
        low = MagicMock()
        low.return_parameters.total_available_tips = 0
        high = MagicMock()
        high.return_parameters.total_available_tips = 200
        client.tip_pool_get_available_tips.side_effect = [low, high, high, high]
        client.on_tip_reload_prompt = MagicMock(return_value=True)
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert client.on_tip_reload_prompt.called
        assert client.tip_pool_reset_tip_counter.called
        assert result.total_wells_processed == 3

    def test_callback_cancel_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 11)])
        client = _make_client(available_tips=0)
        client.on_tip_reload_prompt = MagicMock(return_value=False)
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            pytest.raises(OperatorCancelledError),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)


# ===========================================================================
# Channels
# ===========================================================================


class TestHitPickingChannels:
    def test_partial_channel_set(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 8)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, channels=[1, 3, 5], **_BASE_KWARGS)
        # 7 transfers, 3 channels -> 3 blocks (3, 3, 1).
        assert result.iterations == 3
        first_pickup = client.tip_pickup.call_args_list[0]
        assert _kwarg(first_pickup, "channels") == [1, 3, 5]

    def test_invalid_channels_raise(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with pytest.raises(ValueError, match="between 1 and 16"):
            execute_hit_picking(client, transfer_csv=csv_path, channels=[1, 99], **_BASE_KWARGS)


# ===========================================================================
# Error profile
# ===========================================================================


class TestHitPickingErrorProfile:
    def test_error_profile_scope_entered(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        scope = MagicMock()
        client.use_error_profile.return_value = scope
        profile = MagicMock()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, error_profile=profile, **_BASE_KWARGS)
        client.use_error_profile.assert_called_once_with(profile)
        scope.__enter__.assert_called_once()
        scope.__exit__.assert_called_once()


# ===========================================================================
# Settings slicing
# ===========================================================================


class TestHitPickingSettings:
    def test_settings_sliced_to_active_channels(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "B1", 50.0)])
        client = _make_client()
        asp = AspirateSettings(submerge_depth=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        disp = DispenseSettings(submerge_depth=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(
                client,
                transfer_csv=csv_path,
                aspirate_settings=asp,
                dispense_settings=disp,
                follow_csv_order=True,
                **_BASE_KWARGS,
            )
        asp_settings = _kwarg(client.aspirate.call_args_list[0], "settings")
        assert len(asp_settings.submerge_depth) == 2


# ===========================================================================
# Result model wiring
# ===========================================================================


class TestHitPickingResultModel:
    def test_transfers_order_matches_execution(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "B1", 50.0), ("S", "A1", "D", "C1", 50.0)],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        assert [t.dest_well for t in result.transfers] == ["A1", "B1", "C1"]

    def test_iterations_equals_aspirate_call_count(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", f"A{i}", 50.0) for i in range(1, 10)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        # 9 transfers, 8 channels -> 2 blocks -> 2 aspirate calls.
        assert result.iterations == 2
        assert result.iterations == client.aspirate.call_count

    def test_tadm_curves_aggregate(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        client.aspirate.return_value = _make_aspirate_response(tadm=_tadm("asp"))
        client.dispense.return_value = _make_dispense_response(tadm=_tadm("disp"))
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert [c.step_type_name for c in result.tadm_curves] == ["asp", "disp"]

    def test_tadm_curves_no_double_count_in_multi_channel_chunk(self, tmp_path):
        # Two transfers processed in the same chunk share the same asp/disp
        # response objects.  tadm_curves must yield each response's curves once,
        # not once per transfer that references that response.
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "B1", "D", "B1", 50.0)],
        )
        client = _make_client()
        client.aspirate.return_value = _make_aspirate_response(tadm=_tadm("asp"))
        client.dispense.return_value = _make_dispense_response(tadm=_tadm("disp"))
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        # Both transfers share the same response objects (one chunk of 2).
        assert result.transfers[0].aspirate is result.transfers[1].aspirate
        # tadm_curves should contain exactly one asp + one disp curve, not two of each.
        assert [c.step_type_name for c in result.tadm_curves] == ["asp", "disp"]


# ===========================================================================
# Position caching
# ===========================================================================


class TestHitPickingPositionCaching:
    def test_repeated_well_queried_once(self, tmp_path):
        # Same source well feeds three different destinations.
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "B1", 50.0), ("S", "A1", "D", "C1", 50.0)],
        )
        client = _make_client()
        calls: list[str] = []

        def _resolve(_client, selector: str, _ctx=None):
            calls.append(selector)
            return _identity_resolve(_client, selector, _ctx)

        with patch(_RESOLVE_TARGET, side_effect=_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        # Source well S/A1 resolved once; three distinct dest wells resolved once each = 4 total.
        assert sum(1 for s in calls if "S@wells:A1" in s) == 1
        assert len(calls) == 4

    def test_negative_resolution_cached(self, tmp_path):
        # Same bad well appears in many rows -> resolved once, one error entry.
        csv_path = _write_csv(
            tmp_path,
            [("S", "BAD", "D", "A1", 50.0)] * 5,
        )
        client = _make_client()
        calls: list[str] = []

        def _resolve(_client, selector: str, _ctx=None):
            calls.append(selector)
            if "BAD" in selector:
                return []
            return _identity_resolve(_client, selector, _ctx)

        with (
            patch(_RESOLVE_TARGET, side_effect=_resolve),
            pytest.raises(ValueError, match="could not be resolved") as exc,
        ):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        # Bad well queried exactly once across the five rows.
        assert sum(1 for s in calls if "S@wells:BAD" in s) == 1
        # And appears once in the aggregated error message.
        assert str(exc.value).count("'S'/'BAD'") == 1


class TestHitPickingVolumeContract:
    def test_aspirate_volumes_scalar_when_uniform(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "B1", "D", "B1", 50.0)],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        # All chunks had uniform volume -> aspirate/dispense called with scalar.
        for call in client.aspirate.call_args_list:
            assert call.kwargs["volumes"] == 50.0
        for call in client.dispense.call_args_list:
            assert call.kwargs["volumes"] == 50.0

    def test_aspirate_volumes_list_when_mixed(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "B1", "D", "B1", 60.0)],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        # One chunk with mixed volumes -> list passed to aspirate/dispense.
        assert client.aspirate.call_args_list[0].kwargs["volumes"] == [50.0, 60.0]
        assert client.dispense.call_args_list[0].kwargs["volumes"] == [50.0, 60.0]


# ===========================================================================
# minimize_tips=True modes
# ===========================================================================


_MINIMIZE_KWARGS = {**_BASE_KWARGS, "minimize_tips": True}


class TestHitPickingMinimizeTips:
    def test_one_pickup_per_source_well(self, tmp_path):
        # Two source wells: A1 feeds three dests, B1 feeds one.
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "A1", "D", "A1", 50.0),
                ("S", "A1", "D", "B1", 50.0),
                ("S", "A1", "D", "C1", 50.0),
                ("S", "B1", "D", "D1", 50.0),
            ],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_MINIMIZE_KWARGS)
        # One block per distinct source well -> two pickups / two ejects.
        # 4 single-channel chunks total (3 from A1 + 1 from B1) -> 4 aspirate calls.
        assert result.iterations == 4
        assert client.tip_pickup.call_count == 2
        assert client.tip_eject.call_count == 2
        assert result.total_wells_processed == 4

    def test_single_channel_pickup(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "B1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_MINIMIZE_KWARGS)
        first_pickup = client.tip_pickup.call_args_list[0]
        assert _kwarg(first_pickup, "channels") == [1]

    def test_tips_consumed_equals_distinct_source_wells(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "A1", "D", "A1", 50.0),
                ("S", "B1", "D", "B1", 50.0),
                ("S", "A1", "D", "C1", 50.0),
            ],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_MINIMIZE_KWARGS)
        # Two distinct source wells (A1, B1) -> two tips.
        assert result.tips_consumed == 2

    def test_budget_is_distinct_source_wells(self, tmp_path):
        # Three transfers but only two source wells -> budget 2.  Two tips
        # available is enough (the change_tips=True default would need 3).
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "A1", "D", "A1", 50.0),
                ("S", "A1", "D", "B1", 50.0),
                ("S", "B1", "D", "C1", 50.0),
            ],
        )
        client = _make_client(available_tips=2)
        client.on_tip_reload_prompt = None
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_MINIMIZE_KWARGS)
        assert result.total_wells_processed == 3

    def test_result_flags_reflect_minimize_mode(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_MINIMIZE_KWARGS)
        assert result.minimize_tips is True
        assert result.change_tips is True

    def test_group_dests_share_one_tip(self, tmp_path):
        # A1's three destinations all run under one pickup; B1 under another.
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "A1", "D", "A1", 50.0),
                ("S", "A1", "D", "B1", 50.0),
                ("S", "B1", "D", "C1", 50.0),
            ],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_MINIMIZE_KWARGS)
        # Aspirate/dispense once per transfer (single-channel blocks).
        assert client.aspirate.call_count == 3
        assert [t.dest_well for t in result.transfers] == ["A1", "B1", "C1"]


class TestHitPickingMinimizeTipsReuseAcrossSources:
    """``change_tips=False, minimize_tips=True`` keeps one tip for everything (Q4)."""

    def test_single_pickup_single_eject(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [
                ("S", "A1", "D", "A1", 50.0),
                ("S", "B1", "D", "B1", 50.0),
                ("S", "C1", "D", "C1", 50.0),
            ],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(
                client, transfer_csv=csv_path, change_tips=False, follow_csv_order=True, **_MINIMIZE_KWARGS
            )
        # Single pickup/eject keeps the tip across every source well, but each
        # transfer is its own single-channel chunk -> 3 aspirate calls.
        assert result.iterations == 3
        assert client.tip_pickup.call_count == 1
        assert client.tip_eject.call_count == 1
        assert result.total_wells_processed == 3

    def test_budget_is_one_tip(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "B1", "D", "B1", 50.0), ("S", "C1", "D", "C1", 50.0)],
        )
        client = _make_client(available_tips=1)
        client.on_tip_reload_prompt = None
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(
                client, transfer_csv=csv_path, change_tips=False, follow_csv_order=True, **_MINIMIZE_KWARGS
            )
        assert result.tips_consumed == 1

    def test_warns_about_cross_contamination(self, tmp_path, caplog):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with (
            patch(_RESOLVE_TARGET, side_effect=_identity_resolve),
            caplog.at_level(logging.WARNING, logger="hamilton_venus.compound_commands.hit_picking"),
        ):
            execute_hit_picking(client, transfer_csv=csv_path, change_tips=False, **_MINIMIZE_KWARGS)
        assert any("cross-contamination" in r.message for r in caplog.records)

    def test_result_flags_reflect_keep_tips_mode(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, change_tips=False, **_MINIMIZE_KWARGS)
        assert result.minimize_tips is True
        assert result.change_tips is False


# ===========================================================================
# Edge cases
# ===========================================================================


class TestHitPickingEdgeCases:
    def test_single_row_csv(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, **_BASE_KWARGS)
        assert result.total_wells_processed == 1
        assert result.iterations == 1
        assert result.tips_consumed == 1

    def test_empty_tip_pool_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with pytest.raises(ValueError, match="tip_pool"):
            execute_hit_picking(client, transfer_csv=csv_path, liquid_class="Water", tip_pool="  ")

    def test_multiple_transfers_same_dest_counted_separately(self, tmp_path):
        csv_path = _write_csv(
            tmp_path,
            [("S", "A1", "D", "A1", 50.0), ("S", "A1", "D", "A1", 60.0)],
        )
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = execute_hit_picking(client, transfer_csv=csv_path, follow_csv_order=True, **_BASE_KWARGS)
        assert result.total_wells_processed == 2
        assert len(result.transfers) == 2


class TestHitPickingMixin:
    """The StarClient mixin exposes and forwards to ``execute_hit_picking``."""

    def test_star_client_exposes_hit_picking(self):
        from hamilton_venus.mixins.compound_commands import CompoundCommandsMixin
        from hamilton_venus.mixins.compound_commands.hit_picking_command import HitPickingCommand
        from hamilton_venus.star_client import StarClient

        assert issubclass(CompoundCommandsMixin, HitPickingCommand)
        assert issubclass(StarClient, HitPickingCommand)
        assert callable(StarClient.hit_picking)

    def test_mixin_forwards_to_execute(self, tmp_path):
        from hamilton_venus.mixins.compound_commands.hit_picking_command import HitPickingCommand

        csv_path = _write_csv(tmp_path, [("S", "A1", "D", "A1", 50.0)])
        client = _make_client()
        with patch(_RESOLVE_TARGET, side_effect=_identity_resolve):
            result = HitPickingCommand.hit_picking(
                client,
                transfer_csv=csv_path,
                liquid_class="Water",
                tip_pool="tips",
                follow_csv_order=True,
            )
        assert isinstance(result, HitPickingResult)
        assert result.total_wells_processed == 1
        client.aspirate.assert_called_once()
        client.dispense.assert_called_once()
