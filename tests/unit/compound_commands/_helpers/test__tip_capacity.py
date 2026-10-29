"""Unit tests for hamilton_venus.compound_commands._helpers._tip_capacity."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hamilton_venus.compound_commands._helpers._tip_capacity import _resolve_tip_capacity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
) -> MagicMock:
    client = MagicMock()
    client.tip_pool_get_tip_counter.return_value = _make_counter_response(tip_type_id, tip_type)
    client.get_tip_types.return_value = _make_tip_types_response(
        tip_types if tip_types is not None else {"0": {"Max Liquid Volume": 300, "tipTypeName": "300uL"}}
    )
    return client


# ---------------------------------------------------------------------------
# _resolve_tip_capacity
# ---------------------------------------------------------------------------


class TestResolveTipCapacity:
    def test_returns_max_liquid_volume(self):
        client = _make_client(
            tip_type_id="0",
            tip_types={"0": {"Max Liquid Volume": 300}},
        )
        result = _resolve_tip_capacity(client, "TransferTips")
        assert result == 300.0

    def test_calls_tip_pool_get_tip_counter_with_pool_name(self):
        client = _make_client()
        _resolve_tip_capacity(client, "MyPool")
        client.tip_pool_get_tip_counter.assert_called_once_with("MyPool")

    def test_calls_get_tip_types(self):
        client = _make_client()
        _resolve_tip_capacity(client, "MyPool")
        client.get_tip_types.assert_called_once()

    def test_selects_correct_tip_type_entry(self):
        client = _make_client(
            tip_type_id="2",
            tip_types={
                "0": {"Max Liquid Volume": 1000},
                "1": {"Max Liquid Volume": 200},
                "2": {"Max Liquid Volume": 50},
            },
        )
        result = _resolve_tip_capacity(client, "SmallTips")
        assert result == 50.0

    def test_returns_float_for_integer_volume(self):
        client = _make_client(
            tip_type_id="1",
            tip_types={"1": {"Max Liquid Volume": 1000}},
        )
        result = _resolve_tip_capacity(client, "LargeTips")
        assert isinstance(result, float)
        assert result == 1000.0

    def test_raises_value_error_for_unknown_tip_type_id(self):
        client = _make_client(
            tip_type_id="99",
            tip_types={"0": {"Max Liquid Volume": 300}},
        )
        with pytest.raises(ValueError, match="not present in the instrument tip-type catalogue"):
            _resolve_tip_capacity(client, "TransferTips")

    def test_raises_key_error_when_max_liquid_volume_missing(self):
        client = _make_client(
            tip_type_id="0",
            tip_types={"0": {"tipTypeName": "300uL"}},  # no "Max Liquid Volume"
        )
        with pytest.raises(KeyError):
            _resolve_tip_capacity(client, "TransferTips")

    def test_tip_type_int_used_when_tip_type_id_empty(self):
        """Simulator returns tip_type_id='' but tip_type=0 — use str(tip_type) as key."""
        client = _make_client(
            tip_type_id="",
            tip_type=0,
            tip_types={"0": {"Max Liquid Volume": 300}},
        )
        result = _resolve_tip_capacity(client, "TransferTips")
        assert result == 300.0

    def test_tip_type_int_selects_correct_entry_among_many(self):
        """tip_type int correctly indexes into a multi-entry tip_types dict."""
        client = _make_client(
            tip_type_id="",
            tip_type=5,
            tip_types={
                "0": {"Max Liquid Volume": 300},
                "5": {"Max Liquid Volume": 1000},
            },
        )
        result = _resolve_tip_capacity(client, "TransferTips")
        assert result == 1000.0

    def test_both_tip_type_id_and_tip_type_empty_raises_value_error(self):
        """Neither tip_type_id nor tip_type is populated — raise ValueError."""
        client = _make_client(
            tip_type_id="",
            tip_type=-1,
            tip_types={"0": {"Max Liquid Volume": 300}},
        )
        with pytest.raises(ValueError, match="tip type"):
            _resolve_tip_capacity(client, "TransferTips")
